from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DataKind = Literal["bars", "crypto_perp_funding", "forex_with_quotes"]


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


class SharedConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DataConfig(SharedConfigModel):
    kind: DataKind
    dataset: str | None = None
    symbols: tuple[str, ...] = Field(min_length=1)
    start: date
    end: date
    strict: bool = True

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        symbols = tuple(symbol.strip() for symbol in value)
        if any(not symbol for symbol in symbols):
            raise ValueError("data.symbols cannot contain empty symbols")
        return symbols

    @model_validator(mode="after")
    def validate_window(self) -> DataConfig:
        if self.end < self.start:
            raise ValueError("data.end must be on or after data.start")
        if self.kind == "bars" and not self.dataset:
            raise ValueError("data.dataset is required when data.kind = 'bars'")
        return self


class FillModelConfig(SharedConfigModel):
    price: Literal["open", "close", "quote"] = "close"
    entry_lag_bars: int = Field(default=1, ge=0)
    exit_lag_bars: int = Field(default=0, ge=0)
    allow_same_bar_close_fill: bool = False

    @model_validator(mode="after")
    def validate_fill_model(self) -> FillModelConfig:
        if self.price == "close" and self.entry_lag_bars == 0 and not self.allow_same_bar_close_fill:
            raise ValueError(
                'fill_model.price = "close" with entry_lag_bars = 0 requires '
                "fill_model.allow_same_bar_close_fill = true"
            )
        return self


class CostModelConfig(SharedConfigModel):
    fee_bps_per_side: float = Field(default=0.0, ge=0)
    slippage_bps_per_side: float = Field(default=0.0, ge=0)


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
    # (no paper-readiness verdict on unvalidated params); the runner quick-run
    # leaves it False and instead flags schema-less runs as exploratory.
    require_param_validator: bool = False
