"""Opt-in extended target-book vocabulary (PRD G1 staged extension).

The default contract (`decisions.models`) expresses the executable v1 path: a signed
weight-of-NAV ``TargetDecision`` over equity/ETF, FX, or crypto-perp instruments. This
module is the **explicit opt-in** extension reserved for futures, options, multi-leg
structures, and the target-notional / target-contracts / vol-targeted sizing axes that a
weight-of-NAV target alone cannot express. It is **not** imported by the default
`decisions` package surface, so the executable path never implies these axes are tradeable
(`test_default_import_boundary_excludes_extended_and_order_vocabulary`).

Status: staged extension, no production consumer. The engine has no executor or market
model for derivative instruments or alternate sizing units yet, so an emitted
``ExtendedTargetDecision`` is not feasible to score today. The models are kept import-clean
and re-based onto the ``TargetDecision`` contract so the multi-asset roadmap
(futures/options/multi-leg) extends this point rather than monkey-patching the foundation;
the executor + market model land with the asset-class follow-on, not here.
"""

from __future__ import annotations

# Pydantic ontology classes intentionally expose validated fields, not methods.
# pylint: disable=too-few-public-methods
import math
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

from quant_strategies.decisions.models import (
    DecisionModel,
    InstrumentRef,
    ObservationRef,
    RiskRule,
    _finite_positive,
    _stripped_non_empty,
)

LegDirection = Literal["long", "short"]
# Sizing units beyond the v1 weight-of-NAV target. ``target_weight`` keeps parity with the
# default contract; the others are the opt-in axes a derivative/multi-asset executor needs.
ExtendedSizingKind = Literal[
    "target_weight",
    "target_notional",
    "target_contracts",
    "vol_targeted",
]


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


class ExtendedTargetDecision(DecisionModel):
    """A standing target over the extended instrument/sizing vocabulary.

    Re-bases the default ``TargetDecision`` (signed weight-of-NAV, standing until changed,
    idempotent, with an optional engine-enforced ``RiskRule``) onto the opt-in axes: a
    multi-leg/derivative ``instrument`` and an explicit ``sizing_kind`` so ``target`` can be
    expressed in notional, contracts, or vol-targeted units rather than only weight-of-NAV.
    No executor consumes it yet (see module docstring).
    """

    decision_id: str | None = None
    strategy_id: str
    instrument: DecisionInstrument
    decision_time: datetime
    as_of_time: datetime
    target: float
    sizing_kind: ExtendedSizingKind = "target_weight"
    risk_rule: RiskRule | None = None
    observations: tuple[ObservationRef, ...] = ()
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("decision_id", "strategy_id")
    @classmethod
    def validate_text_id(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _stripped_non_empty(value, info.field_name)

    @field_validator("decision_time", "as_of_time")
    @classmethod
    def validate_times(cls, value: datetime, info) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{info.field_name} must be timezone-aware")
        return value

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("target must be finite")
        return value

    @model_validator(mode="after")
    def validate_decision(self) -> ExtendedTargetDecision:
        if self.as_of_time > self.decision_time:
            raise ValueError("as_of_time must be on or before decision_time")
        return self


__all__ = [
    "DecisionInstrument",
    "ExtendedSizingKind",
    "ExtendedTargetDecision",
    "InstrumentLeg",
    "LegDirection",
    "MultiLegInstrumentRef",
]
