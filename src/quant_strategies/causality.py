from __future__ import annotations

import hashlib
import heapq
import json
import signal
import threading
import time
from bisect import bisect_right
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal

from quant_strategies.boundary import frozen_params, frozen_rows
from quant_strategies.data_contract import NormalizedRows
from quant_strategies.datetime_utils import parse_aware_datetime
from quant_strategies.decisions import StrategyDecision, validate_decision_output

ReplayMode = Literal["emitted", "strict"]
ReplayScope = Literal["off", "emitted", "strict", "focused", "micro", "bounded", "complete"]
FocusedCausalityStatus = Literal["passed", "failed", "timeout"]
FOCUSED_CAUSALITY_PROFILE_VERSION = "focused-causality/v1"


@dataclass(frozen=True)
class LookaheadCheckResult:
    passed: bool
    violations: tuple[str, ...] = ()
    mode: ReplayMode = "emitted"
    deterministic_replay_verified: bool = False
    emitted_replay_verified: bool = False
    strict_suppression_verified: bool = False
    skipped_probe_count: int = 0
    skipped_probe_reasons: tuple[str, ...] = ()
    strict_replay_capped: bool = False
    strict_probe_count: int | None = None
    strict_probe_limit: int | None = None
    replay_scope: ReplayScope | None = None
    candidate_probe_count: int | None = None
    selected_probe_count: int | None = None
    elapsed_seconds: float | None = None
    timeout_seconds: float | None = None
    timed_out: bool = False
    replay_warning: str | None = None


def causality_completeness_violations(
    lookahead: LookaheadCheckResult,
) -> tuple[str, ...]:
    """Reasons a lookahead result is not complete usable evidence."""
    violations = list(lookahead.violations)
    if lookahead.passed and not lookahead.deterministic_replay_verified:
        violations.append("determinism_replay_not_verified")
    if lookahead.passed and not lookahead.emitted_replay_verified:
        violations.append("emitted_replay_not_verified")
    if lookahead.passed and not lookahead.strict_suppression_verified:
        violations.append("strict_suppression_replay_not_verified")
    return tuple(dict.fromkeys(violations))


@dataclass(frozen=True)
class ReplayBoundary:
    as_of_time: datetime
    decision_time: datetime
    expected_decision_ids: frozenset[str | None] = frozenset()
    allowed_decision_ids: frozenset[str | None] = frozenset()
    symbols: frozenset[str] = frozenset()


@dataclass(frozen=True)
class FocusedCausalityKey:
    strategy_source_sha256: str
    strategy_id: str
    data_kind: str
    profile_version: str = FOCUSED_CAUSALITY_PROFILE_VERSION
    normalized_rows_sha256: str | None = None
    params_sha256: str | None = None
    max_probes: int | None = None
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class FocusedCausalityConfig:
    max_probes: int = 64
    timeout_seconds: float = 60.0
    profile_version: str = FOCUSED_CAUSALITY_PROFILE_VERSION


@dataclass(frozen=True)
class FocusedReplayPlan:
    boundaries: tuple[ReplayBoundary, ...]
    candidate_probe_count: int
    selected_probe_count: int


@dataclass(frozen=True)
class FocusedCausalityResult:
    status: FocusedCausalityStatus
    scoring_allowed: bool
    key: FocusedCausalityKey
    profile_version: str
    timeout_seconds: float
    candidate_probe_count: int = 0
    selected_probe_count: int = 0
    lookahead: LookaheadCheckResult | None = None
    rejection_reason: str | None = None
    cache_hit: bool = False


@dataclass(frozen=True)
class _VisibleRow:
    row: Mapping[str, Any]
    frozen_row: Mapping[str, Any]
    timestamp: datetime | None
    available_at: datetime | None


@dataclass(frozen=True)
class _VisibleRowIndex:
    rows: tuple[_VisibleRow, ...]
    frozen_rows: tuple[Mapping[str, Any], ...]
    timestamps: tuple[datetime, ...]
    timestamps_by_symbol: Mapping[str, tuple[datetime, ...]]
    has_delayed_availability: bool = False


@dataclass(frozen=True)
class _ReplayDecisionIndex:
    baseline_payloads: tuple[dict[str, Any], ...]
    by_decision_id: Mapping[str | None, tuple[tuple[int, StrategyDecision], ...]]
    allowed_by_asof_symbol: Mapping[tuple[datetime, str], frozenset[str | None]]

    @classmethod
    def from_decisions(cls, decisions: Sequence[StrategyDecision]) -> _ReplayDecisionIndex:
        by_decision_id: dict[str | None, list[tuple[int, StrategyDecision]]] = {}
        allowed_by_asof_symbol: dict[tuple[datetime, str], set[str | None]] = {}
        for index, decision in enumerate(decisions):
            by_decision_id.setdefault(decision.decision_id, []).append((index, decision))
            allowed_by_asof_symbol.setdefault(
                (decision.as_of_time, decision.instrument.symbol),
                set(),
            ).add(decision.decision_id)
        return cls(
            baseline_payloads=_decision_payloads(decisions),
            by_decision_id={
                decision_id: tuple(items) for decision_id, items in by_decision_id.items()
            },
            allowed_by_asof_symbol={
                key: frozenset(value) for key, value in allowed_by_asof_symbol.items()
            },
        )

    def allowed_decision_ids(
        self,
        *,
        as_of_time: datetime,
        symbols: frozenset[str],
    ) -> frozenset[str | None]:
        allowed: set[str | None] = set()
        for symbol in symbols:
            allowed.update(self.allowed_by_asof_symbol.get((as_of_time, symbol), frozenset()))
        return frozenset(allowed)

    def expected_payloads_for_boundary(
        self,
        boundary: ReplayBoundary,
    ) -> tuple[dict[str, Any], ...]:
        indexed_decisions: list[tuple[int, StrategyDecision]] = []
        for decision_id in boundary.expected_decision_ids:
            for index, decision in self.by_decision_id.get(decision_id, ()):
                if (
                    _decision_matches_boundary(decision, boundary)
                    and decision.decision_time == boundary.decision_time
                ):
                    indexed_decisions.append((index, decision))
        indexed_decisions.sort(key=lambda item: item[0])
        return _decision_payloads([decision for _, decision in indexed_decisions])


