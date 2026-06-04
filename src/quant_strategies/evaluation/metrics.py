from __future__ import annotations

import math
from numbers import Real
from typing import Any

MetricValue = float | int | str | bool | None


def finite_metric_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None

    metric = float(value)
    if not math.isfinite(metric):
        return None
    return metric


def required_drawdown_metric(name: str, value: Any) -> float:
    metric = finite_metric_or_none(value)
    if metric is None or metric > 0.0:
        raise ValueError(f"invalid_required_metric:{name}")
    return metric


def evaluation_metric_semantics() -> dict[str, dict[str, object]]:
    nav_base = "portfolio NAV path"
    returns_base = "full-grid periodic portfolio returns, including flat/no-position bars"
    trades_base = "portfolio trade records"
    backend = "vectorbtpro for non-funding evaluations; project_perp_ledger_v1 for crypto_perp_funding"
    cost_scope = (
        "net of configured fees/slippage; includes funding cashflows for crypto_perp_funding; "
        "excludes borrow, financing, and market impact"
    )
    not_authority = "not validation, promotion, paper trading, or live trading authority"
    benchmark_not_authority = (
        "benchmark-relative evidence only; not ranking, promotion, paper trading, or live trading authority"
    )
    annualization = (
        "explicit_config.annualization_periods_per_year; requires "
        "annualization_cadence.status == ok and return_sample_count >= "
        "explicit_config.min_annualized_samples"
    )

    return {
        "total_return": {
            "unit": "decimal_fraction",
            "base": nav_base,
            "aggregation": "scenario total",
            "backend": backend,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
            "null_when": "never for completed scenarios; unavailable/non-finite required values fail evaluation",
        },
        "ending_value": {
            "unit": "portfolio_value",
            "base": nav_base,
            "aggregation": "scenario final value",
            "backend": backend,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
            "null_when": "never for completed scenarios; empty or non-finite portfolio value path fails evaluation",
        },
        "annualized_return": {
            "unit": "decimal_fraction_per_year",
            "base": returns_base,
            "aggregation": "annualized by explicit config",
            "backend": backend,
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
            "null_when": "no observed finite returns after the synthetic first return, any non-finite post-initial return is present, return_sample_count is below [metrics].min_annualized_samples, annualization_cadence.status is not ok, or total return <= -100%",
        },
        "volatility": {
            "unit": "decimal_fraction_per_year",
            "base": returns_base,
            "aggregation": "sample standard deviation annualized by explicit config",
            "backend": backend,
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
            "null_when": "return_sample_count is below [metrics].min_annualized_samples, annualization_cadence.status is not ok, or fewer than two observed returns after the synthetic first return",
        },
        "sharpe": {
            "unit": "ratio",
            "base": returns_base,
            "aggregation": "mean return over volatility annualized by explicit config; risk-free rate zero",
            "backend": backend,
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
            "null_when": "return_sample_count is below [metrics].min_annualized_samples, annualization_cadence.status is not ok, or volatility is unavailable or zero",
        },
        "sortino": {
            "unit": "ratio",
            "base": returns_base,
            "aggregation": "mean return over downside volatility annualized by explicit config; target return zero",
            "backend": backend,
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
            "null_when": "return_sample_count is below [metrics].min_annualized_samples, annualization_cadence.status is not ok, or downside deviation is unavailable or zero; no downside returns is reported as null rather than infinity",
        },
        "calmar": {
            "unit": "ratio",
            "base": "annualized return and max drawdown",
            "aggregation": "annualized_return / abs(max_drawdown)",
            "backend": backend,
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
            "null_when": "return_sample_count is below [metrics].min_annualized_samples, annualization_cadence.status is not ok, annualized return is unavailable, max drawdown is unavailable, or max drawdown is zero",
        },
        "max_drawdown": {
            "unit": "decimal_fraction",
            "base": nav_base,
            "aggregation": "minimum drawdown over scenario",
            "backend": backend,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
            "null_when": "never for completed scenarios; unavailable/non-finite required values fail evaluation",
        },
        "trade_count": {
            "unit": "count",
            "base": trades_base,
            "aggregation": "scenario total",
            "backend": backend,
            "not_authority": not_authority,
            "null_when": "never for completed scenarios; unavailable/invalid trade count fails evaluation",
        },
        "win_rate": {
            "unit": "ratio",
            "base": trades_base,
            "aggregation": "winning trades / all closed trades",
            "backend": backend,
            "not_authority": not_authority,
            "null_when": "backend win-rate is unavailable/non-finite, including no closed trades",
        },
        "profit_factor": {
            "unit": "ratio",
            "base": trades_base,
            "aggregation": "gross profits / abs(gross losses)",
            "backend": backend,
            "not_authority": not_authority,
            "null_when": "backend profit factor is unavailable/non-finite; no losses is reported as null rather than infinity",
        },
        "worst_period_return": {
            "unit": "decimal_fraction",
            "base": returns_base,
            "aggregation": "minimum observed return after the synthetic first return",
            "backend": backend,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
            "null_when": "no observed returns after the synthetic first return or any non-finite post-initial return is present",
        },
        "return_total_count_excluding_initial": {
            "unit": "count",
            "base": returns_base,
            "aggregation": "post-initial return count before finite filtering",
            "backend": backend,
            "not_authority": not_authority,
            "null_when": "never for completed scenarios",
        },
        "return_sample_count": {
            "unit": "count",
            "base": returns_base,
            "aggregation": "finite post-initial return count checked against [metrics].min_annualized_samples before annualized/risk metrics are emitted",
            "backend": backend,
            "not_authority": not_authority,
            "null_when": "never for completed scenarios",
        },
        "return_nonfinite_count": {
            "unit": "count",
            "base": returns_base,
            "aggregation": "non-finite post-initial return count excluded from annualized metrics",
            "backend": backend,
            "not_authority": not_authority,
            "null_when": "never for completed scenarios",
        },
        "funding_cashflow_total": {
            "unit": "portfolio_value",
            "base": "funding_cashflows trace table",
            "aggregation": "scenario sum",
            "backend": backend,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
            "null_when": "never for completed scenarios; zero when funding_model is none",
        },
        "funding_event_count": {
            "unit": "count",
            "base": "funding_cashflows trace table",
            "aggregation": "scenario count of applied funding cashflows",
            "backend": backend,
            "not_authority": not_authority,
            "null_when": "never for completed scenarios",
        },
        "funding_model": {
            "unit": "label",
            "base": "evaluation data-kind route",
            "aggregation": "scenario label",
            "backend": backend,
            "not_authority": not_authority,
            "null_when": "never for completed scenarios; project_perp_ledger_v1 for crypto_perp_funding and none otherwise",
        },
        "benchmark_symbol": {
            "unit": "label",
            "base": "configured benchmark symbol",
            "aggregation": "scenario label",
            "backend": "computed from normalized evaluation rows when [benchmark] is configured",
            "not_authority": benchmark_not_authority,
            "null_when": "absent when no benchmark is configured",
        },
        "benchmark_total_return": {
            "unit": "decimal_fraction",
            "base": "benchmark close path",
            "aggregation": "window final close / first close - 1",
            "backend": "computed from normalized evaluation rows when [benchmark] is configured",
            "not_authority": benchmark_not_authority,
            "null_when": "absent when no benchmark is configured; missing or invalid benchmark rows fail evaluation",
        },
        "excess_total_return": {
            "unit": "decimal_fraction",
            "base": "scenario total_return and benchmark_total_return",
            "aggregation": "total_return - benchmark_total_return",
            "backend": "computed from normalized evaluation rows when [benchmark] is configured",
            "not_authority": benchmark_not_authority,
            "null_when": "absent when no benchmark is configured",
        },
    }
