from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from quant_strategies.boundary import frozen_params, frozen_rows
from quant_strategies.decisions import StrategyDecision, validate_decision_output
from quant_strategies.validation.datetime_utils import parse_aware_datetime


@dataclass(frozen=True)
class LookaheadCheckResult:
    passed: bool
    violations: tuple[str, ...] = ()


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
    for baseline in baseline_decisions:
        replay_rows = [row for row in rows if _row_visible_for_decision(row, baseline)]
        try:
            replay_output = generate_decisions(frozen_rows(replay_rows), frozen_params(params))
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


def _row_visible_for_decision(row: Mapping[str, Any], decision: StrategyDecision) -> bool:
    timestamp, _ = parse_aware_datetime(row.get("timestamp"))
    if timestamp is None or timestamp > decision.as_of_time:
        return False

    available_value = row.get("available_at")
    if available_value is not None:
        available_at, _ = parse_aware_datetime(available_value)
        if available_at is not None:
            return available_at <= decision.decision_time

    return True


def _decision_key(decision: StrategyDecision) -> str:
    return json.dumps(
        {
            "strategy_id": decision.strategy_id,
            "instrument": decision.instrument.model_dump(mode="json"),
            "decision_time": decision.decision_time.isoformat(),
            "as_of_time": decision.as_of_time.isoformat(),
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
