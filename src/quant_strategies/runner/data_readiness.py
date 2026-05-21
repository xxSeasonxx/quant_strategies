from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from quant_strategies.runner.errors import DataReadinessError


READINESS_FIELDS = (
    "available_at",
    "bar_ingested_at",
    "quote_ingested_at",
    "funding_ingested_at",
    "joined_refreshed_at",
)


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
        symbol = str(signal.get("symbol", ""))
        for row in rows_by_key.get((symbol, decision_time), []):
            _assert_row_ready(row, symbol=symbol, decision_time=decision_time)


def _assert_row_ready(row: Mapping[str, Any], *, symbol: str, decision_time: datetime) -> None:
    for field in READINESS_FIELDS:
        ready_at = _optional_datetime(row.get(field), field)
        if ready_at is not None and ready_at > decision_time:
            raise DataReadinessError(
                f"{field} for {symbol} at {decision_time.isoformat()} "
                f"is available after decision_time: {ready_at.isoformat()}"
            )


def _matching_datetime(value: object, field_name: str) -> datetime | None:
    try:
        return _parse_datetime(value, field_name)
    except DataReadinessError:
        return None


def _optional_datetime(value: object, field_name: str) -> datetime | None:
    return _parse_datetime(value, field_name)


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
