from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from quant_strategies.decisions import StrategyDecision
from quant_strategies.validation.datetime_utils import parse_aware_datetime


def audit_observation_dependencies(
    row_index: dict[tuple[str, datetime], list[Mapping[str, Any]]],
    decisions: list[StrategyDecision],
) -> tuple[str, ...]:
    violations: list[str] = []

    for decision in decisions:
        for observation in decision.observations:
            label = f"{observation.symbol} at {observation.timestamp.isoformat()}"
            if observation.timestamp > decision.as_of_time:
                violations.append(
                    f"observation for {decision.instrument.symbol} references future row {label}"
                )
                continue

            matching_rows = row_index.get((observation.symbol, observation.timestamp), [])
            if not matching_rows:
                violations.append(
                    f"missing observation row for {decision.instrument.symbol}: {label}"
                )
                continue

            for row in matching_rows:
                if observation.field is not None and row.get(observation.field) is None:
                    violations.append(
                        f"missing observation field {observation.field} for {label} "
                        f"used by {decision.instrument.symbol}"
                    )
                if "available_at" not in row or row.get("available_at") is None:
                    violations.append(
                        f"missing available_at for observation {label} used by {decision.instrument.symbol}"
                    )
                    continue
                available_at, reason = parse_aware_datetime(row.get("available_at"))
                if available_at is None:
                    violations.append(
                        f"invalid available_at for observation {label} used by "
                        f"{decision.instrument.symbol}: {reason}"
                    )
                    continue
                if available_at > decision.decision_time:
                    violations.append(
                        f"observation row {label} used by {decision.instrument.symbol} "
                        "was available after decision_time"
                    )

    return tuple(violations)
