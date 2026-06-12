from __future__ import annotations

import json
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from engine_helpers import decision_for
from quant_strategies.causality import check_hidden_lookahead
from quant_strategies.core import execution
from quant_strategies.core.accounting_model import SHARED_ACCOUNTING_MODEL
from quant_strategies.core.data_loader import LoadedData
from quant_strategies.runner import run_config


def strategy_source() -> str:
    return (
        "from quant_strategies.decisions import InstrumentRef, TargetDecision\n"
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
        "        decisions.append(TargetDecision(\n"
        "            strategy_id='summary_profile',\n"
        "            instrument=InstrumentRef(kind='equity_or_etf', symbol=symbol),\n"
        "            decision_time=timestamp,\n"
        "            as_of_time=timestamp,\n"
        "            target=0.1,\n"
        "        ))\n"
        "    return decisions\n"
    )


def runner_config(tmp_path: Path) -> Path:
    strategy = tmp_path / "strategies" / "summary_profile.py"
    strategy.parent.mkdir(parents=True)
    strategy.write_text(strategy_source())
    config_path = tmp_path / "run.toml"
    config_path.write_text(
        """
strategy_path = "strategies/summary_profile.py"
strategy_id = "summary_profile"

[data]
kind = "bars"
dataset = "synthetic"
symbols = ["SYM000", "SYM001", "SYM002", "SYM003", "SYM004"]
start = "2024-01-01"
end = "2024-01-05"

[params]

[fill_model]
price = "close"
entry_lag_bars = 1

[cost_model]
fee_bps_per_side = 1.0
slippage_bps_per_side = 0.0

[capacity_model]
mode = "adv_impact"
portfolio_notional = 1000.0
adv_lookback_bars = 390
adv_min_observations = 1
max_bar_participation = 1.0
max_adv_participation = 1.0
impact_coefficient_bps = 0.0
impact_exponent = 1.0

[output]
results_dir = "results"
artifact_profile = "summary"
""".lstrip()
    )
    return config_path


def runner_rows(symbol_count: int = 5, bars_per_symbol: int = 400) -> list[dict[str, object]]:
    start = datetime(2024, 1, 1, 9, 30, tzinfo=UTC)
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
                    "available_at": timestamp,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1_000_000.0,
                    "vwap": close,
                    "num_trades": 100,
                }
            )
    return rows


def artifact_bytes(result_dir: Path) -> int:
    return sum(path.stat().st_size for path in result_dir.rglob("*") if path.is_file())


