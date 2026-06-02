from __future__ import annotations

import pytest

from quant_strategies.validation.backends import (
    BackendMetrics,
    BackendRunResult,
    FakeBackend,
    ScenarioBackendRunResult,
    backend_metric_semantics,
    get_backend,
)
from quant_strategies.validation.config import MechanicalThresholdsConfig
from quant_strategies.validation.policy import ValidationPolicyDecision, classify_validation


def test_policy_declares_mechanical_thresholds_gates_in_order():
    from quant_strategies.validation import policy

    assert policy._MECHANICAL_THRESHOLD_GATES == (
        "min_windows",
        "min_total_trades",
        "no_zero_trade_windows",
        "realistic_activity_positive",
        "positive_window_fraction",
        "stressed_activity_floor",
        "fill_lag_activity_floor",
    )
    assert len(policy._MECHANICAL_THRESHOLD_GATES) == len(set(policy._MECHANICAL_THRESHOLD_GATES))


def assert_advisory_only(decision: ValidationPolicyDecision) -> None:
    assert decision.evidence_class == "validation_advisory"
    assert decision.advisory_decision == decision.decision
    assert decision.promotion_eligible is False
    assert decision.paper_trade_eligible is False
    assert decision.live_eligible is False
    assert decision.requires_manual_approval is True
    assert isinstance(decision.passed_gates, tuple)
    assert isinstance(decision.failed_gates, tuple)
    assert isinstance(decision.gate_details, dict)
    assert decision.overfit_controls == {
        "prior_search": "none",
        "candidate_count": None,
        "trial_count": None,
        "parameter_search_space": {},
        "selection_rule": None,
        "split_ids": [],
    }


def completed_backend_result(net_return: float, trade_count: int) -> BackendRunResult:
    return BackendRunResult(
        backend="fake",
        status="completed",
        metrics={"net_return": net_return, "trade_count": trade_count},
        warnings=(),
        unsupported_semantics=(),
    )


def assert_backend_metric_semantics(payload: dict[str, object]) -> None:
    assert set(payload) == {
        "net_return",
        "trade_count",
        "gross_return",
        "funding_return",
        "cost_return",
    }
    net_return = payload["net_return"]
    assert net_return["unit"] == "decimal_fraction"
    assert net_return["base"] == "engine linear signed trade-activity sum, funding-inclusive"
    assert net_return["backend"] == "engine"
    assert net_return["tolerance"] is None
    assert "not a NAV path" in net_return["asymmetry"]
    trade_count = payload["trade_count"]
    assert trade_count["unit"] == "count"
    assert trade_count["tolerance"] == 0.0
    gross_return = payload["gross_return"]
    assert gross_return["unit"] == "decimal_fraction"
    assert "agreement oracle cross-checks" in gross_return["comparability"]
    funding_return = payload["funding_return"]
    assert funding_return["unit"] == "decimal_fraction"
    assert "included in net_return" in funding_return["base"]
    cost_return = payload["cost_return"]
    assert cost_return["unit"] == "decimal_fraction"


def completed_scenario(
    window_id: str,
    scenario_kind: str,
    *,
    net_return: float,
    trade_count: int,
    extra_metrics: dict[str, object] | None = None,
) -> ScenarioBackendRunResult:
    metrics = {"net_return": net_return, "trade_count": trade_count}
    if extra_metrics:
        metrics.update(extra_metrics)
    return ScenarioBackendRunResult(
        window_id=window_id,
        scenario_id=f"{window_id}/{scenario_kind}",
        scenario_kind=scenario_kind,
        required=True,
        result=BackendRunResult(
            backend="fake",
            status="completed",
            metrics=metrics,
            warnings=(),
            unsupported_semantics=(),
        ),
    )


