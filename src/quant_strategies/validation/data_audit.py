from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from quant_strategies.decisions import StrategyDecision
from quant_strategies.observation_dependencies import (
    audit_observation_dependencies,
    observation_row_index,
)
from quant_strategies.validation.datetime_utils import parse_aware_datetime


class DataAudit(BaseModel):
    model_config = ConfigDict(frozen=True)

    row_count: int
    decision_count: int
    passed: bool
    violations: tuple[str, ...] = ()


def audit_decision_rows(
    rows: Sequence[Mapping[str, Any]],
    decisions: list[StrategyDecision],
) -> DataAudit:
    violations: list[str] = []
    row_index, timestamp_violations = observation_row_index(rows)
    violations.extend(timestamp_violations)

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
            available_at, reason = parse_aware_datetime(row.get("available_at"))
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

    violations.extend(audit_observation_dependencies(row_index, decisions))

    return DataAudit(
        row_count=len(rows),
        decision_count=len(decisions),
        passed=not violations,
        violations=tuple(violations),
    )
