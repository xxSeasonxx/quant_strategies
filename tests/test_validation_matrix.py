from __future__ import annotations

import pytest

from quant_strategies.validation.matrix import MatrixScenario, expand_validation_matrix


def _scenario_by_id(scenarios: tuple[MatrixScenario, ...], scenario_id: str) -> MatrixScenario:
    return next(scenario for scenario in scenarios if scenario.id == scenario_id)


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
    assert _scenario_by_id(scenarios, "validation_2026_h1/base").required is True
    assert _scenario_by_id(scenarios, "validation_2026_h1/realistic_costs").required is True
    assert _scenario_by_id(scenarios, "validation_2026_h1/stressed_costs").required is True
    assert _scenario_by_id(scenarios, "validation_2026_h1/fill_lag_plus_1").required is True
    assert _scenario_by_id(scenarios, "validation_2026_h1/param_threshold_down_10pct").required is False
    assert _scenario_by_id(scenarios, "validation_2026_h1/param_threshold_up_10pct").required is False


def test_base_scenario_uses_no_cost_baseline():
    scenarios = expand_validation_matrix(
        window_id="validation_2026_h1",
        base_params={},
        base_costs={"fee_bps_per_side": 0.5, "slippage_bps_per_side": 0.75},
        base_fill={},
    )

    base = _scenario_by_id(scenarios, "validation_2026_h1/base")

    assert base.cost_model == {
        "fee_bps_per_side": 0.0,
        "slippage_bps_per_side": 0.0,
    }


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


def test_matrix_contract_documents_override_semantics():
    assert "override" in (MatrixScenario.__doc__ or "").lower()
    assert "override" in (expand_validation_matrix.__doc__ or "").lower()


def test_stressed_cost_doubles_fee_and_slippage_values():
    scenarios = expand_validation_matrix(
        window_id="validation_2026_h1",
        base_params={},
        base_costs={"fee_bps_per_side": 0.5, "slippage_bps_per_side": 0.75},
        base_fill={},
    )

    stressed_costs = _scenario_by_id(scenarios, "validation_2026_h1/stressed_costs")

    assert stressed_costs.cost_model == {
        "fee_bps_per_side": 1.0,
        "slippage_bps_per_side": 1.5,
    }


def test_fill_lag_preserves_base_fill_keys_and_increments_entry_lag():
    scenarios = expand_validation_matrix(
        window_id="validation_2026_h1",
        base_params={},
        base_costs={},
        base_fill={"entry_lag_bars": 1, "exit_lag_bars": 0, "fill_price": "next_open"},
    )

    fill_lag = _scenario_by_id(scenarios, "validation_2026_h1/fill_lag_plus_1")

    assert fill_lag.fill_model == {
        "entry_lag_bars": 2,
        "exit_lag_bars": 0,
        "fill_price": "next_open",
    }


def test_bool_params_are_skipped_for_perturbation():
    scenarios = expand_validation_matrix(
        window_id="validation_2026_h1",
        base_params={"enabled": True},
        base_costs={},
        base_fill={},
    )

    assert not any("param_enabled" in scenario.id for scenario in scenarios)


def test_only_first_numeric_non_bool_param_is_perturbed_for_v1():
    scenarios = expand_validation_matrix(
        window_id="validation_2026_h1",
        base_params={"enabled": True, "threshold": 1.0, "lookback": 20},
        base_costs={},
        base_fill={},
    )

    names = {scenario.id for scenario in scenarios}
    threshold_down = _scenario_by_id(
        scenarios, "validation_2026_h1/param_threshold_down_10pct"
    )

    assert "validation_2026_h1/param_threshold_up_10pct" in names
    assert "validation_2026_h1/param_lookback_down_10pct" not in names
    assert "validation_2026_h1/param_lookback_up_10pct" not in names
    assert threshold_down.params == {
        "enabled": True,
        "threshold": 0.9,
        "lookback": 20,
    }
    assert threshold_down.required is False


def test_scenario_override_maps_are_immutable_and_isolated_from_callers():
    params = {"threshold": 1.0, "nested": {"levels": [1, 2]}}
    cost_model = {"tiers": {"fee_bps_per_side": [0.5, 1.0]}}
    fill_model = {"route": {"lags": [0, 1]}}

    scenario = MatrixScenario(
        id="validation_2026_h1/base",
        kind="base",
        params=params,
        cost_model=cost_model,
        fill_model=fill_model,
    )

    params["threshold"] = 2.0
    params["nested"]["levels"].append(3)
    cost_model["tiers"]["fee_bps_per_side"].append(2.0)
    fill_model["route"]["lags"].append(2)

    assert scenario.params["threshold"] == 1.0
    assert scenario.params["nested"]["levels"] == (1, 2)
    assert scenario.cost_model["tiers"]["fee_bps_per_side"] == (0.5, 1.0)
    assert scenario.fill_model["route"]["lags"] == (0, 1)

    with pytest.raises(TypeError):
        scenario.params["threshold"] = 3.0
    with pytest.raises(TypeError):
        scenario.params["nested"]["extra"] = 4
    with pytest.raises(TypeError):
        scenario.params["nested"]["levels"][0] = 99
    with pytest.raises(TypeError):
        scenario.cost_model["tiers"]["fee_bps_per_side"][0] = 99.0
    with pytest.raises(TypeError):
        scenario.fill_model["route"]["lags"][0] = 99
