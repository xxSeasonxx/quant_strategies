from __future__ import annotations

import json
import math
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EVIDENCE_SCHEMA_VERSION = "quant_strategies.engine.evidence/v2"


class EngineModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _timezone_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


ExitReason = Literal["stop_loss", "take_profit", "trailing_stop", "max_hold"]


class Bar(EngineModel):
    symbol: str = Field(min_length=1)
    timestamp: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    funding_timestamp: datetime | None = None
    funding_rate: float | None = None
    has_funding_event: bool = False

    @field_validator("timestamp", "funding_timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime | None, info) -> datetime | None:
        if value is None:
            return None
        return _timezone_aware(value, info.field_name)

    @model_validator(mode="after")
    def validate_prices(self) -> Bar:
        values = (self.open, self.high, self.low, self.close)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("bar prices must be finite")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be at least open, low, and close")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be at most open, high, and close")
        quotes = tuple(value for value in (self.bid, self.ask, self.mid) if value is not None)
        if not all(math.isfinite(value) and value > 0 for value in quotes):
            raise ValueError("quote prices must be finite and positive")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("bid must be less than or equal to ask")
        if self.mid is not None and self.bid is not None and self.mid < self.bid:
            raise ValueError("mid must be between bid and ask")
        if self.mid is not None and self.ask is not None and self.mid > self.ask:
            raise ValueError("mid must be between bid and ask")
        if self.funding_rate is not None and not math.isfinite(self.funding_rate):
            raise ValueError("funding_rate must be finite")
        if self.has_funding_event and self.funding_timestamp is None:
            raise ValueError("funding event requires funding_timestamp")
        if self.has_funding_event and self.funding_rate is None:
            raise ValueError("funding event requires funding_rate")
        return self


class Signal(EngineModel):
    symbol: str = Field(min_length=1)
    decision_time: datetime
    side: Side
    weight: float = Field(default=1.0, gt=0)
    max_hold_bars: int = Field(ge=1)
    take_profit_bps: float | None = None
    stop_loss_bps: float | None = None
    trailing_stop_bps: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("decision_time")
    @classmethod
    def validate_decision_time(cls, value: datetime) -> datetime:
        return _timezone_aware(value, "decision_time")

    @model_validator(mode="after")
    def validate_signal(self) -> Signal:
        if not math.isfinite(self.weight):
            raise ValueError("weight must be finite")
        exit_bps_values = (self.take_profit_bps, self.stop_loss_bps, self.trailing_stop_bps)
        if any(value is not None and (not math.isfinite(value) or value <= 0.0) for value in exit_bps_values):
            raise ValueError("exit bps values must be finite and positive")
        try:
            json.dumps(self.metadata, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must be JSON-compatible") from exc
        return self


class FillModel(EngineModel):
    price: Literal["open", "close", "quote"] = "close"
    entry_lag_bars: int = Field(default=1, ge=0)
    exit_lag_bars: int = Field(default=0, ge=0)


class CostModel(EngineModel):
    fee_bps_per_side: float = Field(default=0.0, ge=0)
    slippage_bps_per_side: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def validate_costs(self) -> CostModel:
        if not math.isfinite(self.fee_bps_per_side) or not math.isfinite(self.slippage_bps_per_side):
            raise ValueError("cost values must be finite")
        return self

    @property
    def round_trip_bps(self) -> float:
        return 2.0 * (self.fee_bps_per_side + self.slippage_bps_per_side)


class StrategySpec(EngineModel):
    strategy_id: str = Field(min_length=1)
    signals: tuple[Signal, ...] = Field(min_length=1)


class EvaluationRequest(EngineModel):
    spec: StrategySpec
    bars: tuple[Bar, ...] = ()
    fill_model: FillModel = Field(default_factory=FillModel)
    cost_model: CostModel = Field(default_factory=CostModel)


class Trade(EngineModel):
    symbol: str
    side: Side
    decision_time: datetime
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    exit_reason: ExitReason
    weight: float
    gross_return: float
    funding_return: float = 0.0
    cost_return: float
    net_return: float
    signal_metadata: dict[str, Any] = Field(default_factory=dict)


class SmokeScore(EngineModel):
    sum_signed_trade_activity_gross: float
    sum_signed_trade_activity_funding: float = 0.0
    sum_signed_trade_activity_cost: float
    sum_signed_trade_activity_net: float


class ScreeningResult(EngineModel):
    mode: Literal["screen"] = "screen"
    strategy_id: str
    trade_count: int
    smoke_score: SmokeScore
    trades: tuple[Trade, ...]


class ValidationConfig(EngineModel):
    min_trades: int = Field(default=1, ge=1)
    require_positive_net: bool = True
    require_positive_gross: bool = True


class GateResult(EngineModel):
    name: str
    passed: bool
    detail: str


class ValidationReport(EngineModel):
    mode: Literal["validate"] = "validate"
    strategy_id: str
    passed: bool
    gates: tuple[GateResult, ...]
    screening_result: ScreeningResult | None = None


class EvidencePacket(EngineModel):
    schema_version: Literal["quant_strategies.engine.evidence/v2"] = "quant_strategies.engine.evidence/v2"
    mode: Literal["screen", "validate"]
    strategy_id: str
    screening_result: ScreeningResult | None = None
    validation_report: ValidationReport | None = None