def minimal_trace_table_artifacts(
    result_dir: Path, *, scenario_ids: tuple[str, ...]
) -> list[dict[str, Any]]:
    pd = pytest.importorskip("pandas")
    from quant_strategies.evaluation.artifacts import write_parquet_artifact

    return [
        write_parquet_artifact(
            result_dir,
            "tables/portfolio_path.parquet",
            pd.DataFrame(
                {
                    "scenario_id": list(scenario_ids),
                    "timestamp": [datetime(2026, 1, 1, tzinfo=UTC)] * len(scenario_ids),
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
            pd.DataFrame(
                {"scenario_id": list(scenario_ids), "trade_id": list(range(len(scenario_ids)))}
            ),
            artifact_kind="trades",
            scenario_ids=scenario_ids,
        ),
        write_parquet_artifact(
            result_dir,
            "tables/target_positions.parquet",
            pd.DataFrame(
                {
                    "scenario_id": list(scenario_ids),
                    "timestamp": [datetime(2026, 1, 1, tzinfo=UTC)] * len(scenario_ids),
                    "asset": ["BTC-PERP"] * len(scenario_ids),
                    "target_weight": [0.25] * len(scenario_ids),
                    "event": ["entry"] * len(scenario_ids),
                    "decision_time": [datetime(2026, 1, 1, tzinfo=UTC)] * len(scenario_ids),
                    "direction": ["long"] * len(scenario_ids),
                }
            ),
            artifact_kind="target_positions",
            scenario_ids=scenario_ids,
        ),
        write_parquet_artifact(
            result_dir,
            "tables/target_exposure_summary.parquet",
            pd.DataFrame(
                {
                    "scenario_id": list(scenario_ids),
                    "asset": ["BTC-PERP"] * len(scenario_ids),
                    "decision_count": [1] * len(scenario_ids),
                }
            ),
            artifact_kind="target_exposure_summary",
            scenario_ids=scenario_ids,
        ),
        write_parquet_artifact(
            result_dir,
            "tables/execution_events.parquet",
            pd.DataFrame({"scenario_id": []}),
            artifact_kind="execution_events",
            scenario_ids=scenario_ids,
        ),
        write_parquet_artifact(
            result_dir,
            "tables/funding_cashflows.parquet",
            pd.DataFrame(
                {
                    "scenario_id": [],
                    "timestamp": [],
                    "asset": [],
                    "funding_rate": [],
                    "position_units": [],
                    "mark_price": [],
                    "funding_cashflow": [],
                }
            ),
            artifact_kind="funding_cashflows",
            scenario_ids=scenario_ids,
        ),
    ]


def evaluation_rows() -> list[dict[str, Any]]:
    as_of = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    decision = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
    return [
        {
            "symbol": "BTC-PERP",
            "timestamp": as_of,
            "available_at": as_of,
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1_000.0,
            "vwap": 100.0,
            "num_trades": 100,
            "has_funding_event": False,
        },
        {
            "symbol": "BTC-PERP",
            "timestamp": decision,
            "available_at": decision,
            "open": 101.0,
            "high": 101.0,
            "low": 101.0,
            "close": 101.0,
            "volume": 1_000.0,
            "vwap": 101.0,
            "num_trades": 100,
            "has_funding_event": False,
        },
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
            "available_at": datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
            "open": 102.0,
            "high": 102.0,
            "low": 102.0,
            "close": 102.0,
            "volume": 1_000.0,
            "vwap": 102.0,
            "num_trades": 100,
            "has_funding_event": False,
        },
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 3, tzinfo=UTC),
            "available_at": datetime(2026, 1, 1, 0, 3, tzinfo=UTC),
            "open": 103.0,
            "high": 103.0,
            "low": 103.0,
            "close": 103.0,
            "volume": 1_000.0,
            "vwap": 103.0,
            "num_trades": 100,
            "has_funding_event": False,
        },
    ]


def write_evaluation_candidate(tmp_path: Path) -> Path:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, TargetDecision\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    if len(rows) < 2:\n"
        "        return []\n"
        "    return [TargetDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[1]['timestamp'],\n"
        "        target=0.25,\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[1]['timestamp'], "
        "field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    (candidate / "evaluation.toml").write_text(
        """
strategy_path = "strategy.py"
strategy_id = "demo"

[[windows]]
id = "eval_2026_h1"
start = "2026-01-01"
end = "2026-06-30"

[data]
kind = "bars"
dataset = "demo_bars"
symbols = ["BTC-PERP"]

[params]
weight = 0.25

[fill_model]
price = "close"
entry_lag_bars = 1

[cost_model]
fee_bps_per_side = 0.5
slippage_bps_per_side = 0.5

[capacity_model]
mode = "adv_impact"
portfolio_notional = 1000.0
adv_lookback_bars = 3
adv_min_observations = 1
max_bar_participation = 1.0
max_adv_participation = 1.0
impact_coefficient_bps = 0.0
impact_exponent = 1.0

[metrics]
annualization_periods_per_year = 365

[output]
results_dir = "evaluation_results/demo"
""".lstrip()
    )
    return candidate


