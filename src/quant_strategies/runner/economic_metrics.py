from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import median
from typing import Any

from quant_strategies.core.serialization import json_safe_value

SUMMARY_SCHEMA_VERSION = "quant_strategies.runner.economic_metrics/v1"
SLICES_SCHEMA_VERSION = "quant_strategies.runner.economic_slices/v1"
BASIS = "engine_trade_ledger"


def summary_metrics(
    trades: Sequence[Mapping[str, Any]],
    trade_result: Mapping[str, Any],
) -> dict[str, Any]:
    nets = [_net_return(trade) for trade in trades]
    wins = [net for net in nets if net > 0]
    losses = [net for net in nets if net < 0]
    flats = [net for net in nets if net == 0]
    gross = _float_or_none(trade_result.get("sum_signed_trade_activity_gross"))
    cost = _float_or_none(trade_result.get("sum_signed_trade_activity_cost"))
    funding = _float_or_none(trade_result.get("sum_signed_trade_activity_funding"))

    payload = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "basis": BASIS,
        "trade_count": len(nets),
        "winning_trade_count": len(wins),
        "losing_trade_count": len(losses),
        "flat_trade_count": len(flats),
        "hit_rate": _ratio(len(wins), len(nets)),
        "average_trade_net": _average(nets),
        "average_win_net": _average(wins),
        "average_loss_net": _average(losses),
        "profit_factor": _profit_factor(wins, losses),
        "cost_share_of_abs_gross": _share_of_abs_gross(cost, gross),
        "funding_share_of_abs_gross": _share_of_abs_gross(funding, gross),
    }
    return json_safe_value(payload)


def diagnostic_slices(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    payload = {
        "schema_version": SLICES_SCHEMA_VERSION,
        "basis": BASIS,
        "by_symbol": _group_summaries(trades, "symbol"),
        "by_direction": _group_summaries(trades, "side"),
        "by_exit_reason": _group_summaries(trades, "exit_reason"),
        "win_loss_distribution": _win_loss_distribution(trades),
    }
    return json_safe_value(payload)


def trades_from_engine_summary(engine: Mapping[str, Any]) -> list[dict[str, Any]]:
    trades = engine.get("diagnostic_trades")
    if not isinstance(trades, Sequence) or isinstance(trades, str | bytes):
        return []
    return [dict(item) for item in trades if isinstance(item, Mapping)]


def trade_result_from_engine_summary(engine: Mapping[str, Any]) -> dict[str, Any]:
    trade_result = engine.get("trade_result")
    return dict(trade_result) if isinstance(trade_result, Mapping) else {}


def _group_summaries(
    trades: Sequence[Mapping[str, Any]],
    key: str,
) -> dict[str, dict[str, Any]]:
    grouped: defaultdict[str, list[float]] = defaultdict(list)
    for trade in trades:
        grouped[str(trade.get(key, "unknown"))].append(_net_return(trade))
    return {
        name: _group_summary(nets)
        for name, nets in sorted(grouped.items(), key=lambda item: item[0])
    }


def _group_summary(nets: Sequence[float]) -> dict[str, Any]:
    wins = [net for net in nets if net > 0]
    losses = [net for net in nets if net < 0]
    flats = [net for net in nets if net == 0]
    return {
        "count": len(nets),
        "winning_trade_count": len(wins),
        "losing_trade_count": len(losses),
        "flat_trade_count": len(flats),
        "net_sum": sum(nets),
        "average_trade_net": _average(nets),
        "hit_rate": _ratio(len(wins), len(nets)),
        "average_win_net": _average(wins),
        "average_loss_net": _average(losses),
    }


def _win_loss_distribution(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    nets = [_net_return(trade) for trade in trades]
    wins = [net for net in nets if net > 0]
    losses = [net for net in nets if net < 0]
    return {
        "largest_win_net": max(wins) if wins else None,
        "largest_loss_net": min(losses) if losses else None,
        "median_trade_net": median(nets) if nets else None,
        "sum_positive_net": sum(wins),
        "sum_negative_net": sum(losses),
    }


def _net_return(trade: Mapping[str, Any]) -> float:
    value = _float_or_none(trade.get("net_return"))
    return 0.0 if value is None else value


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _average(values: Sequence[float]) -> float | None:
    return None if not values else sum(values) / len(values)


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _profit_factor(wins: Sequence[float], losses: Sequence[float]) -> float | None:
    if not wins and not losses:
        return None
    if not losses:
        return None
    return sum(wins) / abs(sum(losses))


def _share_of_abs_gross(value: float | None, gross: float | None) -> float | None:
    if value is None or gross is None or gross == 0.0:
        return None
    return value / abs(gross)