def mechanical_threshold_scenarios(
    *,
    cost_returns: tuple[float, float] = (0.02, 0.015),
    cost_trades: tuple[int, int] = (20, 20),
    stress_returns: tuple[float, float] = (-0.005, -0.005),
    fill_lag_returns: tuple[float, float] = (-0.004, -0.004),
) -> tuple[ScenarioBackendRunResult, ...]:
    windows = ("validation_2026_h1", "validation_2026_h2")
    scenarios: list[ScenarioBackendRunResult] = []
    for index, window_id in enumerate(windows):
        scenarios.extend(
            (
                completed_scenario(
                    window_id,
                    "cost",
                    net_return=cost_returns[index],
                    trade_count=cost_trades[index],
                ),
                completed_scenario(
                    window_id,
                    "cost_stress",
                    net_return=stress_returns[index],
                    trade_count=20,
                ),
                completed_scenario(
                    window_id,
                    "fill_lag",
                    net_return=fill_lag_returns[index],
                    trade_count=20,
                ),
            )
        )
    return tuple(scenarios)


def test_fake_backend_returns_configured_result():
    backend = FakeBackend(
        BackendRunResult(
            backend="fake",
            status="completed",
            metrics={"net_return": 0.02, "trade_count": 25},
            warnings=(),
            unsupported_semantics=(),
        )
    )

    result = backend.run(decisions=[], rows=[], config=None)

    assert result.backend == "fake"
    assert result.metrics["trade_count"] == 25


def test_backend_metrics_parses_required_metrics_and_preserves_extras():
    metrics = BackendMetrics.from_mapping(
        {
            "net_return": 0.02,
            "trade_count": 25,
            "max_drawdown": -0.12,
            "funding_model": "linear_additive_adjustment",
        }
    )

    assert metrics is not None
    assert metrics.net_return == 0.02
    assert metrics.trade_count == 25
    assert metrics.extras == {
        "max_drawdown": -0.12,
        "funding_model": "linear_additive_adjustment",
    }


def test_backend_metrics_rejects_invalid_required_metrics():
    assert BackendMetrics.from_mapping({"net_return": float("nan"), "trade_count": 25}) is None
    assert BackendMetrics.from_mapping({"net_return": 0.02, "trade_count": 1.5}) is None
    assert BackendMetrics.from_mapping({"net_return": 0.02, "trade_count": True}) is None


def test_backend_metric_semantics_declares_tolerance_and_asymmetry():
    assert_backend_metric_semantics(backend_metric_semantics())


def test_get_backend_rejects_unknown_backend_name():
    try:
        get_backend("missing")
    except ValueError as exc:
        assert "unsupported validation backend" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_policy_mechanical_fail_for_data_failure():
    decision = classify_validation(
        data_passed=False,
        backend_results=[],
        min_trades=10,
    )

    assert decision.decision == "mechanical_fail"
    assert "data_audit_failed" in decision.reasons
    assert_advisory_only(decision)


def test_policy_mechanical_fail_for_required_unsupported_semantics():
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            BackendRunResult(
                backend="fake",
                status="unsupported",
                metrics={},
                warnings=(),
                unsupported_semantics=("trailing_stop",),
            )
        ],
        min_trades=10,
    )

    assert decision.decision == "mechanical_fail"
    assert "unsupported_semantics" in decision.reasons
    assert_advisory_only(decision)


def test_policy_mechanical_fail_without_positive_realistic_activity_evidence_when_mechanical_thresholds_enabled():
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            BackendRunResult(
                backend="fake",
                status="completed",
                metrics={"net_return": 0.03, "trade_count": 50},
                warnings=(),
                unsupported_semantics=(),
            )
        ],
        min_trades=10,
    )

    assert decision.decision == "mechanical_fail"
    assert decision.reasons == ("no_positive_realistic_activity_evidence",)
    assert_advisory_only(decision)


def test_policy_mechanical_threshold_pass_when_all_threshold_gates_pass():
    decision = classify_validation(
        data_passed=True,
        backend_results=mechanical_threshold_scenarios(),
        min_trades=10,
    )

    assert decision.decision == "mechanical_threshold_pass"
    assert decision.reasons == ()
    assert decision.failed_gates == ()
    assert "mechanical_validation" in decision.passed_gates
    assert "min_windows" in decision.passed_gates
    assert "min_total_trades" in decision.passed_gates
    assert "no_zero_trade_windows" in decision.passed_gates
    assert "realistic_activity_positive" in decision.passed_gates
    assert "positive_window_fraction" in decision.passed_gates
    assert "stressed_activity_floor" in decision.passed_gates
    assert "fill_lag_activity_floor" in decision.passed_gates
    assert_advisory_only(decision)


