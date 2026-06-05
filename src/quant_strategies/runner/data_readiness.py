from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from quant_strategies.core.errors import DataReadinessError
from quant_strategies.data_contract import NormalizedRows
from quant_strategies.datetime_utils import parse_aware_datetime
from quant_strategies.decisions import StrategyDecision

AVAILABILITY_FIELD = "available_at"
DECISION_AS_OF_FIELD = "as_of_time"


def assert_decision_rows_ready(
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
    decisions: list[StrategyDecision],
) -> None:
    if isinstance(rows, NormalizedRows):
        _assert_normalized_decision_rows_ready(rows, decisions)
        return

    rows_by_key: dict[tuple[str, datetime], list[Mapping[str, Any]]] = {}
    for row in rows:
        timestamp = _matching_datetime(row.get("timestamp"), "timestamp")
        if timestamp is None:
            continue
        rows_by_key.setdefault((str(row.get("symbol", "")), timestamp), []).append(row)

    for decision in decisions:
        decision_time = decision.decision_time
        as_of_time = decision.as_of_time
        if as_of_time > decision_time:
            raise DataReadinessError(
                f"{DECISION_AS_OF_FIELD} for {decision.instrument.symbol} "
                f"must be at or before decision_time"
            )
        symbol = decision.instrument.symbol
        matching_rows = rows_by_key.get((symbol, as_of_time), [])
        if not matching_rows:
            raise DataReadinessError(
                f"{DECISION_AS_OF_FIELD} does not match a row timestamp for "
                f"{symbol}: {as_of_time.isoformat()}"
            )
        for row in matching_rows:
            _assert_row_ready(
                row, symbol=symbol, as_of_time=as_of_time, decision_time=decision_time
            )


def _assert_normalized_decision_rows_ready(
    normalized_rows: NormalizedRows,
    decisions: list[StrategyDecision],
) -> None:
    rows_by_key: dict[tuple[str, datetime], list[Mapping[str, Any]]] = {}
    for row in normalized_rows.projection_rows():
        timestamp = row.get("timestamp")
        if not _is_aware_datetime(timestamp):
            continue
        rows_by_key.setdefault((str(row.get("symbol", "")), timestamp), []).append(row)

    for decision in decisions:
        decision_time = decision.decision_time
        as_of_time = decision.as_of_time
        if as_of_time > decision_time:
            raise DataReadinessError(
                f"{DECISION_AS_OF_FIELD} for {decision.instrument.symbol} "
                f"must be at or before decision_time"
            )
        symbol = decision.instrument.symbol
        matching_rows = rows_by_key.get((symbol, as_of_time), [])
        if not matching_rows:
            raise DataReadinessError(
                f"{DECISION_AS_OF_FIELD} does not match a row timestamp for "
                f"{symbol}: {as_of_time.isoformat()}"
            )
        for row in matching_rows:
            _assert_normalized_row_ready(
                row,
                symbol=symbol,
                as_of_time=as_of_time,
                decision_time=decision_time,
            )


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


def _assert_normalized_row_ready(
    row: Mapping[str, Any],
    *,
    symbol: str,
    as_of_time: datetime,
    decision_time: datetime,
) -> None:
    ready_at = row.get(AVAILABILITY_FIELD)
    if _is_aware_datetime(ready_at) and ready_at > decision_time:
        raise DataReadinessError(
            f"{AVAILABILITY_FIELD} for {symbol} as_of_time {as_of_time.isoformat()} "
            f"is available after decision_time {decision_time.isoformat()}: {ready_at.isoformat()}"
        )


def _is_aware_datetime(value: object) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
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
