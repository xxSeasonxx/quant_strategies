from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_strategies.engine import Bar, EvaluationRequest, FillModel, Side, Signal, StrategySpec, screen
from quant_strategies.runner import data_loader, run_config
from quant_strategies.runner.data_loader import LoadedData


def large_engine_request(
    *,
    symbol_count: int = 80,
    bars_per_symbol: int = 2_000,
    signals_per_symbol: int = 100,
) -> EvaluationRequest:
    start = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    bars: list[Bar] = []
    signals: list[Signal] = []
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
        first_decision_bar_index = bars_per_symbol - signals_per_symbol - 5
        for signal_index in range(signals_per_symbol):
            decision_bar_index = first_decision_bar_index + signal_index
            signals.append(
                Signal(
                    symbol=symbol,
                    decision_time=start + timedelta(minutes=decision_bar_index),
                    side=Side.LONG if signal_index % 2 == 0 else Side.SHORT,
                    hold_bars=2,
                )
            )
    return EvaluationRequest(
        spec=StrategySpec(strategy_id="phase5_perf", signals=tuple(signals)),
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
    monkeypatch.setattr(data_loader, "load_data", lambda config: LoadedData(rows=runner_rows()))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is True
    assert result.result_dir is not None
    assert artifact_bytes(result.result_dir) < 75_000
    profile = json.loads((result.result_dir / "artifact_profile_summary.json").read_text())
    assert profile["rows"]["row_count"] == 2_000
    assert profile["decisions"]["count"] == 5
    assert not (result.result_dir / "strategy_input_rows.jsonl").exists()
    assert not (result.result_dir / "engine_request.json").exists()
    assert not (result.result_dir / "evidence.json").exists()
