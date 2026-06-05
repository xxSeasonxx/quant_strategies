from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from quant_strategies.data_contract import NormalizedRows
from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.runner import data_readiness
from quant_strategies.core.errors import DataReadinessError


DECISION_TIME = datetime(2024, 1, 1, tzinfo=timezone.utc)


def config() -> SimpleNamespace:
    return SimpleNamespace(
        data=SimpleNamespace(kind="bars"),
        fill_model=SimpleNamespace(price="close"),
    )


def row(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": "SPY",
        "timestamp": DECISION_TIME,
    }
    payload.update(overrides)
    return payload


def decision(**overrides: object) -> StrategyDecision:
    payload = {
        "strategy_id": "demo",
        "instrument": InstrumentRef(kind="equity_or_etf", symbol="SPY"),
        "decision_time": DECISION_TIME,
        "as_of_time": DECISION_TIME,
        "target": PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
        "exit_policy": ExitPolicy(max_hold_bars=1),
    }
    payload.update(overrides)
    return StrategyDecision(**payload)


@pytest.mark.parametrize("ready_at", [DECISION_TIME - timedelta(minutes=1), DECISION_TIME])
def test_matching_decision_row_is_ready_at_or_before_decision_time(ready_at: datetime):
    data_readiness.assert_decision_rows_ready(
        [row(available_at=ready_at)],
        [decision()],
    )


def test_late_matching_available_at_is_rejected():
    with pytest.raises(DataReadinessError, match="available_at"):
        data_readiness.assert_decision_rows_ready(
            [row(available_at=DECISION_TIME + timedelta(minutes=1))],
            [decision()],
        )


def test_decision_as_of_time_checks_completed_row_against_later_decision_time():
    data_readiness.assert_decision_rows_ready(
        [
            row(timestamp=DECISION_TIME, available_at=DECISION_TIME + timedelta(minutes=1)),
            row(timestamp=DECISION_TIME + timedelta(minutes=1), available_at=DECISION_TIME + timedelta(minutes=2)),
        ],
        [
            decision(
                decision_time=DECISION_TIME + timedelta(minutes=1),
                as_of_time=DECISION_TIME,
            )
        ],
    )


def test_decision_as_of_time_must_match_a_row_for_that_symbol():
    with pytest.raises(DataReadinessError, match="does not match a row timestamp"):
        data_readiness.assert_decision_rows_ready(
            [row(symbol="QQQ")],
            [decision(as_of_time=DECISION_TIME)],
        )


def test_audit_ingestion_timestamps_do_not_block_when_available_at_is_causal():
    data_readiness.assert_decision_rows_ready(
        [
            row(
                available_at=DECISION_TIME,
                bar_ingested_at=DECISION_TIME + timedelta(days=365),
                quote_ingested_at=DECISION_TIME + timedelta(days=365),
                funding_ingested_at=DECISION_TIME + timedelta(days=365),
                joined_refreshed_at=DECISION_TIME + timedelta(days=365),
            )
        ],
        [decision()],
    )


def test_timezone_equivalent_iso_strings_match_and_allow_ready_row():
    data_readiness.assert_decision_rows_ready(
        [
            row(
                timestamp="2024-01-01T00:00:00Z",
                available_at="2023-12-31T19:00:00-05:00",
            )
        ],
        [decision()],
    )


def test_normalized_rows_path_uses_shared_timestamp_normalization(monkeypatch: pytest.MonkeyPatch):
    normalized = NormalizedRows.from_rows(
        config(),
        [
            row(
                timestamp="2024-01-01T00:00:00Z",
                available_at="2023-12-31T19:00:00-05:00",
                open="100",
                high="101",
                low="99",
                close="100.5",
            )
        ],
    )
    monkeypatch.setattr(
        data_readiness,
        "parse_aware_datetime",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not parse normalized rows")),
    )

    data_readiness.assert_decision_rows_ready(normalized, [decision()])


def test_no_matching_readiness_metadata_does_not_block_when_as_of_row_is_ready():
    data_readiness.assert_decision_rows_ready(
        [row(), row(symbol="QQQ", available_at=DECISION_TIME + timedelta(days=1))],
        [decision()],
    )


@pytest.mark.parametrize("missing", [float("nan")])
def test_missing_like_optional_metadata_is_ignored(missing: object):
    data_readiness.assert_decision_rows_ready(
        [row(available_at=missing)],
        [decision()],
    )


@pytest.mark.parametrize(
    "invalid",
    ["not-a-timestamp", datetime(2024, 1, 1)],
)
def test_invalid_optional_available_at_is_left_to_evidence_quality(invalid: object):
    data_readiness.assert_decision_rows_ready(
        [row(available_at=invalid)],
        [decision()],
    )


def test_pandas_missing_like_optional_metadata_is_ignored():
    pd = pytest.importorskip("pandas")

    for missing in (pd.NaT, pd.NA):
        data_readiness.assert_decision_rows_ready(
            [row(available_at=missing)],
            [decision()],
        )


def test_malformed_key_timestamps_are_left_to_request_build_validation():
    with pytest.raises(DataReadinessError, match="does not match a row timestamp"):
        data_readiness.assert_decision_rows_ready(
            [row(timestamp="not-a-timestamp", available_at=DECISION_TIME + timedelta(days=1))],
            [decision()],
        )
