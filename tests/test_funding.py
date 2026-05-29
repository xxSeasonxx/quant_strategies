from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from quant_strategies.engine.bar_index import build_bar_index
from quant_strategies.engine.evaluation import EvaluationError, _funding_return
from quant_strategies.engine.models import Bar, Side
from quant_strategies.funding import funding_rates_match, funding_return_over_window

START = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def _ts(minute: int) -> datetime:
    return START + timedelta(minutes=minute)


def _conflict(ts: datetime) -> Exception:
    return ValueError(f"conflicting funding rates at {ts.isoformat()}")


# --- the shared funding-window function (single source of the invariants) ----


@pytest.mark.parametrize(
    "direction_sign, expected",
    [(1.0, -0.00015), (-1.0, 0.00015)],
)
def test_sign_convention_long_pays_short_receives(direction_sign: float, expected: float):
    result = funding_return_over_window(
        [(_ts(1), 0.0003)],
        entry_time=_ts(0),
        exit_time=_ts(2),
        direction_sign=direction_sign,
        weight=0.5,
        conflict_error=_conflict,
    )
    assert result == pytest.approx(expected)


def test_window_is_entry_exclusive_and_exit_inclusive():
    events = [(_ts(1), 0.001), (_ts(2), 0.002), (_ts(3), 0.003)]
    result = funding_return_over_window(
        events,
        entry_time=_ts(1),  # minute 1 excluded
        exit_time=_ts(3),  # minute 3 included
        direction_sign=-1.0,
        weight=1.0,
        conflict_error=_conflict,
    )
    assert result == pytest.approx(0.002 + 0.003)


def test_duplicate_matching_timestamp_counted_once():
    events = [(_ts(1), 0.0002), (_ts(1), 0.0002)]
    result = funding_return_over_window(
        events,
        entry_time=_ts(0),
        exit_time=_ts(2),
        direction_sign=-1.0,
        weight=1.0,
        conflict_error=_conflict,
    )
    assert result == pytest.approx(0.0002)


def test_conflicting_duplicate_timestamp_raises_via_callback():
    events = [(_ts(1), 0.0002), (_ts(1), 0.0003)]
    with pytest.raises(ValueError, match="conflicting funding rates"):
        funding_return_over_window(
            events,
            entry_time=_ts(0),
            exit_time=_ts(2),
            direction_sign=-1.0,
            weight=1.0,
            conflict_error=_conflict,
        )


def test_weight_scales_and_empty_window_is_zero():
    assert (
        funding_return_over_window(
            [],
            entry_time=_ts(0),
            exit_time=_ts(2),
            direction_sign=1.0,
            weight=1.0,
            conflict_error=_conflict,
        )
        == 0.0
    )
    assert funding_return_over_window(
        [(_ts(1), 0.001)],
        entry_time=_ts(0),
        exit_time=_ts(2),
        direction_sign=-1.0,
        weight=2.0,
        conflict_error=_conflict,
    ) == pytest.approx(0.002)


def test_funding_rates_match_tolerance():
    assert funding_rates_match(0.0002, 0.0002 + 5e-13)
    assert not funding_rates_match(0.0002, 0.0003)


# --- the engine adapter (Bar-sourced) over the same shared function -----------


def _engine_indexed(events: list[tuple[int, int, float]]):
    bars = tuple(
        Bar(
            symbol="BTC-PERP",
            timestamp=_ts(bar_minute),
            open=100.0,
            high=100.0,
            low=100.0,
            close=100.0,
            funding_timestamp=_ts(funding_minute),
            funding_rate=rate,
            has_funding_event=True,
        )
        for bar_minute, funding_minute, rate in events
    )
    return build_bar_index(bars, error_factory=EvaluationError)


def test_engine_funding_adapter_signs_and_dedups():
    indexed = _engine_indexed([(1, 1, 0.0002), (2, 1, 0.0002)])  # same funding ts, two bars
    short = _funding_return(indexed, "BTC-PERP", _ts(0), _ts(3), Side.SHORT, 1.0)
    long = _funding_return(indexed, "BTC-PERP", _ts(0), _ts(3), Side.LONG, 1.0)
    assert short == pytest.approx(0.0002)  # short receives positive funding, counted once
    assert long == pytest.approx(-0.0002)