class _FocusedCausalityDeadline(BaseException):
    pass


DecisionGenerator = Callable[
    [Sequence[Mapping[str, Any]], Mapping[str, Any]],
    object,
]


def focused_replay_plan(
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
    baseline_decisions: Sequence[StrategyDecision],
    *,
    key: FocusedCausalityKey,
    config: FocusedCausalityConfig,
) -> FocusedReplayPlan:
    row_index = _visible_row_index(rows)
    candidates, candidate_count = _focused_candidate_boundaries(
        row_index,
        baseline_decisions,
        key=key,
        config=config,
    )
    if config.max_probes <= 0 or not candidates:
        return FocusedReplayPlan(
            boundaries=(),
            candidate_probe_count=candidate_count,
            selected_probe_count=0,
        )
    return FocusedReplayPlan(
        boundaries=candidates,
        candidate_probe_count=candidate_count,
        selected_probe_count=len(candidates),
    )


def micro_replay_plan(
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
    baseline_decisions: Sequence[StrategyDecision],
    *,
    max_probes: int = 5,
) -> FocusedReplayPlan:
    plan, _, _ = _micro_replay_plan_with_index(
        rows,
        baseline_decisions,
        max_probes=max_probes,
    )
    return plan


def _micro_replay_plan_with_index(
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
    baseline_decisions: Sequence[StrategyDecision],
    *,
    max_probes: int,
) -> tuple[FocusedReplayPlan, _VisibleRowIndex, _ReplayDecisionIndex]:
    row_index = _visible_row_index(rows)
    decision_index = _ReplayDecisionIndex.from_decisions(baseline_decisions)
    emitted = _emitted_boundaries(baseline_decisions)
    if max_probes <= 0:
        return (
            FocusedReplayPlan(
                boundaries=(),
                candidate_probe_count=len(row_index.rows) + len(emitted),
                selected_probe_count=0,
            ),
            row_index,
            decision_index,
        )
    boundaries = _dedupe_boundaries(
        (
            *_micro_row_anchor_boundaries(row_index, decision_index),
            *emitted[: max(0, max_probes)],
        )
    )[:max_probes]
    return (
        FocusedReplayPlan(
            boundaries=boundaries,
            candidate_probe_count=len(row_index.rows) + len(emitted),
            selected_probe_count=len(boundaries),
        ),
        row_index,
        decision_index,
    )


def check_micro_causality(
    generate_decisions: DecisionGenerator,
    *,
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
    params: Mapping[str, Any],
    baseline_decisions: list[StrategyDecision],
    strategy_id: str,
    max_probes: int = 5,
    timeout_seconds: float = 2.0,
) -> LookaheadCheckResult:
    started = time.perf_counter()
    plan, row_index, decision_index = _micro_replay_plan_with_index(
        rows,
        baseline_decisions,
        max_probes=max_probes,
    )
    if timeout_seconds <= 0:
        return _micro_timeout_result(started, timeout_seconds, plan)
    if _timed_out(started, timeout_seconds):
        return _micro_timeout_result(started, timeout_seconds, plan)
    if not _focused_timeout_supported(timeout_seconds):
        return _micro_timeout_result(started, timeout_seconds, plan)
    try:
        with _focused_timeout(timeout_seconds):
            lookahead = check_hidden_lookahead(
                generate_decisions,
                rows=rows,
                params=params,
                baseline_decisions=baseline_decisions,
                strategy_id=strategy_id,
                mode="strict",
                boundaries=plan.boundaries,
                _row_index=row_index,
                _decision_index=decision_index,
            )
    except _FocusedCausalityDeadline:
        return _micro_timeout_result(started, timeout_seconds, plan)
    elapsed = time.perf_counter() - started
    if elapsed > timeout_seconds:
        return _micro_timeout_result(started, timeout_seconds, plan, lookahead=lookahead)
    warning = None
    if lookahead.violations:
        warning = lookahead.violations[0]
    elif lookahead.skipped_probe_reasons:
        warning = f"micro_probe_skipped: {lookahead.skipped_probe_reasons[0]}"
    return replace(
        lookahead,
        replay_scope="micro",
        candidate_probe_count=plan.candidate_probe_count,
        selected_probe_count=plan.selected_probe_count,
        elapsed_seconds=elapsed,
        timeout_seconds=timeout_seconds,
        replay_warning=warning,
    )


def check_bounded_causality(
    generate_decisions: DecisionGenerator,
    *,
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
    params: Mapping[str, Any],
    baseline_decisions: list[StrategyDecision],
    strategy_id: str,
    max_probes: int = 64,
    timeout_seconds: float = 60.0,
) -> LookaheadCheckResult:
    started = time.perf_counter()
    plan, row_index, decision_index = _bounded_replay_plan_with_index(
        rows,
        baseline_decisions,
        max_row_probes=max_probes,
    )
    if timeout_seconds <= 0:
        return _bounded_timeout_result(started, timeout_seconds, plan)
    if _timed_out(started, timeout_seconds):
        return _bounded_timeout_result(started, timeout_seconds, plan)
    if not _focused_timeout_supported(timeout_seconds):
        return _bounded_timeout_result(started, timeout_seconds, plan)
    try:
        with _focused_timeout(timeout_seconds):
            lookahead = check_hidden_lookahead(
                generate_decisions,
                rows=rows,
                params=params,
                baseline_decisions=baseline_decisions,
                strategy_id=strategy_id,
                mode="strict",
                boundaries=plan.boundaries,
                _row_index=row_index,
                _decision_index=decision_index,
            )
    except _FocusedCausalityDeadline:
        return _bounded_timeout_result(started, timeout_seconds, plan)
    elapsed = time.perf_counter() - started
    if elapsed > timeout_seconds:
        return _bounded_timeout_result(started, timeout_seconds, plan, lookahead=lookahead)
    warning = None
    if lookahead.violations:
        warning = lookahead.violations[0]
    elif lookahead.skipped_probe_reasons:
        warning = f"bounded_probe_skipped: {lookahead.skipped_probe_reasons[0]}"
    return replace(
        lookahead,
        replay_scope="bounded",
        candidate_probe_count=plan.candidate_probe_count,
        selected_probe_count=plan.selected_probe_count,
        elapsed_seconds=elapsed,
        timeout_seconds=timeout_seconds,
        replay_warning=warning,
    )


