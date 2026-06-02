from __future__ import annotations

from datetime import date

from quant_strategies.core.config import CostModelConfig, FillModelConfig
from quant_strategies.evaluation.config import EvaluationWindow
from quant_strategies.evaluation.scenarios import expand_evaluation_scenarios


def test_expand_evaluation_scenarios_uses_fixed_cross_product():
    window = EvaluationWindow(id="eval_2026_h1", start=date(2026, 1, 1), end=date(2026, 6, 30))
    scenarios = expand_evaluation_scenarios(
        window=window,
        base_costs=CostModelConfig(fee_bps_per_side=0.5, slippage_bps_per_side=1.5),
        base_fill=FillModelConfig(price="close", entry_lag_bars=1, exit_lag_bars=0),
    )

    assert [item.scenario_id for item in scenarios] == [
        "eval_2026_h1/zero_costs/base_fill",
        "eval_2026_h1/realistic_costs/base_fill",
        "eval_2026_h1/stressed_costs/base_fill",
        "eval_2026_h1/zero_costs/fill_lag_plus_1",
        "eval_2026_h1/realistic_costs/fill_lag_plus_1",
        "eval_2026_h1/stressed_costs/fill_lag_plus_1",
    ]
    assert scenarios[0].cost_model.fee_bps_per_side == 0.0
    assert scenarios[0].cost_model.slippage_bps_per_side == 0.0
    assert scenarios[1].cost_model.fee_bps_per_side == 0.5
    assert scenarios[1].cost_model.slippage_bps_per_side == 1.5
    assert scenarios[2].cost_model.fee_bps_per_side == 1.0
    assert scenarios[2].cost_model.slippage_bps_per_side == 3.0
    assert scenarios[3].fill_model.entry_lag_bars == 2
    assert all(item.window_id == "eval_2026_h1" for item in scenarios)
    assert all(item.required is True for item in scenarios)


def test_expand_evaluation_scenarios_preserves_fill_fields_except_entry_lag():
    window = EvaluationWindow(id="w", start=date(2026, 1, 1), end=date(2026, 1, 31))
    scenarios = expand_evaluation_scenarios(
        window=window,
        base_costs=CostModelConfig(fee_bps_per_side=0.0, slippage_bps_per_side=0.0),
        base_fill=FillModelConfig(
            price="open",
            entry_lag_bars=3,
            exit_lag_bars=2,
            allow_same_bar_close_fill=False,
        ),
    )

    fill_lag = [item for item in scenarios if item.fill_scenario == "fill_lag_plus_1"]
    assert len(fill_lag) == 3
    assert all(item.fill_model.price == "open" for item in fill_lag)
    assert all(item.fill_model.entry_lag_bars == 4 for item in fill_lag)
    assert all(item.fill_model.exit_lag_bars == 2 for item in fill_lag)
