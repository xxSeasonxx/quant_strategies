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


def audit_decision_rows(rows: list[dict[str, Any]], decisions: list[StrategyDecision]) -> DataAudit:
    row_index = {(str(row.get("symbol")), row.get("timestamp")): row for row in rows}
    violations: list[str] = []
    for decision in decisions:
        key = (decision.instrument.symbol, decision.as_of_time)
        row = row_index.get(key)
        if row is None:
            violations.append(
                f"missing as_of row for {decision.instrument.symbol} at {decision.as_of_time.isoformat()}"
            )
            continue
        available_at = row.get("available_at")
        if isinstance(available_at, datetime) and available_at > decision.decision_time:
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
