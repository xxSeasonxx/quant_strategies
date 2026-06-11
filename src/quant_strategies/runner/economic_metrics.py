from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from types import MappingProxyType
from typing import Any

from quant_strategies.core.portfolio_foundation import (
    INITIAL_EQUITY,
    RoundTrip,
    RunPortfolioFoundation,
)
from quant_strategies.core.serialization import json_safe_value

SUMMARY_SCHEMA_VERSION = "quant_strategies.runner.economic_metrics/v1"
SLICES_SCHEMA_VERSION = "quant_strategies.runner.economic_slices/v1"
BASIS = "portfolio_book_round_trip_attribution"


@dataclass(frozen=True)
class RunTrade:
    """One completed netted-book round-trip, attributed as a fraction of NAV.

    The returns are the realized cash attribution of the single book walk divided by
    the book's standing NAV base, so ``net_return = gross_return + funding_return -
    cost_return`` and the ledger sums reconcile with the NAV path's realized PnL
    (design D4 / `quick-run-economics`). This is an attribution view, never an
    independent scored quantity.
    """

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
    impact_return: float
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
    impact_share_of_abs_gross: float | None
    sum_gross_return: float
    sum_funding_return: float
    sum_cost_return: float
    sum_impact_return: float
    sum_net_return: float
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
                "impact_share_of_abs_gross": self.impact_share_of_abs_gross,
                "sum_gross_return": self.sum_gross_return,
                "sum_funding_return": self.sum_funding_return,
                "sum_cost_return": self.sum_cost_return,
                "sum_impact_return": self.sum_impact_return,
                "sum_net_return": self.sum_net_return,
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


def build_run_economics(foundation: RunPortfolioFoundation) -> RunEconomics:
    """Derive the per-trade ledger from the authoritative portfolio book walk.

    The round-trips come from the realistic-cost scenario's single causal walk
    (`foundation.ledger`); there is no separate per-trade summation that could
    disagree with the NAV path.
    """
    trades = tuple(_run_trade_from_round_trip(trip) for trip in foundation.ledger.round_trips)
    nets = [trade.net_return for trade in trades]
    wins = [net for net in nets if net > 0]
    losses = [net for net in nets if net < 0]
    flats = [net for net in nets if net == 0]
    sum_gross = sum(trade.gross_return for trade in trades)
    sum_funding = sum(trade.funding_return for trade in trades)
    sum_cost = sum(trade.cost_return for trade in trades)
    sum_impact = sum(trade.impact_return for trade in trades)
    sum_net = sum(nets)
    return RunEconomics(
        schema_version=SUMMARY_SCHEMA_VERSION,
        basis=BASIS,
        trades=trades,
        trade_count=len(trades),
        winning_trade_count=len(wins),
        losing_trade_count=len(losses),
        flat_trade_count=len(flats),
        hit_rate=_ratio(len(wins), len(nets)),
        average_trade_net=_average(nets),
        average_win_net=_average(wins),
        average_loss_net=_average(losses),
        profit_factor=_profit_factor(wins, losses),
        cost_share_of_abs_gross=_share_of_abs_gross(sum_cost, sum_gross),
        funding_share_of_abs_gross=_share_of_abs_gross(sum_funding, sum_gross),
        impact_share_of_abs_gross=_share_of_abs_gross(sum_impact, sum_gross),
        sum_gross_return=sum_gross,
        sum_funding_return=sum_funding,
        sum_cost_return=sum_cost,
        sum_impact_return=sum_impact,
        sum_net_return=sum_net,
        by_symbol=_group_summaries(trades, lambda trade: trade.symbol),
        by_direction=_group_summaries(trades, lambda trade: trade.side),
        by_exit_reason=_group_summaries(trades, lambda trade: trade.exit_reason),
        win_loss_distribution=_mapping_proxy(_win_loss_distribution(nets)),
    )


def _run_trade_from_round_trip(trip: RoundTrip) -> RunTrade:
    return RunTrade(
        symbol=trip.symbol,
        side=trip.direction,
        weight=abs(trip.entry_weight),
        decision_time=trip.decision_time,
        entry_time=trip.entry_time,
        exit_time=trip.exit_time,
        entry_price=trip.entry_mark,
        exit_price=trip.exit_mark,
        exit_reason=trip.exit_reason,
        gross_return=trip.gross_cash / INITIAL_EQUITY,
        funding_return=trip.funding_cash / INITIAL_EQUITY,
        cost_return=trip.cost_cash / INITIAL_EQUITY,
        impact_return=trip.impact_cost_cash / INITIAL_EQUITY,
        net_return=trip.realized_pnl / INITIAL_EQUITY,
        decision_id=trip.decision_id,
    )


def _group_summaries(
    trades: Sequence[RunTrade],
    key: Any,
) -> Mapping[str, Mapping[str, Any]]:
    grouped: defaultdict[str, list[RunTrade]] = defaultdict(list)
    for trade in trades:
        grouped[str(key(trade))].append(trade)
    result: dict[str, Mapping[str, Any]] = {}
    for name, group_trades in sorted(grouped.items(), key=lambda item: item[0]):
        result[name] = MappingProxyType(_group_summary(group_trades))
    return MappingProxyType(result)


def _group_summary(trades: Sequence[RunTrade]) -> dict[str, Any]:
    nets = [trade.net_return for trade in trades]
    wins = [net for net in nets if net > 0]
    losses = [net for net in nets if net < 0]
    flats = [net for net in nets if net == 0]
    return {
        "count": len(nets),
        "winning_trade_count": len(wins),
        "losing_trade_count": len(losses),
        "flat_trade_count": len(flats),
        "gross_sum": sum(trade.gross_return for trade in trades),
        "funding_sum": sum(trade.funding_return for trade in trades),
        "cost_sum": sum(trade.cost_return for trade in trades),
        "impact_sum": sum(trade.impact_return for trade in trades),
        "net_sum": sum(nets),
        "average_trade_net": _average(nets),
        "hit_rate": _ratio(len(wins), len(nets)),
        "average_win_net": _average(wins),
        "average_loss_net": _average(losses),
    }


def _win_loss_distribution(nets: Sequence[float]) -> dict[str, Any]:
    wins = [net for net in nets if net > 0]
    losses = [net for net in nets if net < 0]
    return {
        "largest_win_net": max(wins) if wins else None,
        "largest_loss_net": min(losses) if losses else None,
        "median_trade_net": median(nets) if nets else None,
        "sum_positive_net": sum(wins),
        "sum_negative_net": sum(losses),
    }


def _mapping_proxy(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


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