def bounded_replay_plan(
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
    baseline_decisions: Sequence[StrategyDecision],
    *,
    max_row_probes: int = 64,
) -> FocusedReplayPlan:
    plan, _, _ = _bounded_replay_plan_with_index(
        rows,
        baseline_decisions,
        max_row_probes=max_row_probes,
    )
    return plan


def _bounded_replay_plan_with_index(
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
    baseline_decisions: Sequence[StrategyDecision],
    *,
    max_row_probes: int,
) -> tuple[FocusedReplayPlan, _VisibleRowIndex, _ReplayDecisionIndex]:
    row_index = _visible_row_index(rows)
    decision_index = _ReplayDecisionIndex.from_decisions(baseline_decisions)
    emitted = _emitted_boundaries(baseline_decisions)
    row_boundaries = _micro_row_anchor_boundaries(row_index, decision_index)
    selected = _dedupe_boundaries((*emitted, *row_boundaries[: max(0, max_row_probes)]))
    return (
        FocusedReplayPlan(
            boundaries=selected,
            candidate_probe_count=len(row_index.rows) + len(emitted),
            selected_probe_count=len(selected),
        ),
        row_index,
        decision_index,
    )


def check_focused_causality(
    generate_decisions: DecisionGenerator,
    *,
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
    params: Mapping[str, Any],
    baseline_decisions: list[StrategyDecision],
    strategy_id: str,
    key: FocusedCausalityKey,
    config: FocusedCausalityConfig | None = None,
) -> FocusedCausalityResult:
    if config is None:
        config = FocusedCausalityConfig()
    if config.timeout_seconds <= 0:
        return _focused_timeout_result(key=key, config=config)

    started = time.perf_counter()
    plan = focused_replay_plan(rows, baseline_decisions, key=key, config=config)
    if _timed_out(started, config.timeout_seconds):
        return _focused_timeout_result(key=key, config=config, plan=plan)
    if not _focused_timeout_supported(config.timeout_seconds):
        return _focused_timeout_result(key=key, config=config, plan=plan)

    try:
        with _focused_timeout(config.timeout_seconds):
            lookahead = check_hidden_lookahead(
                generate_decisions,
                rows=rows,
                params=params,
                baseline_decisions=baseline_decisions,
                strategy_id=strategy_id,
                mode="strict",
                boundaries=plan.boundaries,
            )
    except _FocusedCausalityDeadline:
        return _focused_timeout_result(key=key, config=config, plan=plan)
    if _timed_out(started, config.timeout_seconds):
        return _focused_timeout_result(key=key, config=config, plan=plan, lookahead=lookahead)
    if lookahead.passed and lookahead.skipped_probe_count:
        return FocusedCausalityResult(
            status="failed",
            scoring_allowed=False,
            key=key,
            profile_version=config.profile_version,
            timeout_seconds=config.timeout_seconds,
            candidate_probe_count=plan.candidate_probe_count,
            selected_probe_count=plan.selected_probe_count,
            lookahead=lookahead,
            rejection_reason=_focused_skipped_probe_reason(lookahead),
        )
    if lookahead.passed:
        return FocusedCausalityResult(
            status="passed",
            scoring_allowed=True,
            key=key,
            profile_version=config.profile_version,
            timeout_seconds=config.timeout_seconds,
            candidate_probe_count=plan.candidate_probe_count,
            selected_probe_count=plan.selected_probe_count,
            lookahead=lookahead,
        )
    return FocusedCausalityResult(
        status="failed",
        scoring_allowed=False,
        key=key,
        profile_version=config.profile_version,
        timeout_seconds=config.timeout_seconds,
        candidate_probe_count=plan.candidate_probe_count,
        selected_probe_count=plan.selected_probe_count,
        lookahead=lookahead,
        rejection_reason=_focused_rejection_reason(lookahead),
    )


