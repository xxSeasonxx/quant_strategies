from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_strategies.decisions import StrategyDecision
from quant_strategies.causality import check_hidden_lookahead
from quant_strategies.engine import Bar, EvaluationRequest, FillModel, Side, StrategySpec, screen
from quant_strategies.runner import execution, run_config
from quant_strategies.runner.data_loader import LoadedData
from engine_helpers import decision_for


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
mode = "screen"
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
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=runner_rows()))

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
    assert calls == 1
    assert elapsed < 1.0
