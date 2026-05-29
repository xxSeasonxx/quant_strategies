from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import quant_strategies.causality as causality
from quant_strategies.causality import ReplayBoundary, check_hidden_lookahead
from quant_strategies.data_contract import NormalizedRows
from quant_strategies.decisions import (
    ExitPolicy,
    InstrumentRef,
    PositionTarget,
    StrategyDecision,
)


AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
FUTURE = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
LATE_DECISION = datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc)


def row(
    timestamp: datetime,
    close: float,
    *,
    available_at: datetime | None = None,
) -> dict[str, object]:
    payload = {
        "symbol": "BTC-PERP",
        "timestamp": timestamp,
        "close": close,
    }
    if available_at is not None:
        payload["available_at"] = available_at
    return payload


def contract_config() -> SimpleNamespace:
    return SimpleNamespace(
        data=SimpleNamespace(kind="bars"),
        fill_model=SimpleNamespace(price="close"),
    )


def ohlc_row(
    timestamp: datetime,
    close: float,
    *,
    available_at: datetime | None = None,
) -> dict[str, object]:
    payload = row(timestamp, close, available_at=available_at)
    payload.update({"open": close, "high": close, "low": close})
    return payload


def decision(size: float = 1.0) -> StrategyDecision:
    return StrategyDecision(
        decision_id=f"demo:{size}",
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
        decision_time=DECISION,
        as_of_time=AS_OF,
        target=PositionTarget(direction="long", sizing_kind="target_weight", size=size),
        exit_policy=ExitPolicy(max_hold_bars=1),
    )


