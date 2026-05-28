from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from quant_strategies.boundary import frozen_params, frozen_rows
from quant_strategies.datetime_utils import parse_aware_datetime
from quant_strategies.decisions import StrategyDecision, validate_decision_output


@dataclass(frozen=True)
class LookaheadCheckResult:
    passed: bool
    violations: tuple[str, ...] = ()


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
    rows: Sequence[Mapping[str, Any]],
    params: Mapping[str, Any],
    baseline_decisions: list[StrategyDecision],
    strategy_id: str,
) -> LookaheadCheckResult:
    row_index = _visible_row_index(rows)
    visible_rows_cache: dict[tuple[datetime, datetime], tuple[Mapping[str, Any], ...]] = {}
    replay_decision_ids_cache: dict[tuple[datetime, datetime], frozenset[str | None]] = {}
    replay_params = frozen_params(params)
    for baseline in baseline_decisions:
        cache_key = (baseline.as_of_time, baseline.decision_time)
        replay_decision_ids = replay_decision_ids_cache.get(cache_key)
        if replay_decision_ids is None:
            replay_rows = _visible_rows_for_decision(
                row_index,
                baseline,
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

            replay_decisions, violations = validate_decision_output(
                replay_output,
                strategy_id=strategy_id,
            )
            if violations:
                return LookaheadCheckResult(
                    passed=False,
                    violations=(f"hidden_lookahead_check_failed: {'; '.join(violations)}",),
                )
            replay_decision_ids = frozenset(replay.decision_id for replay in replay_decisions)
            replay_decision_ids_cache[cache_key] = replay_decision_ids

        if baseline.decision_id not in replay_decision_ids:
            return LookaheadCheckResult(
                passed=False,
                violations=("hidden_lookahead_detected",),
            )

    return LookaheadCheckResult(passed=True)


def _visible_row_index(rows: Sequence[Mapping[str, Any]]) -> _VisibleRowIndex:
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


def _visible_rows_for_decision(
    row_index: _VisibleRowIndex,
    decision: StrategyDecision,
    *,
    visible_rows_cache: dict[tuple[datetime, datetime], tuple[Mapping[str, Any], ...]],
) -> tuple[Mapping[str, Any], ...]:
    cache_key = (decision.as_of_time, decision.decision_time)
    cached = visible_rows_cache.get(cache_key)
    if cached is not None:
        return cached

    prefix_end = bisect_right(row_index.timestamps, decision.as_of_time)
    replay_rows = frozen_rows(
        [
            item.row
            for item in row_index.rows[:prefix_end]
            if _row_available_for_decision(item, decision)
        ]
    )
    visible_rows_cache[cache_key] = replay_rows
    return replay_rows


def _row_available_for_decision(row: _VisibleRow, decision: StrategyDecision) -> bool:
    if row.available_at is not None:
        return row.available_at <= decision.decision_time

    # Availability parse failures are evidence-quality problems. Replay falls
    # back to timestamp-only visibility so bad provenance does not masquerade as
    # a hidden-lookahead strategy failure.
    return True
