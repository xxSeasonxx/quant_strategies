from __future__ import annotations

from collections.abc import Mapping, Sequence

from quant_strategies.decisions.models import StrategyDecision


def validate_decision_output(
    output: object,
    *,
    strategy_id: str,
) -> tuple[list[StrategyDecision], tuple[str, ...]]:
    if (
        isinstance(output, str | bytes | bytearray)
        or isinstance(output, Mapping)
        or not isinstance(output, Sequence)
    ):
        return [], ("invalid_decision_output",)

    decisions: list[StrategyDecision] = []
    violations: list[str] = []
    for index, item in enumerate(output):
        if not isinstance(item, StrategyDecision):
            violations.append(f"invalid_decision_output[{index}]")
            continue
        if item.strategy_id != strategy_id:
            violations.append(
                f"decision_strategy_id_mismatch[{index}]: expected {strategy_id}, got {item.strategy_id}"
            )
            continue
        decisions.append(item)

    return decisions, tuple(violations)
