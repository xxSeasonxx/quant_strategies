from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from quant_strategies.core.serialization import json_safe_value
from quant_strategies.evidence_semantics import replayable_from_artifacts_for_profile
from quant_strategies.runner.config import RunConfig
from quant_strategies.runner.economic_metrics import diagnostic_slices


SAMPLE_TRADE_FIELDS = (
    "decision_id",
    "symbol",
    "side",
    "decision_time",
    "entry_time",
    "exit_time",
    "exit_reason",
    "weight",
    "gross_return",
    "funding_return",
    "cost_return",
    "net_return",
)


def diagnostic_payload(
    *,
    config: RunConfig,
    engine: Mapping[str, Any],
    assessment_status: str,
    evidence_quality: Mapping[str, Any],
) -> dict[str, Any]:
    trades = _diagnostic_trades(engine)
    trade_result = _mapping_or_empty(engine.get("trade_result"))
    return {
        "strategy_id": config.strategy_id,
        "quick_checks": config.output.quick_checks,
        "artifact_profile": "diagnostic",
        "replayable_from_artifacts": replayable_from_artifacts_for_profile("diagnostic"),
        "trade_count": engine.get("trade_count"),
        "trade_result": trade_result,
        "assessment_status": assessment_status,
        "evidence_quality": json_safe_value(dict(evidence_quality)),
        "by_symbol": _group(trades, "symbol"),
        "by_direction": _group(trades, "side"),
        "by_exit_reason": _group(trades, "exit_reason"),
        "holding_period": _holding_period(trades),
        "concentration": _concentration(trades),
        "cost_funding_breakdown": _cost_funding_breakdown(trade_result),
        "economic_slices": diagnostic_slices(trades),
        "sample_trades": _sample_trades(trades, config.output.diagnostic_sample_trades),
    }


def write_diagnostics(result_dir: Path, payload: Mapping[str, Any]) -> Path:
    path = result_dir / "diagnostics.json"
    path.write_text(
        json.dumps(
            json_safe_value(dict(payload)),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )
    return path


def _diagnostic_trades(engine: Mapping[str, Any]) -> list[dict[str, Any]]:
    trades = engine.get("diagnostic_trades")
    if not isinstance(trades, Sequence) or isinstance(trades, str | bytes):
        return []
    return [dict(item) for item in trades if isinstance(item, Mapping)]


def _mapping_or_empty(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _group(trades: Sequence[Mapping[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    grouped: defaultdict[str, dict[str, Any]] = defaultdict(_empty_group)
    for trade in trades:
        name = str(trade.get(key, "unknown"))
        grouped[name]["count"] += 1
        grouped[name]["gross"] += _float_value(trade.get("gross_return"))
        grouped[name]["funding"] += _float_value(trade.get("funding_return"))
        grouped[name]["cost"] += _float_value(trade.get("cost_return"))
        grouped[name]["net"] += _float_value(trade.get("net_return"))
    return dict(sorted(grouped.items()))


def _empty_group() -> dict[str, Any]:
    return {"count": 0, "gross": 0.0, "funding": 0.0, "cost": 0.0, "net": 0.0}


def _holding_period(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    seconds = [
        elapsed
        for trade in trades
        if (elapsed := _elapsed_seconds(trade.get("entry_time"), trade.get("exit_time"))) is not None
    ]
    if not seconds:
        return {
            "count": 0,
            "min_seconds": None,
            "median_seconds": None,
            "max_seconds": None,
            "average_seconds": None,
        }

    ordered = sorted(seconds)
    mid = len(ordered) // 2
    median = (
        ordered[mid]
        if len(ordered) % 2
        else (ordered[mid - 1] + ordered[mid]) / 2.0
    )
    return {
        "count": len(seconds),
        "min_seconds": min(seconds),
        "median_seconds": median,
        "max_seconds": max(seconds),
        "average_seconds": sum(seconds) / len(seconds),
    }


def _elapsed_seconds(entry_time: object, exit_time: object) -> float | None:
    entry = _as_datetime(entry_time)
    exit_ = _as_datetime(exit_time)
    if entry is None or exit_ is None:
        return None
    return float((exit_ - entry).total_seconds())


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _concentration(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    nets = sorted((_float_value(trade.get("net_return")) for trade in trades), reverse=True)
    return {
        "top_winner_net": nets[0] if nets else None,
        "top_loser_net": nets[-1] if nets else None,
        "top_5_winners_net": sum(nets[:5]),
        "top_5_losers_net": sum(sorted(nets)[:5]),
    }


def _cost_funding_breakdown(trade_result: Mapping[str, Any]) -> dict[str, Any]:
    gross = trade_result.get("sum_signed_trade_activity_gross")
    funding = trade_result.get("sum_signed_trade_activity_funding")
    cost = trade_result.get("sum_signed_trade_activity_cost")
    net = trade_result.get("sum_signed_trade_activity_net")
    gross_float = _float_value(gross)
    return {
        "gross": gross,
        "funding": funding,
        "cost": cost,
        "net": net,
        "cost_fraction_of_abs_gross": (
            None if gross_float == 0.0 else _float_value(cost) / abs(gross_float)
        ),
    }


def _sample_trades(trades: Sequence[Mapping[str, Any]], cap: int) -> dict[str, list[dict[str, Any]]]:
    winners = sorted(trades, key=lambda item: _float_value(item.get("net_return")), reverse=True)
    losers = sorted(trades, key=lambda item: _float_value(item.get("net_return")))
    return {
        "largest_winners": [_sample_trade_payload(item) for item in winners[:cap]],
        "largest_losers": [_sample_trade_payload(item) for item in losers[:cap]],
    }


def _sample_trade_payload(trade: Mapping[str, Any]) -> dict[str, Any]:
    return {field: trade.get(field) for field in SAMPLE_TRADE_FIELDS}


def _float_value(value: object) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
