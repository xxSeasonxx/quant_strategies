from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_strategies.evidence_semantics import validation_evidence_semantics
from quant_strategies.validation.backends import BackendMetrics, BackendRunResult, ScenarioBackendRunResult


ValidationDecision = Literal["hard_no", "mechanical_pass", "watchlist", "mechanical_review_candidate"]


class ValidationPolicyDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: ValidationDecision
    reasons: tuple[str, ...] = ()
    advisory_decision: ValidationDecision | None = None
    evidence_class: str = "validation_advisory"
    promotion_eligible: bool = False
    paper_trade_eligible: bool = False
    live_eligible: bool = False
    requires_manual_approval: bool = True
    passed_gates: tuple[str, ...] = ()
    failed_gates: tuple[str, ...] = ()
    gate_details: dict[str, str] = Field(default_factory=dict)
    overfit_controls: dict[str, Any | None] = Field(
        default_factory=lambda: {
            "candidate_count": None,
            "trial_count": None,
            "parameter_search_space": {},
            "selection_rule": None,
            "split_ids": [],
        }
    )

    @model_validator(mode="after")
    def default_advisory_fields(self) -> ValidationPolicyDecision:
        if self.advisory_decision is None:
            object.__setattr__(self, "advisory_decision", self.decision)
        semantics = validation_evidence_semantics()
        object.__setattr__(self, "evidence_class", str(semantics["evidence_class"]))
        object.__setattr__(self, "promotion_eligible", bool(semantics["promotion_eligible"]))
        object.__setattr__(self, "paper_trade_eligible", bool(semantics["paper_trade_eligible"]))
        object.__setattr__(self, "live_eligible", bool(semantics["live_eligible"]))
        object.__setattr__(
            self,
            "requires_manual_approval",
            bool(semantics["requires_manual_approval"]),
        )
        return self


def _validated_backend_metrics(
    metrics: dict[str, float | int | str | bool | None],
) -> BackendMetrics | None:
    return BackendMetrics.from_mapping(metrics)


def classify_validation(
    *,
    data_passed: bool,
    backend_results: Sequence[BackendRunResult | ScenarioBackendRunResult],
    min_trades: int,
    required_scenario_count: int | None = None,
    required_scenario_ids: Sequence[str] | None = None,
    paper_readiness: object | None = None,
    search_pressure: object | None = None,
) -> ValidationPolicyDecision:
    overfit_controls = overfit_controls_from_search_pressure(search_pressure)

    def finish(decision: ValidationPolicyDecision) -> ValidationPolicyDecision:
        reasons = decision.reasons
        verdict = decision.decision
        if decision.decision == "mechanical_review_candidate" and _has_search_pressure(overfit_controls):
            verdict = "watchlist"
            reasons = tuple(
                dict.fromkeys((*reasons, "multiple_testing_not_corrected_advisory_only"))
            )
        return decision.model_copy(
            update={
                "decision": verdict,
                "advisory_decision": verdict,
                "reasons": reasons,
                "overfit_controls": overfit_controls,
            }
        )

    if not data_passed:
        return finish(
            _decision(
                "hard_no",
                reasons=("data_audit_failed",),
                failed=("data_audit",),
                details={"data_audit": "failed"},
            )
        )
    if not backend_results:
        return finish(
            _decision(
                "hard_no",
                reasons=("no_backend_results",),
                failed=("backend_results",),
                details={"backend_results": "none"},
            )
        )

    scenario_results = tuple(_scenario_result(item) for item in backend_results)
    required_results = tuple(item for item in scenario_results if item.required)
    required_gate = _required_scenario_gate(
        required_results,
        required_scenario_count=required_scenario_count,
        required_scenario_ids=required_scenario_ids,
    )
    if required_gate is not None:
        return finish(required_gate)

    backend_gate = _backend_execution_gate(required_results, min_trades=min_trades)
    if backend_gate.decision != "mechanical_pass":
        return finish(backend_gate)

    return finish(
        _paper_readiness_decision(
            required_results,
            min_trades=min_trades,
            paper_readiness=paper_readiness,
            base_passed_gates=backend_gate.passed_gates,
            base_gate_details=backend_gate.gate_details,
        )
    )