class FakeEvaluationBackend:
    name = "fake_evaluation"

    def run(
        self,
        *,
        decisions: Sequence[Any],
        rows: Sequence[dict[str, Any]],
        scenario: Any,
        metrics: Any,
        data_kind: str = "bars",
        capacity_model: Any = None,
        leverage_budget: Any = None,
    ):
        pd = pytest.importorskip("pandas")
        from quant_strategies.evaluation.results import (
            PortfolioEvaluationResult,
            PortfolioTraceTables,
        )

        frame = pd.DataFrame(
            {
                "scenario_id": [scenario.scenario_id],
                "timestamp": [rows[0]["timestamp"]],
                "portfolio_value": [100.0],
                "period_return": [0.0],
                "drawdown": [0.0],
            }
        )
        tables = PortfolioTraceTables(
            portfolio_path=frame,
            trades=pd.DataFrame({"scenario_id": [scenario.scenario_id], "trade_id": [1]}),
            target_positions=pd.DataFrame(
                {
                    "scenario_id": [scenario.scenario_id],
                    "timestamp": [rows[0]["timestamp"]],
                    "asset": ["BTC-PERP"],
                    "target_weight": [0.25],
                }
            ),
            target_exposure_summary=pd.DataFrame(
                {
                    "scenario_id": [scenario.scenario_id],
                    "asset": ["BTC-PERP"],
                    "decision_count": [1],
                }
            ),
            execution_events=pd.DataFrame({"scenario_id": []}),
            funding_cashflows=pd.DataFrame({"scenario_id": []}),
        )
        return PortfolioEvaluationResult(
            scenario_id=scenario.scenario_id,
            backend=self.name,
            status="completed",
            metrics=completed_evaluation_metrics(),
            tables=tables,
        )


def completed_evaluation_metrics() -> dict[str, int | float | str]:
    return {
        "total_return": 0.01,
        "ending_value": 101.0,
        "max_drawdown": -0.01,
        "trade_count": 1,
        "return_total_count_excluding_initial": 1,
        "return_sample_count": 1,
        "return_nonfinite_count": 0,
        "funding_cashflow_total": 0.0,
        "funding_event_count": 0,
        "funding_model": SHARED_ACCOUNTING_MODEL,
    }


def test_summary_profile_artifacts_stay_under_byte_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_path = runner_config(tmp_path)
    monkeypatch.setattr(
        execution, "load_data", lambda config, **_kwargs: LoadedData(rows=runner_rows())
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
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
    import quant_strategies.evaluation._pipeline as evaluation_runner
    from quant_strategies.evaluation._pipeline import _run_evaluation as run_evaluation

    class CountingBackend(FakeEvaluationBackend):
        def __init__(self) -> None:
            self.backend_calls = 0
            self.prepare_calls = 0
            self.row_ids: list[int] = []

        def prepare_inputs(
            self,
            *,
            decisions: Sequence[Any],
            rows: Sequence[dict[str, Any]],
            data_kind: str = "bars",
            capacity_model: Any = None,
            leverage_budget: Any = None,
        ) -> dict[str, Any]:
            self.prepare_calls += 1
            return {"decisions": decisions, "rows": rows}

        def run(
            self,
            *,
            decisions: Sequence[Any],
            rows: Sequence[dict[str, Any]],
            scenario: Any,
            metrics: Any,
            data_kind: str = "bars",
            capacity_model: Any = None,
            leverage_budget: Any = None,
        ):
            self.backend_calls += 1
            self.row_ids.append(id(rows))
            return super().run(decisions=decisions, rows=rows, scenario=scenario, metrics=metrics)

        def run_prepared(self, *, prepared: dict[str, Any], scenario: Any, metrics: Any):
            self.backend_calls += 1
            self.row_ids.append(id(prepared["rows"]))
            return FakeEvaluationBackend.run(
                self,
                decisions=prepared["decisions"],
                rows=prepared["rows"],
                scenario=scenario,
                metrics=metrics,
            )

    candidate = write_evaluation_candidate(tmp_path)
    backend = CountingBackend()
    execution_calls = 0
    original_execute = evaluation_runner.execute_strategy_run

    def counting_execute_strategy_run(*args: Any, **kwargs: Any):
        nonlocal execution_calls
        execution_calls += 1
        return original_execute(*args, **kwargs)

    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=evaluation_rows()),
    )
    monkeypatch.setattr(evaluation_runner, "execute_strategy_run", counting_execute_strategy_run)

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=backend)

    assert result.run_completed is True
    assert execution_calls == 1
    assert backend.prepare_calls == 1
    assert backend.backend_calls == 6
    assert len(set(backend.row_ids)) == 1


