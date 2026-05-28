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


@dataclass(frozen=True)
class LookaheadCheckResult:
    passed: bool
    violations: tuple[str, ...] = ()


ReplayMode = Literal["emitted", "strict"]


@dataclass(frozen=True)
class ReplayBoundary:
    as_of_time: datetime
    decision_time: datetime
    expected_decision_ids: frozenset[str | None] = frozenset()
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
    mode: ReplayMode = "emitted",
    boundaries: Sequence[ReplayBoundary] | None = None,
) -> LookaheadCheckResult:
    if mode == "strict" and boundaries is None:
        return LookaheadCheckResult(
            passed=False,
            violations=(
                "hidden_lookahead_check_failed: strict replay requires caller-supplied boundaries",
            ),
        )
    replay_boundaries = tuple(
        boundaries if boundaries is not None else _emitted_boundaries(baseline_decisions)
    )
    if mode == "strict" and not replay_boundaries:
        return LookaheadCheckResult(
            passed=False,
            violations=(
                "hidden_lookahead_check_failed: strict replay requires at least one boundary",
            ),
        )

    row_index = _visible_row_index(rows)
    visible_rows_cache: dict[tuple[datetime, datetime], tuple[Mapping[str, Any], ...]] = {}
    replay_decision_ids_cache: dict[tuple[datetime, datetime], frozenset[str | None]] = {}
    replay_decisions_cache: dict[tuple[datetime, datetime], tuple[StrategyDecision, ...]] = {}
    replay_params = frozen_params(params)
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
                return LookaheadCheckResult(
                    passed=False,
                    violations=(f"hidden_lookahead_check_failed: SystemExit: {exc}",),
                )
            except Exception as exc:
                return LookaheadCheckResult(
                    passed=False,
                    violations=(f"hidden_lookahead_check_failed: {type(exc).__name__}: {exc}",),
                )

            parsed_decisions, violations = validate_decision_output(
                replay_output,
                strategy_id=strategy_id,
            )
            if violations:
                return LookaheadCheckResult(
                    passed=False,
                    violations=(f"hidden_lookahead_check_failed: {'; '.join(violations)}",),
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
                violations=("hidden_lookahead_detected",),
            )
        if mode == "strict":
            scoped_decision_ids = frozenset(
                replay.decision_id
                for replay in replay_decisions
                if _decision_matches_boundary(replay, boundary)
            )
            if not scoped_decision_ids.issubset(boundary.expected_decision_ids):
                return LookaheadCheckResult(
                    passed=False,
                    violations=("hidden_lookahead_suppression_detected",),
                )

    return LookaheadCheckResult(passed=True)


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
