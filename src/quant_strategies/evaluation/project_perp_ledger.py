from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from quant_strategies.evaluation._portfolio_common import (
    cost_bps_fraction,
    downside_deviation,
    funding_cashflows_frame,
    required_final_metric,
    return_coverage,
    sample_stdev,
    series_values,
    signed_target_weight,
    target_exposure_summary_frame,
    target_positions_frame,
)
from quant_strategies.evaluation.config import EvaluationMetricsConfig
from quant_strategies.evaluation.metrics import (
    MetricValue,
    finite_metric_or_none,
    required_drawdown_metric,
)
from quant_strategies.evaluation.results import (
    PortfolioEvaluationResult,
    PortfolioMetricPayload,
    PortfolioTraceTables,
    PreparedPortfolioInputs,
)
from quant_strategies.evaluation.scenarios import EvaluationScenario
from quant_strategies.funding import funding_rates_match

INITIAL_EQUITY = 100.0
PROJECT_PERP_FUNDING_MODEL = "project_perp_ledger_v1"


@dataclass
class PerpPosition:
    symbol: str
    direction: str
    decision_time: Any
    entry_time: Any
    exit_time: Any
    target_weight: float
    signed_units: float
    entry_fill_price: float
    entry_notional: float
    entry_fee: float
    funding_cashflow: float = 0.0


