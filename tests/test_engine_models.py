from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from engine_helpers import decision_for
from quant_strategies.core.config import CostModelConfig, FillModelConfig
from quant_strategies.engine import Bar, CostModel, FillModel, Side, StrategySpec, Trade


def test_engine_fill_and_cost_models_are_shared_core_contracts():
    assert FillModel is FillModelConfig
    assert CostModel is CostModelConfig
    assert FillModel.__module__ == "quant_strategies.core.config"
    assert CostModel.__module__ == "quant_strategies.core.config"


def test_fill_model_rejects_same_bar_entry_everywhere():
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        FillModel(entry_lag_bars=0)


def test_bars_require_timezone_aware_timestamps():
    with pytest.raises(ValidationError, match="timestamp must be timezone-aware"):
        Bar(symbol="BTC", timestamp=datetime(2024, 1, 1), open=1.0, high=1.0, low=1.0, close=1.0)


def test_strategy_spec_rejects_legacy_signal_shape():
    with pytest.raises(ValidationError, match="decisions"):
        StrategySpec.model_validate(
            {
                "strategy_id": "demo",
                "signals": [
                    {
                        "symbol": "BTC",
                        "decision_time": "2024-01-01T00:00:00Z",
                        "side": "long",
                        "max_hold_bars": 1,
                    }
                ],
            }
        )


def test_strategy_spec_accepts_strategy_decisions():
    decision = decision_for("BTC")

    spec = StrategySpec(strategy_id="demo", decisions=(decision,))

    assert spec.decisions == (decision,)


def test_costs_must_be_finite():
    with pytest.raises(ValidationError, match="cost values must be finite"):
        CostModel(fee_bps_per_side=float("inf"))


def test_cost_model_keeps_round_trip_bps_on_shared_contract():
    assert CostModel(fee_bps_per_side=2.0, slippage_bps_per_side=3.0).round_trip_bps == 10.0


def test_trade_accepts_decision_metadata():
    aware_time = datetime(2024, 1, 1, tzinfo=UTC)

    trade = Trade(
        decision_id="decision-1",
        symbol="BTC",
        side=Side.LONG,
        decision_time=aware_time,
        entry_time=aware_time,
        exit_time=aware_time,
        entry_price=100.0,
        exit_price=101.0,
        exit_reason="max_hold",
        weight=0.5,
        gross_return=0.005,
        cost_return=0.0,
        net_return=0.005,
        decision_metadata={"funding_pressure_bps": 3.5},
    )

    assert trade.decision_metadata == {"funding_pressure_bps": 3.5}


def test_bar_accepts_valid_optional_quotes():
    aware_time = datetime(2024, 1, 1, tzinfo=UTC)

    bar = Bar(
        symbol="EURUSD",
        timestamp=aware_time,
        open=1.1000,
        high=1.1005,
        low=1.0995,
        close=1.1001,
        bid=1.1000,
        ask=1.1002,
        mid=1.1001,
    )

    assert bar.bid == 1.1000
    assert bar.ask == 1.1002
    assert bar.mid == 1.1001


def test_bar_rejects_invalid_quote_shapes():
    aware_time = datetime(2024, 1, 1, tzinfo=UTC)
    base = {
        "symbol": "EURUSD",
        "timestamp": aware_time,
        "open": 1.1000,
        "high": 1.1005,
        "low": 1.0995,
        "close": 1.1001,
    }

    with pytest.raises(ValidationError, match="bid must be less than or equal to ask"):
        Bar(**base, bid=1.1003, ask=1.1002)

    with pytest.raises(ValidationError, match="mid must be between bid and ask"):
        Bar(**base, bid=1.1000, ask=1.1002, mid=1.1003)

    with pytest.raises(ValidationError, match="quote prices must be finite and positive"):
        Bar(**base, bid=0.0, ask=1.1002)


def test_fill_model_accepts_quote_price():
    assert FillModel(price="quote").price == "quote"


def test_bar_accepts_valid_funding_event():
    aware_time = datetime(2024, 1, 1, tzinfo=UTC)

    bar = Bar(
        symbol="BTC-PERP",
        timestamp=aware_time,
        open=100.0,
        high=100.0,
        low=100.0,
        close=100.0,
        funding_timestamp=aware_time,
        funding_rate=0.0001,
        has_funding_event=True,
    )

    assert bar.funding_timestamp == aware_time
    assert bar.funding_rate == 0.0001
    assert bar.has_funding_event is True


def test_bar_rejects_incomplete_or_invalid_funding_event():
    aware_time = datetime(2024, 1, 1, tzinfo=UTC)
    base = {
        "symbol": "BTC-PERP",
        "timestamp": aware_time,
        "open": 100.0,
        "high": 100.0,
        "low": 100.0,
        "close": 100.0,
    }

    with pytest.raises(ValidationError, match="funding event requires funding_timestamp"):
        Bar(**base, funding_rate=0.0001, has_funding_event=True)

    with pytest.raises(ValidationError, match="funding event requires funding_rate"):
        Bar(**base, funding_timestamp=aware_time, has_funding_event=True)

    with pytest.raises(ValidationError, match="funding_rate must be finite"):
        Bar(**base, funding_timestamp=aware_time, funding_rate=float("nan"), has_funding_event=True)
