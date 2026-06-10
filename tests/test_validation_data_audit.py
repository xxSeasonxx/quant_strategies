from __future__ import annotations

from datetime import UTC, datetime

from quant_strategies.core.data_audit import audit_decision_rows
from quant_strategies.decisions import InstrumentRef, TargetDecision

AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)


def decision(symbol: str = "BTC-PERP") -> TargetDecision:
    return TargetDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol=symbol),
        decision_time=DECISION,
        as_of_time=AS_OF,
        target=-1.0,
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
            "available_at": datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
            "close": 100.0,
        }
    ]

    audit = audit_decision_rows(rows, [decision()])

    assert audit.passed is False
    assert audit.violations == (
        "as_of row for BTC-PERP at 2026-01-01T00:00:00+00:00 was available after decision_time",
    )


def test_audit_normalized_rows_flags_missing_available_at():
    # Validation audits NormalizedRows (not raw dicts); a row missing available_at must
    # fail the audit via the row-contract violations path. This is how the unconditional
    # available_at requirement is enforced on the validation surface.
    from types import SimpleNamespace

    from quant_strategies.data_contract import NormalizedRows

    config = SimpleNamespace(
        data=SimpleNamespace(kind="bars"),
        fill_model=SimpleNamespace(price="close"),
    )
    rows = [
        {
            "symbol": "BTC-PERP",
            "timestamp": AS_OF,
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
        }
    ]
    normalized = NormalizedRows.from_rows(config, rows)

    audit = audit_decision_rows(normalized, [decision()])

    assert audit.passed is False
    assert any("row_missing_available_at" in violation for violation in audit.violations)


def test_audit_parses_iso_timestamp_and_available_at_for_late_violation():
    rows = [
        {
            "symbol": "BTC-PERP",
            "timestamp": "2026-01-01T00:00:00Z",
            "available_at": "2026-01-01T00:02:00Z",
            "close": 100.0,
        }
    ]

    audit = audit_decision_rows(rows, [decision()])

    assert audit.passed is False
    assert audit.violations == (
        "as_of row for BTC-PERP at 2026-01-01T00:00:00+00:00 was available after decision_time",
    )


def test_audit_flags_naive_available_at_without_raising():
    rows = [
        {
            "symbol": "BTC-PERP",
            "timestamp": AS_OF,
            "available_at": datetime(2026, 1, 1, 0, 0),
            "close": 100.0,
        }
    ]

    audit = audit_decision_rows(rows, [decision()])

    assert audit.passed is False
    assert audit.violations == (
        "invalid available_at for BTC-PERP at 2026-01-01T00:00:00+00:00: expected aware datetime",
    )


def test_audit_flags_invalid_available_at_without_raising():
    rows = [
        {
            "symbol": "BTC-PERP",
            "timestamp": AS_OF,
            "available_at": "not-a-time",
            "close": 100.0,
        }
    ]

    audit = audit_decision_rows(rows, [decision()])

    assert audit.passed is False
    assert audit.violations == (
        "invalid available_at for BTC-PERP at 2026-01-01T00:00:00+00:00: invalid datetime",
    )


def test_audit_flags_invalid_row_timestamp_without_raising():
    rows = [
        {
            "symbol": "BTC-PERP",
            "timestamp": "not-a-time",
            "available_at": DECISION,
            "close": 100.0,
        }
    ]

    audit = audit_decision_rows(rows, [decision()])

    assert audit.passed is False
    assert audit.violations == (
        "invalid timestamp for BTC-PERP: invalid datetime",
        "missing as_of row for BTC-PERP at 2026-01-01T00:00:00+00:00",
    )


def test_audit_flags_duplicate_matching_rows():
    rows = [
        {
            "symbol": "BTC-PERP",
            "timestamp": AS_OF,
            "available_at": DECISION,
            "close": 100.0,
        },
        {
            "symbol": "BTC-PERP",
            "timestamp": "2026-01-01T00:00:00Z",
            "available_at": DECISION,
            "close": 101.0,
        },
    ]

    audit = audit_decision_rows(rows, [decision()])

    assert audit.passed is False
    assert audit.violations == ("duplicate as_of rows for BTC-PERP at 2026-01-01T00:00:00+00:00",)


def test_audit_flags_missing_available_at():
    rows = [
        {
            "symbol": "BTC-PERP",
            "timestamp": AS_OF,
            "close": 100.0,
        }
    ]

    audit = audit_decision_rows(rows, [decision()])

    assert audit.passed is False
    assert audit.violations == ("missing available_at for BTC-PERP at 2026-01-01T00:00:00+00:00",)
