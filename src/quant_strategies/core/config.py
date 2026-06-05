from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DataKind = Literal["bars", "crypto_perp_funding", "forex_with_quotes"]


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


class SharedConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WindowedDataConfig(SharedConfigModel):
    kind: DataKind
    dataset: str | None = None
    symbols: tuple[str, ...] = Field(min_length=1)

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        symbols = tuple(symbol.strip() for symbol in value)
        if any(not symbol for symbol in symbols):
            raise ValueError("data.symbols cannot contain empty symbols")
        return symbols

    @model_validator(mode="after")
    def validate_dataset(self) -> Self:
        if self.kind == "bars" and not self.dataset:
            raise ValueError("data.dataset is required when data.kind = 'bars'")
        return self


class DataConfig(WindowedDataConfig):
    start: date
    end: date

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.end < self.start:
            raise ValueError("data.end must be on or after data.start")
        return self


class FillModelConfig(SharedConfigModel):
    price: Literal["open", "close", "quote"] = "close"
    entry_lag_bars: int = Field(default=1, ge=1)
    exit_lag_bars: int = Field(default=0, ge=0)


class CostModelConfig(SharedConfigModel):
    fee_bps_per_side: float = Field(default=0.0, ge=0)
    slippage_bps_per_side: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def validate_costs(self) -> CostModelConfig:
        if not math.isfinite(self.fee_bps_per_side) or not math.isfinite(self.slippage_bps_per_side):
            raise ValueError("cost values must be finite")
        return self

    @property
    def round_trip_bps(self) -> float:
        return 2.0 * (self.fee_bps_per_side + self.slippage_bps_per_side)


@dataclass(frozen=True)
class StrategyExecutionSpec:
    """Neutral inputs to the shared execution kernel — no output/artifact policy.

    Both the runner quick-run and the validation run adapt their own config into
    this, so neither owns the other's execution surface and execution carries no
    output concerns (the runner manages `[output]`; validation manages its own
    artifacts).
    """

    strategy_path: Path
    strategy_id: str
    data: DataConfig
    params: dict[str, Any] = field(default_factory=dict)
    fill_model: FillModelConfig = field(default_factory=FillModelConfig)
    cost_model: CostModelConfig = field(default_factory=CostModelConfig)
    # The validation run sets this so a missing `validate_params` is a hard error
    # (no mechanical-threshold verdict on unvalidated params); the runner quick-run
    # leaves it False and instead flags schema-less runs as exploratory.
    require_param_validator: bool = False
