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
from quant_strategies.validation.config import PaperReadinessConfig
from quant_strategies.validation.policy import ValidationPolicyDecision, classify_validation


def test_policy_declares_paper_readiness_gates_in_order():
    from quant_strategies.validation import policy

    assert policy._PAPER_READINESS_GATES == (
        "min_windows",
        "min_total_trades",
        "no_zero_trade_windows",
        "compounded_realistic_net_positive",
        "positive_window_fraction",
        "stressed_net_floor",
        "fill_lag_net_floor",
    )
    assert len(policy._PAPER_READINESS_GATES) == len(set(policy._PAPER_READINESS_GATES))


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
        "funding_return",
        "linear_funding_adjusted_return",
    }
    net_return = payload["net_return"]
    assert net_return["unit"] == "decimal_fraction"
    assert net_return["base"] == "backend portfolio price/cost return path"
    assert net_return["tolerance"] is None
    assert "runner smoke" in net_return["asymmetry"]
    trade_count = payload["trade_count"]
    assert trade_count["unit"] == "count"
    assert trade_count["tolerance"] == 0.0
    funding_return = payload["funding_return"]
    assert funding_return["unit"] == "decimal_fraction"
    assert funding_return["base"] == "linear funding cashflow approximation"
    adjusted = payload["linear_funding_adjusted_return"]
    assert adjusted["unit"] == "decimal_fraction"
    assert adjusted["base"] == "backend net_return plus linear funding_return"
    assert "not a NAV-path funding return" in adjusted["asymmetry"]


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


