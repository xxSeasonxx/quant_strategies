from __future__ import annotations

from datetime import UTC, datetime

from quant_strategies.decisions import (
    ExitPolicy,
    InstrumentRef,
    ObservationRef,
    PositionTarget,
    StrategyDecision,
)
from quant_strategies.validation.config import ValidationReadinessConfig
from quant_strategies.validation.readiness import check_validation_readiness

AS_OF = datetime(2026, 1, 1, tzinfo=UTC)


def decision(*, observations: tuple[ObservationRef, ...]) -> StrategyDecision:
    return StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
        decision_time=AS_OF,
        as_of_time=AS_OF,
        target=PositionTarget(direction="short", sizing_kind="target_weight", size=1.0),
        exit_policy=ExitPolicy(max_hold_bars=1),
        observations=observations,
    )


def readiness() -> ValidationReadinessConfig:
    return ValidationReadinessConfig(
        min_observations_per_decision=1,
        required_observation_fields=("close",),
    )


def test_validation_readiness_passes_with_required_observation_field():
    violations = check_validation_readiness(
        [
            decision(
                observations=(ObservationRef(symbol="BTC-PERP", timestamp=AS_OF, field="close"),)
            )
        ],
        readiness(),
    )

    assert violations == ()


def test_validation_readiness_fails_when_observations_are_missing():
    violations = check_validation_readiness([decision(observations=())], readiness())

    assert violations == (
        "decision[0] has 0 observations; requires at least 1",
        "decision[0] has 0 distinct observation symbols; requires at least 1",
        "decision[0] missing required observation fields: ['close']",
    )


def test_validation_readiness_fails_when_required_field_is_missing():
    violations = check_validation_readiness(
        [
            decision(
                observations=(
                    ObservationRef(symbol="BTC-PERP", timestamp=AS_OF, field="funding_rate"),
                )
            )
        ],
        readiness(),
    )

    assert violations == ("decision[0] missing required observation fields: ['close']",)


def test_validation_readiness_fails_when_distinct_symbol_floor_is_not_met():
    config = ValidationReadinessConfig(
        min_observations_per_decision=1,
        min_distinct_observation_symbols_per_decision=2,
        required_observation_fields=("close",),
    )

    violations = check_validation_readiness(
        [
            decision(
                observations=(
                    ObservationRef(symbol="BTC-PERP", timestamp=AS_OF, field="close"),
                    ObservationRef(symbol="BTC-PERP", timestamp=AS_OF, field="funding_rate"),
                )
            )
        ],
        config,
    )

    assert violations == ("decision[0] has 1 distinct observation symbols; requires at least 2",)


def test_crypto_perp_funding_readiness_infers_complete_funding_event_fields():
    observations = (
        ObservationRef(symbol="BTC-PERP", timestamp=AS_OF, field="close"),
        ObservationRef(symbol="BTC-PERP", timestamp=AS_OF, field="funding_timestamp"),
        ObservationRef(symbol="BTC-PERP", timestamp=AS_OF, field="funding_rate"),
        ObservationRef(symbol="BTC-PERP", timestamp=AS_OF, field="has_funding_event"),
    )

    assert (
        check_validation_readiness(
            [decision(observations=observations)],
            readiness(),
            data_kind="crypto_perp_funding",
        )
        == ()
    )


def test_crypto_perp_funding_readiness_rejects_close_only_observations():
    violations = check_validation_readiness(
        [
            decision(
                observations=(ObservationRef(symbol="BTC-PERP", timestamp=AS_OF, field="close"),)
            )
        ],
        readiness(),
        data_kind="crypto_perp_funding",
    )

    assert violations == (
        "decision[0] missing required observation fields: "
        "['funding_rate', 'funding_timestamp', 'has_funding_event']",
    )
