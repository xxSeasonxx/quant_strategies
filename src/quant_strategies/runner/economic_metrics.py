from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from types import MappingProxyType
from typing import Any

from quant_strategies.core.serialization import json_safe_value

SUMMARY_SCHEMA_VERSION = "quant_strategies.runner.economic_metrics/v1"
SLICES_SCHEMA_VERSION = "quant_strategies.runner.economic_slices/v1"
BASIS = "engine_trade_ledger"


@dataclass(frozen=True)
class RunTrade:
    symbol: str
    side: str
    weight: float
    decision_time: datetime
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    exit_reason: str
    gross_return: float
    funding_return: float
    cost_return: float
    net_return: float
    decision_id: str | None


@dataclass(frozen=True)
class RunEconomics:
    schema_version: str
    basis: str
    trades: tuple[RunTrade, ...]
    trade_count: int
    winning_trade_count: int
    losing_trade_count: int
    flat_trade_count: int
    hit_rate: float | None
    average_trade_net: float | None
    average_win_net: float | None
    average_loss_net: float | None
    profit_factor: float | None
    cost_share_of_abs_gross: float | None
    funding_share_of_abs_gross: float | None
    by_symbol: Mapping[str, Mapping[str, Any]]
    by_direction: Mapping[str, Mapping[str, Any]]
    by_exit_reason: Mapping[str, Mapping[str, Any]]
    win_loss_distribution: Mapping[str, Any]

    def summary_payload(self) -> dict[str, Any]:
        return json_safe_value(
            {
                "schema_version": self.schema_version,
                "basis": self.basis,
                "trade_count": self.trade_count,
                "winning_trade_count": self.winning_trade_count,
                "losing_trade_count": self.losing_trade_count,
                "flat_trade_count": self.flat_trade_count,
                "hit_rate": self.hit_rate,
                "average_trade_net": self.average_trade_net,
                "average_win_net": self.average_win_net,
                "average_loss_net": self.average_loss_net,
                "profit_factor": self.profit_factor,
                "cost_share_of_abs_gross": self.cost_share_of_abs_gross,
                "funding_share_of_abs_gross": self.funding_share_of_abs_gross,
            }
        )

    def slices_payload(self) -> dict[str, Any]:
        return json_safe_value(
            {
                "schema_version": SLICES_SCHEMA_VERSION,
                "basis": self.basis,
                "by_symbol": self.by_symbol,
                "by_direction": self.by_direction,
                "by_exit_reason": self.by_exit_reason,
                "win_loss_distribution": self.win_loss_distribution,
            }
        )


def build_run_economics(engine_run: Any) -> RunEconomics:
    engine_summary = _engine_summary_with_trades(engine_run)
    completed_trades = trades_from_engine_summary(engine_summary)
    trade_result = trade_result_from_engine_summary(engine_summary)
    summary = summary_metrics(completed_trades, trade_result)
    slices = diagnostic_slices(completed_trades)

    return RunEconomics(
        schema_version=str(summary["schema_version"]),
        basis=str(summary["basis"]),
        trades=tuple(_run_trade_from_mapping(trade) for trade in completed_trades),
        trade_count=int(summary["trade_count"]),
        winning_trade_count=int(summary["winning_trade_count"]),
        losing_trade_count=int(summary["losing_trade_count"]),
        flat_trade_count=int(summary["flat_trade_count"]),
        hit_rate=_optional_float(summary["hit_rate"]),
        average_trade_net=_optional_float(summary["average_trade_net"]),
        average_win_net=_optional_float(summary["average_win_net"]),
        average_loss_net=_optional_float(summary["average_loss_net"]),
        profit_factor=_optional_float(summary["profit_factor"]),
        cost_share_of_abs_gross=_optional_float(summary["cost_share_of_abs_gross"]),
        funding_share_of_abs_gross=_optional_float(summary["funding_share_of_abs_gross"]),
        by_symbol=_dict_of_dicts(slices["by_symbol"]),
        by_direction=_dict_of_dicts(slices["by_direction"]),
        by_exit_reason=_dict_of_dicts(slices["by_exit_reason"]),
        win_loss_distribution=_mapping_proxy(slices["win_loss_distribution"]),
    )


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
            raise ValueError("engine diagnostic_trades length does not match trade_count")
    return copied_trades


def trade_result_from_engine_summary(engine: Mapping[str, Any]) -> dict[str, Any]:
    if "trade_result" not in engine:
        raise ValueError("engine summary is missing trade_result")
    trade_result = engine["trade_result"]
    if not isinstance(trade_result, Mapping):
        raise ValueError("engine trade_result must be a mapping")
    return dict(trade_result)