def test_strip_trace_tables_removes_dataframe_payload_from_summaries():
    pd = pytest.importorskip("pandas")
    from quant_strategies.evaluation._pipeline import _strip_trace_tables
    from quant_strategies.evaluation.results import PortfolioEvaluationResult, PortfolioTraceTables

    tables = PortfolioTraceTables(
        portfolio_path=pd.DataFrame({"scenario_id": ["base"], "portfolio_value": [100.0]}),
        trades=pd.DataFrame({"scenario_id": ["base"], "trade_id": [1]}),
        target_positions=pd.DataFrame(
            {"scenario_id": ["base"], "asset": ["BTC-PERP"], "target_weight": [0.25]}
        ),
        target_exposure_summary=pd.DataFrame(
            {"scenario_id": ["base"], "asset": ["BTC-PERP"], "decision_count": [1]}
        ),
        execution_events=pd.DataFrame({"scenario_id": []}),
        funding_cashflows=pd.DataFrame({"scenario_id": []}),
    )
    result = PortfolioEvaluationResult(
        scenario_id="base",
        backend="fake",
        status="completed",
        metrics=completed_evaluation_metrics(),
        tables=tables,
    )

    stripped = _strip_trace_tables(result)

    assert stripped.tables is None
    assert stripped.metrics == result.metrics


def test_evaluation_manifest_uses_table_hashes_without_rehashing_parquet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import quant_strategies.evaluation.artifacts as evaluation_artifacts
    import quant_strategies.provenance as provenance

    result_dir = tmp_path / "results"
    result_dir.mkdir()
    config_path = tmp_path / "evaluation.toml"
    config_path.write_text("strategy_id = 'demo'\n")
    strategy_path = tmp_path / "strategy.py"
    strategy_path.write_text('"""Demo strategy."""\n')
    table_artifacts = minimal_trace_table_artifacts(result_dir, scenario_ids=("base",))
    original_artifact_file_sha256 = evaluation_artifacts.file_sha256
    original_provenance_file_sha256 = provenance.file_sha256

    def fail_on_parquet_hash(path: Path | str) -> str:
        materialized = Path(path)
        if materialized.suffix == ".parquet":
            raise AssertionError(
                f"Parquet trace table was rehashed during manifest write: {materialized}"
            )
        return original_artifact_file_sha256(materialized)

    def fail_on_parquet_provenance_hash(path: Path | str) -> str:
        materialized = Path(path)
        if materialized.suffix == ".parquet":
            raise AssertionError(
                f"Parquet trace table was rehashed in artifact inventory: {materialized}"
            )
        return original_provenance_file_sha256(materialized)

    monkeypatch.setattr(evaluation_artifacts, "file_sha256", fail_on_parquet_hash)
    monkeypatch.setattr(provenance, "file_sha256", fail_on_parquet_provenance_hash)

    evaluation_artifacts.write_evaluation_manifest(
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
    public_table_artifacts = [dict(item) for item in table_artifacts]

    assert manifest["tables"] == public_table_artifacts
    assert manifest["trace_artifacts"]["total_byte_size"] == sum(
        item["byte_size"] for item in public_table_artifacts
    )
    assert not any(
        path.startswith("tables/") and path.endswith(".parquet") for path in manifest["artifacts"]
    )


def test_hidden_lookahead_grouped_replay_completes_under_runtime_budget():
    row_count = 50_000
    decision_count = 5_000
    start_time = datetime(2024, 1, 1, 9, 30, tzinfo=UTC)
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