def check_hidden_lookahead(
    generate_decisions: DecisionGenerator,
    *,
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
    params: Mapping[str, Any],
    baseline_decisions: list[StrategyDecision],
    strategy_id: str,
    mode: ReplayMode = "strict",
    boundaries: Sequence[ReplayBoundary] | None = None,
    _row_index: _VisibleRowIndex | None = None,
    _decision_index: _ReplayDecisionIndex | None = None,
) -> LookaheadCheckResult:
    """Replay a strategy at point-in-time boundaries to detect hidden lookahead.

    Two directions are checked. The *subset* check (``expected ⊆ replay``) catches a
    strategy that reads future rows to *change* a decision: truncated replay fails
    to reproduce the emitted decision. The *suppression* check (``scoped ⊆ allowed``,
    strict only) catches a strategy that reads the future to *withhold* a losing
    trade: at the row-grid boundary where the trade would otherwise be emitted, the
    truncated replay emits a decision the baseline never produced.

    ``mode="strict"`` is the default and the only mode that may set
    ``strict_suppression_verified``; it auto-derives row-grid boundaries when none
    are supplied. The check also repeats full generation once on the same rows and
    params. Strict probes that cannot run on short prefixes are counted as skipped
    probes; they do not fail replay, but they keep strict suppression evidence
    incomplete.
    """
    if boundaries is not None:
        replay_boundaries = tuple(boundaries)
    elif mode == "strict":
        replay_boundaries = strict_replay_boundaries(rows, baseline_decisions)
    else:
        replay_boundaries = _emitted_boundaries(baseline_decisions)

    replay_params = frozen_params(params)
    decision_index = _decision_index or _ReplayDecisionIndex.from_decisions(baseline_decisions)
    deterministic_failure = _deterministic_replay_failure(
        generate_decisions,
        rows=rows,
        params=replay_params,
        baseline_decisions=baseline_decisions,
        baseline_payloads=decision_index.baseline_payloads,
        strategy_id=strategy_id,
        mode=mode,
    )
    if deterministic_failure is not None:
        return deterministic_failure

    if not replay_boundaries:
        # Nothing to replay (no rows and no decisions): vacuously verified.
        return LookaheadCheckResult(
            passed=True,
            mode=mode,
            deterministic_replay_verified=True,
            emitted_replay_verified=True,
            strict_suppression_verified=mode == "strict",
        )

    row_index = _row_index or _visible_row_index(rows)
    replay_decision_ids_cache: dict[tuple[datetime, datetime], frozenset[str | None]] = {}
    replay_decisions_cache: dict[tuple[datetime, datetime], tuple[StrategyDecision, ...]] = {}
    replay_payloads_cache: dict[tuple[datetime, datetime], tuple[dict[str, Any], ...]] = {}
    expected_payloads_by_boundary = {
        _boundary_identity(boundary): decision_index.expected_payloads_for_boundary(boundary)
        for boundary in replay_boundaries
        if boundary.expected_decision_ids
    }
    skipped_probe_reasons: list[str] = []
    for boundary in replay_boundaries:
        cache_key = (boundary.as_of_time, boundary.decision_time)
        replay_decisions = replay_decisions_cache.get(cache_key)
        if replay_decisions is None:
            replay_rows = _visible_rows_for_boundary(row_index, boundary)
            try:
                replay_output = generate_decisions(replay_rows, replay_params)
            except SystemExit as exc:
                if boundary.expected_decision_ids:
                    return LookaheadCheckResult(
                        passed=False,
                        mode=mode,
                        deterministic_replay_verified=True,
                        violations=(f"hidden_lookahead_check_failed: SystemExit: {exc}",),
                        skipped_probe_count=len(skipped_probe_reasons),
                        skipped_probe_reasons=tuple(skipped_probe_reasons),
                    )
                # Pure probe boundary (no emitted decision to reproduce): a strategy
                # that cannot run on this prefix did not suppress a trade here, so
                # skip rather than fail. The skipped probe still means strict
                # suppression evidence was incomplete.
                skipped_probe_reasons.append(_exception_reason(exc))
                continue
            except Exception as exc:
                if boundary.expected_decision_ids:
                    return LookaheadCheckResult(
                        passed=False,
                        mode=mode,
                        deterministic_replay_verified=True,
                        violations=(f"hidden_lookahead_check_failed: {type(exc).__name__}: {exc}",),
                        skipped_probe_count=len(skipped_probe_reasons),
                        skipped_probe_reasons=tuple(skipped_probe_reasons),
                    )
                skipped_probe_reasons.append(_exception_reason(exc))
                continue

            parsed_decisions, violations = validate_decision_output(
                replay_output,
                strategy_id=strategy_id,
            )
            if violations:
                return LookaheadCheckResult(
                    passed=False,
                    mode=mode,
                    deterministic_replay_verified=True,
                    violations=(f"hidden_lookahead_check_failed: {'; '.join(violations)}",),
                    skipped_probe_count=len(skipped_probe_reasons),
                    skipped_probe_reasons=tuple(skipped_probe_reasons),
                )
            replay_decisions = tuple(parsed_decisions)
            replay_decisions_cache[cache_key] = replay_decisions

        replay_decision_ids = replay_decision_ids_cache.get(cache_key)
        if replay_decision_ids is None:
            replay_decision_ids = frozenset(replay.decision_id for replay in replay_decisions)
            replay_decision_ids_cache[cache_key] = replay_decision_ids

        if not boundary.expected_decision_ids.issubset(replay_decision_ids):
            return LookaheadCheckResult(
                passed=False,
                mode=mode,
                deterministic_replay_verified=True,
                violations=("hidden_lookahead_detected",),
                skipped_probe_count=len(skipped_probe_reasons),
                skipped_probe_reasons=tuple(skipped_probe_reasons),
            )
        if boundary.expected_decision_ids:
            replay_payloads = replay_payloads_cache.get(cache_key)
            if replay_payloads is None:
                replay_payloads = _decision_payloads(replay_decisions)
                replay_payloads_cache[cache_key] = replay_payloads
            expected_payloads = expected_payloads_by_boundary[_boundary_identity(boundary)]
            if not _payloads_contain_expected(replay_payloads, expected_payloads):
                return LookaheadCheckResult(
                    passed=False,
                    mode=mode,
                    deterministic_replay_verified=True,
                    violations=("hidden_lookahead_detected",),
                    skipped_probe_count=len(skipped_probe_reasons),
                    skipped_probe_reasons=tuple(skipped_probe_reasons),
                )
        if mode == "strict":
            scoped_decision_ids = frozenset(
                replay.decision_id
                for replay in replay_decisions
                if _decision_matches_boundary(replay, boundary)
            )
            if not scoped_decision_ids.issubset(boundary.allowed_decision_ids):
                return LookaheadCheckResult(
                    passed=False,
                    mode="strict",
                    deterministic_replay_verified=True,
                    emitted_replay_verified=True,
                    strict_suppression_verified=False,
                    violations=("hidden_lookahead_suppression_detected",),
                    skipped_probe_count=len(skipped_probe_reasons),
                    skipped_probe_reasons=tuple(skipped_probe_reasons),
                )

    skipped_probe_count = len(skipped_probe_reasons)
    return LookaheadCheckResult(
        passed=True,
        mode=mode,
        deterministic_replay_verified=True,
        emitted_replay_verified=True,
        strict_suppression_verified=mode == "strict" and skipped_probe_count == 0,
        skipped_probe_count=skipped_probe_count,
        skipped_probe_reasons=tuple(skipped_probe_reasons),
    )