def run_perp_ledger(
    pd: Any,
    prepared: PreparedPortfolioInputs,
    scenario: EvaluationScenario,
    metrics_config: EvaluationMetricsConfig,
    windows: list[dict[str, Any]],
) -> PortfolioEvaluationResult:
    funding_events = funding_events_by_symbol(pd, prepared.close, prepared.source_rows)
    fee_fraction = cost_bps_fraction(scenario, "fee_bps_per_side")
    slippage_fraction = cost_bps_fraction(scenario, "slippage_bps_per_side")
    entries_by_time: dict[Any, list[tuple[int, dict[str, Any]]]] = {}
    exits_by_time: dict[Any, list[tuple[int, dict[str, Any]]]] = {}
    for index, window in enumerate(windows):
        entries_by_time.setdefault(window["entry_time"], []).append((index, window))
        exits_by_time.setdefault(window["exit_time"], []).append((index, window))

    cash = INITIAL_EQUITY
    active: dict[int, PerpPosition] = {}
    nav_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    funding_rows: list[dict[str, Any]] = []
    previous_nav: float | None = None
    peak_nav = INITIAL_EQUITY

    for timestamp in prepared.close.index:
        for symbol, funding_rate in funding_events_at(funding_events, timestamp):
            mark_price = mark_price_at(prepared.close, symbol, timestamp)
            for position in list(active.values()):
                if position.symbol != symbol:
                    continue
                cashflow = -position.signed_units * mark_price * funding_rate
                cash += cashflow
                position.funding_cashflow += cashflow
                funding_rows.append(
                    {
                        "scenario_id": scenario.scenario_id,
                        "timestamp": timestamp,
                        "asset": symbol,
                        "funding_rate": funding_rate,
                        "position_units": position.signed_units,
                        "mark_price": mark_price,
                        "funding_cashflow": cashflow,
                    }
                )

        for position_key, _window in exits_by_time.get(timestamp, ()):
            position = active.pop(position_key)
            mark_price = mark_price_at(prepared.close, position.symbol, timestamp)
            exit_fill_price = exit_fill_price_at(mark_price, position.direction, slippage_fraction)
            realized_pnl = position.signed_units * (exit_fill_price - position.entry_fill_price)
            exit_notional = abs(position.signed_units * exit_fill_price)
            exit_fee = exit_notional * fee_fraction
            cash += realized_pnl - exit_fee
            net_pnl = realized_pnl + position.funding_cashflow - position.entry_fee - exit_fee
            trade_rows.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "asset": position.symbol,
                    "direction": position.direction,
                    "decision_time": position.decision_time,
                    "entry_time": position.entry_time,
                    "exit_time": position.exit_time,
                    "target_weight": position.target_weight,
                    "signed_units": position.signed_units,
                    "entry_fill_price": position.entry_fill_price,
                    "exit_fill_price": exit_fill_price,
                    "entry_notional": position.entry_notional,
                    "exit_notional": exit_notional,
                    "entry_fee": position.entry_fee,
                    "exit_fee": exit_fee,
                    "realized_pnl": realized_pnl,
                    "funding_cashflow": position.funding_cashflow,
                    "net_pnl": net_pnl,
                }
            )

        entry_events = entries_by_time.get(timestamp, ())
        if entry_events:
            equity_snapshot = equity_at_mark(prepared.close, active.values(), timestamp, cash)
            if equity_snapshot <= 0.0:
                raise ValueError(
                    f"nonpositive_equity_for_entry:{timestamp.isoformat()}:{equity_snapshot}"
                )
            for position_key, window in entry_events:
                item = window["decision"]
                symbol = window["symbol"]
                mark_price = mark_price_at(prepared.close, symbol, timestamp)
                entry_fill_price = entry_fill_price_at(
                    mark_price, item.target.direction, slippage_fraction
                )
                target_weight = signed_target_weight(window)
                signed_target_notional = target_weight * equity_snapshot
                signed_units = signed_target_notional / entry_fill_price
                entry_notional = abs(signed_units * entry_fill_price)
                entry_fee = entry_notional * fee_fraction
                cash -= entry_fee
                active[position_key] = PerpPosition(
                    symbol=symbol,
                    direction=item.target.direction,
                    decision_time=item.decision_time,
                    entry_time=window["entry_time"],
                    exit_time=window["exit_time"],
                    target_weight=target_weight,
                    signed_units=signed_units,
                    entry_fill_price=entry_fill_price,
                    entry_notional=entry_notional,
                    entry_fee=entry_fee,
                )

        nav = equity_at_mark(prepared.close, active.values(), timestamp, cash)
        period_return = 0.0 if previous_nav is None else (nav / previous_nav) - 1.0
        peak_nav = max(peak_nav, nav)
        drawdown = 0.0 if peak_nav == 0.0 else (nav / peak_nav) - 1.0
        nav_rows.append(
            {
                "scenario_id": scenario.scenario_id,
                "timestamp": timestamp,
                "portfolio_value": nav,
                "period_return": period_return,
                "drawdown": drawdown,
            }
        )
        previous_nav = nav

    if active:
        open_symbols = ",".join(sorted(position.symbol for position in active.values()))
        raise ValueError(f"open_positions_after_ledger:{open_symbols}")

    portfolio_path = pd.DataFrame.from_records(
        nav_rows,
        columns=("scenario_id", "timestamp", "portfolio_value", "period_return", "drawdown"),
    )
    trades = pd.DataFrame.from_records(
        trade_rows,
        columns=(
            "scenario_id",
            "asset",
            "direction",
            "decision_time",
            "entry_time",
            "exit_time",
            "target_weight",
            "signed_units",
            "entry_fill_price",
            "exit_fill_price",
            "entry_notional",
            "exit_notional",
            "entry_fee",
            "exit_fee",
            "realized_pnl",
            "funding_cashflow",
            "net_pnl",
        ),
    )
    funding_cashflows = funding_cashflows_frame(pd, funding_rows)
    tables = PortfolioTraceTables(
        portfolio_path=portfolio_path,
        trades=trades,
        target_positions=target_positions_frame(pd, windows, scenario.scenario_id),
        target_exposure_summary=target_exposure_summary_frame(pd, windows, scenario.scenario_id),
        funding_cashflows=funding_cashflows,
    )
    metric_payload = perp_ledger_metrics(
        portfolio_path,
        trades,
        annualization_periods_per_year=metrics_config.annualization_periods_per_year,
        min_annualized_samples=metrics_config.min_annualized_samples,
        funding_cashflow_total=sum(float(row["funding_cashflow"]) for row in funding_rows),
        funding_event_count=len(funding_rows),
    )
    return PortfolioEvaluationResult(
        scenario_id=scenario.scenario_id,
        backend=PROJECT_PERP_FUNDING_MODEL,
        status="completed",
        metrics=metric_payload.metrics,
        warnings=metric_payload.warnings,
        tables=tables,
    )


