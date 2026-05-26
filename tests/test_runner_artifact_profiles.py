from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.runner.artifact_profiles import (
    normalized_rows_sha256,
    summary_profile_payload,
    write_summary_profile_artifact,
)
from quant_strategies.runner.config import load_config


def row(symbol: str, timestamp: datetime, close: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
    }


def decision(symbol: str, timestamp: datetime, direction: str = "long") -> StrategyDecision:
    return StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="equity_or_etf", symbol=symbol),
        decision_time=timestamp,
        as_of_time=timestamp,
        target=PositionTarget(direction=direction, sizing_kind="target_weight", size=0.5),
        exit_policy=ExitPolicy(max_hold_bars=2),
        metadata={"family": "test"},
    )


def config(tmp_path: Path):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True)
    strategy.write_text("def generate_decisions(rows, params):\n    return []\n")
    config_path = tmp_path / "run.toml"
    config_path.write_text(
        '''
strategy_path = "tested/demo.py"
strategy_id = "demo"

[data]
kind = "bars"
dataset = "equity_1min"
symbols = ["SPY", "QQQ"]
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
mode = "validate"
artifact_profile = "summary"
'''.lstrip()
    )
    return load_config(config_path, repo_root=tmp_path)


def test_normalized_rows_sha256_is_stable_for_json_equivalent_rows():
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = [
        {"symbol": "SPY", "timestamp": timestamp, "close": 100.0, "nested": {"b": 2, "a": 1}},
        {"nested": {"a": 1, "b": 2}, "close": 101.0, "timestamp": timestamp, "symbol": "SPY"},
    ]

    first = normalized_rows_sha256(rows)
    second = normalized_rows_sha256([dict(item) for item in rows])

    assert first == second
    assert len(first) == 64


def test_summary_profile_payload_contains_rows_decisions_signals_and_engine(tmp_path: Path):
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    run_config = config(tmp_path)
    rows = [
        row("SPY", timestamp, 100.0),
        row("SPY", timestamp.replace(day=2), 101.0),
        row("QQQ", timestamp, 200.0),
    ]
    decisions = [
        decision("SPY", timestamp, "long"),
        decision("QQQ", timestamp, "short"),
    ]
    signals = [
        {"symbol": "SPY", "decision_time": timestamp, "side": "long", "weight": 0.5, "hold_bars": 2},
        {"symbol": "QQQ", "decision_time": timestamp, "side": "short", "weight": 0.5, "hold_bars": 2},
    ]

    payload = summary_profile_payload(
        config=run_config,
        rows=rows,
        decisions=decisions,
        signals=signals,
        engine={
            "passed": True,
            "trade_count": 2,
            "gross_return": 0.03,
            "funding_return": 0.0,
            "cost_return": 0.0,
            "net_return": 0.03,
        },
    )

    assert payload["artifact_profile"] == "summary"
    assert payload["rows"]["row_count"] == 3
    assert payload["rows"]["sample_count"] == 3
    assert payload["rows"]["by_symbol"]["SPY"]["count"] == 2
    assert payload["decisions"]["count"] == 2
    assert payload["decisions"]["by_direction"] == {"long": 1, "short": 1}
    assert payload["signals"]["count"] == 2
    assert payload["signals"]["by_side"] == {"long": 1, "short": 1}
    assert payload["engine"] == {
        "passed": True,
        "trade_count": 2,
        "gross_return": 0.03,
        "funding_return": 0.0,
        "cost_return": 0.0,
        "net_return": 0.03,
    }


def test_summary_profile_payload_uses_precomputed_row_hash(tmp_path: Path):
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    payload = summary_profile_payload(
        config=config(tmp_path),
        rows=[row("SPY", timestamp, 100.0)],
        decisions=[decision("SPY", timestamp)],
        signals=[{"symbol": "SPY", "decision_time": timestamp, "side": "long", "weight": 0.5, "hold_bars": 2}],
        engine={"passed": True, "trade_count": 1},
        normalized_rows_hash="a" * 64,
    )

    assert payload["rows"]["normalized_rows_sha256"] == "a" * 64


def test_summary_profile_payload_normalizes_common_non_json_row_values(tmp_path: Path):
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)

    payload = summary_profile_payload(
        config=config(tmp_path),
        rows=[{**row("SPY", timestamp, 100.0), "research_nan": float("nan"), "research_decimal": Decimal("1.25")}],
        decisions=[decision("SPY", timestamp)],
        signals=[{"symbol": "SPY", "decision_time": timestamp, "side": "long", "weight": 0.5, "hold_bars": 2}],
        engine={"passed": True, "trade_count": 1},
    )

    sample = payload["rows"]["sample"][0]
    assert sample["research_nan"] is None
    assert sample["research_decimal"] == 1.25
    assert len(payload["rows"]["normalized_rows_sha256"]) == 64


def test_write_summary_profile_artifact_writes_json(tmp_path: Path):
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    run_config = config(tmp_path)
    result_dir = tmp_path / "results" / "run"
    result_dir.mkdir(parents=True)

    path = write_summary_profile_artifact(
        result_dir,
        config=run_config,
        rows=[row("SPY", timestamp, 100.0)],
        decisions=[decision("SPY", timestamp)],
        signals=[{"symbol": "SPY", "decision_time": timestamp, "side": "long", "weight": 0.5, "hold_bars": 2}],
        engine={
            "passed": True,
            "trade_count": 1,
            "gross_return": 0.01,
            "funding_return": 0.0,
            "cost_return": 0.0,
            "net_return": 0.01,
        },
    )

    parsed = json.loads(path.read_text())
    assert path == result_dir / "artifact_profile_summary.json"
    assert parsed["rows"]["row_count"] == 1
    assert parsed["rows"]["normalized_rows_sha256"] == normalized_rows_sha256([row("SPY", timestamp, 100.0)])
