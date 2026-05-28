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
    seen_decision_ids: set[str] = set()
    seen_execution_keys: set[tuple[str, object]] = set()
    for index, item in enumerate(output):
        if not isinstance(item, StrategyDecision):
            violations.append(f"invalid_decision_output[{index}]")
            continue
        if item.strategy_id != strategy_id:
            violations.append(
                f"decision_strategy_id_mismatch[{index}]: expected {strategy_id}, got {item.strategy_id}"
            )
            continue
        if item.decision_id in seen_decision_ids:
            violations.append(f"duplicate_decision_id[{index}]: {item.decision_id}")
            continue
        seen_decision_ids.add(item.decision_id)
        execution_key = (item.instrument.symbol, item.decision_time)
        if execution_key in seen_execution_keys:
            violations.append(
                "duplicate_decision_execution_key"
                f"[{index}]: {item.instrument.symbol}@{item.decision_time.isoformat()}"
            )
            continue
        seen_execution_keys.add(execution_key)
        decisions.append(item)

    return decisions, tuple(violations)
