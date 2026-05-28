from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from quant_strategies.datetime_utils import parse_aware_datetime
from quant_strategies.runner.errors import DataReadinessError


AVAILABILITY_FIELD = "available_at"
SIGNAL_AS_OF_FIELD = "as_of_time"


def assert_decision_rows_ready(
    rows: list[dict[str, Any]],
    signals: list[dict[str, Any]],
) -> None:
    rows_by_key: dict[tuple[str, datetime], list[Mapping[str, Any]]] = {}
    for row in rows:
        timestamp = _matching_datetime(row.get("timestamp"), "timestamp")
        if timestamp is None:
            continue
        rows_by_key.setdefault((str(row.get("symbol", "")), timestamp), []).append(row)

    for signal in signals:
        decision_time = _matching_datetime(signal.get("decision_time"), "decision_time")
        if decision_time is None:
            continue
        as_of_time = _signal_as_of_time(signal, decision_time)
        if as_of_time > decision_time:
            raise DataReadinessError(
                f"{SIGNAL_AS_OF_FIELD} for {signal.get('symbol', '<unknown>')} "
                f"must be at or before decision_time"
            )
        symbol = str(signal.get("symbol", ""))
        matching_rows = rows_by_key.get((symbol, as_of_time), [])
        if SIGNAL_AS_OF_FIELD in signal and not matching_rows:
            raise DataReadinessError(
                f"{SIGNAL_AS_OF_FIELD} does not match a row timestamp for "
                f"{symbol}: {as_of_time.isoformat()}"
            )
        for row in matching_rows:
            _assert_row_ready(row, symbol=symbol, as_of_time=as_of_time, decision_time=decision_time)


def _signal_as_of_time(signal: Mapping[str, Any], decision_time: datetime) -> datetime:
    value = signal.get(SIGNAL_AS_OF_FIELD)
    if _is_missing(value):
        return decision_time
    return _parse_datetime(value, SIGNAL_AS_OF_FIELD)


def _assert_row_ready(
    row: Mapping[str, Any],
    *,
    symbol: str,
    as_of_time: datetime,
    decision_time: datetime,
) -> None:
    ready_at = _optional_datetime(row.get(AVAILABILITY_FIELD))
    if ready_at is not None and ready_at > decision_time:
        raise DataReadinessError(
            f"{AVAILABILITY_FIELD} for {symbol} as_of_time {as_of_time.isoformat()} "
            f"is available after decision_time {decision_time.isoformat()}: {ready_at.isoformat()}"
        )


def _matching_datetime(value: object, field_name: str) -> datetime | None:
    try:
        return _parse_datetime(value, field_name)
    except DataReadinessError:
        return None


def _optional_datetime(value: object) -> datetime | None:
    if _is_missing(value):
        return None
    parsed, _ = parse_aware_datetime(value)
    return parsed


def _parse_datetime(value: object, field_name: str) -> datetime | None:
    if _is_missing(value):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DataReadinessError(f"{field_name} must be a valid ISO timestamp") from exc
    else:
        raise DataReadinessError(f"{field_name} must be a datetime or ISO timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DataReadinessError(f"{field_name} must be timezone-aware")
    return parsed


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if type(value).__name__ in {"NaTType", "NAType"}:
        return True
    try:
        return bool(value != value)
    except (TypeError, ValueError):
        return False
