from __future__ import annotations

from datetime import datetime, timedelta, timezone

from quant_strategies.decisions import (
    ExitPolicy,
    InstrumentRef,
    ObservationRef,
    PositionTarget,
    StrategyDecision,
)
from quant_strategies.validation.data_audit import audit_decision_rows


AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
FUTURE = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)


def decision(
    symbol: str = "BTC-PERP",
    observations: tuple[ObservationRef, ...] = (),
) -> StrategyDecision:
    return StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol=symbol),
        decision_time=DECISION,
        as_of_time=AS_OF,
        target=PositionTarget(direction="short", sizing_kind="target_weight", size=1.0),
        exit_policy=ExitPolicy(max_hold_bars=2),
        observations=observations,
    )


def row(symbol: str, timestamp: datetime = AS_OF, available_at: object = AS_OF) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "available_at": available_at,
        "close": 100.0,
    }


def test_no_observations_remains_valid():
    audit = audit_decision_rows([row("BTC-PERP")], [decision()])

    assert audit.passed is True
    assert audit.violations == ()


def test_declared_cross_section_observations_pass():
    observations = (
        ObservationRef(symbol="BTC-PERP", timestamp=AS_OF, field="close"),
        ObservationRef(symbol="ETH-PERP", timestamp=AS_OF, field="return_21d"),
    )

    audit = audit_decision_rows(
        [row("BTC-PERP"), row("ETH-PERP")],
        [decision(observations=observations)],
    )

    assert audit.passed is True
    assert audit.violations == ()


def test_future_observation_timestamp_fails():
    observations = (ObservationRef(symbol="ETH-PERP", timestamp=FUTURE, field="close"),)

    audit = audit_decision_rows(
        [row("BTC-PERP"), row("ETH-PERP", timestamp=FUTURE)],
        [decision(observations=observations)],
    )

    assert audit.passed is False
    assert audit.violations == (
        "observation for BTC-PERP references future row ETH-PERP at 2026-01-01T00:02:00+00:00",
    )


def test_missing_observation_row_fails():
    observations = (ObservationRef(symbol="ETH-PERP", timestamp=AS_OF, field="close"),)

    audit = audit_decision_rows([row("BTC-PERP")], [decision(observations=observations)])

    assert audit.passed is False
    assert audit.violations == (
        "missing observation row for BTC-PERP: ETH-PERP at 2026-01-01T00:00:00+00:00",
    )


def test_missing_observation_available_at_fails():
    observations = (ObservationRef(symbol="ETH-PERP", timestamp=AS_OF, field="close"),)
    missing_available_at = {"symbol": "ETH-PERP", "timestamp": AS_OF, "close": 100.0}

    audit = audit_decision_rows(
        [row("BTC-PERP"), missing_available_at],
        [decision(observations=observations)],
    )

    assert audit.passed is False
    assert audit.violations == (
        "missing available_at for observation ETH-PERP at 2026-01-01T00:00:00+00:00 used by BTC-PERP",
    )


def test_invalid_observation_available_at_fails():
    observations = (ObservationRef(symbol="ETH-PERP", timestamp=AS_OF, field="close"),)

    audit = audit_decision_rows(
        [row("BTC-PERP"), row("ETH-PERP", available_at=datetime(2026, 1, 1, 0, 0))],
        [decision(observations=observations)],
    )

    assert audit.passed is False
    assert audit.violations == (
        "invalid available_at for observation ETH-PERP at 2026-01-01T00:00:00+00:00 used by "
        "BTC-PERP: expected aware datetime",
    )


def test_late_observation_available_at_fails():
    observations = (ObservationRef(symbol="ETH-PERP", timestamp=AS_OF, field="close"),)

    audit = audit_decision_rows(
        [row("BTC-PERP"), row("ETH-PERP", available_at=DECISION + timedelta(minutes=1))],
        [decision(observations=observations)],
    )

    assert audit.passed is False
    assert audit.violations == (
        "observation row ETH-PERP at 2026-01-01T00:00:00+00:00 used by BTC-PERP "
        "was available after decision_time",
    )
