from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from quant_strategies.data_contract import NormalizedRows, RowContractMode


TIMESTAMP = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
AVAILABLE_AT = datetime(2024, 1, 1, 9, 31, tzinfo=timezone.utc)


def config(kind: str = "bars", *, fill_price: str = "close") -> SimpleNamespace:
    return SimpleNamespace(
        data=SimpleNamespace(kind=kind),
        fill_model=SimpleNamespace(price=fill_price),
    )


def valid_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": "SPY",
        "timestamp": TIMESTAMP,
        "available_at": AVAILABLE_AT,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
    }
    row.update(overrides)
    return row


def issue_reasons(rows: NormalizedRows) -> list[str]:
    return [issue.reason for issue in rows.issues]


def test_invalid_and_naive_timestamp_emit_invalid_timestamp():
    normalized = NormalizedRows.from_rows(
        config(),
        [
            valid_row(timestamp=datetime(2024, 1, 1, 9, 30)),
            valid_row(timestamp="not-a-datetime"),
        ],
        mode=RowContractMode.VALIDATION,
    )

    assert issue_reasons(normalized).count("row_invalid_timestamp") == 2
    assert normalized.row_contract_summary()["timestamp_status"] == "invalid_or_naive"


def test_missing_ohlc_emits_missing_required_field():
    row = valid_row()
    del row["open"]

    normalized = NormalizedRows.from_rows(config(), [row], mode="validation")

    assert "row_missing_required_field" in issue_reasons(normalized)
    assert normalized.issues[0].field == "open"
    assert normalized.row_contract_summary()["missing_required_fields"] == {"open": 1}


def test_invalid_numeric_field_emits_invalid_numeric_field():
    normalized = NormalizedRows.from_rows(
        config(),
        [valid_row(close="not-a-number")],
        mode="validation",
    )

    assert "row_invalid_numeric_field" in issue_reasons(normalized)
    assert normalized.issues[0].field == "close"


def test_invalid_ohlc_order_emits_invalid_ohlc_order():
    normalized = NormalizedRows.from_rows(
        config(),
        [valid_row(open=100.0, high=99.0, low=98.0, close=100.5)],
        mode="validation",
    )

    assert "row_invalid_ohlc_order" in issue_reasons(normalized)
    assert normalized.row_contract_summary()["status"] == "failed"


def test_duplicate_symbol_timestamp_emits_duplicate_issue_and_index_keeps_first_row():
    first = valid_row(close=100.5)
    second = valid_row(close=100.7)

    normalized = NormalizedRows.from_rows(config(), [first, second], mode="validation")

    assert "row_duplicate_symbol_timestamp" in issue_reasons(normalized)
    assert normalized.duplicate_key_count == 1
    assert normalized.duplicate_keys == (("SPY", TIMESTAMP),)
    assert len(normalized.by_symbol_timestamp) == 1
    assert normalized.by_symbol_timestamp[("SPY", TIMESTAMP)]["close"] == 100.5


def test_duplicate_invalid_timestamp_strings_still_emit_duplicate_issue():
    normalized = NormalizedRows.from_rows(
        config(),
        [
            valid_row(timestamp="not-a-datetime"),
            valid_row(timestamp="not-a-datetime"),
        ],
        mode="validation",
    )

    assert issue_reasons(normalized).count("row_invalid_timestamp") == 2
    assert "row_duplicate_symbol_timestamp" in issue_reasons(normalized)
    assert normalized.duplicate_key_count == 1
    assert normalized.duplicate_keys == ()
    assert normalized.by_symbol_timestamp == {}


def test_search_missing_available_at_warns_without_failing_validation_mode_errors():
    search_row = valid_row()
    del search_row["available_at"]
    search_rows = NormalizedRows.from_rows(config(), [search_row], mode="search")

    assert search_rows.row_contract_summary()["status"] == "passed"
    assert [(issue.reason, issue.severity) for issue in search_rows.issues] == [
        ("row_missing_available_at", "warning")
    ]
    assert search_rows.row_contract_summary()["quant_data_feedback"] == []
    assert search_rows.evidence_quality(causality_verified=True)["causality_verified"] is False

    validation_row = valid_row()
    del validation_row["available_at"]
    validation_rows = NormalizedRows.from_rows(config(), [validation_row], mode="validation")

    assert validation_rows.row_contract_summary()["status"] == "failed"
    assert [(issue.reason, issue.severity) for issue in validation_rows.issues] == [
        ("row_missing_available_at", "error")
    ]
    assert validation_rows.row_contract_summary()["required_fields"][-1] == "available_at"
    assert validation_rows.row_contract_summary()["missing_required_fields"] == {
        "available_at": 1
    }


