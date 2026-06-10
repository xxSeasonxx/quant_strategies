"""Project one spine ``BookWalkResult`` into the evaluation observable contract.

The single causal netted portfolio book (``core/portfolio_foundation.py``) is the only
money model on every surface (design D9). For each ``(window, scenario)`` evaluation
runs the book once over that fold's rows at the scenario's costs/fills, and this module
derives, from the resulting NAV path and round-trip ledger:

- the per-fold ``portfolio_path`` frame (the OOS per-period return series the typed
  ``FoldReturnSeries`` and the on-disk Parquet trace both read);
- the completed-scenario metric payload (the required NAV/return/funding scalars plus
  the annualized risk family the cadence trust boundary later nulls);
- the ``trades``, ``target_positions``, ``target_exposure_summary`` and
  ``funding_cashflows`` trace frames.

It adds no deflated/significance statistics (PSR/DSR/PBO); significance is the
consumer's responsibility.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from quant_strategies.core.portfolio_foundation import (
    BookWalkResult,
    FundingEvent,
    RoundTrip,
)
from quant_strategies.evaluation.metrics import (
    SHARED_ACCOUNTING_MODEL,
    MetricValue,
)
from quant_strategies.evaluation.results import PortfolioMetricPayload, PortfolioTraceTables

INITIAL_EQUITY = 100.0

_PORTFOLIO_PATH_COLUMNS = (
    "scenario_id",
    "timestamp",
    "portfolio_value",
    "period_return",
    "drawdown",
)
_TRADE_COLUMNS = (
    "scenario_id",
    "asset",
    "direction",
    "decision_time",
    "entry_time",
    "exit_time",
    "entry_weight",
    "entry_mark",
    "exit_mark",
    "exit_reason",
    "realized_pnl",
    "gross_cash",
    "funding_cash",
    "cost_cash",
)
_FUNDING_COLUMNS = (
    "scenario_id",
    "timestamp",
    "asset",
    "funding_rate",
    "position_units",
    "mark_price",
    "funding_cashflow",
)


def spine_metric_payload(
    walk: BookWalkResult,
    *,
    annualization_periods_per_year: int,
    min_annualized_samples: int,
) -> PortfolioMetricPayload:
    """Compute the completed-scenario metric payload from one book walk.

    Required NAV/return/funding scalars are always present for a completed walk; the
    annualized risk family (``annualized_return``/``volatility``/``sharpe``/``sortino``/
    ``calmar``) is emitted only with a sufficient finite return sample and is otherwise
    ``None`` (the cadence trust boundary nulls it again downstream).
    """
    warnings: list[str] = []
    navs = [point.portfolio_value for point in walk.path]
    ending_value = navs[-1] if navs else None
    if ending_value is None or not math.isfinite(ending_value):
        raise ValueError("invalid_required_metric:ending_value")
    total_return = (ending_value / INITIAL_EQUITY) - 1.0
    # The book guarantees non-positive drawdown (``nav/peak - 1`` with a running peak);
    # the minimum over the path is the scenario max drawdown.
    max_drawdown = min((point.drawdown for point in walk.path), default=0.0)
    funding_total = sum(event.cashflow for event in walk.funding_events)

    payload: dict[str, MetricValue] = {
        "total_return": total_return,
        "ending_value": ending_value,
        "max_drawdown": max_drawdown,
        "trade_count": len(walk.round_trips),
        "win_rate": _win_rate(walk.round_trips),
        "profit_factor": _profit_factor(walk.round_trips),
        "annualized_return": None,
        "volatility": None,
        "sharpe": None,
        "sortino": None,
        "calmar": None,
        "worst_period_return": None,
        "funding_cashflow_total": funding_total,
        "funding_event_count": len(walk.funding_events),
        "funding_model": SHARED_ACCOUNTING_MODEL,
    }

    coverage = _return_coverage(walk)
    payload["return_total_count_excluding_initial"] = coverage.total_count
    payload["return_sample_count"] = coverage.sample_count
    payload["return_nonfinite_count"] = coverage.nonfinite_count
    if coverage.nonfinite_count:
        warnings.append(f"return_coverage_nonfinite:{coverage.nonfinite_count}")
    if coverage.sample_count < min_annualized_samples:
        warnings.append(
            f"annualized_metrics_insufficient_samples:{coverage.sample_count}:"
            f"min_required={min_annualized_samples}"
        )

    if coverage.observed and coverage.nonfinite_count == 0:
        observed = list(coverage.observed)
        payload["worst_period_return"] = min(observed)
        if coverage.sample_count >= min_annualized_samples:
            _fill_annualized_metrics(
                payload,
                observed,
                total_return=total_return,
                max_drawdown=max_drawdown,
                annualization_periods_per_year=annualization_periods_per_year,
            )
    return PortfolioMetricPayload(metrics=payload, warnings=tuple(warnings))


def spine_trace_tables(
    pd: Any,
    walk: BookWalkResult,
    scenario_id: str,
) -> PortfolioTraceTables:
    """Build the evaluation trace frames from one book walk."""
    return PortfolioTraceTables(
        portfolio_path=_portfolio_path_frame(pd, walk, scenario_id),
        trades=_trades_frame(pd, walk.round_trips, scenario_id),
        target_positions=_target_positions_frame(pd, walk.round_trips, scenario_id),
        target_exposure_summary=_target_exposure_summary_frame(pd, walk.round_trips, scenario_id),
        funding_cashflows=_funding_cashflows_frame(pd, walk.funding_events, scenario_id),
    )


class _ReturnCoverage:
    __slots__ = ("nonfinite_count", "observed", "sample_count", "total_count")

    def __init__(
        self,
        *,
        observed: tuple[float, ...],
        total_count: int,
        sample_count: int,
        nonfinite_count: int,
    ) -> None:
        self.observed = observed
        self.total_count = total_count
        self.sample_count = sample_count
        self.nonfinite_count = nonfinite_count


def _return_coverage(walk: BookWalkResult) -> _ReturnCoverage:
    """Observed-return semantics: drop the synthetic first period return, exclude
    non-finite. This is the same sample the typed series and the Parquet trace use."""
    returns = [point.period_return for point in walk.path][1:]
    observed = tuple(value for value in returns if math.isfinite(value))
    return _ReturnCoverage(
        observed=observed,
        total_count=len(returns),
        sample_count=len(observed),
        nonfinite_count=len(returns) - len(observed),
    )


def _fill_annualized_metrics(
    payload: dict[str, MetricValue],
    observed: Sequence[float],
    *,
    total_return: float,
    max_drawdown: float,
    annualization_periods_per_year: int,
) -> None:
    annualized_return = (
        None
        if total_return <= -1.0
        else ((1.0 + total_return) ** (annualization_periods_per_year / len(observed))) - 1.0
    )
    mean_return = sum(observed) / len(observed)
    volatility = (
        None
        if len(observed) < 2
        else _sample_stdev(observed) * math.sqrt(annualization_periods_per_year)
    )
    downside = _downside_deviation(observed, annualization_periods_per_year)
    annualized_mean = mean_return * annualization_periods_per_year
    payload["annualized_return"] = annualized_return
    payload["volatility"] = volatility
    payload["sharpe"] = None if not volatility else annualized_mean / volatility
    payload["sortino"] = None if not downside else annualized_mean / downside
    payload["calmar"] = (
        None
        if annualized_return is None or max_drawdown == 0.0
        else annualized_return / abs(max_drawdown)
    )


def _win_rate(round_trips: Sequence[RoundTrip]) -> float | None:
    if not round_trips:
        return None
    wins = sum(1 for trip in round_trips if trip.realized_pnl > 0.0)
    return wins / len(round_trips)


def _profit_factor(round_trips: Sequence[RoundTrip]) -> float | None:
    gross_profit = sum(trip.realized_pnl for trip in round_trips if trip.realized_pnl > 0.0)
    gross_loss = sum(trip.realized_pnl for trip in round_trips if trip.realized_pnl < 0.0)
    if gross_loss == 0.0:
        return None
    return gross_profit / abs(gross_loss)


def _sample_stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _downside_deviation(
    values: Sequence[float], annualization_periods_per_year: int
) -> float | None:
    downside = [value for value in values if value < 0.0]
    if not downside:
        return None
    periodic = math.sqrt(sum(value**2 for value in downside) / len(values))
    annualized = periodic * math.sqrt(annualization_periods_per_year)
    return annualized if annualized > 0.0 else None


def _portfolio_path_frame(pd: Any, walk: BookWalkResult, scenario_id: str) -> Any:
    return pd.DataFrame.from_records(
        [
            {
                "scenario_id": scenario_id,
                "timestamp": point.timestamp,
                "portfolio_value": point.portfolio_value,
                "period_return": point.period_return,
                "drawdown": point.drawdown,
            }
            for point in walk.path
        ],
        columns=_PORTFOLIO_PATH_COLUMNS,
    )


def _trades_frame(pd: Any, round_trips: Sequence[RoundTrip], scenario_id: str) -> Any:
    return pd.DataFrame.from_records(
        [
            {
                "scenario_id": scenario_id,
                "asset": trip.symbol,
                "direction": trip.direction,
                "decision_time": trip.decision_time,
                "entry_time": trip.entry_time,
                "exit_time": trip.exit_time,
                "entry_weight": trip.entry_weight,
                "entry_mark": trip.entry_mark,
                "exit_mark": trip.exit_mark,
                "exit_reason": trip.exit_reason,
                "realized_pnl": trip.realized_pnl,
                "gross_cash": trip.gross_cash,
                "funding_cash": trip.funding_cash,
                "cost_cash": trip.cost_cash,
            }
            for trip in round_trips
        ],
        columns=_TRADE_COLUMNS,
    )


def _target_positions_frame(pd: Any, round_trips: Sequence[RoundTrip], scenario_id: str) -> Any:
    records = [
        record
        for trip in round_trips
        for record in (
            {
                "scenario_id": scenario_id,
                "timestamp": trip.entry_time,
                "asset": trip.symbol,
                "target_weight": trip.entry_weight,
                "event": "entry",
                "decision_time": trip.decision_time,
                "direction": trip.direction,
            },
            {
                "scenario_id": scenario_id,
                "timestamp": trip.exit_time,
                "asset": trip.symbol,
                "target_weight": 0.0,
                "event": "exit",
                "decision_time": trip.decision_time,
                "direction": trip.direction,
            },
        )
    ]
    return pd.DataFrame.from_records(
        records,
        columns=(
            "scenario_id",
            "timestamp",
            "asset",
            "target_weight",
            "event",
            "decision_time",
            "direction",
        ),
    )


def _target_exposure_summary_frame(
    pd: Any, round_trips: Sequence[RoundTrip], scenario_id: str
) -> Any:
    by_asset: dict[str, dict[str, float | int | str]] = {}
    for trip in round_trips:
        metrics = by_asset.setdefault(
            trip.symbol,
            {
                "scenario_id": scenario_id,
                "asset": trip.symbol,
                "decision_count": 0,
                "target_round_trip_turnover": 0.0,
            },
        )
        metrics["decision_count"] = int(metrics["decision_count"]) + 1
        metrics["target_round_trip_turnover"] = float(metrics["target_round_trip_turnover"]) + (
            2.0 * abs(trip.entry_weight)
        )
    return pd.DataFrame.from_records(
        list(by_asset.values()),
        columns=("scenario_id", "asset", "decision_count", "target_round_trip_turnover"),
    )


def _funding_cashflows_frame(pd: Any, events: Sequence[FundingEvent], scenario_id: str) -> Any:
    return pd.DataFrame.from_records(
        [
            {
                "scenario_id": scenario_id,
                "timestamp": event.timestamp,
                "asset": event.symbol,
                "funding_rate": event.funding_rate,
                "position_units": event.position_units,
                "mark_price": event.mark_price,
                "funding_cashflow": event.cashflow,
            }
            for event in events
        ],
        columns=_FUNDING_COLUMNS,
    )
