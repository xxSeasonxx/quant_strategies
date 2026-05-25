from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ScenarioKind = Literal["base", "cost", "cost_stress", "fill_lag", "parameter"]


class MatrixScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    kind: ScenarioKind
    required: bool = True
    params: dict[str, Any] = Field(default_factory=dict)
    cost_model: dict[str, Any] = Field(default_factory=dict)
    fill_model: dict[str, Any] = Field(default_factory=dict)


def expand_validation_matrix(
    *,
    window_id: str,
    base_params: dict[str, Any],
    base_costs: dict[str, Any],
    base_fill: dict[str, Any],
) -> tuple[MatrixScenario, ...]:
    scenarios: list[MatrixScenario] = [
        MatrixScenario(id=f"{window_id}/base", kind="base", params=base_params),
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
    for name, value in base_params.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        scenarios.append(
            MatrixScenario(
                id=f"{window_id}/param_{name}_down_10pct",
                kind="parameter",
                params={**base_params, name: float(value) * 0.9},
            )
        )
        scenarios.append(
            MatrixScenario(
                id=f"{window_id}/param_{name}_up_10pct",
                kind="parameter",
                params={**base_params, name: float(value) * 1.1},
            )
        )
        break
    return tuple(scenarios)