def test_policy_gates_on_engine_funding_inclusive_net_return():
    # F2: the engine verdict source emits a funding-inclusive net_return. The
    # positive-evidence gate must key on that funding-inclusive number, not on the
    # price/cost-only path -- a perp that is price/cost-positive but funding-negative
    # must not clear the gate (this is the perp economics the old vbt "net" omitted).
    def realistic(net_return: float, gross_return: float) -> tuple[ScenarioBackendRunResult, ...]:
        return tuple(
            completed_scenario(
                window_id,
                "cost",
                net_return=net_return,
                trade_count=20,
                extra_metrics={"gross_return": gross_return},
            )
            for window_id in ("validation_2026_h1", "validation_2026_h2")
        )

    floors = tuple(
        completed_scenario(window_id, scenario_kind, net_return=net, trade_count=20)
        for window_id in ("validation_2026_h1", "validation_2026_h2")
        for scenario_kind, net in (("cost_stress", -0.005), ("fill_lag", -0.004))
    )

    # Price path positive, but funding drags the funding-inclusive net negative.
    funding_negative = classify_validation(
        data_passed=True,
        backend_results=realistic(net_return=-0.01, gross_return=0.03) + floors,
        min_trades=10,
    )
    assert "realistic_activity_positive" in funding_negative.failed_gates
    assert funding_negative.decision != "mechanical_threshold_pass"

    # Same price path, funding-inclusive net positive -> the gate clears.
    funding_positive = classify_validation(
        data_passed=True,
        backend_results=realistic(net_return=0.02, gross_return=0.03) + floors,
        min_trades=10,
    )
    assert "realistic_activity_positive" in funding_positive.passed_gates
    assert funding_positive.decision == "mechanical_threshold_pass"


def test_policy_does_not_use_linear_funding_adjusted_return_for_net_gates():
    funding_extras = {
        "funding_return": 0.04,
        "linear_funding_adjusted_return": 0.03,
        "funding_model": "linear_additive_adjustment",
    }
    decision = classify_validation(
        data_passed=True,
        backend_results=(
            completed_scenario(
                "validation_2026_h1",
                "cost",
                net_return=-0.01,
                trade_count=20,
                extra_metrics=funding_extras,
            ),
            completed_scenario(
                "validation_2026_h1",
                "cost_stress",
                net_return=-0.005,
                trade_count=20,
                extra_metrics=funding_extras,
            ),
            completed_scenario(
                "validation_2026_h1",
                "fill_lag",
                net_return=-0.004,
                trade_count=20,
                extra_metrics=funding_extras,
            ),
            completed_scenario(
                "validation_2026_h2",
                "cost",
                net_return=-0.01,
                trade_count=20,
                extra_metrics=funding_extras,
            ),
            completed_scenario(
                "validation_2026_h2",
                "cost_stress",
                net_return=-0.005,
                trade_count=20,
                extra_metrics=funding_extras,
            ),
            completed_scenario(
                "validation_2026_h2",
                "fill_lag",
                net_return=-0.004,
                trade_count=20,
                extra_metrics=funding_extras,
            ),
        ),
        min_trades=10,
    )

    assert decision.decision == "mechanical_fail"
    assert decision.reasons == ("no_positive_realistic_activity_evidence",)
    assert "realistic_activity_positive" in decision.failed_gates
    assert_advisory_only(decision)


def test_policy_mechanical_fail_for_zero_realistic_activity_evidence_when_mechanical_thresholds_enabled():
    decision = classify_validation(
        data_passed=True,
        backend_results=mechanical_threshold_scenarios(cost_returns=(0.0, 0.0)),
        min_trades=10,
    )

    assert decision.decision == "mechanical_fail"
    assert decision.reasons == ("no_positive_realistic_activity_evidence",)
    assert "realistic_activity_positive" in decision.failed_gates
    assert_advisory_only(decision)