def _deterministic_replay_failure(
    generate_decisions: DecisionGenerator,
    *,
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
    params: Mapping[str, Any],
    baseline_decisions: Sequence[StrategyDecision],
    baseline_payloads: tuple[dict[str, Any], ...] | None = None,
    strategy_id: str,
    mode: ReplayMode,
) -> LookaheadCheckResult | None:
    full_rows = frozen_rows(_projection_rows(rows))
    try:
        replay_output = generate_decisions(full_rows, params)
    except SystemExit as exc:
        return LookaheadCheckResult(
            passed=False,
            mode=mode,
            violations=(f"determinism_check_failed: SystemExit: {exc}",),
        )
    except Exception as exc:
        return LookaheadCheckResult(
            passed=False,
            mode=mode,
            violations=(f"determinism_check_failed: {type(exc).__name__}: {exc}",),
        )

    replay_decisions, violations = validate_decision_output(
        replay_output,
        strategy_id=strategy_id,
    )
    if violations:
        return LookaheadCheckResult(
            passed=False,
            mode=mode,
            violations=(f"determinism_check_failed: {'; '.join(violations)}",),
        )
    expected_payloads = (
        _decision_payloads(baseline_decisions) if baseline_payloads is None else baseline_payloads
    )
    if _decision_payloads(replay_decisions) != expected_payloads:
        return LookaheadCheckResult(
            passed=False,
            mode=mode,
            violations=("strategy_generation_not_deterministic",),
        )
    return None


def _projection_rows(
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
) -> Sequence[Mapping[str, Any]]:
    return rows.projection_rows() if isinstance(rows, NormalizedRows) else rows


def _decision_payloads(
    decisions: Sequence[StrategyDecision],
) -> tuple[dict[str, Any], ...]:
    return tuple(decision.model_dump(mode="json") for decision in decisions)


def _expected_payloads_for_boundary(
    decisions: Sequence[StrategyDecision],
    boundary: ReplayBoundary,
) -> tuple[dict[str, Any], ...]:
    return _decision_payloads(
        [
            decision
            for decision in decisions
            if decision.decision_id in boundary.expected_decision_ids
            and _decision_matches_boundary(decision, boundary)
            and decision.decision_time == boundary.decision_time
        ]
    )


def _payloads_contain_expected(
    replay_payloads: Sequence[Mapping[str, Any]],
    expected_payloads: Sequence[Mapping[str, Any]],
) -> bool:
    remaining = [dict(payload) for payload in replay_payloads]
    for expected in expected_payloads:
        try:
            index = remaining.index(dict(expected))
        except ValueError:
            return False
        remaining.pop(index)
    return True


def _exception_reason(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _focused_timeout_result(
    *,
    key: FocusedCausalityKey,
    config: FocusedCausalityConfig,
    plan: FocusedReplayPlan | None = None,
    lookahead: LookaheadCheckResult | None = None,
) -> FocusedCausalityResult:
    return FocusedCausalityResult(
        status="timeout",
        scoring_allowed=False,
        key=key,
        profile_version=config.profile_version,
        timeout_seconds=config.timeout_seconds,
        candidate_probe_count=0 if plan is None else plan.candidate_probe_count,
        selected_probe_count=0 if plan is None else plan.selected_probe_count,
        lookahead=lookahead,
        rejection_reason="focused_causality_timeout",
    )


def _focused_rejection_reason(lookahead: LookaheadCheckResult) -> str:
    if lookahead.violations:
        return lookahead.violations[0]
    return "focused_causality_failed"


def _focused_skipped_probe_reason(lookahead: LookaheadCheckResult) -> str:
    if lookahead.skipped_probe_reasons:
        return f"focused_probe_skipped: {lookahead.skipped_probe_reasons[0]}"
    return "focused_probe_skipped"


def _micro_timeout_result(
    started: float,
    timeout_seconds: float,
    plan: FocusedReplayPlan,
    lookahead: LookaheadCheckResult | None = None,
) -> LookaheadCheckResult:
    return LookaheadCheckResult(
        passed=False,
        mode="strict",
        deterministic_replay_verified=bool(lookahead and lookahead.deterministic_replay_verified),
        emitted_replay_verified=False,
        strict_suppression_verified=False,
        violations=("micro_causality_timeout",),
        replay_scope="micro",
        candidate_probe_count=plan.candidate_probe_count,
        selected_probe_count=plan.selected_probe_count,
        elapsed_seconds=time.perf_counter() - started,
        timeout_seconds=timeout_seconds,
        timed_out=True,
        replay_warning="micro_causality_timeout",
    )


def _bounded_timeout_result(
    started: float,
    timeout_seconds: float,
    plan: FocusedReplayPlan,
    lookahead: LookaheadCheckResult | None = None,
) -> LookaheadCheckResult:
    return LookaheadCheckResult(
        passed=False,
        mode="strict",
        deterministic_replay_verified=bool(lookahead and lookahead.deterministic_replay_verified),
        emitted_replay_verified=False,
        strict_suppression_verified=False,
        violations=("bounded_causality_timeout",),
        replay_scope="bounded",
        candidate_probe_count=plan.candidate_probe_count,
        selected_probe_count=plan.selected_probe_count,
        elapsed_seconds=time.perf_counter() - started,
        timeout_seconds=timeout_seconds,
        timed_out=True,
        replay_warning="bounded_causality_timeout",
    )


def _timed_out(started: float, timeout_seconds: float) -> bool:
    return time.perf_counter() - started > timeout_seconds


class _focused_timeout:
    def __init__(self, timeout_seconds: float) -> None:
        self._timeout_seconds = timeout_seconds
        self._enabled = _focused_timeout_supported(timeout_seconds)
        self._previous_handler: object | None = None
        self._previous_timer: tuple[float, float] | None = None

    def __enter__(self) -> None:
        if not self._enabled:
            return
        self._previous_handler = signal.getsignal(signal.SIGALRM)
        self._previous_timer = signal.setitimer(signal.ITIMER_REAL, self._timeout_seconds)
        signal.signal(signal.SIGALRM, self._raise_deadline)

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if not self._enabled:
            return False
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        if self._previous_handler is not None:
            signal.signal(signal.SIGALRM, self._previous_handler)
        if self._previous_timer is not None and self._previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, *self._previous_timer)
        return False

    def _raise_deadline(self, signum: int, frame: object) -> None:
        raise _FocusedCausalityDeadline()