def funding_events_by_symbol(
    pd: Any,
    close: Any,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[Any, float]]:
    events: dict[str, dict[Any, float]] = {}
    for row in rows:
        if not is_true_flag(row.get("has_funding_event")):
            continue
        try:
            symbol = str(row["symbol"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid_funding_event:{exc}") from exc
        if not symbol:
            raise ValueError("invalid_funding_event:empty_symbol")
        if symbol not in close.columns:
            continue
        funding_timestamp = coerce_utc_timestamp(
            pd, row.get("funding_timestamp"), "funding_timestamp"
        )
        # Funding settles at a sub-minute instant (real quant_data stamps the exact
        # settlement, e.g. 08:00:00.003), but it is marked and applied at the 1-minute
        # bar that contains it. Snap to that bar so the mark lookup hits the
        # minute-indexed close; a funding_timestamp outside the bar grid (wrong/missing
        # bar) still floors to a missing mark and is reported as not-aligned.
        bar_timestamp = funding_timestamp.floor("min")
        try:
            funding_rate = float(row["funding_rate"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"invalid_funding_rate:{symbol}:{funding_timestamp.isoformat()}"
            ) from exc
        if not math.isfinite(funding_rate):
            raise ValueError(f"invalid_funding_rate:{symbol}:{funding_timestamp.isoformat()}")
        try:
            mark_price_at(close, symbol, bar_timestamp)
        except ValueError as exc:
            raise ValueError(
                f"funding_timestamp_not_aligned:{symbol}:{funding_timestamp.isoformat()}"
            ) from exc

        symbol_events = events.setdefault(symbol, {})
        existing = symbol_events.get(bar_timestamp)
        if existing is not None and not funding_rates_match(existing, funding_rate):
            raise ValueError(f"conflicting_funding_rates:{symbol}:{funding_timestamp.isoformat()}")
        symbol_events[bar_timestamp] = funding_rate
    return events


def funding_events_at(
    events: Mapping[str, Mapping[Any, float]], timestamp: Any
) -> list[tuple[str, float]]:
    return [
        (symbol, float(rate))
        for symbol, by_timestamp in events.items()
        for event_timestamp, rate in by_timestamp.items()
        if event_timestamp == timestamp
    ]


def is_true_flag(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def coerce_utc_timestamp(pd: Any, value: Any, field: str) -> Any:
    try:
        timestamp = pd.to_datetime(value, utc=True)
    except Exception as exc:
        raise ValueError(f"invalid_{field}:{value}") from exc
    if pd.isna(timestamp):
        raise ValueError(f"invalid_{field}:{value}")
    return timestamp


def equity_at_mark(
    close: Any, positions: Sequence[PerpPosition], timestamp: Any, cash: float
) -> float:
    equity = cash
    for position in positions:
        mark_price = mark_price_at(close, position.symbol, timestamp)
        equity += position.signed_units * (mark_price - position.entry_fill_price)
    if not math.isfinite(equity):
        raise ValueError(f"nonfinite_equity:{timestamp.isoformat()}")
    return equity


def mark_price_at(close: Any, symbol: str, timestamp: Any) -> float:
    try:
        value = close.loc[timestamp, symbol]
    except Exception as exc:
        raise ValueError(f"missing_mark:{symbol}:{timestamp.isoformat()}") from exc
    metric = finite_metric_or_none(value)
    if metric is None or metric <= 0.0:
        raise ValueError(f"missing_mark:{symbol}:{timestamp.isoformat()}")
    return metric


def entry_fill_price_at(mark_price: float, direction: str, slippage_fraction: float) -> float:
    if direction == "long":
        return mark_price * (1.0 + slippage_fraction)
    if direction == "short":
        return mark_price * (1.0 - slippage_fraction)
    raise ValueError(f"unsupported_direction:{direction}")


def exit_fill_price_at(mark_price: float, direction: str, slippage_fraction: float) -> float:
    if direction == "long":
        return mark_price * (1.0 - slippage_fraction)
    if direction == "short":
        return mark_price * (1.0 + slippage_fraction)
    raise ValueError(f"unsupported_direction:{direction}")


def perp_ledger_metrics(
    portfolio_path: Any,
    trades: Any,
    *,
    annualization_periods_per_year: int,
    funding_cashflow_total: float,
    funding_event_count: int,
    min_annualized_samples: int = 20,
) -> PortfolioMetricPayload:
    values = portfolio_path["portfolio_value"] if "portfolio_value" in portfolio_path else []
    returns = portfolio_path["period_return"] if "period_return" in portfolio_path else []
    drawdowns = portfolio_path["drawdown"] if "drawdown" in portfolio_path else []
    ending_value = required_final_metric("ending_value", values)
    max_drawdown = required_drawdown_metric(
        "max_drawdown",
        min(series_values(drawdowns)) if series_values(drawdowns) else None,
    )

    trade_pnls = (
        [float(value) for value in series_values(trades["net_pnl"])] if "net_pnl" in trades else []
    )
    wins = [value for value in trade_pnls if value > 0.0]
    losses = [value for value in trade_pnls if value < 0.0]
    trade_count = len(trade_pnls)
    gross_profit = sum(wins)
    gross_loss = sum(losses)

    total_return = (ending_value / INITIAL_EQUITY) - 1.0
    payload: dict[str, MetricValue] = {
        "total_return": total_return,
        "ending_value": ending_value,
        "max_drawdown": max_drawdown,
        "trade_count": trade_count,
        "win_rate": None if trade_count == 0 else len(wins) / trade_count,
        "profit_factor": None if gross_loss == 0.0 else gross_profit / abs(gross_loss),
        "annualized_return": None,
        "volatility": None,
        "sharpe": None,
        "sortino": None,
        "calmar": None,
        "worst_period_return": None,
        "funding_cashflow_total": funding_cashflow_total,
        "funding_event_count": funding_event_count,
        "funding_model": PROJECT_PERP_FUNDING_MODEL,
    }
    warnings: list[str] = []
    coverage = return_coverage(returns)
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
        observed_returns = list(coverage.observed)
        payload["worst_period_return"] = min(observed_returns)
        if coverage.sample_count >= min_annualized_samples:
            annualized_return = (
                None
                if total_return <= -1.0
                else (
                    (1.0 + total_return) ** (annualization_periods_per_year / coverage.sample_count)
                )
                - 1.0
            )
            mean_return = sum(observed_returns) / len(observed_returns)
            volatility = (
                None
                if len(observed_returns) < 2
                else sample_stdev(observed_returns) * math.sqrt(annualization_periods_per_year)
            )
            annualized_downside_deviation = downside_deviation(
                observed_returns,
                annualization_periods_per_year,
            )
            payload["annualized_return"] = annualized_return
            payload["volatility"] = volatility
            annualized_mean = mean_return * annualization_periods_per_year
            payload["sharpe"] = None if not volatility else annualized_mean / volatility
            payload["sortino"] = (
                None
                if not annualized_downside_deviation
                else annualized_mean / annualized_downside_deviation
            )
            max_dd = finite_metric_or_none(payload["max_drawdown"])
            payload["calmar"] = (
                None
                if annualized_return is None or max_dd in (None, 0.0)
                else annualized_return / abs(max_dd)
            )
    return PortfolioMetricPayload(metrics=payload, warnings=tuple(warnings))