def test_policy_records_search_pressure_inputs_and_downgrades_review_candidate():
    search_pressure = type(
        "SearchPressure",
        (),
        {
            "prior_search": "known",
            "candidate_count": 120,
            "trial_count": 18,
            "parameter_search_space": {"lookback": [12, 24, 48]},
            "selection_rule": "top risk-adjusted trade result",
            "split_ids": ("validation_2026_h1", "validation_2026_h2"),
        },
    )()

    decision = classify_validation(
        data_passed=True,
        backend_results=mechanical_threshold_scenarios(),
        min_trades=10,
        mechanical_thresholds=MechanicalThresholdsConfig(),
        search_pressure=search_pressure,
    )

    assert decision.decision == "mechanical_caution"
    assert decision.reasons == ("multiple_testing_not_corrected_advisory_only",)
    assert decision.overfit_controls == {
        "prior_search": "known",
        "candidate_count": 120,
        "trial_count": 18,
        "parameter_search_space": {"lookback": [12, 24, 48]},
        "selection_rule": "top risk-adjusted trade result",
        "split_ids": ["validation_2026_h1", "validation_2026_h2"],
    }
    assert decision.evidence_class == "validation_advisory"
    assert decision.requires_manual_approval is True
    assert decision.paper_trade_eligible is False


def test_policy_unknown_search_pressure_downgrades_review_candidate():
    search_pressure = type(
        "SearchPressure",
        (),
        {
            "prior_search": "unknown",
            "candidate_count": None,
            "trial_count": None,
            "parameter_search_space": {},
            "selection_rule": None,
            "split_ids": (),
        },
    )()

    decision = classify_validation(
        data_passed=True,
        backend_results=mechanical_threshold_scenarios(),
        min_trades=10,
        mechanical_thresholds=MechanicalThresholdsConfig(),
        search_pressure=search_pressure,
    )

    assert decision.decision == "mechanical_caution"
    assert decision.reasons == ("search_pressure_unknown_advisory_only",)
    assert decision.overfit_controls["prior_search"] == "unknown"
    assert decision.paper_trade_eligible is False


def test_policy_mechanical_caution_for_one_cost_window():
    decision = classify_validation(
        data_passed=True,
        backend_results=(
            completed_scenario(
                "validation_2026_h1",
                "cost",
                net_return=0.03,
                trade_count=40,
            ),
            completed_scenario(
                "validation_2026_h1",
                "cost_stress",
                net_return=-0.005,
                trade_count=20,
            ),
            completed_scenario(
                "validation_2026_h1",
                "fill_lag",
                net_return=-0.005,
                trade_count=20,
            ),
        ),
        min_trades=10,
    )

    assert decision.decision == "mechanical_caution"
    assert decision.reasons == ("mechanical_threshold_gates_failed",)
    assert "min_windows" in decision.failed_gates
    assert_advisory_only(decision)


def test_policy_mechanical_caution_for_stressed_cost_collapse():
    decision = classify_validation(
        data_passed=True,
        backend_results=mechanical_threshold_scenarios(stress_returns=(-0.03, -0.03)),
        min_trades=10,
    )

    assert decision.decision == "mechanical_caution"
    assert decision.reasons == ("mechanical_threshold_gates_failed",)
    assert "stressed_activity_floor" in decision.failed_gates
    assert_advisory_only(decision)


def test_policy_uses_worst_window_stressed_and_fill_lag_loss_floors():
    decision = classify_validation(
        data_passed=True,
        backend_results=mechanical_threshold_scenarios(
            stress_returns=(-0.015, -0.015),
            fill_lag_returns=(-0.015, -0.015),
        ),
        min_trades=10,
    )

    assert decision.decision == "mechanical_threshold_pass"
    assert "stressed_activity_floor" in decision.passed_gates
    assert "fill_lag_activity_floor" in decision.passed_gates
    assert decision.gate_details["stressed_activity_floor"] == "-0.015 >= -0.02"
    assert decision.gate_details["fill_lag_activity_floor"] == "-0.015 >= -0.02"
    assert_advisory_only(decision)