def _engine_summary_with_trades(engine_run: Any) -> dict[str, object]:
    source = getattr(engine_run, "screen_summary", None)
    validate_summary = getattr(engine_run, "validate_summary", None)
    if source is None and isinstance(validate_summary, Mapping):
        screening_result = validate_summary.get("screening_result")
        source = screening_result if isinstance(screening_result, Mapping) else None

    summary: dict[str, object] = {
        "passed": getattr(engine_run, "passed", None),
        "trade_count": _engine_trade_count(source),
    }
    trade_result = source.get("trade_result") if isinstance(source, Mapping) else None
    if isinstance(trade_result, Mapping):
        summary["trade_result"] = {
            "sum_signed_trade_activity_gross": trade_result.get("sum_signed_trade_activity_gross"),
            "sum_signed_trade_activity_funding": trade_result.get(
                "sum_signed_trade_activity_funding"
            ),
            "sum_signed_trade_activity_cost": trade_result.get("sum_signed_trade_activity_cost"),
            "sum_signed_trade_activity_net": trade_result.get("sum_signed_trade_activity_net"),
        }
    else:
        summary["trade_result"] = {
            "sum_signed_trade_activity_gross": None,
            "sum_signed_trade_activity_funding": None,
            "sum_signed_trade_activity_cost": None,
            "sum_signed_trade_activity_net": None,
        }

    trades = source.get("trades") if isinstance(source, Mapping) else None
    if isinstance(trades, list):
        summary["diagnostic_trades"] = trades
    return summary


def _engine_trade_count(source: object) -> int | None:
    if not isinstance(source, Mapping):
        return None
    value = source.get("trade_count")
    return int(value) if value is not None else None


def _run_trade_from_mapping(trade: Mapping[str, Any]) -> RunTrade:
    return RunTrade(
        symbol=_required_str_field(trade, "symbol"),
        side=_required_str_field(trade, "side"),
        weight=_required_trade_numeric_field(trade, "weight"),
        decision_time=_required_datetime_field(trade, "decision_time"),
        entry_time=_required_datetime_field(trade, "entry_time"),
        exit_time=_required_datetime_field(trade, "exit_time"),
        entry_price=_required_trade_numeric_field(trade, "entry_price"),
        exit_price=_required_trade_numeric_field(trade, "exit_price"),
        exit_reason=_required_str_field(trade, "exit_reason"),
        gross_return=_required_trade_numeric_field(trade, "gross_return"),
        funding_return=_required_trade_numeric_field(trade, "funding_return"),
        cost_return=_required_trade_numeric_field(trade, "cost_return"),
        net_return=_required_trade_numeric_field(trade, "net_return"),
        decision_id=_optional_str_field(trade, "decision_id"),
    )


def _required_str_field(trade: Mapping[str, Any], field: str) -> str:
    value = trade.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"trade {field} must be a non-empty string")
    return value


def _optional_str_field(trade: Mapping[str, Any], field: str) -> str | None:
    value = trade.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"trade {field} must be a non-empty string when provided")
    return value


def _required_datetime_field(trade: Mapping[str, Any], field: str) -> datetime:
    value = trade.get(field)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"trade {field} must be a valid ISO datetime") from exc
    else:
        raise ValueError(f"trade {field} must be a datetime or ISO datetime string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"trade {field} must be timezone-aware")
    return parsed


def _required_trade_numeric_field(trade: Mapping[str, Any], field: str) -> float:
    if field not in trade or trade[field] is None:
        raise ValueError(f"trade {field} is required")
    value = trade[field]
    if isinstance(value, bool) or isinstance(value, str | bytes):
        raise ValueError(f"trade {field} must be finite numeric")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"trade {field} must be finite numeric") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"trade {field} must be finite numeric")
    return numeric


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, str | bytes):
        raise ValueError("optional float value must be finite numeric")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("optional float value must be finite numeric") from exc
    if not math.isfinite(numeric):
        raise ValueError("optional float value must be finite numeric")
    return numeric


def _dict_of_dicts(value: object) -> Mapping[str, Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        raise ValueError("economic slices must be mappings")
    result: dict[str, Mapping[str, Any]] = {}
    for key, item in value.items():
        if not isinstance(item, Mapping):
            raise ValueError("economic slice entries must be mappings")
        result[str(key)] = MappingProxyType(dict(item))
    return MappingProxyType(result)


def _mapping_proxy(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("economic slice payload must be a mapping")
    return MappingProxyType(dict(value))


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
