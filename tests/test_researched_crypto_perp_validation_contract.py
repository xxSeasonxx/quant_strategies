from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_strategies.decisions import StrategyDecision


STRATEGY_PATH = Path(
    "researched/crypto_perp_funding_crowding_reversal/"
    "families/family_03_exploratory_time_only_exit/variants/rank_03/strategy.py"
)


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


def test_rank_03_generate_decisions_returns_typed_decisions():
    module = load_module()
    params = {
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
        "long_hold_bars": 2,
        "require_exit_horizon": False,
        "weight": 1.0,
    }

    decisions = module.generate_decisions(synthetic_rows(), params)

    assert decisions
    assert all(isinstance(item, StrategyDecision) for item in decisions)
    assert {item.instrument.kind for item in decisions} == {"crypto_perp"}