def test_policy_mechanical_complete_when_mechanical_thresholds_disabled():
    decision = classify_validation(
        data_passed=True,
        backend_results=mechanical_threshold_scenarios(cost_returns=(-0.01, 0.0)),
        min_trades=10,
        mechanical_thresholds=MechanicalThresholdsConfig(enabled=False),
    )

    assert decision.decision == "mechanical_complete"
    assert decision.decision not in {"mechanical_caution", "mechanical_threshold_pass"}
    assert decision.reasons == ("mechanical_thresholds_disabled",)
    assert "mechanical_thresholds_enabled" in decision.failed_gates
    assert_advisory_only(decision)


def test_policy_requires_all_expected_required_scenarios():
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            ScenarioBackendRunResult(
                window_id="validation_2026_h1",
                scenario_id="validation_2026_h1/base",
                required=True,
                result=BackendRunResult(
                    backend="fake",
                    status="completed",
                    metrics={"net_return": 0.03, "trade_count": 50},
                    warnings=(),
                    unsupported_semantics=(),
                ),
            )
        ],
        min_trades=10,
        required_scenario_count=2,
    )

    assert decision.decision == "mechanical_fail"
    assert "missing_required_scenarios" in decision.reasons
    assert_advisory_only(decision)


def test_policy_requires_expected_required_scenario_ids():
    duplicate_base = [
        ScenarioBackendRunResult(
            window_id="validation_2026_h1",
            scenario_id="validation_2026_h1/base",
            required=True,
            result=BackendRunResult(
                backend="fake",
                status="completed",
                metrics={"net_return": 0.03, "trade_count": 50},
                warnings=(),
                unsupported_semantics=(),
            ),
        ),
        ScenarioBackendRunResult(
            window_id="validation_2026_h1",
            scenario_id="validation_2026_h1/base",
            required=True,
            result=BackendRunResult(
                backend="fake",
                status="completed",
                metrics={"net_return": 0.03, "trade_count": 50},
                warnings=(),
                unsupported_semantics=(),
            ),
        ),
    ]

    decision = classify_validation(
        data_passed=True,
        backend_results=duplicate_base,
        min_trades=10,
        required_scenario_ids=(
            "validation_2026_h1/base",
            "validation_2026_h1/stressed_costs",
        ),
    )

    assert decision.decision == "mechanical_fail"
    assert "duplicate_required_scenarios" in decision.reasons
    assert_advisory_only(decision)


def test_policy_rejects_missing_required_scenario_id_even_when_count_matches():
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            ScenarioBackendRunResult(
                window_id="validation_2026_h1",
                scenario_id="validation_2026_h1/base",
                required=True,
                result=BackendRunResult(
                    backend="fake",
                    status="completed",
                    metrics={"net_return": 0.03, "trade_count": 50},
                    warnings=(),
                    unsupported_semantics=(),
                ),
            ),
            ScenarioBackendRunResult(
                window_id="validation_2026_h1",
                scenario_id="validation_2026_h1/other",
                required=True,
                result=BackendRunResult(
                    backend="fake",
                    status="completed",
                    metrics={"net_return": 0.03, "trade_count": 50},
                    warnings=(),
                    unsupported_semantics=(),
                ),
            ),
        ],
        min_trades=10,
        required_scenario_ids=(
            "validation_2026_h1/base",
            "validation_2026_h1/stressed_costs",
        ),
    )

    assert decision.decision == "mechanical_fail"
    assert "missing_required_scenarios" in decision.reasons
    assert_advisory_only(decision)


