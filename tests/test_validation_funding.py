from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from quant_strategies.validation.funding import (
    FundingEventError,
    funding_return_for_window,
    has_funding_cashflow_rows,
)


START = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def row(
    minute: int,
    *,
    symbol: str = "BTC-PERP",
    funding_rate: float | None = None,
    funding_minute: int | None = None,
    has_funding_event: bool = False,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timestamp": START + timedelta(minutes=minute),
        "close": 100.0,
        "funding_timestamp": START + timedelta(minutes=funding_minute)
        if funding_minute is not None
        else None,
        "funding_rate": funding_rate,
        "has_funding_event": has_funding_event,
    }


def test_has_funding_cashflow_rows_detects_event_fields():
    assert has_funding_cashflow_rows([row(0)]) is False
    assert has_funding_cashflow_rows([row(0, funding_rate=0.0001)]) is True
    assert has_funding_cashflow_rows([row(0, funding_minute=0)]) is True
    assert has_funding_cashflow_rows([row(0, has_funding_event=True)]) is True


def test_long_pays_positive_funding_and_short_receives_it():
    rows = [row(1, funding_rate=0.0003, funding_minute=1, has_funding_event=True)]

    long_return = funding_return_for_window(
        rows,
        symbol="BTC-PERP",
        entry_time=START,
        exit_time=START + timedelta(minutes=2),
        direction="long",
        weight=0.5,
    )
    short_return = funding_return_for_window(
        rows,
        symbol="BTC-PERP",
        entry_time=START,
        exit_time=START + timedelta(minutes=2),
        direction="short",
        weight=0.5,
    )

    assert long_return == pytest.approx(-0.00015)
    assert short_return == pytest.approx(0.00015)


def test_funding_window_is_entry_exclusive_and_exit_inclusive():
    rows = [
        row(0, funding_rate=0.0010, funding_minute=0, has_funding_event=True),
        row(1, funding_rate=0.0020, funding_minute=1, has_funding_event=True),
        row(2, funding_rate=0.0030, funding_minute=2, has_funding_event=True),
        row(3, funding_rate=0.0040, funding_minute=3, has_funding_event=True),
    ]

    result = funding_return_for_window(
        rows,
        symbol="BTC-PERP",
        entry_time=START + timedelta(minutes=1),
        exit_time=START + timedelta(minutes=2),
        direction="short",
        weight=1.0,
    )

    assert result == pytest.approx(0.0030)


def test_funding_symbol_matching_strips_row_symbol_whitespace():
    rows = [row(1, symbol=" BTC-PERP ", funding_rate=0.0002, funding_minute=1, has_funding_event=True)]

    result = funding_return_for_window(
        rows,
        symbol="BTC-PERP",
        entry_time=START,
        exit_time=START + timedelta(minutes=2),
        direction="short",
        weight=1.0,
    )

    assert result == pytest.approx(0.0002)


def test_funding_observables_without_event_flag_do_not_create_cashflow():
    rows = [
        row(1, funding_rate=0.0020, funding_minute=1, has_funding_event=False),
        row(2, funding_rate=0.0030, funding_minute=2, has_funding_event=True),
    ]

    result = funding_return_for_window(
        rows,
        symbol="BTC-PERP",
        entry_time=START,
        exit_time=START + timedelta(minutes=2),
        direction="short",
        weight=1.0,
    )

    assert result == pytest.approx(0.0030)


def test_duplicate_matching_funding_events_are_counted_once():
    rows = [
        row(1, funding_rate=0.0002, funding_minute=1, has_funding_event=True),
        row(1, funding_rate=0.0002, funding_minute=1, has_funding_event=True),
    ]

    result = funding_return_for_window(
        rows,
        symbol="BTC-PERP",
        entry_time=START,
        exit_time=START + timedelta(minutes=2),
        direction="short",
        weight=1.0,
    )

    assert result == pytest.approx(0.0002)


def test_near_equal_duplicate_funding_rates_are_counted_once():
    rows = [
        row(1, funding_rate=0.0002, funding_minute=1, has_funding_event=True),
        row(1, funding_rate=0.0002 + 5e-13, funding_minute=1, has_funding_event=True),
    ]

    result = funding_return_for_window(
        rows,
        symbol="BTC-PERP",
        entry_time=START,
        exit_time=START + timedelta(minutes=2),
        direction="short",
        weight=1.0,
    )

    assert result == pytest.approx(0.0002)


def test_conflicting_duplicate_funding_rates_fail_closed():
    rows = [
        row(1, funding_rate=0.0002, funding_minute=1, has_funding_event=True),
        row(1, funding_rate=0.0003, funding_minute=1, has_funding_event=True),
    ]

    with pytest.raises(FundingEventError, match="conflicting funding rates"):
        funding_return_for_window(
            rows,
            symbol="BTC-PERP",
            entry_time=START,
            exit_time=START + timedelta(minutes=2),
            direction="short",
            weight=1.0,
        )


def test_incomplete_funding_event_fails_closed():
    rows = [row(1, funding_rate=None, funding_minute=1, has_funding_event=True)]

    with pytest.raises(FundingEventError, match="incomplete funding event"):
        funding_return_for_window(
            rows,
            symbol="BTC-PERP",
            entry_time=START,
            exit_time=START + timedelta(minutes=2),
            direction="long",
            weight=1.0,
        )


def test_exit_before_entry_fails_closed():
    with pytest.raises(FundingEventError, match="exit_time must be on or after entry_time"):
        funding_return_for_window(
            [],
            symbol="BTC-PERP",
            entry_time=START + timedelta(minutes=2),
            exit_time=START,
            direction="long",
            weight=1.0,
        )
