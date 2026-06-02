from __future__ import annotations

import json
import time
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from quant_strategies.decisions import StrategyDecision
from quant_strategies.causality import check_hidden_lookahead
from quant_strategies.engine import Bar, EvaluationRequest, FillModel, Side, StrategySpec, screen
from quant_strategies.evaluation.artifacts import write_evaluation_manifest, write_parquet_artifact
from quant_strategies.evaluation.backend import PortfolioEvaluationResult, PortfolioTraceTables
import quant_strategies.evaluation.runner as evaluation_runner
from quant_strategies.evaluation.runner import _strip_trace_tables, run_evaluation
from quant_strategies.runner import execution, run_config
from quant_strategies.runner.data_loader import LoadedData
from engine_helpers import decision_for
from tests.test_evaluation_runner import FakeBackend, rows, write_candidate


def large_engine_request(
    *,
    symbol_count: int = 80,
    bars_per_symbol: int = 2_000,
    decisions_per_symbol: int = 100,
) -> EvaluationRequest:
    start = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    bars: list[Bar] = []
    decisions: list[StrategyDecision] = []
    for symbol_index in range(symbol_count):
        symbol = f"SYM{symbol_index:03d}"
        for bar_index in range(bars_per_symbol):
            timestamp = start + timedelta(minutes=bar_index)
            close = 100.0 + symbol_index + (bar_index * 0.01)
            bars.append(
                Bar(
                    symbol=symbol,
                    timestamp=timestamp,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                )
            )
        first_decision_bar_index = bars_per_symbol - decisions_per_symbol - 5
        for decision_index in range(decisions_per_symbol):
            decision_bar_index = first_decision_bar_index + decision_index
            decisions.append(
                decision_for(
                    symbol=symbol,
                    decision_time=start + timedelta(minutes=decision_bar_index),
                    side=Side.LONG if decision_index % 2 == 0 else Side.SHORT,
                    max_hold_bars=2,
                )
            )
    return EvaluationRequest(
        spec=StrategySpec(strategy_id="phase5_perf", decisions=tuple(decisions)),
        bars=tuple(bars),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )


def strategy_source() -> str:
    return (
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    decisions = []\n"
        "    symbols = []\n"
        "    for row in rows:\n"
        "        symbol = row['symbol']\n"
        "        if symbol not in symbols:\n"
        "            symbols.append(symbol)\n"
        "    for symbol in symbols[:5]:\n"
        "        symbol_rows = [row for row in rows if row['symbol'] == symbol]\n"
        "        timestamp = symbol_rows[1]['timestamp']\n"
        "        decisions.append(StrategyDecision(\n"
        "            strategy_id='phase5_summary',\n"
        "            instrument=InstrumentRef(kind='equity_or_etf', symbol=symbol),\n"
        "            decision_time=timestamp,\n"
        "            as_of_time=timestamp,\n"
        "            target=PositionTarget(direction='long', sizing_kind='target_weight', size=0.1),\n"
        "            exit_policy=ExitPolicy(max_hold_bars=2),\n"
        "        ))\n"
        "    return decisions\n"
    )


def runner_config(tmp_path: Path) -> Path:
    strategy = tmp_path / "tested" / "phase5_summary.py"
    strategy.parent.mkdir(parents=True)
    strategy.write_text(strategy_source())
    config_path = tmp_path / "run.toml"
    config_path.write_text(
        '''
strategy_path = "tested/phase5_summary.py"
strategy_id = "phase5_summary"

[data]
kind = "bars"
dataset = "synthetic"
symbols = ["SYM000", "SYM001", "SYM002", "SYM003", "SYM004"]
start = "2024-01-01"
end = "2024-01-05"
strict = true

[params]

[fill_model]
price = "close"
entry_lag_bars = 1
exit_lag_bars = 0

[cost_model]
fee_bps_per_side = 0.0
slippage_bps_per_side = 0.0

[output]
results_dir = "results"
artifact_profile = "summary"
'''.lstrip()
    )
    return config_path


def runner_rows(symbol_count: int = 5, bars_per_symbol: int = 400) -> list[dict[str, object]]:
    start = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    rows: list[dict[str, object]] = []
    for symbol_index in range(symbol_count):
        symbol = f"SYM{symbol_index:03d}"
        for bar_index in range(bars_per_symbol):
            timestamp = start + timedelta(minutes=bar_index)
            close = 100.0 + symbol_index + (bar_index * 0.01)
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": timestamp,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                }
            )
    return rows