def paper_ready_scenarios(
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


def test_policy_hard_no_for_data_failure():
    decision = classify_validation(
        data_passed=False,
        backend_results=[],
        min_trades=10,
    )

    assert decision.decision == "hard_no"
    assert "data_audit_failed" in decision.reasons
    assert_advisory_only(decision)


def test_policy_hard_no_for_required_unsupported_semantics():
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

    assert decision.decision == "hard_no"
    assert "unsupported_semantics" in decision.reasons
    assert_advisory_only(decision)


def test_policy_hard_no_without_positive_realistic_cost_evidence_when_paper_enabled():
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

    assert decision.decision == "hard_no"
    assert decision.reasons == ("no_positive_realistic_cost_evidence",)
    assert_advisory_only(decision)


def test_policy_mechanical_review_candidate_when_all_paper_gates_pass():
    decision = classify_validation(
        data_passed=True,
        backend_results=paper_ready_scenarios(),
        min_trades=10,
    )

    assert decision.decision == "mechanical_review_candidate"
    assert decision.reasons == ()
    assert decision.failed_gates == ()
    assert "mechanical_validation" in decision.passed_gates
    assert "min_windows" in decision.passed_gates
    assert "min_total_trades" in decision.passed_gates
    assert "no_zero_trade_windows" in decision.passed_gates
    assert "compounded_realistic_net_positive" in decision.passed_gates
    assert "positive_window_fraction" in decision.passed_gates
    assert "stressed_net_floor" in decision.passed_gates
    assert "fill_lag_net_floor" in decision.passed_gates
    assert_advisory_only(decision)


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

    assert decision.decision == "hard_no"
    assert decision.reasons == ("no_positive_realistic_cost_evidence",)
    assert "compounded_realistic_net_positive" in decision.failed_gates
    assert_advisory_only(decision)


def test_policy_hard_no_for_zero_realistic_cost_evidence_when_paper_enabled():
    decision = classify_validation(
        data_passed=True,
        backend_results=paper_ready_scenarios(cost_returns=(0.0, 0.0)),
        min_trades=10,
    )

    assert decision.decision == "hard_no"
    assert decision.reasons == ("no_positive_realistic_cost_evidence",)
    assert "compounded_realistic_net_positive" in decision.failed_gates
    assert_advisory_only(decision)


def test_policy_records_search_pressure_inputs_and_downgrades_review_candidate():
    search_pressure = type(
        "SearchPressure",
        (),
        {
            "candidate_count": 120,
            "trial_count": 18,
            "parameter_search_space": {"lookback": [12, 24, 48]},
            "selection_rule": "top risk-adjusted smoke score",
            "split_ids": ("validation_2026_h1", "validation_2026_h2"),
        },
    )()

    decision = classify_validation(
        data_passed=True,
        backend_results=paper_ready_scenarios(),
        min_trades=10,
        paper_readiness=PaperReadinessConfig(),
        search_pressure=search_pressure,
    )

    assert decision.decision == "watchlist"
    assert decision.reasons == ("multiple_testing_not_corrected_advisory_only",)
    assert decision.overfit_controls == {
        "candidate_count": 120,
        "trial_count": 18,
        "parameter_search_space": {"lookback": [12, 24, 48]},
        "selection_rule": "top risk-adjusted smoke score",
        "split_ids": ["validation_2026_h1", "validation_2026_h2"],
    }
    assert decision.evidence_class == "validation_advisory"
    assert decision.requires_manual_approval is True
    assert decision.paper_trade_eligible is False


def test_policy_watchlist_for_one_cost_window():
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

    assert decision.decision == "watchlist"
    assert decision.reasons == ("paper_readiness_gates_failed",)
    assert "min_windows" in decision.failed_gates
    assert_advisory_only(decision)


def test_policy_watchlist_for_stressed_cost_collapse():
    decision = classify_validation(
        data_passed=True,
        backend_results=paper_ready_scenarios(stress_returns=(-0.03, -0.03)),
        min_trades=10,
    )

    assert decision.decision == "watchlist"
    assert decision.reasons == ("paper_readiness_gates_failed",)
    assert "stressed_net_floor" in decision.failed_gates
    assert_advisory_only(decision)


def test_policy_uses_worst_window_stressed_and_fill_lag_loss_floors():
    decision = classify_validation(
        data_passed=True,
        backend_results=paper_ready_scenarios(
            stress_returns=(-0.015, -0.015),
            fill_lag_returns=(-0.015, -0.015),
        ),
        min_trades=10,
    )

    assert decision.decision == "mechanical_review_candidate"
    assert "stressed_net_floor" in decision.passed_gates
    assert "fill_lag_net_floor" in decision.passed_gates
    assert decision.gate_details["stressed_net_floor"] == "-0.015 >= -0.02"
    assert decision.gate_details["fill_lag_net_floor"] == "-0.015 >= -0.02"
    assert_advisory_only(decision)


def test_policy_mechanical_pass_when_paper_readiness_disabled():
    decision = classify_validation(
        data_passed=True,
        backend_results=paper_ready_scenarios(cost_returns=(-0.01, 0.0)),
        min_trades=10,
        paper_readiness=PaperReadinessConfig(enabled=False),
    )

    assert decision.decision == "mechanical_pass"
    assert decision.reasons == ("paper_readiness_disabled",)
    assert "paper_readiness_enabled" in decision.failed_gates
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

    assert decision.decision == "hard_no"
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

    assert decision.decision == "hard_no"
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

    assert decision.decision == "hard_no"
    assert "missing_required_scenarios" in decision.reasons
    assert_advisory_only(decision)


def test_policy_ignores_diagnostic_scenarios_before_paper_readiness_classification():
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

    assert decision.decision == "hard_no"
    assert decision.reasons == ("no_positive_realistic_cost_evidence",)
    assert "unsupported_semantics" not in decision.reasons
    assert_advisory_only(decision)


def test_policy_hard_no_for_negative_realistic_cost_evidence():
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

    assert decision.decision == "hard_no"
    assert decision.reasons == ("no_positive_realistic_cost_evidence",)
    assert "compounded_realistic_net_positive" in decision.failed_gates
    assert_advisory_only(decision)


def test_policy_hard_no_for_zero_realistic_cost_evidence():
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

    assert decision.decision == "hard_no"
    assert decision.reasons == ("no_positive_realistic_cost_evidence",)
    assert "compounded_realistic_net_positive" in decision.failed_gates
    assert_advisory_only(decision)


def test_policy_uses_compounded_realistic_return_not_arithmetic_sum():
    decision = classify_validation(
        data_passed=True,
        backend_results=paper_ready_scenarios(cost_returns=(1.0, -0.5)),
        min_trades=10,
        required_scenario_ids=tuple(item.scenario_id for item in paper_ready_scenarios()),
    )

    assert decision.decision == "hard_no"
    assert decision.reasons == ("no_positive_realistic_cost_evidence",)
    assert "compounded_realistic_net_positive" in decision.failed_gates
    assert decision.gate_details["compounded_realistic_net_positive"] == "0.0 > 0.0"
    assert_advisory_only(decision)


def test_policy_hard_no_for_no_backend_results():
    decision = classify_validation(
        data_passed=True,
        backend_results=[],
        min_trades=10,
    )

    assert decision.decision == "hard_no"
    assert "no_backend_results" in decision.reasons
    assert_advisory_only(decision)


def test_policy_hard_no_for_non_completed_backend_status():
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

    assert decision.decision == "hard_no"
    assert "fake_failed" in decision.reasons
    assert_advisory_only(decision)


def test_policy_hard_no_for_required_backend_unavailable():
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

    assert decision.decision == "hard_no"
    assert "backend_unavailable" in decision.reasons
    assert_advisory_only(decision)


def test_policy_hard_no_for_invalid_completed_metrics_before_backend_unavailable():
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

    assert decision.decision == "hard_no"
    assert "invalid_backend_metrics" in decision.reasons
    assert_advisory_only(decision)


def test_policy_hard_no_for_insufficient_completed_trades_before_unsupported_watchlist():
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

    assert decision.decision == "hard_no"
    assert "insufficient_trades" in decision.reasons
    assert_advisory_only(decision)


def test_policy_marks_missing_paper_scenario_group_details_as_missing():
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

    assert decision.decision == "hard_no"
    assert decision.gate_details["no_zero_trade_windows"] == "missing cost scenarios"
    assert decision.gate_details["compounded_realistic_net_positive"] == "missing cost scenarios"
    assert decision.gate_details["stressed_net_floor"] == "missing cost_stress scenarios"
    assert decision.gate_details["fill_lag_net_floor"] == "missing fill_lag scenarios"
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

    assert decision.decision == "hard_no"
    assert decision.reasons == ("fake_failed",)
    assert_advisory_only(decision)


def test_policy_hard_no_for_insufficient_trades():
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

    assert decision.decision == "hard_no"
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
def test_policy_hard_no_for_invalid_backend_metrics(metrics):
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

    assert decision.decision == "hard_no"
    assert "invalid_backend_metrics" in decision.reasons
    assert_advisory_only(decision)
