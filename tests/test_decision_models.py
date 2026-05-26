from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from quant_strategies.decisions import (
    ExitPolicy,
    InstrumentRef,
    ObservationRef,
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


def test_strategy_decision_accepts_multiple_typed_observations():
    decision = StrategyDecision(
        strategy_id="cross_sectional_momentum",
        instrument=InstrumentRef(kind="equity_or_etf", symbol="SPY"),
        decision_time=DECISION_TIME,
        as_of_time=AS_OF_TIME,
        target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
        exit_policy=ExitPolicy(max_hold_bars=5),
        observations=(
            ObservationRef(symbol="AAPL", timestamp=AS_OF_TIME, field="close", source="quant_data"),
            ObservationRef(symbol="MSFT", timestamp=AS_OF_TIME, field="return_21d", source="quant_data"),
        ),
    )

    assert decision.observations == (
        ObservationRef(symbol="AAPL", timestamp=AS_OF_TIME, field="close", source="quant_data"),
        ObservationRef(symbol="MSFT", timestamp=AS_OF_TIME, field="return_21d", source="quant_data"),
    )


def test_strategy_decision_defaults_observations_to_empty_tuple():
    decision = StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
        decision_time=DECISION_TIME,
        as_of_time=AS_OF_TIME,
        target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
        exit_policy=ExitPolicy(max_hold_bars=5),
    )

    assert decision.observations == ()


def test_observation_ref_rejects_naive_timestamp():
    with pytest.raises(ValidationError, match="timestamp must be timezone-aware"):
        ObservationRef(symbol="BTC-PERP", timestamp=datetime(2026, 1, 2, 12, 0))


def test_observation_ref_rejects_empty_symbol():
    with pytest.raises(ValidationError, match="symbol must be non-empty"):
        ObservationRef(symbol=" ", timestamp=AS_OF_TIME)


def test_strategy_decision_serializes_observations_to_json():
    decision = StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
        decision_time=DECISION_TIME,
        as_of_time=AS_OF_TIME,
        target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
        exit_policy=ExitPolicy(max_hold_bars=5),
        observations=(ObservationRef(symbol="BTC-PERP", timestamp=AS_OF_TIME, field="funding_rate"),),
    )

    assert decision.model_dump(mode="json")["observations"] == [
        {
            "symbol": "BTC-PERP",
            "timestamp": "2026-01-02T12:00:00Z",
            "field": "funding_rate",
            "source": None,
        }
    ]


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


def test_strategy_decision_requires_timezone_aware_as_of_time():
    with pytest.raises(ValidationError, match="as_of_time must be timezone-aware"):
        StrategyDecision(
            strategy_id="demo",
            instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
            decision_time=DECISION_TIME,
            as_of_time=datetime(2026, 1, 2, 12, 0),
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


def test_position_target_rejects_coerced_size():
    with pytest.raises(ValidationError):
        PositionTarget(direction="long", sizing_kind="target_weight", size="1.25")


def test_exit_policy_rejects_non_positive_thresholds():
    with pytest.raises(ValidationError, match="exit bps values must be finite and positive"):
        ExitPolicy(max_hold_bars=5, stop_loss_bps=0.0)


def test_exit_policy_rejects_coerced_max_hold_bars():
    with pytest.raises(ValidationError):
        ExitPolicy(max_hold_bars="5")


@pytest.mark.parametrize(
    "thresholds",
    [
        {"stop_loss_bps": float("inf")},
        {"take_profit_bps": float("nan")},
    ],
)
def test_exit_policy_rejects_non_finite_thresholds(thresholds):
    with pytest.raises(ValidationError, match="exit bps values must be finite and positive"):
        ExitPolicy(max_hold_bars=5, **thresholds)


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


def test_metadata_rejects_non_standard_json_nan():
    with pytest.raises(ValidationError, match="metadata must be JSON-compatible"):
        StrategyDecision(
            strategy_id="demo",
            instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
            decision_time=DECISION_TIME,
            as_of_time=AS_OF_TIME,
            target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
            exit_policy=ExitPolicy(max_hold_bars=5),
            metadata={"bad": float("nan")},
        )


def test_metadata_is_immutable_after_construction():
    decision = StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
        decision_time=DECISION_TIME,
        as_of_time=AS_OF_TIME,
        target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
        exit_policy=ExitPolicy(max_hold_bars=5),
        metadata={"x": 1},
    )

    with pytest.raises(TypeError):
        decision.metadata["x"] = 2


def test_nested_metadata_is_immutable_after_construction():
    decision = StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
        decision_time=DECISION_TIME,
        as_of_time=AS_OF_TIME,
        target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
        exit_policy=ExitPolicy(max_hold_bars=5),
        metadata={"outer": {"items": [{"x": 1}]}},
    )

    with pytest.raises(TypeError):
        decision.metadata["outer"]["items"][0] = {"x": 2}
    with pytest.raises(TypeError):
        decision.metadata["outer"]["items"][0]["x"] = 2


def test_nested_metadata_is_isolated_from_caller_mutation():
    metadata = {"outer": {"items": [{"x": 1}]}}
    decision = StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
        decision_time=DECISION_TIME,
        as_of_time=AS_OF_TIME,
        target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
        exit_policy=ExitPolicy(max_hold_bars=5),
        metadata=metadata,
    )

    metadata["outer"]["items"][0]["x"] = 2
    metadata["outer"]["items"].append({"x": 3})
    metadata["outer"]["new"] = "caller"

    assert decision.metadata["outer"]["items"][0]["x"] == 1
    assert len(decision.metadata["outer"]["items"]) == 1
    assert "new" not in decision.metadata["outer"]


def test_metadata_rejects_nested_non_string_mapping_keys():
    with pytest.raises(ValidationError, match="metadata must be JSON-compatible"):
        StrategyDecision(
            strategy_id="demo",
            instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
            decision_time=DECISION_TIME,
            as_of_time=AS_OF_TIME,
            target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
            exit_policy=ExitPolicy(max_hold_bars=5),
            metadata={"outer": [{1: "lossy"}]},
        )
