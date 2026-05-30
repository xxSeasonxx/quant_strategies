from __future__ import annotations

from datetime import datetime, timezone

import pytest

from quant_strategies.decisions import DecisionIntent, ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.decisions.extended_ontology import (
    DecisionIntent as ExtendedDecisionIntent,
    FutureRef,
    PositionTarget as ExtendedPositionTarget,
    StrategyDecision as ExtendedStrategyDecision,
)
from quant_strategies.engine.executable import base_unsupported_semantics, executable_decision
from quant_strategies.engine.models import Side


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def decision(
    *,
    instrument=None,
    intent=None,
    direction: str = "long",
    sizing_kind: str = "target_weight",
    size: float = 1.0,
    metadata: dict[str, object] | None = None,
):
    instrument = instrument or InstrumentRef(kind="equity_or_etf", symbol="SPY")
    intent = intent or DecisionIntent(action="open")
    is_extended = (
        not isinstance(instrument, InstrumentRef)
        or type(intent) is not DecisionIntent
        or sizing_kind != "target_weight"
    )
    target_cls = ExtendedPositionTarget if is_extended else PositionTarget
    decision_cls = ExtendedStrategyDecision if is_extended else StrategyDecision
    if is_extended and type(intent) is DecisionIntent:
        intent = ExtendedDecisionIntent(action=intent.action)
    return decision_cls(
        strategy_id="demo",
        instrument=instrument,
        intent=intent,
        decision_time=NOW,
        as_of_time=NOW,
        target=target_cls(direction=direction, sizing_kind=sizing_kind, size=size),
        exit_policy=ExitPolicy(max_hold_bars=1),
        metadata=metadata or {},
    )


def test_executable_decision_returns_engine_fields_and_jsonable_metadata():
    item = executable_decision(
        decision(metadata={"nested": {"items": (1, 2)}}),
        error_factory=ValueError,
    )

    assert item.symbol == "SPY"
    assert item.side is Side.LONG
    assert item.weight == 1.0
    assert item.metadata == {"nested": {"items": [1, 2]}}


@pytest.mark.parametrize(
    ("source_decision", "semantic", "message"),
    [
        (
            decision(intent=ExtendedDecisionIntent(action="close", book_side="sell")),
            "non_open_intent",
            "open intent",
        ),
        (
            decision(
                instrument=FutureRef(
                    kind="future",
                    symbol="ESM26",
                    expiry=NOW,
                    multiplier=50.0,
                    settlement="cash",
                )
            ),
            "future_instrument",
            "future instrument",
        ),
        (decision(direction="flat", size=0.0), "flat_target", "flat target"),
        (
            decision(sizing_kind="target_notional"),
            "non_target_weight_sizing",
            "target_weight",
        ),
    ],
)
def test_base_executable_semantics_are_shared(source_decision, semantic: str, message: str):
    assert semantic in base_unsupported_semantics(source_decision)
    with pytest.raises(ValueError, match=message):
        executable_decision(source_decision, error_factory=ValueError)
