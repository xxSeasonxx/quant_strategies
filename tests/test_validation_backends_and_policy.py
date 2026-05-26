from __future__ import annotations

import pytest

from quant_strategies.validation.backends import (
    BackendRunResult,
    FakeBackend,
    ScenarioBackendRunResult,
    get_backend,
)
from quant_strategies.validation.policy import ValidationPolicyDecision, classify_validation


def assert_advisory_only(decision: ValidationPolicyDecision) -> None:
    assert decision.evidence_class == "validation_advisory"
    assert decision.advisory_decision == decision.decision
    assert decision.promotion_eligible is False
    assert decision.paper_trade_eligible is False
    assert decision.live_eligible is False
    assert decision.requires_manual_approval is True


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


def test_policy_maybe_for_unsupported_semantics():
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

    assert decision.decision == "maybe"
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
    assert decision.reasons == ()
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
    assert decision.reasons == ()
    assert_advisory_only(decision)


def test_policy_hard_no_for_nonpositive_net_return():
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            BackendRunResult(
                backend="fake",
                status="completed",
                metrics={"net_return": -0.01, "trade_count": 50},
                warnings=(),
                unsupported_semantics=(),
            )
        ],
        min_trades=10,
    )

    assert decision.decision == "hard_no"
    assert "nonpositive_net_return" in decision.reasons
    assert_advisory_only(decision)


def test_policy_hard_no_for_zero_net_return():
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            BackendRunResult(
                backend="fake",
                status="completed",
                metrics={"net_return": 0.0, "trade_count": 50},
                warnings=(),
                unsupported_semantics=(),
            )
        ],
        min_trades=10,
    )

    assert decision.decision == "hard_no"
    assert "nonpositive_net_return" in decision.reasons
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


def test_policy_maybe_for_required_backend_unavailable():
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

    assert decision.decision == "maybe"
    assert "backend_unavailable" in decision.reasons
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
