from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from quant_strategies.decisions import (
    ExitPolicy,
    InstrumentRef,
    PositionTarget,
    StrategyDecision,
)


DECISION_TIME = datetime(2026, 1, 2, 12, 1, tzinfo=timezone.utc)
AS_OF_TIME = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)


def test_strategy_decision_accepts_explicit_position_target():
    decision = StrategyDecision(
        strategy_id="crypto_perp_funding_crowding_reversal",
        instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
        decision_time=DECISION_TIME,
        as_of_time=AS_OF_TIME,
        target=PositionTarget(direction="short", sizing_kind="target_weight", size=1.0),
        exit_policy=ExitPolicy(max_hold_bars=480),
        metadata={"funding_pressure_bps": 3.5},
    )

    assert decision.instrument.symbol == "BTC-PERP"
    assert decision.target.direction == "short"
    assert decision.exit_policy.max_hold_bars == 480


def test_strategy_decision_requires_timezone_aware_times():
    with pytest.raises(ValidationError, match="decision_time must be timezone-aware"):
        StrategyDecision(
            strategy_id="demo",
            instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
            decision_time=datetime(2026, 1, 2, 12, 1),
            as_of_time=AS_OF_TIME,
            target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
            exit_policy=ExitPolicy(max_hold_bars=5),
        )


def test_strategy_decision_rejects_lookahead_as_of_time():
    with pytest.raises(ValidationError, match="as_of_time must be on or before decision_time"):
        StrategyDecision(
            strategy_id="demo",
            instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
            decision_time=AS_OF_TIME,
            as_of_time=DECISION_TIME,
            target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
            exit_policy=ExitPolicy(max_hold_bars=5),
        )


def test_position_target_rejects_raw_order_language():
    with pytest.raises(ValidationError):
        PositionTarget(direction="sell", sizing_kind="target_weight", size=1.0)


def test_flat_target_must_have_zero_size():
    with pytest.raises(ValidationError, match="flat target size must be 0"):
        PositionTarget(direction="flat", sizing_kind="target_weight", size=1.0)


def test_non_flat_target_must_have_positive_size():
    with pytest.raises(ValidationError, match="long and short target size must be positive"):
        PositionTarget(direction="short", sizing_kind="target_weight", size=0.0)


def test_exit_policy_rejects_non_positive_thresholds():
    with pytest.raises(ValidationError, match="exit bps values must be finite and positive"):
        ExitPolicy(max_hold_bars=5, stop_loss_bps=0.0)


def test_metadata_must_be_json_compatible():
    with pytest.raises(ValidationError, match="metadata must be JSON-compatible"):
        StrategyDecision(
            strategy_id="demo",
            instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
            decision_time=DECISION_TIME,
            as_of_time=AS_OF_TIME,
            target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
            exit_policy=ExitPolicy(max_hold_bars=5),
            metadata={"bad": {1, 2, 3}},
        )
