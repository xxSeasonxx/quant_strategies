from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from quant_strategies.decisions import (
    ExitPolicy,
    InstrumentRef,
    PositionTarget,
    StrategyDecision,
)
from quant_strategies.causality import check_hidden_lookahead
from quant_strategies.validation.lookahead import check_hidden_lookahead as legacy_check_hidden_lookahead


AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
FUTURE = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)


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


def decision(size: float = 1.0) -> StrategyDecision:
    return StrategyDecision(
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


def test_validation_lookahead_reexports_causality_checker():
    assert legacy_check_hidden_lookahead is check_hidden_lookahead


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
