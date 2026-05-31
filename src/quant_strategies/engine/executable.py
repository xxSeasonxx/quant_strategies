from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable

from quant_strategies.decisions import InstrumentRef, StrategyDecision
from quant_strategies.engine.models import Side


@dataclass(frozen=True)
class ExecutableDecision:
    decision: StrategyDecision
    symbol: str
    side: Side
    weight: float
    metadata: dict[str, Any]


def base_unsupported_semantics(decision: StrategyDecision) -> tuple[str, ...]:
    unsupported: list[str] = []
    if decision.intent.action != "open":
        unsupported.append("non_open_intent")
    if not isinstance(decision.instrument, InstrumentRef):
        unsupported.append(_instrument_semantic(decision.instrument.kind))
    if decision.target.direction == "flat":
        unsupported.append("flat_target")
    if decision.target.sizing_kind != "target_weight":
        unsupported.append("non_target_weight_sizing")
    return tuple(dict.fromkeys(unsupported))


def executable_decision(
    decision: StrategyDecision,
    *,
    error_factory: Callable[[str], Exception] = ValueError,
) -> ExecutableDecision:
    unsupported = base_unsupported_semantics(decision)
    if unsupported:
        raise error_factory(_unsupported_message(decision, unsupported[0]))
    side = Side.LONG if decision.target.direction == "long" else Side.SHORT
    return ExecutableDecision(
        decision=decision,
        symbol=decision.instrument.symbol,
        side=side,
        weight=decision.target.size,
        metadata=_jsonable_metadata_value(decision.metadata),
    )


def _instrument_semantic(kind: str) -> str:
    return {
        "future": "future_instrument",
        "option": "option_instrument",
        "multi_leg": "multi_leg_decision",
    }.get(kind, "unsupported_instrument")


def _unsupported_message(decision: StrategyDecision, semantic: str) -> str:
    symbol = decision.instrument.symbol
    if semantic == "non_open_intent":
        return f"execution kernel supports open intent only: {symbol}"
    if semantic in {
        "future_instrument",
        "option_instrument",
        "multi_leg_decision",
        "unsupported_instrument",
    }:
        return f"execution kernel cannot represent {decision.instrument.kind} instrument: {symbol}"
    if semantic == "flat_target":
        return f"execution kernel cannot represent flat target for {symbol}"
    if semantic == "non_target_weight_sizing":
        return f"execution kernel requires target_weight sizing: {symbol}"
    return f"execution kernel cannot represent decision: {symbol}"


def _jsonable_metadata_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable_metadata_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable_metadata_value(item) for item in value]
    return value
