from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import datetime


class FundingEventError(ValueError):
    """Raised when funding cashflow rows cannot be evaluated safely."""


def has_funding_cashflow_rows(rows: Iterable[Mapping[str, object]]) -> bool:
    return any(
        row.get("has_funding_event") is True
        or row.get("funding_rate") is not None
        or row.get("funding_timestamp") is not None
        for row in rows
    )


def funding_return_for_window(
    rows: Iterable[Mapping[str, object]],
    symbol: str,
    entry_time: datetime,
    exit_time: datetime,
    direction: str,
    weight: float,
) -> float:
    _require_aware_datetime(entry_time, "entry_time")
    _require_aware_datetime(exit_time, "exit_time")
    if direction not in {"long", "short"}:
        raise FundingEventError("direction must be 'long' or 'short'")

    numeric_weight = _finite_number(weight, "weight")
    if numeric_weight < 0:
        raise FundingEventError("weight must be finite and >= 0")

    funding_rates_by_time: dict[datetime, float] = {}
    for row in rows:
        if row.get("symbol") != symbol or not _has_funding_event_fields(row):
            continue

        funding_timestamp = _funding_timestamp(row)
        funding_rate = _funding_rate(row)
        if not entry_time < funding_timestamp <= exit_time:
            continue

        existing_rate = funding_rates_by_time.get(funding_timestamp)
        if existing_rate is None:
            funding_rates_by_time[funding_timestamp] = funding_rate
        elif existing_rate != funding_rate:
            raise FundingEventError(
                f"conflicting funding rates for {symbol} at {funding_timestamp.isoformat()}"
            )

    side_multiplier = 1 if direction == "long" else -1
    return sum(-side_multiplier * rate for rate in funding_rates_by_time.values()) * numeric_weight


def _has_funding_event_fields(row: Mapping[str, object]) -> bool:
    return (
        row.get("has_funding_event") is True
        or row.get("funding_rate") is not None
        or row.get("funding_timestamp") is not None
    )


def _funding_timestamp(row: Mapping[str, object]) -> datetime:
    value = row.get("funding_timestamp")
    if value is None:
        raise FundingEventError("incomplete funding event: missing funding_timestamp")
    return _require_aware_datetime(value, "funding_timestamp")


def _funding_rate(row: Mapping[str, object]) -> float:
    value = row.get("funding_rate")
    if value is None:
        raise FundingEventError("incomplete funding event: missing funding_rate")
    return _finite_number(value, "funding_rate")


def _require_aware_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise FundingEventError(f"{field_name} must be a timezone-aware datetime")
    return value


def _finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool):
        raise FundingEventError(f"{field_name} must be finite")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise FundingEventError(f"{field_name} must be finite") from exc
    if not math.isfinite(number):
        raise FundingEventError(f"{field_name} must be finite")
    return number
