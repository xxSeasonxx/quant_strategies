from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from quant_strategies.validation.backends import BackendRunResult


ValidationDecision = Literal["hard_no", "maybe", "clear_yes"]


class PromotionDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: ValidationDecision
    reasons: tuple[str, ...] = ()


def classify_validation(
    *,
    data_passed: bool,
    backend_results: list[BackendRunResult],
    min_trades: int,
) -> PromotionDecision:
    reasons: list[str] = []
    if not data_passed:
        reasons.append("data_audit_failed")
        return PromotionDecision(decision="hard_no", reasons=tuple(reasons))
    if not backend_results:
        return PromotionDecision(decision="hard_no", reasons=("no_backend_results",))

    unsupported = [
        result
        for result in backend_results
        if result.unsupported_semantics or result.status == "unsupported"
    ]
    if unsupported:
        return PromotionDecision(decision="maybe", reasons=("unsupported_semantics",))

    for result in backend_results:
        if result.status != "completed":
            return PromotionDecision(decision="hard_no", reasons=(f"{result.backend}_failed",))
        net_return = float(result.metrics.get("net_return", 0.0) or 0.0)
        trade_count = int(result.metrics.get("trade_count", 0) or 0)
        if trade_count < min_trades:
            reasons.append("insufficient_trades")
        if net_return <= 0.0:
            reasons.append("negative_net_return")

    if reasons:
        return PromotionDecision(decision="hard_no", reasons=tuple(dict.fromkeys(reasons)))
    return PromotionDecision(decision="clear_yes")
