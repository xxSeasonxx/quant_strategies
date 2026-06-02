from __future__ import annotations

import math


def test_evaluation_metric_semantics_label_nav_metrics_as_portfolio_evidence():
    from quant_strategies.evaluation.metrics import evaluation_metric_semantics

    semantics = evaluation_metric_semantics()

    assert semantics["total_return"]["base"] == "portfolio NAV path"
    assert semantics["sharpe"]["annualization"] == "explicit_config.annualization_periods_per_year"
    assert semantics["trade_count"]["base"] == "VectorBT Pro portfolio trade records"
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
