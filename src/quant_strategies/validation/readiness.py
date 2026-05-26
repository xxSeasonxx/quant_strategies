from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from quant_strategies.decisions import StrategyDecision


def check_validation_readiness(
    decisions: Sequence[StrategyDecision],
    readiness: Any,
) -> tuple[str, ...]:
    violations: list[str] = []
    minimum = int(readiness.min_observations_per_decision)
    required_fields = tuple(readiness.required_observation_fields)

    for index, decision in enumerate(decisions):
        observations = tuple(decision.observations)
        if len(observations) < minimum:
            violations.append(
                f"decision[{index}] has {len(observations)} observations; "
                f"requires at least {minimum}"
            )
        observed_fields = {item.field for item in observations if item.field is not None}
        missing_fields = sorted(set(required_fields).difference(observed_fields))
        if missing_fields:
            violations.append(
                f"decision[{index}] missing required observation fields: {missing_fields}"
            )

    return tuple(violations)
