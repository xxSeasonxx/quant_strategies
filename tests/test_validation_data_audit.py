from __future__ import annotations

from datetime import datetime, timezone

from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.validation.data_audit import audit_decision_rows


AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


def decision(symbol: str = "BTC-PERP") -> StrategyDecision:
    return StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol=symbol),
        decision_time=DECISION,
        as_of_time=AS_OF,
        target=PositionTarget(direction="short", sizing_kind="target_weight", size=1.0),
        exit_policy=ExitPolicy(max_hold_bars=2),
    )


def test_audit_passes_when_as_of_row_is_available_by_decision_time():
    rows = [
        {
            "symbol": "BTC-PERP",
            "timestamp": AS_OF,
            "available_at": DECISION,
            "close": 100.0,
        }
    ]

    audit = audit_decision_rows(rows, [decision()])

    assert audit.passed is True
    assert audit.decision_count == 1
    assert audit.violations == ()


def test_audit_fails_when_as_of_row_is_missing():
    audit = audit_decision_rows([], [decision()])

    assert audit.passed is False
    assert audit.violations == ("missing as_of row for BTC-PERP at 2026-01-01T00:00:00+00:00",)


def test_audit_fails_when_available_after_decision_time():
    rows = [
        {
            "symbol": "BTC-PERP",
            "timestamp": AS_OF,
            "available_at": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
            "close": 100.0,
        }
    ]

    audit = audit_decision_rows(rows, [decision()])

    assert audit.passed is False
    assert audit.violations == (
        "as_of row for BTC-PERP at 2026-01-01T00:00:00+00:00 was available after decision_time",
    )
