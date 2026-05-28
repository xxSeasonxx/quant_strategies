from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator

from quant_strategies.decisions.models import (
    DecisionIntent as BaseDecisionIntent,
    DecisionModel,
    Direction,
    ExitPolicy,
    InstrumentRef,
    ObservationRef,
    PositionTarget as BasePositionTarget,
    StrategyDecision as BaseStrategyDecision,
    _finite_positive,
    _stripped_non_empty,
    _timezone_aware,
)


LegDirection = Literal["long", "short"]
BookSide = Literal["buy", "sell"]
DecisionAction = Literal["open", "close", "adjust", "roll"]
SizingKind = Literal["target_weight", "target_notional", "target_contracts", "target_vol"]
Settlement = Literal["cash", "physical"]
OptionType = Literal["call", "put"]


class FutureRef(DecisionModel):
    kind: Literal["future"]
    symbol: str
    expiry: datetime
    multiplier: float = Field(gt=0)
    settlement: Settlement

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return _stripped_non_empty(value, "symbol")

    @field_validator("expiry")
    @classmethod
    def validate_expiry(cls, value: datetime) -> datetime:
        return _timezone_aware(value, "expiry")

    @field_validator("multiplier")
    @classmethod
    def validate_multiplier(cls, value: float) -> float:
        return _finite_positive(value, "multiplier")


class OptionRef(DecisionModel):
    kind: Literal["option"]
    symbol: str
    underlying_symbol: str
    option_type: OptionType
    strike: float = Field(gt=0)
    expiry: datetime
    multiplier: float = Field(gt=0)
    settlement: Settlement

    @field_validator("symbol", "underlying_symbol")
    @classmethod
    def validate_symbol(cls, value: str, info) -> str:
        return _stripped_non_empty(value, info.field_name)

    @field_validator("expiry")
    @classmethod
    def validate_expiry(cls, value: datetime) -> datetime:
        return _timezone_aware(value, "expiry")

    @field_validator("strike")
    @classmethod
    def validate_strike(cls, value: float) -> float:
        return _finite_positive(value, "strike")

    @field_validator("multiplier")
    @classmethod
    def validate_multiplier(cls, value: float) -> float:
        return _finite_positive(value, "multiplier")


SingleInstrumentRef = Annotated[InstrumentRef | FutureRef | OptionRef, Field(discriminator="kind")]


class InstrumentLeg(DecisionModel):
    instrument: SingleInstrumentRef
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
    InstrumentRef | FutureRef | OptionRef | MultiLegInstrumentRef,
    Field(discriminator="kind"),
]


class DecisionIntent(BaseDecisionIntent):
    action: DecisionAction = "open"
    book_side: BookSide | None = None


class PositionTarget(BasePositionTarget):
    direction: Direction
    sizing_kind: SizingKind = "target_weight"


class StrategyDecision(BaseStrategyDecision):
    instrument: DecisionInstrument
    intent: DecisionIntent = Field(default_factory=DecisionIntent)
    target: PositionTarget


__all__ = [
    "BookSide",
    "DecisionAction",
    "DecisionIntent",
    "DecisionInstrument",
    "FutureRef",
    "InstrumentLeg",
    "LegDirection",
    "MultiLegInstrumentRef",
    "OptionRef",
    "OptionType",
    "PositionTarget",
    "Settlement",
    "SingleInstrumentRef",
    "SizingKind",
    "StrategyDecision",
]
