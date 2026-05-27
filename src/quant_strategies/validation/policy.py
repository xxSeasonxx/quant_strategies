from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_strategies.evidence_semantics import validation_evidence_semantics
from quant_strategies.validation.backends import BackendRunResult, ScenarioBackendRunResult


ValidationDecision = Literal["hard_no", "mechanical_pass", "watchlist", "paper_candidate"]


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
            "trial_count": None,
            "deflated_sharpe": None,
            "monte_carlo": None,
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


def _metric_number(metrics: dict[str, float | int | str | bool | None], name: str) -> float | None:
    if name not in metrics:
        return None
    value = metrics[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _validated_backend_metrics(
    metrics: dict[str, float | int | str | bool | None],
) -> tuple[float, int] | None:
    net_return = _metric_number(metrics, "net_return")
    trade_count = _metric_number(metrics, "trade_count")
    if net_return is None or trade_count is None:
        return None
    if trade_count < 0 or not trade_count.is_integer():
        return None
    return net_return, int(trade_count)


def classify_validation(
    *,
    data_passed: bool,
    backend_results: Sequence[BackendRunResult | ScenarioBackendRunResult],
    min_trades: int,
    required_scenario_count: int | None = None,
    required_scenario_ids: Sequence[str] | None = None,
    paper_readiness: object | None = None,
) -> ValidationPolicyDecision:
    if not data_passed:
        return _decision(
            "hard_no",
            reasons=("data_audit_failed",),
            failed=("data_audit",),
            details={"data_audit": "failed"},
        )
    if not backend_results:
        return _decision(
            "hard_no",
            reasons=("no_backend_results",),
            failed=("backend_results",),
            details={"backend_results": "none"},
        )

    scenario_results = tuple(_scenario_result(item) for item in backend_results)
    required_results = tuple(item for item in scenario_results if item.required)
    required_gate = _required_scenario_gate(
        required_results,
        required_scenario_count=required_scenario_count,
        required_scenario_ids=required_scenario_ids,
    )
    if required_gate is not None:
        return required_gate

    backend_gate = _backend_execution_gate(required_results, min_trades=min_trades)
    if backend_gate.decision != "mechanical_pass":
        return backend_gate

    return _paper_readiness_decision(
        required_results,
        min_trades=min_trades,
        paper_readiness=paper_readiness,
        base_passed_gates=backend_gate.passed_gates,
        base_gate_details=backend_gate.gate_details,
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
        _, trade_count = metrics
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
            "watchlist",
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
            "watchlist",
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

    passed_gates = list(base_passed_gates)
    failed_gates: list[str] = []
    gate_details = dict(base_gate_details)

    if not _paper_enabled(paper_readiness):
        return _decision(
            "mechanical_pass",
            reasons=("paper_readiness_disabled",),
            passed=tuple(passed_gates),
            failed=("paper_readiness_enabled",),
            details={**gate_details, "paper_readiness_enabled": "false"},
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
    if window_count >= min_windows:
        passed_gates.append("min_windows")
    else:
        failed_gates.append("min_windows")
    gate_details["min_windows"] = (
        _gate_detail(window_count, ">=", min_windows)
        if has_realistic
        else _missing_scenario_detail("cost")
    )

    realistic_total_trades = sum(trade_count for _, trade_count in realistic_metrics)
    if realistic_total_trades >= min_total_trades:
        passed_gates.append("min_total_trades")
    else:
        failed_gates.append("min_total_trades")
    gate_details["min_total_trades"] = (
        _gate_detail(realistic_total_trades, ">=", min_total_trades)
        if has_realistic
        else _missing_scenario_detail("cost")
    )

    zero_trade_windows = [
        item.window_id
        for item in realistic
        if complete_metrics[item.scenario_id][1] == 0
    ]
    if not zero_trade_windows and has_realistic:
        passed_gates.append("no_zero_trade_windows")
    else:
        failed_gates.append("no_zero_trade_windows")
    if not has_realistic:
        gate_details["no_zero_trade_windows"] = _missing_scenario_detail("cost")
    elif zero_trade_windows:
        gate_details["no_zero_trade_windows"] = ",".join(zero_trade_windows)
    else:
        gate_details["no_zero_trade_windows"] = "passed"

    realistic_net = sum(net_return for net_return, _ in realistic_metrics)
    positive_realistic_evidence = realistic_net > 0.0
    if positive_realistic_evidence:
        passed_gates.append("aggregate_realistic_net_positive")
    else:
        failed_gates.append("aggregate_realistic_net_positive")
    gate_details["aggregate_realistic_net_positive"] = (
        _gate_detail(realistic_net, ">", 0.0)
        if has_realistic
        else _missing_scenario_detail("cost")
    )

    positive_windows = sum(
        1 for item in realistic if complete_metrics[item.scenario_id][0] > 0.0
    )
    positive_fraction = positive_windows / window_count if window_count else 0.0
    if positive_fraction >= min_positive_window_fraction:
        passed_gates.append("positive_window_fraction")
    else:
        failed_gates.append("positive_window_fraction")
    gate_details["positive_window_fraction"] = _gate_detail(
        positive_fraction,
        ">=",
        min_positive_window_fraction,
    )
    if not has_realistic:
        gate_details["positive_window_fraction"] = _missing_scenario_detail("cost")

    worst_stressed_net = min((net_return for net_return, _ in stressed_metrics), default=0.0)
    if has_stressed and worst_stressed_net >= max_stressed_net_loss:
        passed_gates.append("stressed_net_floor")
    else:
        failed_gates.append("stressed_net_floor")
    gate_details["stressed_net_floor"] = (
        _gate_detail(worst_stressed_net, ">=", max_stressed_net_loss)
        if has_stressed
        else _missing_scenario_detail("cost_stress")
    )

    worst_fill_lag_net = min((net_return for net_return, _ in fill_lag_metrics), default=0.0)
    if has_fill_lag and worst_fill_lag_net >= max_fill_lag_net_loss:
        passed_gates.append("fill_lag_net_floor")
    else:
        failed_gates.append("fill_lag_net_floor")
    gate_details["fill_lag_net_floor"] = (
        _gate_detail(worst_fill_lag_net, ">=", max_fill_lag_net_loss)
        if has_fill_lag
        else _missing_scenario_detail("fill_lag")
    )

    if not failed_gates:
        return _decision(
            "paper_candidate",
            passed=tuple(passed_gates),
            details=gate_details,
        )
    if positive_realistic_evidence:
        return _decision(
            "watchlist",
            reasons=("paper_readiness_gates_failed",),
            passed=tuple(passed_gates),
            failed=tuple(failed_gates),
            details=gate_details,
        )
    return _decision(
        "mechanical_pass",
        reasons=("no_positive_realistic_cost_evidence",),
        passed=tuple(passed_gates),
        failed=tuple(failed_gates),
        details=gate_details,
    )


def _settings_value(settings: object | None, name: str, default: object) -> object:
    if settings is None:
        return default
    return getattr(settings, name, default)


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
