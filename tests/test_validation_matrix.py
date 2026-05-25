from __future__ import annotations

from quant_strategies.validation.matrix import MatrixScenario, expand_validation_matrix


def test_expand_validation_matrix_includes_required_v1_scenarios():
    scenarios = expand_validation_matrix(
        window_id="validation_2026_h1",
        base_params={"threshold": 1.0},
        base_costs={"fee_bps_per_side": 0.5, "slippage_bps_per_side": 0.5},
        base_fill={"entry_lag_bars": 1, "exit_lag_bars": 0},
    )

    names = {scenario.id for scenario in scenarios}

    assert "validation_2026_h1/base" in names
    assert "validation_2026_h1/realistic_costs" in names
    assert "validation_2026_h1/stressed_costs" in names
    assert "validation_2026_h1/fill_lag_plus_1" in names
    assert "validation_2026_h1/param_threshold_down_10pct" in names
    assert "validation_2026_h1/param_threshold_up_10pct" in names
    assert all(scenario.required for scenario in scenarios)


def test_matrix_scenario_records_overrides_explicitly():
    scenario = MatrixScenario(
        id="validation_2026_h1/stressed_costs",
        kind="cost_stress",
        required=True,
        params={},
        cost_model={"fee_bps_per_side": 2.0, "slippage_bps_per_side": 2.0},
        fill_model={},
    )

    assert scenario.kind == "cost_stress"
    assert scenario.cost_model["fee_bps_per_side"] == 2.0