def artifact_bytes(result_dir: Path) -> int:
    return sum(path.stat().st_size for path in result_dir.rglob("*") if path.is_file())


def minimal_trace_table_artifacts(result_dir: Path, *, scenario_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        write_parquet_artifact(
            result_dir,
            "tables/portfolio_path.parquet",
            pd.DataFrame(
                {
                    "scenario_id": list(scenario_ids),
                    "timestamp": [datetime(2026, 1, 1, tzinfo=timezone.utc)] * len(scenario_ids),
                    "portfolio_value": [100.0] * len(scenario_ids),
                    "period_return": [0.0] * len(scenario_ids),
                    "drawdown": [0.0] * len(scenario_ids),
                }
            ),
            artifact_kind="portfolio_path",
            scenario_ids=scenario_ids,
        ),
        write_parquet_artifact(
            result_dir,
            "tables/trades.parquet",
            pd.DataFrame({"scenario_id": list(scenario_ids), "trade_id": list(range(len(scenario_ids)))}),
            artifact_kind="trades",
            scenario_ids=scenario_ids,
        ),
        write_parquet_artifact(
            result_dir,
            "tables/positions.parquet",
            pd.DataFrame(
                {
                    "scenario_id": list(scenario_ids),
                    "asset": ["BTC-PERP"] * len(scenario_ids),
                    "weight": [0.25] * len(scenario_ids),
                }
            ),
            artifact_kind="positions",
            scenario_ids=scenario_ids,
        ),
        write_parquet_artifact(
            result_dir,
            "tables/per_asset_metrics.parquet",
            pd.DataFrame(
                {
                    "scenario_id": list(scenario_ids),
                    "asset": ["BTC-PERP"] * len(scenario_ids),
                    "trade_count": [1] * len(scenario_ids),
                }
            ),
            artifact_kind="per_asset_metrics",
            scenario_ids=scenario_ids,
        ),
    ]


def test_large_engine_screen_completes_under_runtime_budget():
    request = large_engine_request()

    start = time.perf_counter()
    result = screen(request)
    elapsed = time.perf_counter() - start

    assert result.trade_count == 8_000
    assert elapsed < 0.50


def test_summary_profile_artifacts_stay_under_byte_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_path = runner_config(tmp_path)
    monkeypatch.setattr(execution, "load_data", lambda config, **_kwargs: LoadedData(rows=runner_rows()))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    assert artifact_bytes(result.result_dir) < 75_000
    profile = json.loads((result.result_dir / "artifact_profile_summary.json").read_text())
    assert profile["rows"]["row_count"] == 2_000
    assert profile["decisions"]["count"] == 5
    assert not (result.result_dir / "strategy_input_rows.jsonl").exists()
    assert not (result.result_dir / "engine_request.json").exists()
    assert not (result.result_dir / "evidence.json").exists()


def test_run_evaluation_executes_once_per_window_and_fans_out_scenarios(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class CountingBackend(FakeBackend):
        def __init__(self) -> None:
            self.backend_calls = 0
            self.prepare_calls = 0
            self.row_ids: list[int] = []

        def prepare_inputs(self, *, decisions: Sequence[Any], rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
            self.prepare_calls += 1
            return {"decisions": decisions, "rows": rows}

        def run(self, *, decisions: Sequence[Any], rows: Sequence[dict[str, Any]], scenario: Any, metrics: Any):
            self.backend_calls += 1
            self.row_ids.append(id(rows))
            return super().run(decisions=decisions, rows=rows, scenario=scenario, metrics=metrics)

        def run_prepared(self, *, prepared: dict[str, Any], scenario: Any, metrics: Any):
            self.backend_calls += 1
            self.row_ids.append(id(prepared["rows"]))
            return FakeBackend.run(
                self,
                decisions=prepared["decisions"],
                rows=prepared["rows"],
                scenario=scenario,
                metrics=metrics,
            )

    candidate = write_candidate(tmp_path)
    backend = CountingBackend()
    execution_calls = 0
    original_execute = evaluation_runner.execute_strategy_run

    def counting_execute_strategy_run(*args: Any, **kwargs: Any):
        nonlocal execution_calls
        execution_calls += 1
        return original_execute(*args, **kwargs)

    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config, **_kwargs: LoadedData(rows=rows()))
    monkeypatch.setattr(evaluation_runner, "execute_strategy_run", counting_execute_strategy_run)

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=backend)

    assert result.run_completed is True
    assert execution_calls == 1
    assert backend.prepare_calls == 1
    assert backend.backend_calls == 6
    assert len(set(backend.row_ids)) == 1


