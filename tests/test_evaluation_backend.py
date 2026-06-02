from __future__ import annotations

import math


def test_evaluation_metric_semantics_label_nav_metrics_as_portfolio_evidence():
    from quant_strategies.evaluation.metrics import MetricValue, evaluation_metric_semantics

    semantics = evaluation_metric_semantics()

    assert MetricValue == float | int | str | bool | None
    assert semantics == {
        "total_return": {
            "unit": "decimal_fraction",
            "base": "portfolio NAV path",
            "aggregation": "scenario total",
            "backend": "vectorbtpro",
            "cost_scope": "net of configured fees/slippage; excludes funding, borrow, financing, market impact",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
        },
        "ending_value": {
            "unit": "portfolio_value",
            "base": "portfolio NAV path",
            "aggregation": "scenario final value",
            "backend": "vectorbtpro",
            "cost_scope": "net of configured fees/slippage; excludes funding, borrow, financing, market impact",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
        },
        "annualized_return": {
            "unit": "decimal_fraction_per_year",
            "base": "periodic portfolio returns",
            "aggregation": "annualized by explicit config",
            "backend": "vectorbtpro",
            "annualization": "explicit_config.annualization_periods_per_year",
            "cost_scope": "net of configured fees/slippage; excludes funding, borrow, financing, market impact",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
        },
        "volatility": {
            "unit": "decimal_fraction_per_year",
            "base": "periodic portfolio returns",
            "aggregation": "sample standard deviation annualized by explicit config",
            "backend": "vectorbtpro",
            "annualization": "explicit_config.annualization_periods_per_year",
            "cost_scope": "net of configured fees/slippage; excludes funding, borrow, financing, market impact",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
        },
        "sharpe": {
            "unit": "ratio",
            "base": "periodic portfolio returns",
            "aggregation": "mean return over volatility annualized by explicit config; risk-free rate zero",
            "backend": "vectorbtpro",
            "annualization": "explicit_config.annualization_periods_per_year",
            "cost_scope": "net of configured fees/slippage; excludes funding, borrow, financing, market impact",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
        },
        "sortino": {
            "unit": "ratio",
            "base": "periodic portfolio returns",
            "aggregation": "mean return over downside volatility annualized by explicit config; target return zero",
            "backend": "vectorbtpro",
            "annualization": "explicit_config.annualization_periods_per_year",
            "cost_scope": "net of configured fees/slippage; excludes funding, borrow, financing, market impact",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
        },
        "calmar": {
            "unit": "ratio",
            "base": "annualized return and max drawdown",
            "aggregation": "annualized_return / abs(max_drawdown)",
            "backend": "vectorbtpro",
            "annualization": "explicit_config.annualization_periods_per_year",
            "cost_scope": "net of configured fees/slippage; excludes funding, borrow, financing, market impact",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
        },
        "max_drawdown": {
            "unit": "decimal_fraction",
            "base": "portfolio NAV path",
            "aggregation": "minimum drawdown over scenario",
            "backend": "vectorbtpro",
            "cost_scope": "net of configured fees/slippage; excludes funding, borrow, financing, market impact",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
        },
        "trade_count": {
            "unit": "count",
            "base": "VectorBT Pro portfolio trade records",
            "aggregation": "scenario total",
            "backend": "vectorbtpro",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
        },
        "win_rate": {
            "unit": "ratio",
            "base": "VectorBT Pro portfolio trade records",
            "aggregation": "winning trades / all closed trades",
            "backend": "vectorbtpro",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
        },
        "profit_factor": {
            "unit": "ratio",
            "base": "VectorBT Pro portfolio trade records",
            "aggregation": "gross profits / abs(gross losses)",
            "backend": "vectorbtpro",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
        },
    }
    assert (
        semantics["total_return"]["not_authority"]
        == "not validation, promotion, paper trading, or live trading authority"
    )
    assert (
        semantics["total_return"]["cost_scope"]
        == "net of configured fees/slippage; excludes funding, borrow, financing, market impact"
    )
    assert "net_return" not in semantics
    assert "turnover" not in semantics


def test_finite_metric_or_none_rejects_nan_inf_and_booleans():
    from quant_strategies.evaluation.metrics import finite_metric_or_none

    assert finite_metric_or_none(1) == 1.0
    assert finite_metric_or_none(1.5) == 1.5
    assert finite_metric_or_none(math.nan) is None
    assert finite_metric_or_none(math.inf) is None
    assert finite_metric_or_none(-math.inf) is None
    assert finite_metric_or_none(True) is None
    assert finite_metric_or_none(False) is None
    assert finite_metric_or_none("1.0") is None
