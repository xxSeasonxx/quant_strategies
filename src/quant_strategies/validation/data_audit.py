from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from quant_strategies.decisions import StrategyDecision


class DataAudit(BaseModel):
    model_config = ConfigDict(frozen=True)

    row_count: int
    decision_count: int
    passed: bool
    violations: tuple[str, ...] = ()


def _parse_aware_datetime(value: Any) -> tuple[datetime | None, str | None]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        raw_value = value.strip()
        if raw_value.endswith("Z"):
            raw_value = f"{raw_value[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(raw_value)
        except ValueError:
            return None, "invalid datetime"
    else:
        return None, "expected aware datetime"

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None, "expected aware datetime"
    return parsed, None


def audit_decision_rows(rows: list[dict[str, Any]], decisions: list[StrategyDecision]) -> DataAudit:
    violations: list[str] = []
    row_index: dict[tuple[str, datetime], list[dict[str, Any]]] = {}
    for row in rows:
        symbol = str(row.get("symbol"))
        timestamp, reason = _parse_aware_datetime(row.get("timestamp"))
        if timestamp is None:
            violations.append(f"invalid timestamp for {symbol}: {reason}")
            continue
        row_index.setdefault((symbol, timestamp), []).append(row)

    for decision in decisions:
        key = (decision.instrument.symbol, decision.as_of_time)
        matching_rows = row_index.get(key, [])
        if not matching_rows:
            violations.append(
                f"missing as_of row for {decision.instrument.symbol} at {decision.as_of_time.isoformat()}"
            )
            continue
        if len(matching_rows) > 1:
            violations.append(
                f"duplicate as_of rows for {decision.instrument.symbol} at {decision.as_of_time.isoformat()}"
            )
        for row in matching_rows:
            if "available_at" not in row or row.get("available_at") is None:
                violations.append(
                    f"missing available_at for {decision.instrument.symbol} at {decision.as_of_time.isoformat()}"
                )
                continue
            available_at, reason = _parse_aware_datetime(row.get("available_at"))
            if available_at is None:
                violations.append(
                    f"invalid available_at for {decision.instrument.symbol} at "
                    f"{decision.as_of_time.isoformat()}: {reason}"
                )
                continue
            if available_at > decision.decision_time:
                violations.append(
                    f"as_of row for {decision.instrument.symbol} at {decision.as_of_time.isoformat()} "
                    "was available after decision_time"
                )

    return DataAudit(
        row_count=len(rows),
        decision_count=len(decisions),
        passed=not violations,
        violations=tuple(violations),
    )
