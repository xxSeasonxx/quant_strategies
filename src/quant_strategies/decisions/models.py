from __future__ import annotations

import json
import hashlib
import math
from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator


InstrumentKind = Literal["equity_or_etf", "fx_pair", "crypto_perp"]
Direction = Literal["long", "short", "flat"]
DecisionAction = Literal["open"]
SizingKind = Literal["target_weight"]


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


class DecisionIntent(DecisionModel):
    action: DecisionAction = "open"


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


class PositionTarget(DecisionModel):
    direction: Direction
    sizing_kind: SizingKind = "target_weight"
    size: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_size(self) -> PositionTarget:
        if not math.isfinite(self.size):
            raise ValueError("target size must be finite")
        if self.direction == "flat" and self.size != 0.0:
            raise ValueError("flat target size must be 0")
        if self.direction in {"long", "short"} and self.size <= 0.0:
            raise ValueError("long and short target size must be positive")
        return self


class ExitPolicy(DecisionModel):
    max_hold_bars: int = Field(ge=1)
    stop_loss_bps: float | None = None
    take_profit_bps: float | None = None
    trailing_stop_bps: float | None = None

    @model_validator(mode="after")
    def validate_exit_thresholds(self) -> ExitPolicy:
        values = (self.stop_loss_bps, self.take_profit_bps, self.trailing_stop_bps)
        if any(value is not None and (not math.isfinite(value) or value <= 0.0) for value in values):
            raise ValueError("exit bps values must be finite and positive")
        return self


class StrategyDecision(DecisionModel):
    decision_id: str | None = None
    strategy_id: str
    instrument: DecisionInstrument
    intent: DecisionIntent = Field(default_factory=DecisionIntent)
    decision_time: datetime
    as_of_time: datetime
    target: PositionTarget
    exit_policy: ExitPolicy
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

    @model_validator(mode="after")
    def validate_decision(self) -> StrategyDecision:
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


def _generated_decision_id(decision: StrategyDecision, frozen_metadata: Mapping[str, Any]) -> str:
    payload = {
        "strategy_id": decision.strategy_id,
        "instrument": decision.instrument.model_dump(mode="json"),
        "intent": decision.intent.model_dump(mode="json"),
        "decision_time": decision.decision_time.isoformat(),
        "as_of_time": decision.as_of_time.isoformat(),
        "target": decision.target.model_dump(mode="json"),
        "exit_policy": decision.exit_policy.model_dump(mode="json"),
        "observations": [item.model_dump(mode="json") for item in decision.observations],
        "metadata": _jsonable_metadata_value(frozen_metadata),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{decision.strategy_id}:{digest}"
