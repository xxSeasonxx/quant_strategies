from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from quant_strategies.core.serialization import json_safe_value

if TYPE_CHECKING:
    from quant_strategies.runner.economic_metrics import RunEconomics

EngineMode = Literal["screen", "gate"]


@dataclass(frozen=True)
class EngineRun:
    """Book-derived run summary for the quick-run artifacts.

    The single causal netted book (`core.portfolio_foundation`) is the only PnL/NAV
    computation; this DTO carries the feasibility verdict and the book's realized
    attribution totals (derived from the same walk as the per-trade ledger) for the
    ``summary.json`` engine block. The old per-trade linear-sum scorer was retired by
    the ``portfolio-book-spine`` change.
    """

    mode: EngineMode
    feasible: bool
    trade_count: int
    nav_attribution: dict[str, float]
    diagnostic_trades: tuple[dict[str, Any], ...]

    @property
    def passed(self) -> bool:
        return self.feasible


def evaluate_foundation(
    economics: RunEconomics,
    *,
    feasible: bool,
    mode: EngineMode,
    include_diagnostics: bool = False,
) -> EngineRun:
    """Summarize the authoritative book walk for the runner's completion artifacts."""
    diagnostic_trades: tuple[dict[str, Any], ...] = ()
    if include_diagnostics:
        diagnostic_trades = tuple(_trade_payload(trade) for trade in economics.trades)
    return EngineRun(
        mode=mode,
        feasible=feasible,
        trade_count=economics.trade_count,
        nav_attribution={
            "sum_gross_return": economics.sum_gross_return,
            "sum_funding_return": economics.sum_funding_return,
            "sum_cost_return": economics.sum_cost_return,
            "sum_impact_return": economics.sum_impact_return,
            "sum_net_return": economics.sum_net_return,
        },
        diagnostic_trades=diagnostic_trades,
    )


def _trade_payload(trade: Any) -> dict[str, Any]:
    return json_safe_value(
        {
            "symbol": trade.symbol,
            "side": trade.side,
            "weight": trade.weight,
            "decision_time": trade.decision_time,
            "entry_time": trade.entry_time,
            "exit_time": trade.exit_time,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "exit_reason": trade.exit_reason,
            "gross_return": trade.gross_return,
            "funding_return": trade.funding_return,
            "cost_return": trade.cost_return,
            "impact_return": trade.impact_return,
            "net_return": trade.net_return,
            "decision_id": trade.decision_id,
        }
    )