def test_policy_ignores_diagnostic_scenarios_before_mechanical_threshold_classification():
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            ScenarioBackendRunResult(
                window_id="validation_2026_h1",
                scenario_id="validation_2026_h1/base",
                required=True,
                result=BackendRunResult(
                    backend="fake",
                    status="completed",
                    metrics={"net_return": 0.03, "trade_count": 50},
                    warnings=(),
                    unsupported_semantics=(),
                ),
            ),
            ScenarioBackendRunResult(
                window_id="validation_2026_h1",
                scenario_id="validation_2026_h1/diagnostic",
                required=False,
                result=BackendRunResult(
                    backend="fake",
                    status="unsupported",
                    metrics={},
                    warnings=(),
                    unsupported_semantics=("threshold_exit_policy",),
                ),
            ),
        ],
        min_trades=10,
        required_scenario_count=1,
    )

    assert decision.decision == "mechanical_fail"
    assert decision.reasons == ("no_positive_realistic_activity_evidence",)
    assert "unsupported_semantics" not in decision.reasons
    assert_advisory_only(decision)


def test_policy_mechanical_fail_for_negative_realistic_activity_evidence():
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            completed_scenario(
                "validation_2026_h1",
                "cost",
                net_return=-0.01,
                trade_count=50,
            )
        ],
        min_trades=10,
    )

    assert decision.decision == "mechanical_fail"
    assert decision.reasons == ("no_positive_realistic_activity_evidence",)
    assert "realistic_activity_positive" in decision.failed_gates
    assert_advisory_only(decision)


def test_policy_mechanical_fail_for_zero_realistic_activity_evidence():
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            completed_scenario(
                "validation_2026_h1",
                "cost",
                net_return=0.0,
                trade_count=50,
            )
        ],
        min_trades=10,
    )

    assert decision.decision == "mechanical_fail"
    assert decision.reasons == ("no_positive_realistic_activity_evidence",)
    assert "realistic_activity_positive" in decision.failed_gates
    assert_advisory_only(decision)


def test_policy_uses_linear_realistic_net_activity_not_compounded_return():
    scenarios = mechanical_threshold_scenarios(cost_returns=(1.0, -0.5))

    decision = classify_validation(
        data_passed=True,
        backend_results=scenarios,
        min_trades=10,
        required_scenario_ids=tuple(item.scenario_id for item in scenarios),
    )

    assert decision.decision == "mechanical_threshold_pass"
    assert "realistic_activity_positive" in decision.passed_gates
    assert decision.gate_details["realistic_activity_positive"] == "0.5 > 0.0"
    assert_advisory_only(decision)


def test_policy_mechanical_fail_for_no_backend_results():
    decision = classify_validation(
        data_passed=True,
        backend_results=[],
        min_trades=10,
    )

    assert decision.decision == "mechanical_fail"
    assert "no_backend_results" in decision.reasons
    assert_advisory_only(decision)


def test_policy_mechanical_fail_for_non_completed_backend_status():
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            BackendRunResult(
                backend="fake",
                status="failed",
                metrics={},
                warnings=(),
                unsupported_semantics=(),
            )
        ],
        min_trades=10,
    )

    assert decision.decision == "mechanical_fail"
    assert "fake_failed" in decision.reasons
    assert_advisory_only(decision)


def test_policy_mechanical_fail_for_required_backend_unavailable():
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            BackendRunResult(
                backend="vectorbtpro",
                status="unavailable",
                metrics={},
                warnings=("vectorbtpro import failed",),
                unsupported_semantics=(),
            )
        ],
        min_trades=10,
    )

    assert decision.decision == "mechanical_fail"
    assert "backend_unavailable" in decision.reasons
    assert_advisory_only(decision)


def test_policy_mechanical_fail_for_invalid_completed_metrics_before_backend_unavailable():
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            ScenarioBackendRunResult(
                window_id="validation_2026_h1",
                scenario_id="validation_2026_h1/base",
                scenario_kind="base",
                required=True,
                result=BackendRunResult(
                    backend="fake",
                    status="completed",
                    metrics={"net_return": "bad", "trade_count": 50},
                    warnings=(),
                    unsupported_semantics=(),
                ),
            ),
            ScenarioBackendRunResult(
                window_id="validation_2026_h1",
                scenario_id="validation_2026_h1/cost",
                scenario_kind="cost",
                required=True,
                result=BackendRunResult(
                    backend="vectorbtpro",
                    status="unavailable",
                    metrics={},
                    warnings=("vectorbtpro import failed",),
                    unsupported_semantics=(),
                ),
            ),
        ],
        min_trades=10,
    )

    assert decision.decision == "mechanical_fail"
    assert "invalid_backend_metrics" in decision.reasons
    assert_advisory_only(decision)


