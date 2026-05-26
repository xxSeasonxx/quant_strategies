from __future__ import annotations

from quant_strategies.validation.capabilities import backend_capability_matrix
from quant_strategies.validation.backends import BackendRunResult, ScenarioBackendRunResult


def scenario_result(*unsupported_semantics: str) -> ScenarioBackendRunResult:
    return ScenarioBackendRunResult(
        window_id="validation_2026_h1",
        scenario_id="validation_2026_h1/base",
        required=True,
        result=BackendRunResult(
            backend="vectorbtpro",
            status="unsupported" if unsupported_semantics else "completed",
            metrics={},
            warnings=(),
            unsupported_semantics=unsupported_semantics,
        ),
    )


def failed_scenario_result(*warnings: str) -> ScenarioBackendRunResult:
    return ScenarioBackendRunResult(
        window_id="validation_2026_h1",
        scenario_id="validation_2026_h1/base",
        required=True,
        result=BackendRunResult(
            backend="vectorbtpro",
            status="failed",
            metrics={},
            warnings=warnings,
            unsupported_semantics=(),
        ),
    )


def test_vectorbtpro_matrix_marks_portfolio_target_weights_conditional():
    matrix = backend_capability_matrix("vectorbtpro", [])
    semantics = {item["semantic"]: item for item in matrix["semantics"]}

    assert matrix["backend"] == "vectorbtpro"
    assert matrix["observed_unsupported_semantics"] == []
    assert semantics["close_fills"]["status"] == "supported"
    assert semantics["target_weight_sizing"]["status"] == "supported"
    assert semantics["portfolio_target_weight"]["status"] == "conditional"
    assert "gross active target weight" in semantics["portfolio_target_weight"]["details"]
    assert semantics["crypto_perp_funding_linear_additive_adjustment"]["status"] == "conditional"


def test_observed_unsupported_semantic_codes_are_flagged():
    matrix = backend_capability_matrix(
        "vectorbtpro",
        [
            scenario_result("threshold_exit_policy"),
            scenario_result("non_close_fill_price"),
        ],
    )
    semantics = {item["semantic"]: item for item in matrix["semantics"]}

    assert matrix["observed_unsupported_semantics"] == [
        "non_close_fill_price",
        "threshold_exit_policy",
    ]
    assert semantics["threshold_exit_policy"]["observed_unsupported"] is True
    assert semantics["non_close_fill_price"]["observed_unsupported"] is True
    assert semantics["portfolio_target_weight"]["observed_unsupported"] is False


def test_warning_prefix_marks_same_symbol_overlap_observed():
    matrix = backend_capability_matrix(
        "vectorbtpro",
        [failed_scenario_result("overlapping_decision_window:BTC-PERP:entry:exit")],
    )
    semantics = {item["semantic"]: item for item in matrix["semantics"]}

    assert matrix["observed_unsupported_semantics"] == ["same_symbol_overlap"]
    assert semantics["same_symbol_overlap"]["observed_unsupported"] is True


def test_warning_prefix_marks_portfolio_target_weight_observed():
    matrix = backend_capability_matrix(
        "vectorbtpro",
        [failed_scenario_result("portfolio_target_weight_exceeds_one:2026-01-01T00:02:00Z:1.1")],
    )
    semantics = {item["semantic"]: item for item in matrix["semantics"]}

    assert matrix["observed_unsupported_semantics"] == ["portfolio_target_weight"]
    assert semantics["portfolio_target_weight"]["observed_unsupported"] is True


def test_fake_matrix_records_test_double_semantic():
    matrix = backend_capability_matrix("fake", [])

    assert matrix == {
        "backend": "fake",
        "observed_unsupported_semantics": [],
        "semantics": [
            {
                "semantic": "test_double",
                "status": "supported",
                "details": "Deterministic validation test double.",
                "observed_unsupported": False,
            }
        ],
    }
