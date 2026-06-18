from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

InstrumentKind = Literal["equity_or_etf", "fx_pair", "crypto_perp"]


class DecisionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _stripped_non_empty(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must be non-empty")
    return stripped


def _timezone_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _finite_positive(value: float, field_name: str) -> float:
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{field_name} must be finite and positive")
    return value


def _freeze_metadata_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        frozen_items: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("metadata mapping keys must be strings")
            frozen_items[key] = _freeze_metadata_value(item)
        return MappingProxyType(frozen_items)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_metadata_value(item) for item in value)
    return value


def _jsonable_metadata_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _jsonable_metadata_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable_metadata_value(item) for item in value]
    return value


class InstrumentRef(DecisionModel):
    kind: InstrumentKind
    symbol: str

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return _stripped_non_empty(value, "symbol")


DecisionInstrument = InstrumentRef


class ObservationRef(DecisionModel):
    symbol: str
    timestamp: datetime
    field: str | None = None
    source: str | None = None

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return _stripped_non_empty(value, "symbol")

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return _timezone_aware(value, "timestamp")

    @field_validator("field", "source")
    @classmethod
    def validate_optional_text(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _stripped_non_empty(value, info.field_name)


class RiskRule(DecisionModel):
    """Declared price-path exit thresholds enforced by the engine on the net position.

    Each threshold is an optional positive fraction of the position's entry mark
    (for example ``stop_loss=0.05`` flattens after a 5% adverse move). The engine
    evaluates them causally against the bar's **intrabar range** (high/low), so a
    barrier pierced intrabar fires even if the close recovered. The exit fills at the
    barrier level, worsened to the bar's open on a gap-through (a long that opens below
    its stop fills at the lower open); ``take_profit`` fills at the level and is never
    granted a gap-favorable bonus. When a single bar touches both an adverse barrier
    (``stop_loss``/``trailing``) and ``take_profit``, the adverse one wins, since intrabar
    order is unobservable. Exits derivable from data or time (signal reversal, fixed hold
    horizon) are expressed as explicit target decisions, not as ``RiskRule`` thresholds.
    """

    stop_loss: float | None = None
    take_profit: float | None = None
    trailing: float | None = None

    @model_validator(mode="after")
    def validate_thresholds(self) -> RiskRule:
        for field_name in ("stop_loss", "take_profit", "trailing"):
            value = getattr(self, field_name)
            if value is not None:
                _finite_positive(value, field_name)
        return self


class TargetDecision(DecisionModel):
    """A standing, signed base target shape for one instrument as of a causal time.

    The strategy owns the complete portfolio shape: ``target`` is a signed
    weight-like scalar (positive long, negative short, ``0`` = flat/close) that
    stands until the next decision for the instrument changes it. The foundation
    normalizes the emitted shape and applies the configured risk budget to produce
    final executable signed weights. A single signed target per instrument makes
    same-symbol exposure net by construction and additive stacking structurally
    inexpressible. Flat and leveraged shape targets are valid contract inputs;
    final executable exposure beyond the operator envelope is handled by the
    engine's feasibility verdict, never by rejecting the decision shape.
    """

    decision_id: str | None = None
    strategy_id: str
    instrument: DecisionInstrument
    decision_time: datetime
    as_of_time: datetime
    target: float
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
        return _timezone_aware(value, info.field_name)

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("target must be finite")
        return value

    @model_validator(mode="after")
    def validate_decision(self) -> TargetDecision:
        if self.as_of_time > self.decision_time:
            raise ValueError("as_of_time must be on or before decision_time")
        try:
            frozen_metadata = _freeze_metadata_value(self.metadata)
            generated_decision_id = _generated_decision_id(self, frozen_metadata)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must be JSON-compatible") from exc
        object.__setattr__(self, "metadata", frozen_metadata)
        if self.decision_id is None:
            object.__setattr__(self, "decision_id", generated_decision_id)
        return self

    @field_serializer("metadata")
    def serialize_metadata(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return _jsonable_metadata_value(value)


def _generated_decision_id(decision: TargetDecision, frozen_metadata: Mapping[str, Any]) -> str:
    payload = {
        "strategy_id": decision.strategy_id,
        "instrument": decision.instrument.model_dump(mode="json"),
        "decision_time": decision.decision_time.isoformat(),
        "as_of_time": decision.as_of_time.isoformat(),
        "target": decision.target,
        "risk_rule": (
            decision.risk_rule.model_dump(mode="json") if decision.risk_rule is not None else None
        ),
        "observations": [item.model_dump(mode="json") for item in decision.observations],
        "metadata": _jsonable_metadata_value(frozen_metadata),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{decision.strategy_id}:{digest}"
