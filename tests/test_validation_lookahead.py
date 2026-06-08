from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import quant_strategies.causality as causality
from quant_strategies.causality import (
    FocusedCausalityConfig,
    FocusedCausalityKey,
    ReplayBoundary,
    check_focused_causality,
    check_hidden_lookahead,
    focused_replay_plan,
)
from quant_strategies.data_contract import NormalizedRows
from quant_strategies.decisions import (
    ExitPolicy,
    InstrumentRef,
    PositionTarget,
    StrategyDecision,
)

AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
FUTURE = datetime(2026, 1, 1, 0, 2, tzinfo=UTC)
LATE_DECISION = datetime(2026, 1, 1, 0, 3, tzinfo=UTC)


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


def focused_key() -> FocusedCausalityKey:
    return FocusedCausalityKey(
        strategy_source_sha256="source-a",
        strategy_id="demo",
        data_kind="bars",
        profile_version="focused-test/v1",
    )


def test_focused_replay_plan_is_deterministic_capped_and_mixed():
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    source_rows = [
        {
            "symbol": "BTC-PERP" if index % 2 == 0 else "ETH-PERP",
            "timestamp": start.replace(minute=index),
            "available_at": start.replace(minute=index),
            "close": 100.0 + index,
        }
        for index in range(8)
    ]
    baseline = [
        decision().model_copy(
            update={
                "decision_id": "demo:first",
                "as_of_time": source_rows[2]["timestamp"],
                "decision_time": source_rows[3]["timestamp"],
            }
        ),
        decision().model_copy(
            update={
                "decision_id": "demo:last",
                "as_of_time": source_rows[6]["timestamp"],
                "decision_time": source_rows[7]["timestamp"],
            }
        ),
    ]
    config = FocusedCausalityConfig(max_probes=5, timeout_seconds=60.0)

    first = focused_replay_plan(source_rows, baseline, key=focused_key(), config=config)
    second = focused_replay_plan(source_rows, baseline, key=focused_key(), config=config)

    assert first == second
    assert first.selected_probe_count == 5
    assert first.candidate_probe_count > first.selected_probe_count
    assert any(boundary.expected_decision_ids for boundary in first.boundaries)
    assert any(not boundary.expected_decision_ids for boundary in first.boundaries)


def test_focused_replay_plan_does_not_materialize_full_strict_grid(monkeypatch):
    source_rows = [
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, index, tzinfo=UTC),
            "available_at": datetime(2026, 1, 1, 0, index, tzinfo=UTC),
            "close": 100.0 + index,
        }
        for index in range(20)
    ]

    monkeypatch.setattr(
        causality,
        "strict_replay_boundaries",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("focused planning should not build the full strict grid")
        ),
    )

    plan = focused_replay_plan(
        source_rows,
        [],
        key=focused_key(),
        config=FocusedCausalityConfig(max_probes=5, timeout_seconds=60.0),
    )

    assert plan.candidate_probe_count == 20
    assert plan.selected_probe_count == 5


def test_focused_causality_passes_causal_strategy():
    source_rows = [
        row(AS_OF, 100.0, available_at=AS_OF),
        row(FUTURE, 101.0, available_at=FUTURE),
    ]
    baseline = as_of_strategy(source_rows, {})

    result = check_focused_causality(
        as_of_strategy,
        rows=source_rows,
        params={},
        baseline_decisions=baseline,
        strategy_id="demo",
        key=focused_key(),
        config=FocusedCausalityConfig(max_probes=4, timeout_seconds=60.0),
    )

    assert result.status == "passed"
    assert result.scoring_allowed is True
    assert result.rejection_reason is None
    assert result.selected_probe_count > 0


def test_focused_causality_rejects_future_sensitive_strategy():
    source_rows = [
        row(AS_OF, 100.0, available_at=AS_OF),
        row(FUTURE, 999.0, available_at=FUTURE),
    ]
    baseline = future_sensitive_strategy(source_rows, {})

    result = check_focused_causality(
        future_sensitive_strategy,
        rows=source_rows,
        params={},
        baseline_decisions=baseline,
        strategy_id="demo",
        key=focused_key(),
        config=FocusedCausalityConfig(max_probes=4, timeout_seconds=60.0),
    )

    assert result.status == "failed"
    assert result.scoring_allowed is False
    assert result.rejection_reason == "hidden_lookahead_detected"


