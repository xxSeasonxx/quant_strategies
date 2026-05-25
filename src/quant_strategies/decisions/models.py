from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator


InstrumentKind = Literal["equity_or_etf", "fx_pair", "crypto_perp"]
Direction = Literal["long", "short", "flat"]
SizingKind = Literal["target_weight", "notional"]


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


class InstrumentRef(DecisionModel):
    kind: InstrumentKind
    symbol: str

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return _stripped_non_empty(value, "symbol")


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
    strategy_id: str
    instrument: InstrumentRef
    decision_time: datetime
    as_of_time: datetime
    target: PositionTarget
    exit_policy: ExitPolicy
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("strategy_id")
    @classmethod
    def validate_strategy_id(cls, value: str) -> str:
        return _stripped_non_empty(value, "strategy_id")

    @field_validator("decision_time", "as_of_time")
    @classmethod
    def validate_times(cls, value: datetime, info) -> datetime:
        return _timezone_aware(value, info.field_name)

    @model_validator(mode="after")
    def validate_decision(self) -> StrategyDecision:
        if self.as_of_time > self.decision_time:
            raise ValueError("as_of_time must be on or before decision_time")
        try:
            json.dumps(self.metadata, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must be JSON-compatible") from exc
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        return self

    @field_serializer("metadata")
    def serialize_metadata(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return dict(value)
