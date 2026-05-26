from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from quant_strategies.evidence_semantics import validation_evidence_semantics
from quant_strategies.validation.backends import BackendRunResult, ScenarioBackendRunResult


ValidationDecision = Literal["hard_no", "maybe", "mechanical_pass"]


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
) -> ValidationPolicyDecision:
    reasons: list[str] = []
    if not data_passed:
        reasons.append("data_audit_failed")
        return ValidationPolicyDecision(decision="hard_no", reasons=tuple(reasons))
    if not backend_results:
        return ValidationPolicyDecision(decision="hard_no", reasons=("no_backend_results",))

    scenario_results = tuple(_scenario_result(item) for item in backend_results)
    required_results = [item for item in scenario_results if item.required]
    if required_scenario_ids is not None:
        expected_ids = set(required_scenario_ids)
        actual_ids = [item.scenario_id for item in required_results]
        if len(actual_ids) != len(set(actual_ids)):
            return ValidationPolicyDecision(decision="hard_no", reasons=("duplicate_required_scenarios",))
        if set(actual_ids) != expected_ids:
            return ValidationPolicyDecision(decision="hard_no", reasons=("missing_required_scenarios",))
    if required_scenario_count is not None and len(required_results) < required_scenario_count:
        return ValidationPolicyDecision(decision="hard_no", reasons=("missing_required_scenarios",))
    if not required_results:
        return ValidationPolicyDecision(decision="hard_no", reasons=("no_required_backend_results",))

    for item in required_results:
        result = item.result
        if result.status == "failed":
            return ValidationPolicyDecision(decision="hard_no", reasons=(f"{result.backend}_failed",))

    unavailable = [item.result for item in required_results if item.result.status == "unavailable"]
    if unavailable:
        return ValidationPolicyDecision(decision="maybe", reasons=("backend_unavailable",))

    unsupported = [
        item.result
        for item in required_results
        if item.result.unsupported_semantics or item.result.status == "unsupported"
    ]
    if unsupported:
        return ValidationPolicyDecision(decision="maybe", reasons=("unsupported_semantics",))

    for item in required_results:
        result = item.result
        if result.status != "completed":
            return ValidationPolicyDecision(decision="hard_no", reasons=(f"{result.backend}_failed",))
        metrics = _validated_backend_metrics(result.metrics)
        if metrics is None:
            reasons.append("invalid_backend_metrics")
            continue
        net_return, trade_count = metrics
        if trade_count < min_trades:
            reasons.append("insufficient_trades")
        if net_return <= 0.0:
            reasons.append("nonpositive_net_return")

    if reasons:
        return ValidationPolicyDecision(decision="hard_no", reasons=tuple(dict.fromkeys(reasons)))
    return ValidationPolicyDecision(decision="mechanical_pass")


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