def test_focused_causality_timeout_rejects_variant():
    source_rows = [row(AS_OF, 100.0, available_at=AS_OF)]

    result = check_focused_causality(
        as_of_strategy,
        rows=source_rows,
        params={},
        baseline_decisions=as_of_strategy(source_rows, {}),
        strategy_id="demo",
        key=focused_key(),
        config=FocusedCausalityConfig(max_probes=4, timeout_seconds=0.0),
    )

    assert result.status == "timeout"
    assert result.scoring_allowed is False
    assert result.rejection_reason == "focused_causality_timeout"


def test_focused_causality_interrupts_slow_replay():
    source_rows = [row(AS_OF, 100.0, available_at=AS_OF)]

    def slow_strategy(rows: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
        time.sleep(1.0)
        return []

    started = time.perf_counter()
    result = check_focused_causality(
        slow_strategy,
        rows=source_rows,
        params={},
        baseline_decisions=[],
        strategy_id="demo",
        key=focused_key(),
        config=FocusedCausalityConfig(max_probes=4, timeout_seconds=0.01),
    )
    elapsed = time.perf_counter() - started

    assert result.status == "timeout"
    assert result.scoring_allowed is False
    assert result.rejection_reason == "focused_causality_timeout"
    assert elapsed < 0.5


def test_focused_causality_rejects_skipped_sampled_probe():
    source_rows = [
        row(AS_OF, 100.0, available_at=AS_OF),
        row(FUTURE, 101.0, available_at=FUTURE),
    ]

    def prefix_fragile_strategy(rows: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
        if all(item.get("timestamp") != FUTURE for item in rows):
            raise ValueError("needs warmup")
        return []

    result = check_focused_causality(
        prefix_fragile_strategy,
        rows=source_rows,
        params={},
        baseline_decisions=prefix_fragile_strategy(source_rows, {}),
        strategy_id="demo",
        key=focused_key(),
        config=FocusedCausalityConfig(max_probes=4, timeout_seconds=60.0),
    )

    assert result.status == "failed"
    assert result.scoring_allowed is False
    assert result.rejection_reason == "focused_probe_skipped: ValueError: needs warmup"


def test_hidden_lookahead_detects_payload_change_with_stable_decision_id():
    rows = [
        row(AS_OF, 100.0, available_at=AS_OF),
        row(FUTURE, 999.0, available_at=FUTURE),
    ]

    def stable_id_future_sensitive_strategy(
        rows: Sequence[Mapping[str, Any]],
        params: Mapping[str, Any],
    ):
        future_rows = [item for item in rows if item.get("timestamp") == FUTURE]
        size = 2.0 if future_rows else 1.0
        item = decision(size)
        return [item.model_copy(update={"decision_id": "stable"})]

    baseline = stable_id_future_sensitive_strategy(rows, {})

    result = check_hidden_lookahead(
        stable_id_future_sensitive_strategy,
        rows=rows,
        params={},
        baseline_decisions=baseline,
        strategy_id="demo",
        mode="emitted",
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
    source_rows = [row(AS_OF, 100.0 + index, available_at=AS_OF) for index in range(12)]

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
    )
    baseline = as_of_strategy(normalized.projection_rows(), {})
    monkeypatch.setattr(
        causality,
        "parse_aware_datetime",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("should not parse normalized rows")
        ),
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
    assert result.deterministic_replay_verified is True
    assert result.emitted_replay_verified is True
    assert result.strict_suppression_verified is True
    assert result.skipped_probe_count == 0
    assert result.skipped_probe_reasons == ()


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
    assert result.strict_suppression_verified is True
    assert calls == 2


def test_strict_hidden_lookahead_reports_skipped_probe_as_incomplete_evidence():
    rows = [
        row(AS_OF, 100.0, available_at=AS_OF),
        row(FUTURE, 101.0, available_at=FUTURE),
    ]

    def prefix_fragile_strategy(rows: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
        if all(item.get("timestamp") != FUTURE for item in rows):
            raise RuntimeError("prefix too short")
        return []

    result = check_hidden_lookahead(
        prefix_fragile_strategy,
        rows=rows,
        params={},
        baseline_decisions=prefix_fragile_strategy(rows, {}),
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
    assert result.deterministic_replay_verified is True
    assert result.emitted_replay_verified is True
    assert result.strict_suppression_verified is False
    assert result.skipped_probe_count == 1
    assert result.skipped_probe_reasons == ("RuntimeError: prefix too short",)


def test_causality_completeness_violations_accepts_complete_strict_result():
    result = causality.LookaheadCheckResult(
        passed=True,
        mode="strict",
        deterministic_replay_verified=True,
        emitted_replay_verified=True,
        strict_suppression_verified=True,
    )

    assert causality.causality_completeness_violations(result) == ()


def test_causality_completeness_violations_returns_failed_lookahead_reasons_once():
    result = causality.LookaheadCheckResult(
        passed=False,
        violations=("hidden_lookahead_detected", "hidden_lookahead_detected"),
        mode="strict",
        deterministic_replay_verified=True,
        emitted_replay_verified=False,
        strict_suppression_verified=False,
    )

    assert causality.causality_completeness_violations(result) == ("hidden_lookahead_detected",)


def test_causality_completeness_violations_reports_missing_replay_proofs():
    result = causality.LookaheadCheckResult(
        passed=True,
        mode="strict",
        deterministic_replay_verified=False,
        emitted_replay_verified=False,
        strict_suppression_verified=False,
    )

    assert causality.causality_completeness_violations(result) == (
        "determinism_replay_not_verified",
        "emitted_replay_not_verified",
        "strict_suppression_replay_not_verified",
    )


def test_causality_completeness_violations_reports_skipped_strict_probe():
    result = causality.LookaheadCheckResult(
        passed=True,
        mode="strict",
        deterministic_replay_verified=True,
        emitted_replay_verified=True,
        strict_suppression_verified=False,
        skipped_probe_count=1,
        skipped_probe_reasons=("RuntimeError: prefix too short",),
    )

    assert causality.causality_completeness_violations(result) == (
        "strict_suppression_replay_not_verified",
    )


def test_hidden_lookahead_rejects_nondeterministic_full_replay():
    rows = [row(AS_OF, 100.0, available_at=AS_OF)]
    calls = 0

    def nondeterministic_strategy(rows: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
        nonlocal calls
        calls += 1
        return [decision(float(calls))]

    result = check_hidden_lookahead(
        nondeterministic_strategy,
        rows=rows,
        params={},
        baseline_decisions=nondeterministic_strategy(rows, {}),
        strategy_id="demo",
    )

    assert result.passed is False
    assert result.violations == ("strategy_generation_not_deterministic",)
    assert result.deterministic_replay_verified is False
    assert result.emitted_replay_verified is False
    assert result.strict_suppression_verified is False


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
    assert calls == 2


def test_hidden_lookahead_reuses_visible_rows_for_shared_decision_boundary():
    source_rows = [row(AS_OF, 100.0 + index, available_at=AS_OF) for index in range(4)]
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
    assert len(replay_row_ids) == 2


def test_hidden_lookahead_does_not_share_visible_rows_across_decision_times():
    source_rows = [
        row(AS_OF, 100.0, available_at=AS_OF),
        row(AS_OF, 101.0, available_at=LATE_DECISION),
    ]
    visible_closes_by_call: list[tuple[float, ...]] = []

    def boundary_strategy(rows: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
        closes = tuple(float(item["close"]) for item in rows)
        visible_closes_by_call.append(closes)
        decisions = []
        if 100.0 in closes:
            decisions.append(decision())
        if 101.0 in closes:
            decisions.append(
                StrategyDecision(
                    decision_id="demo:late",
                    strategy_id="demo",
                    instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
                    decision_time=LATE_DECISION,
                    as_of_time=AS_OF,
                    target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
                    exit_policy=ExitPolicy(max_hold_bars=1),
                )
            )
        return decisions

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
    assert visible_closes_by_call == [(100.0, 101.0), (100.0,), (100.0, 101.0)]
