from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from quant_strategies.runner import data_readiness
from quant_strategies.runner.errors import DataReadinessError


DECISION_TIME = datetime(2024, 1, 1, tzinfo=timezone.utc)


def row(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": "SPY",
        "timestamp": DECISION_TIME,
    }
    payload.update(overrides)
    return payload


def signal(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": "SPY",
        "decision_time": DECISION_TIME,
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("ready_at", [DECISION_TIME - timedelta(minutes=1), DECISION_TIME])
def test_matching_decision_row_is_ready_at_or_before_decision_time(ready_at: datetime):
    data_readiness.assert_decision_rows_ready(
        [row(available_at=ready_at)],
        [signal()],
    )


@pytest.mark.parametrize("field", data_readiness.READINESS_FIELDS)
def test_late_matching_readiness_field_is_rejected(field: str):
    with pytest.raises(DataReadinessError, match=field):
        data_readiness.assert_decision_rows_ready(
            [row(**{field: DECISION_TIME + timedelta(minutes=1)})],
            [signal()],
        )


def test_timezone_equivalent_iso_strings_match_and_allow_ready_row():
    data_readiness.assert_decision_rows_ready(
        [
            row(
                timestamp="2024-01-01T00:00:00Z",
                available_at="2023-12-31T19:00:00-05:00",
            )
        ],
        [signal(decision_time="2024-01-01T00:00:00+00:00")],
    )


def test_no_matching_readiness_metadata_does_not_block():
    data_readiness.assert_decision_rows_ready(
        [row(), row(symbol="QQQ", available_at=DECISION_TIME + timedelta(days=1))],
        [signal()],
    )


@pytest.mark.parametrize("missing", [float("nan")])
def test_missing_like_optional_metadata_is_ignored(missing: object):
    data_readiness.assert_decision_rows_ready(
        [row(**{field: missing for field in data_readiness.READINESS_FIELDS})],
        [signal()],
    )


def test_pandas_missing_like_optional_metadata_is_ignored():
    pd = pytest.importorskip("pandas")

    for missing in (pd.NaT, pd.NA):
        data_readiness.assert_decision_rows_ready(
            [row(**{field: missing for field in data_readiness.READINESS_FIELDS})],
            [signal()],
        )


def test_malformed_key_timestamps_are_left_to_request_build_validation():
    data_readiness.assert_decision_rows_ready(
        [row(timestamp="not-a-timestamp", available_at=DECISION_TIME + timedelta(days=1))],
        [signal(decision_time="not-a-timestamp")],
    )
