from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from quant_strategies.core.config import CostModelConfig, FillModelConfig
from quant_strategies.evaluation.config import EvaluationWindow


CostScenario = Literal["zero_costs", "realistic_costs", "stressed_costs"]
FillScenario = Literal["base_fill", "fill_lag_plus_1"]


class EvaluationScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str = Field(min_length=1)
    window_id: str = Field(min_length=1)
    cost_scenario: CostScenario
    fill_scenario: FillScenario
    cost_model: CostModelConfig
    fill_model: FillModelConfig
    required: bool = True


def expand_evaluation_scenarios(
    *,
    window: EvaluationWindow,
    base_costs: CostModelConfig,
    base_fill: FillModelConfig,
) -> tuple[EvaluationScenario, ...]:
    cost_scenarios: tuple[tuple[CostScenario, CostModelConfig], ...] = (
        ("zero_costs", CostModelConfig(fee_bps_per_side=0.0, slippage_bps_per_side=0.0)),
        ("realistic_costs", base_costs),
        (
            "stressed_costs",
            CostModelConfig(
                fee_bps_per_side=base_costs.fee_bps_per_side * 2.0,
                slippage_bps_per_side=base_costs.slippage_bps_per_side * 2.0,
            ),
        ),
    )
    fill_scenarios: tuple[tuple[FillScenario, FillModelConfig], ...] = (
        ("base_fill", base_fill),
        (
            "fill_lag_plus_1",
            base_fill.model_copy(update={"entry_lag_bars": base_fill.entry_lag_bars + 1}),
        ),
    )
    return tuple(
        EvaluationScenario(
            scenario_id=f"{window.id}/{cost_name}/{fill_name}",
            window_id=window.id,
            cost_scenario=cost_name,
            fill_scenario=fill_name,
            cost_model=cost_model,
            fill_model=fill_model,
        )
        for fill_name, fill_model in fill_scenarios
        for cost_name, cost_model in cost_scenarios
    )
