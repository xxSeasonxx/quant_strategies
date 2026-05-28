from __future__ import annotations

import json
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
    replay_params = frozen_params(params)
    for baseline in baseline_decisions:
        replay_rows = _visible_rows_for_decision(
            row_index,
            baseline,
            visible_rows_cache=visible_rows_cache,
        )
        try:
            replay_output = generate_decisions(replay_rows, replay_params)
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

        replay_by_key: dict[str, StrategyDecision] = {}
        for replay in replay_decisions:
            key = _decision_key(replay)
            if key in replay_by_key:
                return LookaheadCheckResult(
                    passed=False,
                    violations=("hidden_lookahead_check_failed: duplicate replay decision key",),
                )
            replay_by_key[key] = replay

        replay = replay_by_key.get(_decision_key(baseline))
        if replay is None or _decision_fingerprint(replay) != _decision_fingerprint(baseline):
            return LookaheadCheckResult(
                passed=False,
                violations=("hidden_lookahead_detected",),
            )

    return LookaheadCheckResult(passed=True)


def _visible_row_index(rows: Sequence[Mapping[str, Any]]) -> tuple[_VisibleRow, ...]:
    return tuple(_visible_row(row) for row in rows)


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
    row_index: tuple[_VisibleRow, ...],
    decision: StrategyDecision,
    *,
    visible_rows_cache: dict[tuple[datetime, datetime], tuple[Mapping[str, Any], ...]],
) -> tuple[Mapping[str, Any], ...]:
    cache_key = (decision.as_of_time, decision.decision_time)
    cached = visible_rows_cache.get(cache_key)
    if cached is not None:
        return cached

    replay_rows = frozen_rows(
        [
            item.row
            for item in row_index
            if _row_visible_for_decision(item, decision)
        ]
    )
    visible_rows_cache[cache_key] = replay_rows
    return replay_rows


def _row_visible_for_decision(row: _VisibleRow, decision: StrategyDecision) -> bool:
    if row.timestamp is None or row.timestamp > decision.as_of_time:
        return False

    if row.available_at is not None:
        return row.available_at <= decision.decision_time

    # Availability parse failures are evidence-quality problems. Replay falls
    # back to timestamp-only visibility so bad provenance does not masquerade as
    # a hidden-lookahead strategy failure.
    return True


def _decision_key(decision: StrategyDecision) -> str:
    return json.dumps(
        {
            "decision_id": decision.decision_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _decision_fingerprint(decision: StrategyDecision) -> str:
    return json.dumps(
        decision.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
