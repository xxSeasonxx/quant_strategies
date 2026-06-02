from __future__ import annotations

import math
from numbers import Real
from typing import Any


def finite_metric_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None

    metric = float(value)
    if not math.isfinite(metric):
        return None
    return metric


def evaluation_metric_semantics() -> dict[str, dict[str, object]]:
    nav_base = "portfolio NAV path"
    cost_scope = "net of configured fees/slippage; excludes funding, borrow, financing, market impact"
    not_authority = "not validation, promotion, paper trading, or live trading authority"
    annualization = "explicit_config.annualization_periods_per_year"

    return {
        "total_return": {
            "base": nav_base,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "ending_value": {
            "base": nav_base,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "annualized_return": {
            "base": nav_base,
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "volatility": {
            "base": nav_base,
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "sharpe": {
            "base": nav_base,
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "sortino": {
            "base": nav_base,
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "calmar": {
            "base": nav_base,
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "max_drawdown": {
            "base": nav_base,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "trade_count": {
            "base": "VectorBT Pro portfolio trade records",
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "win_rate": {
            "base": "VectorBT Pro portfolio trade records",
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "profit_factor": {
            "base": "VectorBT Pro portfolio trade records",
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
    }
