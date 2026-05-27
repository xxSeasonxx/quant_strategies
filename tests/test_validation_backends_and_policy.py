from __future__ import annotations

import pytest

from quant_strategies.validation.backends import (
    BackendRunResult,
    FakeBackend,
    ScenarioBackendRunResult,
    get_backend,
)
from quant_strategies.validation.config import PaperReadinessConfig
from quant_strategies.validation.policy import ValidationPolicyDecision, classify_validation


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
        "trial_count": None,
        "deflated_sharpe": None,
        "monte_carlo": None,
    }


def completed_backend_result(net_return: float, trade_count: int) -> BackendRunResult:
    return BackendRunResult(
        backend="fake",
        status="completed",
        metrics={"net_return": net_return, "trade_count": trade_count},
        warnings=(),
        unsupported_semantics=(),
    )


def completed_scenario(
    window_id: str,
    scenario_kind: str,
    *,
    net_return: float,
    trade_count: int,
) -> ScenarioBackendRunResult:
    return ScenarioBackendRunResult(
        window_id=window_id,
        scenario_id=f"{window_id}/{scenario_kind}",
        scenario_kind=scenario_kind,
        required=True,
        result=completed_backend_result(net_return, trade_count),
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


def test_policy_watchlist_for_unsupported_semantics():
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

    assert decision.decision == "watchlist"
    assert "unsupported_semantics" in decision.reasons
    assert_advisory_only(decision)


def test_policy_mechanical_pass_for_positive_sufficient_backend_result():
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

    assert decision.decision == "mechanical_pass"
    assert decision.reasons == ("no_positive_realistic_cost_evidence",)
    assert_advisory_only(decision)


def test_policy_paper_candidate_when_all_paper_gates_pass():
    decision = classify_validation(
        data_passed=True,
        backend_results=paper_ready_scenarios(),
        min_trades=10,
    )

    assert decision.decision == "paper_candidate"
    assert decision.reasons == ()
    assert decision.failed_gates == ()
    assert "mechanical_validation" in decision.passed_gates
    assert "min_windows" in decision.passed_gates
    assert "min_total_trades" in decision.passed_gates
    assert "no_zero_trade_windows" in decision.passed_gates
    assert "aggregate_realistic_net_positive" in decision.passed_gates
    assert "positive_window_fraction" in decision.passed_gates
    assert "stressed_net_floor" in decision.passed_gates
    assert "fill_lag_net_floor" in decision.passed_gates
    assert_advisory_only(decision)


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

    assert decision.decision == "paper_candidate"
    assert "stressed_net_floor" in decision.passed_gates
    assert "fill_lag_net_floor" in decision.passed_gates
    assert decision.gate_details["stressed_net_floor"] == "-0.015 >= -0.02"
    assert decision.gate_details["fill_lag_net_floor"] == "-0.015 >= -0.02"
    assert_advisory_only(decision)


def test_policy_mechanical_pass_when_paper_readiness_disabled():
    decision = classify_validation(
        data_passed=True,
        backend_results=paper_ready_scenarios(),
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


def test_policy_ignores_diagnostic_scenarios_for_mechanical_pass():
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

    assert decision.decision == "mechanical_pass"
    assert decision.reasons == ("no_positive_realistic_cost_evidence",)
    assert_advisory_only(decision)


def test_policy_mechanical_pass_for_negative_realistic_cost_evidence():
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

    assert decision.decision == "mechanical_pass"
    assert decision.reasons == ("no_positive_realistic_cost_evidence",)
    assert "aggregate_realistic_net_positive" in decision.failed_gates
    assert_advisory_only(decision)


def test_policy_mechanical_pass_for_zero_realistic_cost_evidence():
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

    assert decision.decision == "mechanical_pass"
    assert decision.reasons == ("no_positive_realistic_cost_evidence",)
    assert "aggregate_realistic_net_positive" in decision.failed_gates
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


def test_policy_watchlist_for_required_backend_unavailable():
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

    assert decision.decision == "watchlist"
    assert "backend_unavailable" in decision.reasons
    assert_advisory_only(decision)


def test_policy_hard_no_for_invalid_completed_metrics_before_unavailable_watchlist():
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

    assert decision.decision == "mechanical_pass"
    assert decision.gate_details["no_zero_trade_windows"] == "missing cost scenarios"
    assert decision.gate_details["aggregate_realistic_net_positive"] == "missing cost scenarios"
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