def as_of_strategy(rows: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
    visible = [item for item in rows if item.get("timestamp") == AS_OF]
    if not visible:
        return []
    return [decision(float(visible[-1]["close"]) / 100.0)]


def future_sensitive_strategy(rows: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
    future_rows = [item for item in rows if item.get("timestamp") == FUTURE]
    size = 2.0 if future_rows else 1.0
    return [decision(size)]


def replay_raising_strategy(rows: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
    if all(item.get("timestamp") != FUTURE for item in rows):
        raise RuntimeError("replay cannot run")
    return [decision()]


def test_hidden_lookahead_check_passes_as_of_only_strategy():
    rows = [
        row(AS_OF, 100.0, available_at=AS_OF),
        row(FUTURE, 999.0, available_at=FUTURE),
    ]
    baseline = as_of_strategy(rows, {})

    result = check_hidden_lookahead(
        as_of_strategy,
        rows=rows,
        params={},
        baseline_decisions=baseline,
        strategy_id="demo",
    )

    assert result.passed is True
    assert result.violations == ()


def test_hidden_lookahead_check_detects_future_sensitive_strategy():
    rows = [
        row(AS_OF, 100.0, available_at=AS_OF),
        row(FUTURE, 999.0, available_at=FUTURE),
    ]
    baseline = future_sensitive_strategy(rows, {})

    result = check_hidden_lookahead(
        future_sensitive_strategy,
        rows=rows,
        params={},
        baseline_decisions=baseline,
        strategy_id="demo",
    )

    assert result.passed is False
    assert result.violations == ("hidden_lookahead_detected",)


def test_hidden_lookahead_check_excludes_future_timestamp_even_when_available_early():
    rows = [
        row(AS_OF, 100.0, available_at=AS_OF),
        row(FUTURE, 999.0, available_at=DECISION),
    ]
    baseline = future_sensitive_strategy(rows, {})

    result = check_hidden_lookahead(
        future_sensitive_strategy,
        rows=rows,
        params={},
        baseline_decisions=baseline,
        strategy_id="demo",
    )

    assert result.passed is False
    assert result.violations == ("hidden_lookahead_detected",)


def test_hidden_lookahead_check_reports_replay_exceptions():
    rows = [
        row(AS_OF, 100.0, available_at=AS_OF),
        row(FUTURE, 999.0, available_at=FUTURE),
    ]
    baseline = replay_raising_strategy(rows, {})

    result = check_hidden_lookahead(
        replay_raising_strategy,
        rows=rows,
        params={},
        baseline_decisions=baseline,
        strategy_id="demo",
    )

    assert result.passed is False
    assert result.violations == ("hidden_lookahead_check_failed: RuntimeError: replay cannot run",)


def test_hidden_lookahead_parses_row_visibility_once_per_check(monkeypatch):
    source_rows = [
        row(AS_OF, 100.0 + index, available_at=AS_OF)
        for index in range(12)
    ]

    def multi_decision_strategy(rows: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
        return [
            StrategyDecision(
                decision_id=f"demo:{index}",
                strategy_id="demo",
                instrument=InstrumentRef(kind="crypto_perp", symbol=f"BTC-PERP-{index}"),
                decision_time=DECISION,
                as_of_time=AS_OF,
                target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
                exit_policy=ExitPolicy(max_hold_bars=1),
            )
            for index in range(5)
        ]

    baseline = multi_decision_strategy(source_rows, {})
    original_parse = causality.parse_aware_datetime
    parse_calls = 0

    def counting_parse(value: object):
        nonlocal parse_calls
        parse_calls += 1
        return original_parse(value)

    monkeypatch.setattr(causality, "parse_aware_datetime", counting_parse)

    result = check_hidden_lookahead(
        multi_decision_strategy,
        rows=source_rows,
        params={},
        baseline_decisions=baseline,
        strategy_id="demo",
    )

    assert result.passed is True
    assert parse_calls == len(source_rows) * 2


def test_hidden_lookahead_uses_normalized_rows_without_reparsing(monkeypatch):
    normalized = NormalizedRows.from_rows(
        contract_config(),
        [
            ohlc_row(AS_OF, 100.0, available_at=AS_OF),
            ohlc_row(FUTURE, 999.0, available_at=FUTURE),
        ],
        mode="validation",
    )
    baseline = as_of_strategy(normalized.projection_rows(), {})
    monkeypatch.setattr(
        causality,
        "parse_aware_datetime",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not parse normalized rows")),
    )

    result = check_hidden_lookahead(
        as_of_strategy,
        rows=normalized,
        params={},
        baseline_decisions=baseline,
        strategy_id="demo",
    )

    assert result.passed is True


def test_strict_hidden_lookahead_detects_suppressed_replay_emission():
    source_rows = [
        row(AS_OF, 100.0, available_at=AS_OF),
        row(FUTURE, 999.0, available_at=FUTURE),
    ]

    def suppression_strategy(rows: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
        if any(item.get("timestamp") == FUTURE for item in rows):
            return []
        return [
            StrategyDecision(
                decision_id="demo:suppressed",
                strategy_id="demo",
                instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
                decision_time=DECISION,
                as_of_time=AS_OF,
                target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
                exit_policy=ExitPolicy(max_hold_bars=1),
            )
        ]

    result = check_hidden_lookahead(
        suppression_strategy,
        rows=source_rows,
        params={},
        baseline_decisions=suppression_strategy(source_rows, {}),
        strategy_id="demo",
        mode="strict",
        boundaries=(
            ReplayBoundary(
                as_of_time=AS_OF,
                decision_time=DECISION,
                expected_decision_ids=frozenset(),
                symbols=frozenset({"BTC-PERP"}),
            ),
        ),
    )

    assert result.passed is False
    assert result.violations == ("hidden_lookahead_suppression_detected",)


def test_strict_replay_is_default_and_reports_split_flags():
    rows = [
        row(AS_OF, 100.0, available_at=AS_OF),
        row(FUTURE, 101.0, available_at=FUTURE),
    ]
    baseline = as_of_strategy(rows, {})

    # No mode= -> defaults to strict and auto-derives row-grid boundaries.
    result = check_hidden_lookahead(
        as_of_strategy,
        rows=rows,
        params={},
        baseline_decisions=baseline,
        strategy_id="demo",
    )

    assert result.mode == "strict"
    assert result.passed is True
    assert result.emitted_replay_verified is True
    assert result.strict_suppression_verified is True


def test_strict_replay_auto_derived_boundaries_catch_suppression():
    # A causal baseline emits nothing; a strategy that would emit on the truncated
    # grid (because it peeked ahead to suppress) is caught with no explicit boundaries.
    rows = [
        row(AS_OF, 100.0, available_at=AS_OF),
        row(FUTURE, 999.0, available_at=FUTURE),
    ]

    def suppression_strategy(rows: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
        if any(item.get("timestamp") == FUTURE for item in rows):
            return []
        return [decision()]

    result = check_hidden_lookahead(
        suppression_strategy,
        rows=rows,
        params={},
        baseline_decisions=suppression_strategy(rows, {}),
        strategy_id="demo",
    )

    assert result.passed is False
    assert result.violations == ("hidden_lookahead_suppression_detected",)
    assert result.emitted_replay_verified is True
    assert result.strict_suppression_verified is False


def test_strict_hidden_lookahead_detects_same_bar_replay_emission_for_boundary():
    source_rows = [
        row(AS_OF, 100.0, available_at=AS_OF),
        row(FUTURE, 999.0, available_at=FUTURE),
    ]

    def same_bar_strategy(rows: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
        if any(item.get("timestamp") == FUTURE for item in rows):
            return []
        return [
            StrategyDecision(
                decision_id="demo:same-bar",
                strategy_id="demo",
                instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
                decision_time=AS_OF,
                as_of_time=AS_OF,
                target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
                exit_policy=ExitPolicy(max_hold_bars=1),
            )
        ]

    result = check_hidden_lookahead(
        same_bar_strategy,
        rows=source_rows,
        params={},
        baseline_decisions=same_bar_strategy(source_rows, {}),
        strategy_id="demo",
        mode="strict",
        boundaries=(
            ReplayBoundary(
                as_of_time=AS_OF,
                decision_time=DECISION,
                expected_decision_ids=frozenset(),
                symbols=frozenset({"BTC-PERP"}),
            ),
        ),
    )

    assert result.passed is False
    assert result.violations == ("hidden_lookahead_suppression_detected",)


def test_strict_hidden_lookahead_allows_legitimate_no_emission_boundary():
    calls = 0

    def quiet_strategy(rows: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
        nonlocal calls
        calls += 1
        return []

    result = check_hidden_lookahead(
        quiet_strategy,
        rows=[row(AS_OF, 100.0, available_at=AS_OF)],
        params={},
        baseline_decisions=[],
        strategy_id="demo",
        mode="strict",
        boundaries=(
            ReplayBoundary(
                as_of_time=AS_OF,
                decision_time=DECISION,
                expected_decision_ids=frozenset(),
                symbols=frozenset({"BTC-PERP"}),
            ),
        ),
    )

    assert result.passed is True
    assert calls == 1


def test_strict_hidden_lookahead_replays_unique_boundaries_once():
    calls = 0

    def quiet_strategy(rows: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
        nonlocal calls
        calls += 1
        return []

    shared_boundary = ReplayBoundary(
        as_of_time=AS_OF,
        decision_time=DECISION,
        expected_decision_ids=frozenset(),
        symbols=frozenset({"BTC-PERP"}),
    )

    result = check_hidden_lookahead(
        quiet_strategy,
        rows=[row(AS_OF, 100.0, available_at=AS_OF)],
        params={},
        baseline_decisions=[],
        strategy_id="demo",
        mode="strict",
        boundaries=(shared_boundary, shared_boundary),
    )

    assert result.passed is True
    assert calls == 1


def test_hidden_lookahead_reuses_visible_rows_for_shared_decision_boundary():
    source_rows = [
        row(AS_OF, 100.0 + index, available_at=AS_OF)
        for index in range(4)
    ]
    replay_row_ids: list[int] = []

    def recording_strategy(rows: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
        replay_row_ids.append(id(rows))
        return [
            StrategyDecision(
                decision_id=f"demo:{index}",
                strategy_id="demo",
                instrument=InstrumentRef(kind="crypto_perp", symbol=f"BTC-PERP-{index}"),
                decision_time=DECISION,
                as_of_time=AS_OF,
                target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
                exit_policy=ExitPolicy(max_hold_bars=1),
            )
            for index in range(3)
        ]

    baseline = recording_strategy(source_rows, {})
    replay_row_ids.clear()

    result = check_hidden_lookahead(
        recording_strategy,
        rows=source_rows,
        params={},
        baseline_decisions=baseline,
        strategy_id="demo",
        mode="emitted",
    )

    assert result.passed is True
    assert len(replay_row_ids) == 1


def test_hidden_lookahead_does_not_share_visible_rows_across_decision_times():
    source_rows = [
        row(AS_OF, 100.0, available_at=AS_OF),
        row(AS_OF, 101.0, available_at=LATE_DECISION),
    ]
    visible_closes_by_call: list[tuple[float, ...]] = []

    def boundary_strategy(rows: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
        closes = tuple(float(item["close"]) for item in rows)
        visible_closes_by_call.append(closes)
        if 101.0 in closes:
            return [
                StrategyDecision(
                    decision_id="demo:late",
                    strategy_id="demo",
                    instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
                    decision_time=LATE_DECISION,
                    as_of_time=AS_OF,
                    target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
                    exit_policy=ExitPolicy(max_hold_bars=1),
                )
            ]
        return [decision()]

    baseline = [
        decision(),
        StrategyDecision(
            decision_id="demo:late",
            strategy_id="demo",
            instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
            decision_time=LATE_DECISION,
            as_of_time=AS_OF,
            target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
            exit_policy=ExitPolicy(max_hold_bars=1),
        ),
    ]

    result = check_hidden_lookahead(
        boundary_strategy,
        rows=source_rows,
        params={},
        baseline_decisions=baseline,
        strategy_id="demo",
        mode="emitted",
    )

    assert result.passed is True
    assert visible_closes_by_call == [(100.0,), (100.0, 101.0)]
