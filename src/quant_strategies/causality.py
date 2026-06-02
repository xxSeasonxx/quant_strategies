from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from quant_strategies.boundary import frozen_params, frozen_rows
from quant_strategies.data_contract import NormalizedRows
from quant_strategies.datetime_utils import parse_aware_datetime
from quant_strategies.decisions import StrategyDecision, validate_decision_output


ReplayMode = Literal["emitted", "strict"]


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
class _VisibleRow:
    row: Mapping[str, Any]
    timestamp: datetime | None
    available_at: datetime | None


@dataclass(frozen=True)
class _VisibleRowIndex:
    rows: tuple[_VisibleRow, ...]
    timestamps: tuple[datetime, ...]


DecisionGenerator = Callable[
    [Sequence[Mapping[str, Any]], Mapping[str, Any]],
    object,
]


def check_hidden_lookahead(
    generate_decisions: DecisionGenerator,
    *,
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
    params: Mapping[str, Any],
    baseline_decisions: list[StrategyDecision],
    strategy_id: str,
    mode: ReplayMode = "strict",
    boundaries: Sequence[ReplayBoundary] | None = None,
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
    deterministic_failure = _deterministic_replay_failure(
        generate_decisions,
        rows=rows,
        params=replay_params,
        baseline_decisions=baseline_decisions,
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

    row_index = _visible_row_index(rows)
    visible_rows_cache: dict[tuple[datetime, datetime], tuple[Mapping[str, Any], ...]] = {}
    replay_decision_ids_cache: dict[tuple[datetime, datetime], frozenset[str | None]] = {}
    replay_decisions_cache: dict[tuple[datetime, datetime], tuple[StrategyDecision, ...]] = {}
    skipped_probe_reasons: list[str] = []
    for boundary in replay_boundaries:
        cache_key = (boundary.as_of_time, boundary.decision_time)
        replay_decisions = replay_decisions_cache.get(cache_key)
        if replay_decisions is None:
            replay_rows = _visible_rows_for_boundary(
                row_index,
                boundary,
                visible_rows_cache=visible_rows_cache,
            )
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
    if _decision_payloads(replay_decisions) != _decision_payloads(baseline_decisions):
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


def _exception_reason(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


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
        timestamps=tuple(item.timestamp for item in ordered_rows if item.timestamp is not None),
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
                timestamp=timestamp,
                available_at=available_at if _is_aware_datetime(available_at) else None,
            )
        )
    ordered_rows = tuple(sorted(visible_rows, key=lambda item: item.timestamp))
    return _VisibleRowIndex(
        rows=ordered_rows,
        timestamps=tuple(item.timestamp for item in ordered_rows if item.timestamp is not None),
    )


def _visible_row(row: Mapping[str, Any]) -> _VisibleRow:
    timestamp, _ = parse_aware_datetime(row.get("timestamp"))
    available_at = None
    available_value = row.get("available_at")
    if available_value is not None:
        available_at, _ = parse_aware_datetime(available_value)

    return _VisibleRow(
        row=row,
        timestamp=timestamp,
        available_at=available_at,
    )


def _visible_rows_for_boundary(
    row_index: _VisibleRowIndex,
    boundary: ReplayBoundary,
    *,
    visible_rows_cache: dict[tuple[datetime, datetime], tuple[Mapping[str, Any], ...]],
) -> tuple[Mapping[str, Any], ...]:
    cache_key = (boundary.as_of_time, boundary.decision_time)
    cached = visible_rows_cache.get(cache_key)
    if cached is not None:
        return cached

    prefix_end = bisect_right(row_index.timestamps, boundary.as_of_time)
    replay_rows = frozen_rows(
        [
            item.row
            for item in row_index.rows[:prefix_end]
            if _row_available_for_boundary(item, boundary)
        ]
    )
    visible_rows_cache[cache_key] = replay_rows
    return replay_rows


def _row_available_for_boundary(row: _VisibleRow, boundary: ReplayBoundary) -> bool:
    if row.available_at is not None:
        return row.available_at <= boundary.decision_time

    # Availability parse failures are evidence-quality problems. Replay falls
    # back to timestamp-only visibility so bad provenance does not masquerade as
    # a hidden-lookahead strategy failure.
    return True


def _decision_matches_boundary(decision: StrategyDecision, boundary: ReplayBoundary) -> bool:
    if decision.as_of_time != boundary.as_of_time:
        return False
    if boundary.symbols and decision.instrument.symbol not in boundary.symbols:
        return False
    return True


def _is_aware_datetime(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
