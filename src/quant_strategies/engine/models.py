from __future__ import annotations

import math
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from quant_strategies.core.config import CostModelConfig as CostModel
from quant_strategies.core.config import FillModelConfig as FillModel
from quant_strategies.decisions import StrategyDecision

EVIDENCE_SCHEMA_VERSION = "quant_strategies.engine.evidence/v4"


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


class StrategySpec(EngineModel):
    strategy_id: str = Field(min_length=1)
    decisions: tuple[StrategyDecision, ...]


class EvaluationRequest(EngineModel):
    spec: StrategySpec
    bars: tuple[Bar, ...] = ()
    fill_model: FillModel = Field(default_factory=FillModel)
    cost_model: CostModel = Field(default_factory=CostModel)
    _indexed_bars: Any = PrivateAttr(default=None)


class Trade(EngineModel):
    decision_id: str | None = None
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
    decision_metadata: dict[str, Any] = Field(default_factory=dict)


class TradeResult(EngineModel):
    sum_signed_trade_activity_gross: float
    sum_signed_trade_activity_funding: float = 0.0
    sum_signed_trade_activity_cost: float
    sum_signed_trade_activity_net: float


class ScreeningResult(EngineModel):
    mode: Literal["screen"] = "screen"
    strategy_id: str
    trade_count: int
    trade_result: TradeResult
    trades: tuple[Trade, ...]


class GatingConfig(EngineModel):
    min_trades: int = Field(default=1, ge=1)
    require_positive_net: bool = True
    require_positive_gross: bool = True


class GateResult(EngineModel):
    name: str
    passed: bool
    detail: str


class GatingReport(EngineModel):
    mode: Literal["gate"] = "gate"
    strategy_id: str
    passed: bool
    gates: tuple[GateResult, ...]
    screening_result: ScreeningResult | None = None


class EvidencePacket(EngineModel):
    schema_version: Literal["quant_strategies.engine.evidence/v4"] = EVIDENCE_SCHEMA_VERSION
    mode: Literal["screen", "gate"]
    strategy_id: str
    screening_result: ScreeningResult | None = None
    validation_report: GatingReport | None = None
