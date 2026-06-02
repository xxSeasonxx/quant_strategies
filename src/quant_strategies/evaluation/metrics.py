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


def evaluation_metric_semantics() -> dict[str, dict[str, object]]:
    nav_base = "portfolio NAV path"
    returns_base = "periodic portfolio returns"
    trades_base = "VectorBT Pro portfolio trade records"
    cost_scope = "net of configured fees/slippage; excludes funding, borrow, financing, market impact"
    not_authority = "not validation, promotion, paper trading, or live trading authority"
    annualization = "explicit_config.annualization_periods_per_year"

    return {
        "total_return": {
            "unit": "decimal_fraction",
            "base": nav_base,
            "aggregation": "scenario total",
            "backend": "vectorbtpro",
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "ending_value": {
            "unit": "portfolio_value",
            "base": nav_base,
            "aggregation": "scenario final value",
            "backend": "vectorbtpro",
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "annualized_return": {
            "unit": "decimal_fraction_per_year",
            "base": returns_base,
            "aggregation": "annualized by explicit config",
            "backend": "vectorbtpro",
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "volatility": {
            "unit": "decimal_fraction_per_year",
            "base": returns_base,
            "aggregation": "sample standard deviation annualized by explicit config",
            "backend": "vectorbtpro",
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "sharpe": {
            "unit": "ratio",
            "base": returns_base,
            "aggregation": "mean return over volatility annualized by explicit config; risk-free rate zero",
            "backend": "vectorbtpro",
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "sortino": {
            "unit": "ratio",
            "base": returns_base,
            "aggregation": "mean return over downside volatility annualized by explicit config; target return zero",
            "backend": "vectorbtpro",
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "calmar": {
            "unit": "ratio",
            "base": "annualized return and max drawdown",
            "aggregation": "annualized_return / abs(max_drawdown)",
            "backend": "vectorbtpro",
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "max_drawdown": {
            "unit": "decimal_fraction",
            "base": nav_base,
            "aggregation": "minimum drawdown over scenario",
            "backend": "vectorbtpro",
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "trade_count": {
            "unit": "count",
            "base": trades_base,
            "aggregation": "scenario total",
            "backend": "vectorbtpro",
            "not_authority": not_authority,
        },
        "win_rate": {
            "unit": "ratio",
            "base": trades_base,
            "aggregation": "winning trades / all closed trades",
            "backend": "vectorbtpro",
            "not_authority": not_authority,
        },
        "profit_factor": {
            "unit": "ratio",
            "base": trades_base,
            "aggregation": "gross profits / abs(gross losses)",
            "backend": "vectorbtpro",
            "not_authority": not_authority,
        },
    }