@pytest.mark.parametrize("mode", [RowContractMode.VALIDATION, RowContractMode.RETAINED])
def test_missing_and_invalid_available_at_error_in_validation_and_retained_modes(
    mode: RowContractMode,
):
    missing_row = valid_row()
    del missing_row["available_at"]
    missing_rows = NormalizedRows.from_rows(config(), [missing_row], mode=mode)

    assert [(issue.reason, issue.severity) for issue in missing_rows.issues] == [
        ("row_missing_available_at", "error")
    ]
    assert missing_rows.row_contract_summary()["status"] == "failed"
    assert missing_rows.row_contract_summary()["missing_required_fields"] == {
        "available_at": 1
    }

    invalid_rows = NormalizedRows.from_rows(
        config(),
        [valid_row(available_at="not-a-datetime")],
        mode=mode,
    )

    assert [(issue.reason, issue.severity) for issue in invalid_rows.issues] == [
        ("row_invalid_available_at", "error")
    ]
    assert invalid_rows.data_availability_status == "invalid"
    assert invalid_rows.row_contract_summary()["status"] == "failed"


def test_invalid_available_at_is_error_in_search_mode():
    normalized = NormalizedRows.from_rows(
        config(),
        [valid_row(available_at="not-a-datetime")],
        mode="search",
    )

    assert [(issue.reason, issue.severity) for issue in normalized.issues] == [
        ("row_invalid_available_at", "error")
    ]
    assert normalized.data_availability_status == "invalid"
    assert normalized.row_contract_summary()["status"] == "failed"


def test_quote_fill_missing_quote_field_emits_quote_issue():
    normalized = NormalizedRows.from_rows(
        config("forex_with_quotes", fill_price="quote"),
        [valid_row(symbol="EURUSD", bid=1.08, mid=1.081)],
        mode="validation",
    )

    assert "row_missing_quote_field" in issue_reasons(normalized)
    assert normalized.issues[0].field == "ask"
    assert normalized.row_contract_summary()["missing_required_fields"] == {"ask": 1}


def test_crypto_funding_event_missing_or_invalid_fields_emit_funding_issue():
    normalized = NormalizedRows.from_rows(
        config("crypto_perp_funding"),
        [
            valid_row(symbol="BTC-PERP", has_funding_event=True, funding_rate=Decimal("-0.0001")),
            valid_row(
                symbol="BTC-PERP",
                timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
                has_funding_event=True,
                funding_timestamp=TIMESTAMP,
                funding_rate="not-a-number",
            ),
        ],
        mode="validation",
    )

    funding_issues = [
        issue for issue in normalized.issues if issue.reason == "row_invalid_funding_fields"
    ]
    assert [issue.field for issue in funding_issues] == ["funding_timestamp", "funding_rate"]
    assert normalized.row_contract_summary()["funding_event_missing_fields"] == {
        "funding_rate": 1,
        "funding_timestamp": 1,
    }


def test_projection_rows_are_mapping_compatible_and_hash_ordering_is_stable():
    row_one = {
        "close": Decimal("100.5"),
        "low": Decimal("99.0"),
        "high": Decimal("101.0"),
        "open": Decimal("100.0"),
        "available_at": AVAILABLE_AT,
        "timestamp": TIMESTAMP,
        "symbol": "SPY",
    }
    row_two = {
        "symbol": "SPY",
        "timestamp": TIMESTAMP,
        "available_at": AVAILABLE_AT,
        "open": Decimal("100.0"),
        "high": Decimal("101.0"),
        "low": Decimal("99.0"),
        "close": Decimal("100.5"),
    }

    first = NormalizedRows.from_rows(config(), [row_one], mode="validation")
    second = NormalizedRows.from_rows(config(), [row_two], mode="validation")
    row_one["close"] = Decimal("999.0")
    projected = first.projection_rows()

    assert isinstance(projected[0], Mapping)
    with pytest.raises(TypeError):
        projected[0]["close"] = 1.0
    assert first.projection_rows() is projected
    assert list(projected[0]) == sorted(projected[0])
    assert projected[0]["close"] == 100.5
    assert first.normalized_rows_sha256 == second.normalized_rows_sha256
    assert tuple(dict(row) for row in first.projection_rows()) == tuple(
        dict(row) for row in second.projection_rows()
    )