def overfit_controls_from_search_pressure(search_pressure: object | None) -> dict[str, Any | None]:
    parameter_search_space = _settings_value(search_pressure, "parameter_search_space", {})
    split_ids = _settings_value(search_pressure, "split_ids", ())
    return {
        "candidate_count": _settings_value(search_pressure, "candidate_count", None),
        "trial_count": _settings_value(search_pressure, "trial_count", None),
        "parameter_search_space": dict(parameter_search_space or {}),
        "selection_rule": _settings_value(search_pressure, "selection_rule", None),
        "split_ids": list(split_ids or ()),
    }


def _has_search_pressure(overfit_controls: dict[str, Any | None]) -> bool:
    return any(
        (
            overfit_controls.get("candidate_count") is not None,
            overfit_controls.get("trial_count") is not None,
            bool(overfit_controls.get("parameter_search_space")),
            overfit_controls.get("selection_rule") is not None,
            bool(overfit_controls.get("split_ids")),
        )
    )


def _scenario_result(
    item: BackendRunResult | ScenarioBackendRunResult,
) -> ScenarioBackendRunResult:
    if isinstance(item, ScenarioBackendRunResult):
        return item
    return ScenarioBackendRunResult(
        window_id="",
        scenario_id="",
        required=True,
        result=item,
    )


def _decision(
    decision: ValidationDecision,
    *,
    reasons: tuple[str, ...] = (),
    passed: tuple[str, ...] = (),
    failed: tuple[str, ...] = (),
    details: dict[str, str] | None = None,
) -> ValidationPolicyDecision:
    return ValidationPolicyDecision(
        decision=decision,
        reasons=reasons,
        passed_gates=passed,
        failed_gates=failed,
        gate_details={} if details is None else details,
    )


def _required_scenario_gate(
    required_results: tuple[ScenarioBackendRunResult, ...],
    *,
    required_scenario_count: int | None = None,
    required_scenario_ids: Sequence[str] | None = None,
) -> ValidationPolicyDecision | None:
    actual_non_empty_ids = [item.scenario_id for item in required_results if item.scenario_id]
    if len(actual_non_empty_ids) != len(set(actual_non_empty_ids)):
        return _decision(
            "hard_no",
            reasons=("duplicate_required_scenarios",),
            failed=("required_scenarios",),
            details={"required_scenarios": "duplicate required scenario ids"},
        )
    if required_scenario_ids is not None:
        expected_ids = set(required_scenario_ids)
        actual_ids = [item.scenario_id for item in required_results]
        if len(actual_ids) != len(set(actual_ids)):
            return _decision(
                "hard_no",
                reasons=("duplicate_required_scenarios",),
                failed=("required_scenarios",),
                details={"required_scenarios": "duplicate required scenario ids"},
            )
        if set(actual_ids) != expected_ids:
            return _decision(
                "hard_no",
                reasons=("missing_required_scenarios",),
                failed=("required_scenarios",),
                details={
                    "required_scenarios": (
                        f"{len(actual_ids)} actual ids != {len(expected_ids)} expected ids"
                    )
                },
            )
    if required_scenario_count is not None and len(required_results) < required_scenario_count:
        return _decision(
            "hard_no",
            reasons=("missing_required_scenarios",),
            failed=("required_scenarios",),
            details={
                "required_scenarios": _gate_detail(
                    len(required_results),
                    ">=",
                    required_scenario_count,
                )
            },
        )
    if not required_results:
        return _decision(
            "hard_no",
            reasons=("no_required_backend_results",),
            failed=("required_backend_results",),
            details={"required_backend_results": "none"},
        )
    return None


