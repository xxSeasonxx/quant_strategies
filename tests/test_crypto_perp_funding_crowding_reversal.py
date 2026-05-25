from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from untested.crypto_perp_funding_crowding_reversal import generate_signals


START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def bar(
    symbol: str,
    minute: int,
    close: float,
    *,
    funding_rate: float | None = None,
    funding_minute: int | None = None,
    has_funding_event: bool = False,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timestamp": START + timedelta(minutes=minute),
        "close": close,
        "funding_timestamp": START + timedelta(minutes=funding_minute) if funding_minute is not None else None,
        "funding_rate": funding_rate,
        "has_funding_event": has_funding_event,
    }


def symbol_rows(symbol: str, base_close: float, observed_close: float, decision_close: float, funding_rate: float):
    return [
        bar(symbol, 0, base_close),
        bar(symbol, 9, observed_close, funding_rate=funding_rate, funding_minute=9, has_funding_event=True),
        bar(symbol, 10, decision_close),
    ]


def params(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "decision_interval_minutes": 10,
        "return_lookback_minutes": 10,
        "funding_lookback_events": 1,
        "top_n": 1,
        "min_cross_section": 4,
        "min_abs_funding_bps": 1.0,
        "min_abs_return_bps": 25.0,
        "weight": 0.25,
        "hold_bars": 3,
    }
    values.update(overrides)
    return values


def test_generate_signals_returns_empty_for_empty_input():
    assert generate_signals([], {}) == []


def test_generate_signals_requires_expected_crypto_fields():
    with pytest.raises(ValueError, match="missing required"):
        generate_signals([{"symbol": "BTC-PERP", "timestamp": START}], params())


def test_generate_signals_fades_same_direction_funding_and_return_extremes():
    bars = (
        symbol_rows("BTC-PERP", 100.0, 101.0, 102.0, 0.0002)
        + symbol_rows("ETH-PERP", 100.0, 99.0, 98.0, -0.0002)
        + symbol_rows("SOL-PERP", 100.0, 99.0, 99.0, 0.0002)
        + symbol_rows("XRP-PERP", 100.0, 101.0, 101.0, 0.00005)
    )

    signals = sorted(generate_signals(bars, params()), key=lambda item: str(item["symbol"]))

    assert signals == [
        {
            "symbol": "BTC-PERP",
            "decision_time": START + timedelta(minutes=11),
            "as_of_time": START + timedelta(minutes=10),
            "side": "short",
            "weight": 0.25,
            "hold_bars": 3,
            "max_hold_bars": 3,
            "funding_pressure_bps": pytest.approx(2.0),
            "entry_return_extension_bps": pytest.approx(100.0),
            "signal_family": "crypto_perp_funding_crowding_reversal",
        },
        {
            "symbol": "ETH-PERP",
            "decision_time": START + timedelta(minutes=11),
            "as_of_time": START + timedelta(minutes=10),
            "side": "long",
            "weight": 0.25,
            "hold_bars": 3,
            "max_hold_bars": 3,
            "funding_pressure_bps": pytest.approx(-2.0),
            "entry_return_extension_bps": pytest.approx(-100.0),
            "signal_family": "crypto_perp_funding_crowding_reversal",
        },
    ]


def test_generate_signals_enforces_minimum_cross_section():
    bars = (
        symbol_rows("BTC-PERP", 100.0, 101.0, 101.0, 0.0002)
        + symbol_rows("ETH-PERP", 100.0, 99.0, 99.0, -0.0002)
        + symbol_rows("SOL-PERP", 100.0, 101.0, 101.0, 0.0002)
    )

    assert generate_signals(bars, params(min_cross_section=4)) == []


def test_generate_signals_uses_completed_prior_close_not_decision_close():
    bars = symbol_rows("BTC-PERP", 100.0, 100.0, 200.0, 0.0003)

    assert generate_signals(bars, params(min_cross_section=1)) == []


def test_generate_signals_allows_explicit_zero_decision_lag():
    bars = symbol_rows("BTC-PERP", 100.0, 101.0, 102.0, 0.0003)

    signals = generate_signals(bars, params(min_cross_section=1, decision_lag_minutes=0))

    assert signals[0]["decision_time"] == START + timedelta(minutes=10)
    assert signals[0]["as_of_time"] == START + timedelta(minutes=10)


def test_generate_signals_excludes_future_funding_events():
    bars = [
        bar("BTC-PERP", 0, 100.0),
        bar("BTC-PERP", 9, 101.0, funding_rate=0.0003, funding_minute=20, has_funding_event=True),
        bar("BTC-PERP", 10, 101.0),
    ]

    assert generate_signals(bars, params(min_cross_section=1)) == []


def test_generate_signals_requires_complete_funding_lookback():
    bars = symbol_rows("BTC-PERP", 100.0, 101.0, 101.0, 0.0003)

    assert generate_signals(bars, params(min_cross_section=1, funding_lookback_events=2)) == []


def test_generate_signals_emits_optional_exit_controls():
    bars = symbol_rows("BTC-PERP", 100.0, 101.0, 102.0, 0.0003)

    signals = generate_signals(
        bars,
        params(
            min_cross_section=1,
            max_hold_bars=7,
            take_profit_bps=150.0,
            stop_loss_bps=80.0,
            trailing_stop_bps=40.0,
        ),
    )

    assert signals[0]["max_hold_bars"] == 7
    assert signals[0]["take_profit_bps"] == 150.0
    assert signals[0]["stop_loss_bps"] == 80.0
    assert signals[0]["trailing_stop_bps"] == 40.0
