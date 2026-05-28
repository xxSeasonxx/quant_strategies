from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_strategies.boundary import frozen_params

ScenarioKind = Literal["base", "cost", "cost_stress", "fill_lag"]


class MatrixScenario(BaseModel):
    """Validation scenario with immutable section override maps.

    Empty params, cost_model, or fill_model maps mean the scenario does not
    override that section of the base validation config.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    kind: ScenarioKind
    required: bool = True
    params: Mapping[str, Any] = Field(default_factory=dict)
    cost_model: Mapping[str, Any] = Field(default_factory=dict)
    fill_model: Mapping[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def freeze_override_maps(self) -> MatrixScenario:
        object.__setattr__(self, "params", frozen_params(self.params))
        object.__setattr__(self, "cost_model", frozen_params(self.cost_model))
        object.__setattr__(self, "fill_model", frozen_params(self.fill_model))
        return self


def expand_validation_matrix(
    *,
    window_id: str,
    base_params: dict[str, Any],
    base_costs: dict[str, Any],
    base_fill: dict[str, Any],
) -> tuple[MatrixScenario, ...]:
    """Build v1 validation scenarios as override maps for one validation window."""

    scenarios: list[MatrixScenario] = [
        MatrixScenario(
            id=f"{window_id}/base",
            kind="base",
            params=base_params,
            cost_model={"fee_bps_per_side": 0.0, "slippage_bps_per_side": 0.0},
        ),
        MatrixScenario(id=f"{window_id}/realistic_costs", kind="cost", cost_model=base_costs),
        MatrixScenario(
            id=f"{window_id}/stressed_costs",
            kind="cost_stress",
            cost_model={
                "fee_bps_per_side": float(base_costs.get("fee_bps_per_side", 0.0)) * 2.0,
                "slippage_bps_per_side": float(base_costs.get("slippage_bps_per_side", 0.0))
                * 2.0,
            },
        ),
        MatrixScenario(
            id=f"{window_id}/fill_lag_plus_1",
            kind="fill_lag",
            fill_model={
                **base_fill,
                "entry_lag_bars": int(base_fill.get("entry_lag_bars", 1)) + 1,
            },
        ),
    ]
    return tuple(scenarios)