def _backend_execution_gate(
    required_results: tuple[ScenarioBackendRunResult, ...],
    *,
    min_trades: int,
) -> ValidationPolicyDecision:
    for item in required_results:
        result = item.result
        if result.status == "failed":
            return _decision(
                "hard_no",
                reasons=(f"{result.backend}_failed",),
                failed=("required_backend_completed",),
                details={"required_backend_completed": f"{item.scenario_id} failed"},
            )

    invalid_metrics = False
    insufficient_trades = False
    total_required_trades = 0
    for item in required_results:
        result = item.result
        if result.status != "completed":
            continue
        metrics = _validated_backend_metrics(result.metrics)
        if metrics is None:
            invalid_metrics = True
            continue
        trade_count = metrics.trade_count
        total_required_trades += trade_count
        if trade_count < min_trades:
            insufficient_trades = True

    if invalid_metrics:
        return _decision(
            "hard_no",
            reasons=("invalid_backend_metrics",),
            failed=("backend_metrics",),
            details={"backend_metrics": "missing or invalid net_return/trade_count"},
        )
    if insufficient_trades:
        return _decision(
            "hard_no",
            reasons=("insufficient_trades",),
            failed=("mechanical_min_trades",),
            details={"mechanical_min_trades": f"one or more required scenarios < {min_trades}"},
        )

    unavailable = [item.result for item in required_results if item.result.status == "unavailable"]
    if unavailable:
        return _decision(
            "hard_no",
            reasons=("backend_unavailable",),
            failed=("required_backend_available",),
            details={"required_backend_available": f"{len(unavailable)} unavailable"},
        )

    unsupported = [
        item.result
        for item in required_results
        if item.result.unsupported_semantics or item.result.status == "unsupported"
    ]
    if unsupported:
        return _decision(
            "hard_no",
            reasons=("unsupported_semantics",),
            failed=("required_backend_semantics",),
            details={"required_backend_semantics": f"{len(unsupported)} unsupported"},
        )

    return _decision(
        "mechanical_pass",
        passed=("mechanical_validation",),
        details={
            "mechanical_validation": "required scenarios completed with valid metrics",
            "mechanical_total_required_trades": str(total_required_trades),
        },
    )


_PAPER_READINESS_GATES: tuple[str, ...] = (
    "min_windows",
    "min_total_trades",
    "no_zero_trade_windows",
    "compounded_realistic_net_positive",
    "positive_window_fraction",
    "stressed_net_floor",
    "fill_lag_net_floor",
)