def test_policy_mechanical_fail_for_insufficient_completed_trades_before_unsupported_mechanical_caution():
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            completed_scenario(
                "validation_2026_h1",
                "base",
                net_return=0.03,
                trade_count=5,
            ),
            ScenarioBackendRunResult(
                window_id="validation_2026_h1",
                scenario_id="validation_2026_h1/cost",
                scenario_kind="cost",
                required=True,
                result=BackendRunResult(
                    backend="fake",
                    status="unsupported",
                    metrics={},
                    warnings=(),
                    unsupported_semantics=("threshold_exit_policy",),
                ),
            ),
        ],
        min_trades=10,
    )

    assert decision.decision == "mechanical_fail"
    assert "insufficient_trades" in decision.reasons
    assert_advisory_only(decision)


def test_policy_marks_missing_mechanical_threshold_scenario_group_details_as_missing():
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            completed_scenario(
                "validation_2026_h1",
                "base",
                net_return=0.03,
                trade_count=50,
            )
        ],
        min_trades=10,
    )

    assert decision.decision == "mechanical_fail"
    assert decision.gate_details["no_zero_trade_windows"] == "missing cost scenarios"
    assert decision.gate_details["realistic_activity_positive"] == "missing cost scenarios"
    assert decision.gate_details["stressed_activity_floor"] == "missing cost_stress scenarios"
    assert decision.gate_details["fill_lag_activity_floor"] == "missing fill_lag scenarios"
    assert_advisory_only(decision)


def test_policy_prioritizes_failed_required_result_over_unsupported_result():
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            ScenarioBackendRunResult(
                window_id="validation_2026_h1",
                scenario_id="validation_2026_h1/base",
                required=True,
                result=BackendRunResult(
                    backend="fake",
                    status="failed",
                    metrics={},
                    warnings=("unfillable_exit",),
                    unsupported_semantics=(),
                ),
            ),
            ScenarioBackendRunResult(
                window_id="validation_2026_h1",
                scenario_id="validation_2026_h1/realistic_costs",
                required=True,
                result=BackendRunResult(
                    backend="fake",
                    status="unsupported",
                    metrics={},
                    warnings=(),
                    unsupported_semantics=("threshold_exit_policy",),
                ),
            ),
        ],
        min_trades=10,
    )

    assert decision.decision == "mechanical_fail"
    assert decision.reasons == ("fake_failed",)
    assert_advisory_only(decision)


def test_policy_mechanical_fail_for_insufficient_trades():
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            BackendRunResult(
                backend="fake",
                status="completed",
                metrics={"net_return": 0.03, "trade_count": 5},
                warnings=(),
                unsupported_semantics=(),
            )
        ],
        min_trades=10,
    )

    assert decision.decision == "mechanical_fail"
    assert "insufficient_trades" in decision.reasons
    assert_advisory_only(decision)


@pytest.mark.parametrize(
    "metrics",
    [
        {},
        {"net_return": 0.03},
        {"trade_count": 50},
        {"net_return": "nan", "trade_count": 50},
        {"net_return": float("nan"), "trade_count": 50},
        {"net_return": True, "trade_count": 50},
        {"net_return": "abc", "trade_count": 50},
        {"net_return": 0.03, "trade_count": True},
        {"net_return": 0.03, "trade_count": float("inf")},
        {"net_return": 0.03, "trade_count": "abc"},
    ],
)
def test_policy_mechanical_fail_for_invalid_backend_metrics(metrics):
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            BackendRunResult(
                backend="fake",
                status="completed",
                metrics=metrics,
                warnings=(),
                unsupported_semantics=(),
            )
        ],
        min_trades=10,
    )

    assert decision.decision == "mechanical_fail"
    assert "invalid_backend_metrics" in decision.reasons
    assert_advisory_only(decision)
