from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from quant_strategies.decisions import StrategyDecision

_INFERRED_REQUIRED_FIELDS_BY_DATA_KIND = {
    "crypto_perp_funding": (
        "close",
        "funding_timestamp",
        "funding_rate",
        "has_funding_event",
    ),
}


class DecisionReadinessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    min_observations_per_decision: int = Field(default=1, ge=1)
    min_distinct_observation_symbols_per_decision: int = Field(default=1, ge=1)
    required_observation_fields: tuple[str, ...] = ()

    @field_validator("required_observation_fields")
    @classmethod
    def normalize_required_fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        fields = tuple(field.strip() for field in value)
        if any(not field for field in fields):
            raise ValueError("readiness.required_observation_fields cannot contain empty fields")
        if len(fields) != len(set(fields)):
            raise ValueError("readiness.required_observation_fields cannot contain duplicates")
        return fields


def check_decision_readiness(
    decisions: Sequence[StrategyDecision],
    readiness: DecisionReadinessConfig,
    *,
    data_kind: str = "bars",
    include_inferred_data_kind_fields: bool = True,
) -> tuple[str, ...]:
    violations: list[str] = []
    minimum = int(readiness.min_observations_per_decision)
    minimum_distinct_symbols = int(readiness.min_distinct_observation_symbols_per_decision)
    required_fields = _effective_required_fields(
        tuple(readiness.required_observation_fields),
        data_kind=data_kind,
        include_inferred_data_kind_fields=include_inferred_data_kind_fields,
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


def _effective_required_fields(
    required_fields: tuple[str, ...],
    *,
    data_kind: str,
    include_inferred_data_kind_fields: bool,
) -> tuple[str, ...]:
    inferred = (
        _INFERRED_REQUIRED_FIELDS_BY_DATA_KIND.get(data_kind, ())
        if include_inferred_data_kind_fields
        else ()
    )
    return tuple(dict.fromkeys((*required_fields, *inferred)))
