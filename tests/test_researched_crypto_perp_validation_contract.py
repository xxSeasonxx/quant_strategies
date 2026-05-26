from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_strategies.decisions import StrategyDecision
from quant_strategies.validation.config import load_validation_config


STRATEGY_PATH = Path(
    "researched/crypto_perp_funding_crowding_reversal/"
    "families/family_03_exploratory_time_only_exit/variants/rank_03/strategy.py"
)
PACKAGE_PATH = STRATEGY_PATH.parent


CONTRACT_PARAMS = {
    "funding_lookback_events": 2,
    "return_lookback_minutes": 20,
    "decision_interval_minutes": 20,
    "decision_lag_minutes": 1,
    "top_n": 1,
    "min_cross_section": 4,
    "min_abs_funding_bps": 0.1,
    "min_abs_return_bps": 0.1,
    "include_positive_funding_shorts": True,
    "include_negative_funding_longs": True,
    "hold_bars": 2,
    "short_hold_bars": 2,
    "long_hold_bars": 3,
    "require_exit_horizon": False,
    "weight": 0.5,
    "take_profit_bps": 10.0,
    "stop_loss_bps": 20.0,
    "trailing_stop_bps": 30.0,
}


def load_module():
    spec = importlib.util.spec_from_file_location("researched_rank_03_strategy", STRATEGY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_rows():
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(80):
        timestamp = start + timedelta(minutes=i)
        for symbol, funding_rate, close_base in (
            ("BTC-PERP", 0.0003, 100.0 + i),
            ("ETH-PERP", -0.0003, 100.0 - i * 0.5),
            ("DOGE-PERP", 0.0001, 50.0 + i * 0.1),
            ("ADA-PERP", -0.0001, 40.0 - i * 0.1),
        ):
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": timestamp,
                    "close": close_base,
                    "funding_timestamp": timestamp,
                    "funding_rate": funding_rate,
                    "has_funding_event": i % 8 == 0,
                    "available_at": timestamp,
                }
            )
    return rows


def test_rank_03_strategy_exposes_generate_decisions():
    module = load_module()

    assert callable(module.generate_decisions)


def test_rank_03_generate_decisions_matches_signal_contract():
    module = load_module()
    rows = synthetic_rows()

    signals = module.generate_signals(rows, CONTRACT_PARAMS)
    decisions = module.generate_decisions(rows, CONTRACT_PARAMS)

    assert signals
    assert decisions
    assert len(decisions) == len(signals)
    assert {signal["side"] for signal in signals} == {"long", "short"}
    assert all(isinstance(item, StrategyDecision) for item in decisions)
    assert {item.instrument.kind for item in decisions} == {"crypto_perp"}

    for signal, decision in zip(signals, decisions, strict=True):
        assert decision.decision_time == signal["decision_time"]
        assert decision.as_of_time == signal["as_of_time"]
        assert decision.instrument.symbol == signal["symbol"]
        assert decision.target.direction == signal["side"]
        assert decision.target.sizing_kind == "target_weight"
        assert decision.target.size == pytest.approx(float(signal["weight"]))
        assert decision.exit_policy.max_hold_bars == signal.get("max_hold_bars", signal["hold_bars"])
        assert decision.exit_policy.take_profit_bps == pytest.approx(signal["take_profit_bps"])
        assert decision.exit_policy.stop_loss_bps == pytest.approx(signal["stop_loss_bps"])
        assert decision.exit_policy.trailing_stop_bps == pytest.approx(signal["trailing_stop_bps"])
        assert decision.metadata["funding_pressure_bps"] == pytest.approx(signal["funding_pressure_bps"])
        assert decision.metadata["entry_return_extension_bps"] == pytest.approx(
            signal["entry_return_extension_bps"]
        )
        assert decision.metadata["signal_family"] == signal["signal_family"]
        assert decision.model_dump(mode="json")


def test_rank_03_validation_config_contract():
    config = load_validation_config(PACKAGE_PATH, repo_root=Path.cwd())

    assert config.backend == "vectorbtpro"
    assert [window.id for window in config.windows] == [
        "validation_2025_h1",
        "validation_2025_h2",
        "locked_recent_2026",
    ]
    assert config.output.results_dir == (
        Path.cwd()
        / "validation_results/researched/crypto_perp_funding_crowding_reversal/"
        "family_03_exploratory_time_only_exit/rank_03"
    )
    assert config.data.kind == "crypto_perp_funding"
    assert config.data.symbols == ("BTC-PERP", "ETH-PERP", "DOGE-PERP", "ADA-PERP", "LINK-PERP")
    assert config.params["funding_lookback_events"] == 5
    assert config.params["return_lookback_minutes"] == 120
    assert config.params["decision_interval_minutes"] == 240
    assert config.params["top_n"] == 5
    assert config.params["short_hold_bars"] == 480
    assert config.params["long_hold_bars"] == 960
    assert config.params["require_exit_horizon"] is True
    assert config.params["weight"] == pytest.approx(1.0)


def test_rank_03_exit_horizon_counts_symbol_bars_not_wall_clock_minutes():
    module = load_module()
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    row_state = module._SymbolRows(
        timestamps=(
            start,
            start + timedelta(minutes=1),
            start + timedelta(minutes=10),
        ),
        closes_by_timestamp={},
        conflicting_close_timestamps=frozenset(),
        funding_event_rows=(),
        latest_timestamp=start + timedelta(minutes=10),
    )

    assert module._has_exit_horizon(row_state, start + timedelta(minutes=1), 2) is False
    assert module._has_exit_horizon(row_state, start, 2) is True
