from __future__ import annotations

import pytest

from quant_strategies.validation.backends import (
    BackendRunResult,
    FakeBackend,
    ScenarioBackendRunResult,
    get_backend,
)
from quant_strategies.validation.policy import classify_validation


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


def test_policy_clear_yes_for_positive_sufficient_backend_result():
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

    assert decision.decision == "clear_yes"
    assert decision.reasons == ()


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


def test_policy_ignores_diagnostic_scenarios_for_clear_yes():
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

    assert decision.decision == "clear_yes"
    assert decision.reasons == ()


def test_policy_hard_no_for_negative_net_return():
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
    assert "negative_net_return" in decision.reasons


def test_policy_hard_no_for_no_backend_results():
    decision = classify_validation(
        data_passed=True,
        backend_results=[],
        min_trades=10,
    )

    assert decision.decision == "hard_no"
    assert "no_backend_results" in decision.reasons


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
