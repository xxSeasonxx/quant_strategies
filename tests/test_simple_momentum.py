from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tested.simple_momentum import generate_signals


def bars_for(closes: list[float]) -> list[dict[str, object]]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        {
            "symbol": "DEMO",
            "timestamp": start + timedelta(days=index),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
        }
        for index, close in enumerate(closes)
    ]


def test_generate_signals_emits_long_after_positive_close_change():
    signals = generate_signals(bars_for([100.0, 101.0, 100.0]), {"weight": 1.0, "hold_bars": 1})

    assert signals == [
        {
            "symbol": "DEMO",
            "decision_time": datetime(2024, 1, 2, tzinfo=timezone.utc),
            "side": "long",
            "weight": 1.0,
            "hold_bars": 1,
        }
    ]


def test_generate_signals_uses_current_bar_as_decision_time_without_lookahead():
    signals = generate_signals(bars_for([100.0, 99.0, 101.0, 100.0]), {"weight": 0.5, "hold_bars": 2})

    assert signals == [
        {
            "symbol": "DEMO",
            "decision_time": datetime(2024, 1, 3, tzinfo=timezone.utc),
            "side": "long",
            "weight": 0.5,
            "hold_bars": 2,
        }
    ]


def test_generate_signals_stops_after_first_positive_close_change():
    signals = generate_signals(bars_for([100.0, 101.0, 102.0, 103.0]), {"weight": 1.0, "hold_bars": 1})

    assert signals == [
        {
            "symbol": "DEMO",
            "decision_time": datetime(2024, 1, 2, tzinfo=timezone.utc),
            "side": "long",
            "weight": 1.0,
            "hold_bars": 1,
        }
    ]


def test_generate_signals_returns_empty_list_for_degenerate_inputs():
    assert generate_signals([], {}) == []
    assert generate_signals(bars_for([100.0]), {}) == []


def test_generate_signals_returns_empty_list_without_positive_close_change():
    assert generate_signals(bars_for([100.0, 100.0, 99.0]), {}) == []
