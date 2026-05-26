from __future__ import annotations

from datetime import datetime, timezone

from quant_strategies.decisions import (
    ExitPolicy,
    InstrumentRef,
    ObservationRef,
    PositionTarget,
    StrategyDecision,
)
from quant_strategies.validation.config import ValidationReadinessConfig
from quant_strategies.validation.readiness import check_validation_readiness


AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)


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
                observations=(
                    ObservationRef(symbol="BTC-PERP", timestamp=AS_OF, field="close"),
                )
            )
        ],
        readiness(),
    )

    assert violations == ()


def test_validation_readiness_fails_when_observations_are_missing():
    violations = check_validation_readiness([decision(observations=())], readiness())

    assert violations == (
        "decision[0] has 0 observations; requires at least 1",
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
