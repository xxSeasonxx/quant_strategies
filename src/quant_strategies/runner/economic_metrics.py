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
    gross = _required_numeric_field(trade_result, "sum_signed_trade_activity_gross")
    cost = _required_numeric_field(trade_result, "sum_signed_trade_activity_cost")
    funding = _required_numeric_field(trade_result, "sum_signed_trade_activity_funding")

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
    if "diagnostic_trades" not in engine:
        raise ValueError("engine summary is missing diagnostic_trades")
    trades = engine["diagnostic_trades"]
    if not isinstance(trades, Sequence) or isinstance(trades, str | bytes):
        raise ValueError("engine diagnostic_trades must be a non-string sequence")
    copied_trades = []
    for index, item in enumerate(trades):
        if not isinstance(item, Mapping):
            raise ValueError(f"engine diagnostic_trades[{index}] must be a mapping")
        copied_trades.append(dict(item))
    trade_count = engine.get("trade_count")
    if trade_count is not None:
        if isinstance(trade_count, bool):
            raise ValueError("engine trade_count must be an integer when provided")
        if isinstance(trade_count, int):
            expected_trade_count = trade_count
        elif isinstance(trade_count, float) and trade_count.is_integer():
            expected_trade_count = int(trade_count)
        else:
            raise ValueError("engine trade_count must be an integer when provided")
        if expected_trade_count != len(copied_trades):
            raise ValueError(
                "engine diagnostic_trades length does not match trade_count"
            )
    return copied_trades


def trade_result_from_engine_summary(engine: Mapping[str, Any]) -> dict[str, Any]:
    if "trade_result" not in engine:
        raise ValueError("engine summary is missing trade_result")
    trade_result = engine["trade_result"]
    if not isinstance(trade_result, Mapping):
        raise ValueError("engine trade_result must be a mapping")
    return dict(trade_result)


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
    if "net_return" not in trade:
        raise ValueError("trade is missing net_return")
    value = trade["net_return"]
    if isinstance(value, bool) or isinstance(value, str | bytes) or value is None:
        raise ValueError("trade net_return must be finite numeric")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("trade net_return must be finite numeric") from exc
    if not math.isfinite(numeric):
        raise ValueError("trade net_return must be finite numeric")
    return numeric


def _required_numeric_field(trade_result: Mapping[str, Any], field: str) -> float:
    if field not in trade_result or trade_result[field] is None:
        raise ValueError(f"trade_result {field} is required")
    value = trade_result[field]
    if isinstance(value, bool) or isinstance(value, str | bytes):
        raise ValueError(f"trade_result {field} must be finite numeric")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"trade_result {field} must be finite numeric") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"trade_result {field} must be finite numeric")
    return numeric


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


def _share_of_abs_gross(value: float, gross: float) -> float | None:
    if gross == 0.0:
        return None
    return value / abs(gross)
