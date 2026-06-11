from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DataKind = Literal["bars", "crypto_perp_funding", "forex_with_quotes"]
CausalityReplayScope = Literal["complete", "bounded"]


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
    load_start: date | None = None
    load_end: date | None = None

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.end < self.start:
            raise ValueError("data.end must be on or after data.start")
        if self.load_start is not None and self.load_start > self.start:
            raise ValueError("data.load_start must be on or before data.start")
        if self.load_end is not None and self.load_end < self.end:
            raise ValueError("data.load_end must be on or after data.end")
        return self

    @property
    def effective_load_start(self) -> date:
        return self.load_start or self.start

    @property
    def effective_load_end(self) -> date:
        return self.load_end or self.end


class FillModelConfig(SharedConfigModel):
    price: Literal["open", "close", "quote"] = "close"
    entry_lag_bars: int = Field(default=1, ge=1)
    exit_lag_bars: int = Field(default=0, ge=0)


class CostModelConfig(SharedConfigModel):
    fee_bps_per_side: float = Field(default=0.0, ge=0)
    slippage_bps_per_side: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def validate_costs(self) -> CostModelConfig:
        if not math.isfinite(self.fee_bps_per_side) or not math.isfinite(
            self.slippage_bps_per_side
        ):
            raise ValueError("cost values must be finite")
        return self

    @property
    def round_trip_bps(self) -> float:
        return 2.0 * (self.fee_bps_per_side + self.slippage_bps_per_side)


class CapacityModelConfig(SharedConfigModel):
    """Operator-frozen capacity envelope for scoreable execution realism.

    ``mode='off'`` is explicit and useful for profiling or flat/no-activity books, but
    the portfolio book treats traded notional with capacity off as non-scoreable. The
    config is a protocol envelope, not an output/diagnostic option.
    """

    mode: Literal["off", "adv_impact"]
    portfolio_notional: float | None = None
    adv_lookback_bars: int | None = Field(default=None, ge=1)
    adv_min_observations: int | None = Field(default=None, ge=1)
    max_bar_participation: float | None = Field(default=None, gt=0.0)
    max_adv_participation: float | None = Field(default=None, gt=0.0)
    impact_coefficient_bps: float | None = Field(default=None, ge=0.0)
    impact_exponent: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def validate_capacity(self) -> CapacityModelConfig:
        values = (
            self.portfolio_notional,
            self.max_bar_participation,
            self.max_adv_participation,
            self.impact_coefficient_bps,
            self.impact_exponent,
        )
        if any(value is not None and not math.isfinite(value) for value in values):
            raise ValueError("capacity_model values must be finite")
        if self.mode == "adv_impact":
            required = {
                "portfolio_notional": self.portfolio_notional,
                "adv_lookback_bars": self.adv_lookback_bars,
                "adv_min_observations": self.adv_min_observations,
                "max_bar_participation": self.max_bar_participation,
                "max_adv_participation": self.max_adv_participation,
                "impact_coefficient_bps": self.impact_coefficient_bps,
                "impact_exponent": self.impact_exponent,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                fields = ", ".join(missing)
                raise ValueError(
                    f"capacity_model {fields} must be explicit when mode = 'adv_impact'"
                )
            if self.portfolio_notional <= 0.0:
                raise ValueError(
                    "capacity_model.portfolio_notional must be > 0 when mode = 'adv_impact'"
                )
            if self.adv_min_observations > self.adv_lookback_bars:
                raise ValueError("capacity_model.adv_min_observations must be <= adv_lookback_bars")
        return self


class LeverageBudgetConfig(SharedConfigModel):
    """Operator-frozen leverage envelope (gross + net), part of the protocol set.

    Owned by the operator alongside ``[cost_model]``/``[fill_model]`` — never an
    agent-editable ``[output]`` field. The book measures the strategy's *intended*
    standing exposure against this ceiling and fails closed on a breach (it is never
    clamped). Default is the conservative fully-invested ``1.0/1.0``; a perp program
    that prices its financing can freeze a higher ceiling here.
    """

    max_gross_exposure: float = Field(default=1.0, ge=1.0)
    max_net_exposure: float = Field(default=1.0, ge=1.0)

    @model_validator(mode="after")
    def validate_finite(self) -> LeverageBudgetConfig:
        if not math.isfinite(self.max_gross_exposure) or not math.isfinite(self.max_net_exposure):
            raise ValueError("leverage_budget values must be finite")
        return self


class CausalityPolicyConfig(SharedConfigModel):
    """Operator-frozen scoreability policy for the causality dimension.

    Owned by the operator alongside ``[cost_model]``/``[fill_model]``/``[leverage_budget]`` —
    never an agent-editable ``[output]`` field, so a climbing agent cannot relax it. A
    ``causality_check`` of ``off`` runs *no* look-ahead replay, so its NAV path could be
    built on leaked-future alpha; by default such a run is non-scoreable (a typed
    ``causality`` failure, not a swallowed pass). Every mode that runs some replay
    (``micro``/``emitted``/``focused``/``strict``) remains scoreable; ``micro`` stays the
    Train iteration mode. The operator can set ``allow_unverified_scoring = true`` to permit
    ``off`` to score deliberately (profiling/debugging, or a downstream that accepts the risk).
    """

    allow_unverified_scoring: bool = False


class CausalityReplayConfig(SharedConfigModel):
    scope: CausalityReplayScope = "complete"
    probe_limit: int = Field(default=64, ge=1)
    timeout_seconds: float = Field(default=60.0, ge=0.0)

    @field_validator("timeout_seconds")
    @classmethod
    def validate_timeout_seconds(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("causality_replay.timeout_seconds must be finite")
        return value


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
    capacity_model: CapacityModelConfig
    params: dict[str, Any] = field(default_factory=dict)
    fill_model: FillModelConfig = field(default_factory=FillModelConfig)
    cost_model: CostModelConfig = field(default_factory=CostModelConfig)
    leverage_budget: LeverageBudgetConfig = field(default_factory=LeverageBudgetConfig)
    # The validation run sets this so a missing `validate_params` is a hard error
    # (no mechanical-threshold verdict on unvalidated params); the runner quick-run
    # leaves it False and instead flags schema-less runs as exploratory.
    require_param_validator: bool = False
