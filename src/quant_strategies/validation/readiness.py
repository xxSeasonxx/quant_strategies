from __future__ import annotations

from typing import Any

from quant_strategies.core.decision_readiness import check_decision_readiness
from quant_strategies.decisions import TargetDecision


def check_validation_readiness(
    decisions: list[TargetDecision],
    readiness: Any,
    *,
    data_kind: str = "bars",
) -> tuple[str, ...]:
    return check_decision_readiness(decisions, readiness, data_kind=data_kind)