def _focused_timeout_supported(timeout_seconds: float) -> bool:
    return (
        hasattr(signal, "setitimer")
        and hasattr(signal, "SIGALRM")
        and threading.current_thread() is threading.main_thread()
        and timeout_seconds > 0
    )


def _dedupe_boundaries(boundaries: Sequence[ReplayBoundary]) -> tuple[ReplayBoundary, ...]:
    unique: dict[tuple[object, ...], ReplayBoundary] = {}
    for boundary in boundaries:
        unique.setdefault(_boundary_identity(boundary), boundary)
    return tuple(unique.values())


def _focused_candidate_boundaries(
    row_index: _VisibleRowIndex,
    baseline_decisions: Sequence[StrategyDecision],
    *,
    key: FocusedCausalityKey,
    config: FocusedCausalityConfig,
) -> tuple[tuple[ReplayBoundary, ...], int]:
    emitted = _emitted_boundaries(baseline_decisions)
    row_boundaries, row_grid_count = _focused_row_grid_boundaries(
        row_index,
        baseline_decisions,
        key=key,
        max_items=config.max_probes,
    )
    candidates = _dedupe_boundaries((*emitted, *row_boundaries))
    selected = _select_focused_boundaries(candidates, key=key, max_probes=config.max_probes)
    return selected, row_grid_count + len(emitted)


