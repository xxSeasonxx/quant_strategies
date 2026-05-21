from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from quant_strategies.engine import Bar, CostModel, FillModel, Side, Signal


def test_bars_and_signals_require_timezone_aware_timestamps():
    with pytest.raises(ValidationError, match="timestamp must be timezone-aware"):
        Bar(symbol="BTC", timestamp=datetime(2024, 1, 1), open=1.0, high=1.0, low=1.0, close=1.0)

    with pytest.raises(ValidationError, match="decision_time must be timezone-aware"):
        Signal(symbol="BTC", decision_time=datetime(2024, 1, 1), side=Side.LONG)


def test_signal_weight_and_costs_must_be_finite():
    aware_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

    with pytest.raises(ValidationError, match="weight must be finite"):
        Signal(symbol="BTC", decision_time=aware_time, side=Side.LONG, weight=float("inf"))

    with pytest.raises(ValidationError, match="cost values must be finite"):
        CostModel(fee_bps_per_side=float("inf"))


def test_signal_rejects_legacy_quantity_field():
    with pytest.raises(ValidationError):
        Signal.model_validate(
            {
                "symbol": "BTC",
                "decision_time": "2024-01-01T00:00:00Z",
                "side": "long",
                "quantity": 1.0,
            }
        )


def test_bar_accepts_valid_optional_quotes():
    aware_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

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
    aware_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
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
    aware_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

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
    aware_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
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
