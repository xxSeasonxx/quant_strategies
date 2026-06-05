from __future__ import annotations

# Pydantic ontology classes intentionally expose validated fields, not methods.
# pylint: disable=too-few-public-methods
from typing import Annotated, Literal

from pydantic import Field, field_validator

from quant_strategies.decisions.models import (
    DecisionIntent as BaseDecisionIntent,
)
from quant_strategies.decisions.models import (
    DecisionModel,
    Direction,
    InstrumentRef,
    _finite_positive,
    _stripped_non_empty,
)
from quant_strategies.decisions.models import (
    PositionTarget as BasePositionTarget,
)
from quant_strategies.decisions.models import (
    StrategyDecision as BaseStrategyDecision,
)

LegDirection = Literal["long", "short"]
DecisionAction = Literal["open"]
SizingKind = Literal["target_weight"]


class InstrumentLeg(DecisionModel):
    instrument: InstrumentRef
    direction: LegDirection
    ratio: float = Field(gt=0)

    @field_validator("ratio")
    @classmethod
    def validate_ratio(cls, value: float) -> float:
        return _finite_positive(value, "ratio")


class MultiLegInstrumentRef(DecisionModel):
    kind: Literal["multi_leg"]
    symbol: str
    legs: tuple[InstrumentLeg, ...] = Field(min_length=2)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return _stripped_non_empty(value, "symbol")


DecisionInstrument = Annotated[
    InstrumentRef | MultiLegInstrumentRef,
    Field(discriminator="kind"),
]


class DecisionIntent(BaseDecisionIntent):
    action: DecisionAction = "open"


class PositionTarget(BasePositionTarget):
    direction: Direction
    sizing_kind: SizingKind = "target_weight"


class StrategyDecision(BaseStrategyDecision):
    instrument: DecisionInstrument
    intent: DecisionIntent = Field(default_factory=DecisionIntent)
    target: PositionTarget


__all__ = [
    "DecisionAction",
    "DecisionInstrument",
    "DecisionIntent",
    "InstrumentLeg",
    "LegDirection",
    "MultiLegInstrumentRef",
    "PositionTarget",
    "SizingKind",
    "StrategyDecision",
]