def _micro_row_anchor_boundaries(
    row_index: _VisibleRowIndex,
    decision_index: _ReplayDecisionIndex,
) -> tuple[ReplayBoundary, ...]:
    if not row_index.rows:
        return ()
    positions = (0, len(row_index.rows) // 2, len(row_index.rows) - 1)
    anchors: list[ReplayBoundary] = []
    for position in positions:
        item = row_index.rows[position]
        symbol_value = item.row.get("symbol")
        if item.timestamp is None or not isinstance(symbol_value, str):
            continue
        symbols = frozenset({symbol_value})
        anchors.append(
            ReplayBoundary(
                as_of_time=item.timestamp,
                decision_time=_next_symbol_timestamp(row_index, symbol_value, item.timestamp),
                allowed_decision_ids=decision_index.allowed_decision_ids(
                    as_of_time=item.timestamp,
                    symbols=symbols,
                ),
                symbols=symbols,
            )
        )
    return _dedupe_boundaries(anchors)


def _next_symbol_timestamp(
    row_index: _VisibleRowIndex,
    symbol: str,
    timestamp: datetime,
) -> datetime:
    timestamps = row_index.timestamps_by_symbol.get(symbol, ())
    if not timestamps:
        return timestamp
    position = bisect_right(timestamps, timestamp)
    return timestamps[position] if position < len(timestamps) else timestamp


def _focused_row_grid_boundaries(
    row_index: _VisibleRowIndex,
    baseline_decisions: Sequence[StrategyDecision],
    *,
    key: FocusedCausalityKey,
    max_items: int,
) -> tuple[tuple[ReplayBoundary, ...], int]:
    total = _row_grid_boundary_count(row_index)
    if total == 0 or max_items <= 0:
        return (), total
    anchors: list[tuple[datetime, datetime, str]] = []
    anchor_positions = {0, total // 2, total - 1}
    for index, item in enumerate(_row_grid_boundary_keys(row_index)):
        if index in anchor_positions and item not in anchors:
            anchors.append(item)
    remaining = max_items - len(anchors)
    if remaining > 0:
        anchor_set = set(anchors)
        anchors.extend(
            heapq.nsmallest(
                remaining,
                (item for item in _row_grid_boundary_keys(row_index) if item not in anchor_set),
                key=lambda item: _row_grid_key_score(item, key),
            )
        )
    return (
        tuple(
            ReplayBoundary(
                as_of_time=as_of_time,
                decision_time=decision_time,
                allowed_decision_ids=_allowed_decision_ids(
                    baseline_decisions,
                    as_of_time=as_of_time,
                    symbols=frozenset({symbol}),
                ),
                symbols=frozenset({symbol}),
            )
            for as_of_time, decision_time, symbol in anchors[:max_items]
        ),
        total,
    )


def _row_grid_boundary_count(row_index: _VisibleRowIndex) -> int:
    return sum(1 for _ in _row_grid_boundary_keys(row_index))


def _row_grid_boundary_keys(
    row_index: _VisibleRowIndex,
) -> Iterator[tuple[datetime, datetime, str]]:
    for symbol, timestamps in sorted(_timestamps_by_symbol(row_index).items()):
        ordered = sorted(dict.fromkeys(timestamps))
        for index, timestamp in enumerate(ordered):
            decision_time = ordered[index + 1] if index + 1 < len(ordered) else timestamp
            yield (timestamp, decision_time, symbol)


def _timestamps_by_symbol(row_index: _VisibleRowIndex) -> dict[str, list[datetime]]:
    return {
        symbol: list(timestamps) for symbol, timestamps in row_index.timestamps_by_symbol.items()
    }


def _allowed_decision_ids(
    decisions: Sequence[StrategyDecision],
    *,
    as_of_time: datetime,
    symbols: frozenset[str],
) -> frozenset[str | None]:
    return frozenset(
        decision.decision_id
        for decision in decisions
        if decision.as_of_time == as_of_time
        and (not symbols or decision.instrument.symbol in symbols)
    )


def _row_grid_key_score(
    item: tuple[datetime, datetime, str],
    key: FocusedCausalityKey,
) -> str:
    as_of_time, decision_time, symbol = item
    payload = {
        "key": {
            "strategy_source_sha256": key.strategy_source_sha256,
            "strategy_id": key.strategy_id,
            "data_kind": key.data_kind,
            "profile_version": key.profile_version,
            "normalized_rows_sha256": key.normalized_rows_sha256,
            "params_sha256": key.params_sha256,
            "max_probes": key.max_probes,
            "timeout_seconds": key.timeout_seconds,
        },
        "row_grid": {
            "as_of_time": as_of_time.isoformat(),
            "decision_time": decision_time.isoformat(),
            "symbol": symbol,
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _select_focused_boundaries(
    boundaries: Sequence[ReplayBoundary],
    *,
    key: FocusedCausalityKey,
    max_probes: int,
) -> tuple[ReplayBoundary, ...]:
    if len(boundaries) <= max_probes:
        return tuple(boundaries)

    selected: list[ReplayBoundary] = []
    emitted = [boundary for boundary in boundaries if boundary.expected_decision_ids]
    no_signal = [boundary for boundary in boundaries if not boundary.expected_decision_ids]
    _append_ranked(selected, emitted, key=key, limit=max(1, max_probes // 2))
    remaining = max_probes - len(selected)
    if remaining > 0:
        _append_anchor_boundaries(selected, no_signal, limit=remaining)
    remaining = max_probes - len(selected)
    if remaining > 0:
        pool = [boundary for boundary in boundaries if boundary not in selected]
        _append_ranked(selected, pool, key=key, limit=remaining)
    return tuple(sorted(selected[:max_probes], key=_boundary_sort_key))


def _append_anchor_boundaries(
    selected: list[ReplayBoundary],
    boundaries: Sequence[ReplayBoundary],
    *,
    limit: int,
) -> None:
    if limit <= 0 or not boundaries:
        return
    appended = 0
    positions = (0, len(boundaries) // 2, len(boundaries) - 1)
    for position in positions:
        if appended >= limit:
            return
        boundary = boundaries[position]
        if boundary not in selected:
            selected.append(boundary)
            appended += 1


def _append_ranked(
    selected: list[ReplayBoundary],
    boundaries: Sequence[ReplayBoundary],
    *,
    key: FocusedCausalityKey,
    limit: int,
) -> None:
    if limit <= 0:
        return
    appended = 0
    for boundary in heapq.nsmallest(limit, boundaries, key=lambda item: _boundary_score(item, key)):
        if appended >= limit:
            return
        if boundary not in selected:
            selected.append(boundary)
            appended += 1


def _boundary_score(boundary: ReplayBoundary, key: FocusedCausalityKey) -> str:
    payload = {
        "key": {
            "strategy_source_sha256": key.strategy_source_sha256,
            "strategy_id": key.strategy_id,
            "data_kind": key.data_kind,
            "profile_version": key.profile_version,
            "normalized_rows_sha256": key.normalized_rows_sha256,
            "params_sha256": key.params_sha256,
            "max_probes": key.max_probes,
            "timeout_seconds": key.timeout_seconds,
        },
        "boundary": _boundary_jsonable(boundary),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _boundary_identity(boundary: ReplayBoundary) -> tuple[object, ...]:
    return (
        boundary.as_of_time,
        boundary.decision_time,
        tuple(sorted(boundary.expected_decision_ids, key=str)),
        tuple(sorted(boundary.allowed_decision_ids, key=str)),
        tuple(sorted(boundary.symbols)),
    )


def _boundary_sort_key(boundary: ReplayBoundary) -> tuple[object, ...]:
    return (
        boundary.as_of_time,
        boundary.decision_time,
        tuple(sorted(boundary.symbols)),
        tuple(sorted(boundary.expected_decision_ids, key=str)),
    )


def _boundary_jsonable(boundary: ReplayBoundary) -> dict[str, object]:
    return {
        "as_of_time": boundary.as_of_time.isoformat(),
        "decision_time": boundary.decision_time.isoformat(),
        "expected_decision_ids": sorted(boundary.expected_decision_ids, key=str),
        "allowed_decision_ids": sorted(boundary.allowed_decision_ids, key=str),
        "symbols": sorted(boundary.symbols),
    }


def _emitted_boundaries(decisions: Sequence[StrategyDecision]) -> tuple[ReplayBoundary, ...]:
    items: dict[tuple[datetime, datetime], set[str | None]] = {}
    symbols: dict[tuple[datetime, datetime], set[str]] = {}
    for decision in decisions:
        key = (decision.as_of_time, decision.decision_time)
        items.setdefault(key, set()).add(decision.decision_id)
        symbols.setdefault(key, set()).add(decision.instrument.symbol)
    return tuple(
        ReplayBoundary(
            as_of_time=as_of_time,
            decision_time=decision_time,
            expected_decision_ids=frozenset(items[(as_of_time, decision_time)]),
            allowed_decision_ids=frozenset(items[(as_of_time, decision_time)]),
            symbols=frozenset(symbols[(as_of_time, decision_time)]),
        )
        for as_of_time, decision_time in sorted(items)
    )


def strict_replay_boundaries(
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
    decisions: Sequence[StrategyDecision],
) -> tuple[ReplayBoundary, ...]:
    """Row-grid replay boundaries for strict suppression replay.

    One boundary per (as_of_time, next_timestamp) per symbol on the row grid,
    merged with the emitted-decision boundaries. Strict replay at each grid point
    catches a strategy that peeks ahead to *withhold* a trade: at the point the
    trade would otherwise be emitted, the truncated replay cannot see the future
    used to suppress it, so it emits a decision absent from the expected set.
    """
    # Exact emissions per (as_of, decision_time) drive the subset check; the merged
    # per-(as_of, symbol) set is what the suppression check is allowed to see, so a
    # legitimate decision that depends on later-available data is not wrongly demanded
    # at an earlier grid boundary.
    expected_by_key: dict[tuple[datetime, datetime], set[str | None]] = {}
    allowed_by_asof_symbol: dict[tuple[datetime, str], set[str | None]] = {}
    symbols_by_key: dict[tuple[datetime, datetime], set[str]] = {}
    for decision in decisions:
        key = (decision.as_of_time, decision.decision_time)
        expected_by_key.setdefault(key, set()).add(decision.decision_id)
        symbols_by_key.setdefault(key, set()).add(decision.instrument.symbol)
        allowed_by_asof_symbol.setdefault(
            (decision.as_of_time, decision.instrument.symbol),
            set(),
        ).add(decision.decision_id)

    projection = rows.projection_rows() if isinstance(rows, NormalizedRows) else rows
    timestamps_by_symbol: dict[str, list[datetime]] = {}
    for row in projection:
        symbol = row.get("symbol")
        timestamp = row.get("timestamp")
        if isinstance(symbol, str) and _is_aware_datetime(timestamp):
            timestamps_by_symbol.setdefault(symbol, []).append(timestamp)

    for symbol, timestamps in timestamps_by_symbol.items():
        ordered = sorted(dict.fromkeys(timestamps))
        for index, timestamp in enumerate(ordered):
            decision_time = ordered[index + 1] if index + 1 < len(ordered) else timestamp
            key = (timestamp, decision_time)
            expected_by_key.setdefault(key, set())
            symbols_by_key.setdefault(key, set()).add(symbol)

    boundaries: list[ReplayBoundary] = []
    for as_of_time, decision_time in sorted(expected_by_key):
        symbols = symbols_by_key.get((as_of_time, decision_time), set())
        allowed: set[str | None] = set()
        for symbol in symbols:
            allowed.update(allowed_by_asof_symbol.get((as_of_time, symbol), set()))
        boundaries.append(
            ReplayBoundary(
                as_of_time=as_of_time,
                decision_time=decision_time,
                expected_decision_ids=frozenset(expected_by_key[(as_of_time, decision_time)]),
                allowed_decision_ids=frozenset(allowed),
                symbols=frozenset(symbols),
            )
        )
    return tuple(boundaries)


def _visible_row_index(rows: NormalizedRows | Sequence[Mapping[str, Any]]) -> _VisibleRowIndex:
    if isinstance(rows, NormalizedRows):
        return _visible_row_index_from_normalized(rows)

    visible_rows = []
    for row in rows:
        visible_row = _visible_row(row)
        if visible_row.timestamp is not None:
            visible_rows.append(visible_row)
    ordered_rows = tuple(sorted(visible_rows, key=lambda item: item.timestamp))
    return _VisibleRowIndex(
        rows=ordered_rows,
        frozen_rows=tuple(item.frozen_row for item in ordered_rows),
        timestamps=tuple(item.timestamp for item in ordered_rows if item.timestamp is not None),
        timestamps_by_symbol=_timestamps_by_symbol_from_rows(ordered_rows),
        has_delayed_availability=_has_delayed_availability(ordered_rows),
    )


def _visible_row_index_from_normalized(rows: NormalizedRows) -> _VisibleRowIndex:
    visible_rows = []
    for row in rows.projection_rows():
        timestamp = row.get("timestamp")
        if not _is_aware_datetime(timestamp):
            continue
        available_at = row.get("available_at")
        visible_rows.append(
            _VisibleRow(
                row=row,
                frozen_row=frozen_rows((row,))[0],
                timestamp=timestamp,
                available_at=available_at if _is_aware_datetime(available_at) else None,
            )
        )
    ordered_rows = tuple(sorted(visible_rows, key=lambda item: item.timestamp))
    return _VisibleRowIndex(
        rows=ordered_rows,
        frozen_rows=tuple(item.frozen_row for item in ordered_rows),
        timestamps=tuple(item.timestamp for item in ordered_rows if item.timestamp is not None),
        timestamps_by_symbol=_timestamps_by_symbol_from_rows(ordered_rows),
        has_delayed_availability=_has_delayed_availability(ordered_rows),
    )


def _visible_row(row: Mapping[str, Any]) -> _VisibleRow:
    timestamp, _ = parse_aware_datetime(row.get("timestamp"))
    available_at = None
    available_value = row.get("available_at")
    if available_value is not None:
        available_at, _ = parse_aware_datetime(available_value)

    return _VisibleRow(
        row=row,
        frozen_row=frozen_rows((row,))[0],
        timestamp=timestamp,
        available_at=available_at,
    )


def _visible_rows_for_boundary(
    row_index: _VisibleRowIndex,
    boundary: ReplayBoundary,
) -> tuple[Mapping[str, Any], ...]:
    prefix_end = bisect_right(row_index.timestamps, boundary.as_of_time)
    if not row_index.has_delayed_availability:
        return row_index.frozen_rows[:prefix_end]
    replay_rows = frozen_rows(
        [
            row_index.rows[index].frozen_row
            for index in range(prefix_end)
            if _row_available_for_boundary(row_index.rows[index], boundary)
        ]
    )
    return replay_rows


def _has_delayed_availability(rows: Sequence[_VisibleRow]) -> bool:
    return any(
        row.timestamp is not None
        and row.available_at is not None
        and row.available_at > row.timestamp
        for row in rows
    )


def _timestamps_by_symbol_from_rows(
    rows: Sequence[_VisibleRow],
) -> Mapping[str, tuple[datetime, ...]]:
    timestamps_by_symbol: dict[str, list[datetime]] = {}
    for item in rows:
        symbol = item.row.get("symbol")
        if isinstance(symbol, str) and item.timestamp is not None:
            timestamps_by_symbol.setdefault(symbol, []).append(item.timestamp)
    return {
        symbol: tuple(sorted(dict.fromkeys(timestamps)))
        for symbol, timestamps in timestamps_by_symbol.items()
    }


def _row_available_for_boundary(row: _VisibleRow, boundary: ReplayBoundary) -> bool:
    if row.available_at is not None:
        return row.available_at <= boundary.decision_time

    # `available_at` is a mandatory row-contract field: a row reaching replay without
    # a usable one has already failed the contract, and the run fails at the
    # row-contract gate with a clear data-quality message. Treat such a row as
    # visible here so a provenance defect is never misreported as hidden lookahead.
    return True


def _decision_matches_boundary(decision: StrategyDecision, boundary: ReplayBoundary) -> bool:
    if decision.as_of_time != boundary.as_of_time:
        return False
    if boundary.symbols and decision.instrument.symbol not in boundary.symbols:
        return False
    return True


def _is_aware_datetime(value: object) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )
