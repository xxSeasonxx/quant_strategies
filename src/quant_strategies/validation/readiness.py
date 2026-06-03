from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from quant_strategies.decisions import StrategyDecision


_INFERRED_REQUIRED_FIELDS_BY_DATA_KIND = {
    "crypto_perp_funding": (
        "close",
        "funding_timestamp",
        "funding_rate",
        "has_funding_event",
    ),
}


def check_validation_readiness(
    decisions: Sequence[StrategyDecision],
    readiness: Any,
    *,
    data_kind: str = "bars",
) -> tuple[str, ...]:
    violations: list[str] = []
    minimum = int(readiness.min_observations_per_decision)
    minimum_distinct_symbols = int(readiness.min_distinct_observation_symbols_per_decision)
    required_fields = _effective_required_fields(
        tuple(readiness.required_observation_fields),
        data_kind=data_kind,
    )

    for index, decision in enumerate(decisions):
        observations = tuple(decision.observations)
        if len(observations) < minimum:
            violations.append(
                f"decision[{index}] has {len(observations)} observations; "
                f"requires at least {minimum}"
            )
        distinct_symbols = {item.symbol for item in observations}
        if len(distinct_symbols) < minimum_distinct_symbols:
            violations.append(
                f"decision[{index}] has {len(distinct_symbols)} distinct observation symbols; "
                f"requires at least {minimum_distinct_symbols}"
            )
        observed_fields = {item.field for item in observations if item.field is not None}
        missing_fields = sorted(set(required_fields).difference(observed_fields))
        if missing_fields:
            violations.append(
                f"decision[{index}] missing required observation fields: {missing_fields}"
            )

    return tuple(violations)


def _effective_required_fields(required_fields: tuple[str, ...], *, data_kind: str) -> tuple[str, ...]:
    inferred = _INFERRED_REQUIRED_FIELDS_BY_DATA_KIND.get(data_kind, ())
    return tuple(dict.fromkeys((*required_fields, *inferred)))
