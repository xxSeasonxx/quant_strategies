from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict

from quant_strategies.validation.backends import BackendRunResult


ValidationDecision = Literal["hard_no", "maybe", "clear_yes"]


class PromotionDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: ValidationDecision
    reasons: tuple[str, ...] = ()


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
        metrics = _validated_backend_metrics(result.metrics)
        if metrics is None:
            reasons.append("invalid_backend_metrics")
            continue
        net_return, trade_count = metrics
        if trade_count < min_trades:
            reasons.append("insufficient_trades")
        if net_return <= 0.0:
            reasons.append("negative_net_return")

    if reasons:
        return PromotionDecision(decision="hard_no", reasons=tuple(dict.fromkeys(reasons)))
    return PromotionDecision(decision="clear_yes")