def test_strip_trace_tables_removes_dataframe_payload_from_summaries():
    tables = PortfolioTraceTables(
        portfolio_path=pd.DataFrame({"scenario_id": ["base"], "portfolio_value": [100.0]}),
        trades=pd.DataFrame({"scenario_id": ["base"], "trade_id": [1]}),
        positions=pd.DataFrame({"scenario_id": ["base"], "asset": ["BTC-PERP"], "weight": [0.25]}),
        per_asset_metrics=pd.DataFrame({"scenario_id": ["base"], "asset": ["BTC-PERP"], "trade_count": [1]}),
    )
    result = PortfolioEvaluationResult(
        scenario_id="base",
        backend="fake",
        status="completed",
        metrics={"total_return": 0.01, "trade_count": 1},
        tables=tables,
    )

    stripped = _strip_trace_tables(result)

    assert stripped.tables is None
    assert stripped.metrics == result.metrics


def test_evaluation_manifest_uses_table_hashes_without_rehashing_parquet(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    config_path = tmp_path / "evaluation.toml"
    config_path.write_text("strategy_id = 'demo'\n")
    strategy_path = tmp_path / "strategy.py"
    strategy_path.write_text('"""Demo strategy."""\n')
    table_artifacts = minimal_trace_table_artifacts(result_dir, scenario_ids=("base",))

    write_evaluation_manifest(
        result_dir,
        repo_root=tmp_path,
        path_base=tmp_path,
        config=SimpleNamespace(strategy_id="demo", strategy_path=strategy_path),
        config_path=config_path,
        backend_name="unit-test",
        data_windows=[],
        table_artifacts=table_artifacts,
        scenario_summary={
            "scenario_coverage": {
                "expected_count": 1,
                "completed_count": 1,
                "expected_ids": ["base"],
                "completed_ids": ["base"],
                "missing_ids": [],
                "unexpected_ids": [],
            }
        },
    )

    manifest = json.loads((result_dir / "evaluation_manifest.json").read_text())

    assert [item["file_sha256"] for item in manifest["tables"]] == [
        item["file_sha256"] for item in table_artifacts
    ]
    assert manifest["trace_artifacts"]["total_byte_size"] == sum(item["byte_size"] for item in table_artifacts)
    assert not any(path.startswith("tables/") and path.endswith(".parquet") for path in manifest["artifacts"])


def test_hidden_lookahead_grouped_replay_completes_under_runtime_budget():
    row_count = 50_000
    decision_count = 5_000
    start_time = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    as_of_time = start_time + timedelta(minutes=9)
    rows = [
        {
            "symbol": f"SYM{row_index % decision_count:04d}",
            "timestamp": start_time + timedelta(minutes=row_index % 10),
            "available_at": start_time + timedelta(minutes=row_index % 10),
            "close": 100.0 + row_index,
        }
        for row_index in range(row_count)
    ]
    baseline = [
        decision_for(
            symbol=f"SYM{decision_index:04d}",
            decision_time=as_of_time,
            side=Side.LONG,
            max_hold_bars=1,
            strategy_id="lookahead_perf",
        )
        for decision_index in range(decision_count)
    ]
    calls = 0

    def grouped_strategy(strategy_rows, params):
        nonlocal calls
        calls += 1
        return baseline

    start = time.perf_counter()
    # Emitted mode groups all decisions sharing one (as_of, decision_time) into a
    # single replay; this asserts that grouping optimization. Strict-default
    # performance on realistic datasets is covered by the runner/validation
    # integration budgets.
    result = check_hidden_lookahead(
        grouped_strategy,
        rows=rows,
        params={},
        baseline_decisions=baseline,
        strategy_id="lookahead_perf",
        mode="emitted",
    )
    elapsed = time.perf_counter() - start

    assert result.passed is True
    assert calls == 2
    assert elapsed < 1.0