def _paper_readiness_decision(
    required_results: tuple[ScenarioBackendRunResult, ...],
    *,
    min_trades: int,
    paper_readiness: object | None,
    base_passed_gates: tuple[str, ...],
    base_gate_details: dict[str, str],
) -> ValidationPolicyDecision:
    _ = min_trades
    metrics_by_scenario = {
        item.scenario_id: _validated_backend_metrics(item.result.metrics)
        for item in required_results
    }
    complete_metrics = {
        scenario_id: metrics
        for scenario_id, metrics in metrics_by_scenario.items()
        if metrics is not None
    }

    if not _paper_enabled(paper_readiness):
        return _decision(
            "mechanical_pass",
            reasons=("paper_readiness_disabled",),
            passed=base_passed_gates,
            failed=("paper_readiness_enabled",),
            details={**base_gate_details, "paper_readiness_enabled": "false"},
        )

    min_windows = int(_settings_value(paper_readiness, "min_windows", 2))
    min_total_trades = int(_settings_value(paper_readiness, "min_total_trades", 30))
    min_positive_window_fraction = float(
        _settings_value(paper_readiness, "min_positive_window_fraction", 0.5)
    )
    max_stressed_net_loss = float(_settings_value(paper_readiness, "max_stressed_net_loss", -0.02))
    max_fill_lag_net_loss = float(_settings_value(paper_readiness, "max_fill_lag_net_loss", -0.02))

    realistic = tuple(item for item in required_results if _scenario_key(item) == "cost")
    stressed = tuple(item for item in required_results if _scenario_key(item) == "cost_stress")
    fill_lag = tuple(item for item in required_results if _scenario_key(item) == "fill_lag")
    has_realistic = bool(realistic)
    has_stressed = bool(stressed)
    has_fill_lag = bool(fill_lag)
    windows = sorted({item.window_id for item in realistic})
    realistic_metrics = [complete_metrics[item.scenario_id] for item in realistic]
    stressed_metrics = [complete_metrics[item.scenario_id] for item in stressed]
    fill_lag_metrics = [complete_metrics[item.scenario_id] for item in fill_lag]

    window_count = len(windows)
    realistic_total_trades = sum(metrics.trade_count for metrics in realistic_metrics)
    zero_trade_windows = [
        item.window_id
        for item in realistic
        if complete_metrics[item.scenario_id].trade_count == 0
    ]
    compounded_realistic_net = _compounded_return(metrics.net_return for metrics in realistic_metrics)
    positive_realistic_evidence = compounded_realistic_net > 0.0
    positive_windows = sum(
        1 for item in realistic if complete_metrics[item.scenario_id].net_return > 0.0
    )
    positive_fraction = positive_windows / window_count if window_count else 0.0
    worst_stressed_net = min((metrics.net_return for metrics in stressed_metrics), default=0.0)
    worst_fill_lag_net = min((metrics.net_return for metrics in fill_lag_metrics), default=0.0)

    gate_results: dict[str, tuple[bool, str]] = {
        "min_windows": (
            window_count >= min_windows,
            _gate_detail(window_count, ">=", min_windows)
            if has_realistic
            else _missing_scenario_detail("cost"),
        ),
        "min_total_trades": (
            realistic_total_trades >= min_total_trades,
            _gate_detail(realistic_total_trades, ">=", min_total_trades)
            if has_realistic
            else _missing_scenario_detail("cost"),
        ),
        "no_zero_trade_windows": (
            not zero_trade_windows and has_realistic,
            (
                _missing_scenario_detail("cost")
                if not has_realistic
                else ",".join(zero_trade_windows)
                if zero_trade_windows
                else "passed"
            ),
        ),
        "compounded_realistic_net_positive": (
            positive_realistic_evidence,
            _gate_detail(compounded_realistic_net, ">", 0.0)
            if has_realistic
            else _missing_scenario_detail("cost"),
        ),
        "positive_window_fraction": (
            positive_fraction >= min_positive_window_fraction,
            _gate_detail(positive_fraction, ">=", min_positive_window_fraction)
            if has_realistic
            else _missing_scenario_detail("cost"),
        ),
        "stressed_net_floor": (
            has_stressed and worst_stressed_net >= max_stressed_net_loss,
            _gate_detail(worst_stressed_net, ">=", max_stressed_net_loss)
            if has_stressed
            else _missing_scenario_detail("cost_stress"),
        ),
        "fill_lag_net_floor": (
            has_fill_lag and worst_fill_lag_net >= max_fill_lag_net_loss,
            _gate_detail(worst_fill_lag_net, ">=", max_fill_lag_net_loss)
            if has_fill_lag
            else _missing_scenario_detail("fill_lag"),
        ),
    }

    passed_gates = list(base_passed_gates)
    failed_gates: list[str] = []
    gate_details = dict(base_gate_details)
    for gate_name in _PAPER_READINESS_GATES:
        passed, detail = gate_results[gate_name]
        if passed:
            passed_gates.append(gate_name)
        else:
            failed_gates.append(gate_name)
        gate_details[gate_name] = detail

    passed = tuple(passed_gates)
    failed = tuple(failed_gates)

    if not failed:
        return _decision(
            "mechanical_review_candidate",
            passed=passed,
            details=gate_details,
        )
    if positive_realistic_evidence:
        return _decision(
            "watchlist",
            reasons=("paper_readiness_gates_failed",),
            passed=passed,
            failed=failed,
            details=gate_details,
        )
    return _decision(
        "hard_no",
        reasons=("no_positive_realistic_cost_evidence",),
        passed=passed,
        failed=failed,
        details=gate_details,
    )


def _settings_value(settings: object | None, name: str, default: object) -> object:
    if settings is None:
        return default
    return getattr(settings, name, default)


def _compounded_return(returns: Iterable[float]) -> float:
    return math.prod(1.0 + value for value in returns) - 1.0


def _paper_enabled(settings: object | None) -> bool:
    return bool(_settings_value(settings, "enabled", True))


def _scenario_key(item: ScenarioBackendRunResult) -> str:
    if item.scenario_kind:
        return item.scenario_kind
    return item.scenario_id.rsplit("/", 1)[-1]


def _gate_detail(actual: object, operator: str, expected: object) -> str:
    return f"{actual} {operator} {expected}"


def _missing_scenario_detail(scenario_kind: str) -> str:
    return f"missing {scenario_kind} scenarios"
