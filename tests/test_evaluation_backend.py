from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import quant_strategies.evaluation.backend as backend_module
from quant_strategies.core.config import CostModelConfig, FillModelConfig
from quant_strategies.decisions import DecisionIntent, ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.evaluation.backend import VectorBTProEvaluationBackend
from quant_strategies.evaluation.config import EvaluationMetricsConfig
from quant_strategies.evaluation.dependencies import EvaluationDependencies
from quant_strategies.evaluation.scenarios import EvaluationScenario


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


def test_observed_returns_drops_first_raw_return_before_filtering_nonfinite_values():
    assert backend_module._observed_returns([math.nan, 0.01, -0.02]) == [0.01, -0.02]
    assert backend_module._observed_returns([0.0, math.nan, 0.03]) == [0.03]


AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


def rows():
    return [
        {"symbol": "BTC-PERP", "timestamp": AS_OF, "close": 100.0},
        {"symbol": "BTC-PERP", "timestamp": DECISION, "close": 101.0},
        {"symbol": "BTC-PERP", "timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc), "close": 102.0},
        {"symbol": "BTC-PERP", "timestamp": datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc), "close": 103.0},
    ]


def decision(*, symbol: str = "BTC-PERP", size: float = 1.0, direction: str = "long"):
    return StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol=symbol),
        intent=DecisionIntent(action="open"),
        decision_time=DECISION,
        as_of_time=AS_OF,
        target=PositionTarget(direction=direction, sizing_kind="target_weight", size=size),
        exit_policy=ExitPolicy(max_hold_bars=1),
    )


def scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="w/realistic_costs/base_fill",
        window_id="w",
        cost_scenario="realistic_costs",
        fill_scenario="base_fill",
        cost_model=CostModelConfig(fee_bps_per_side=1.0, slippage_bps_per_side=2.0),
        fill_model=FillModelConfig(price="close", entry_lag_bars=1, exit_lag_bars=0),
    )


def install_fake_vbt(monkeypatch: pytest.MonkeyPatch):
    pd = pytest.importorskip("pandas")

    class FakeSeries:
        def __init__(self, values):
            self._values = values

        def to_frame(self, name):
            import pandas as pd

            return pd.DataFrame({name: self._values})

        def pct_change(self):
            return FakeSeries([0.0, 0.01, -0.02])

        def fillna(self, value):
            return self

    class FakeTrades:
        def count(self):
            return 2

        def win_rate(self):
            return 0.5

        def profit_factor(self):
            return 1.5

        @property
        def records_readable(self):
            import pandas as pd

            return pd.DataFrame({"Trade Id": [1, 2], "Column": ["BTC-PERP", "BTC-PERP"]})

    class FakePortfolio:
        trades = FakeTrades()

        def __init__(self, close, **kwargs):
            self.close = close
            self.kwargs = kwargs

        def value(self):
            return FakeSeries([100.0, 101.0, 99.0])

        def returns(self):
            return FakeSeries([0.0, 0.01, -0.019801980198])

        def drawdowns(self):
            return FakeSeries([0.0, 0.0, -0.019801980198])

        def get_total_return(self):
            return -0.01

        def get_max_drawdown(self):
            return -0.019801980198

    captured = {}

    def from_signals(close, **kwargs):
        captured["close_columns"] = list(close.columns)
        captured["kwargs"] = kwargs
        return FakePortfolio(close, **kwargs)

    fake_vbt = SimpleNamespace(Portfolio=SimpleNamespace(from_signals=from_signals))
    fake_pyarrow = SimpleNamespace(__name__="pyarrow")
    monkeypatch.setattr(
        backend_module,
        "require_evaluation_dependencies",
        lambda: EvaluationDependencies(pandas=pd, pyarrow=fake_pyarrow, vectorbtpro=fake_vbt),
    )
    return captured


def test_vectorbtpro_evaluation_backend_returns_metrics_and_tables(monkeypatch: pytest.MonkeyPatch):
    captured = install_fake_vbt(monkeypatch)

    result = VectorBTProEvaluationBackend().run(
        decisions=[decision()],
        rows=rows(),
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
    )

    assert result.status == "completed"
    assert result.backend == "vectorbtpro"
    assert result.scenario_id == "w/realistic_costs/base_fill"
    assert result.metrics["total_return"] == pytest.approx(-0.01)
    assert result.metrics["max_drawdown"] == pytest.approx(-0.019801980198)
    assert result.metrics["trade_count"] == 2
    assert result.metrics["win_rate"] == pytest.approx(0.5)
    assert result.metrics["profit_factor"] == pytest.approx(1.5)
    assert "sharpe" in result.metrics
    assert result.tables is not None
    assert not result.tables.portfolio_path.empty
    assert not result.tables.trades.empty
    assert set(captured["close_columns"]) == {"BTC-PERP"}
    assert captured["kwargs"]["cash_sharing"] is True
    assert captured["kwargs"]["group_by"] is True


def test_vectorbtpro_evaluation_backend_reports_unsupported_threshold_exit():
    bad = decision()
    bad = bad.model_copy(update={"exit_policy": ExitPolicy(max_hold_bars=1, stop_loss_bps=100.0)})

    result = VectorBTProEvaluationBackend().run(
        decisions=[bad],
        rows=rows(),
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
    )

    assert result.status == "unsupported"
    assert result.unsupported_semantics == ("threshold_exit_policy",)
    assert result.tables is None


def test_vectorbtpro_evaluation_backend_reports_leveraged_target_weight():
    result = VectorBTProEvaluationBackend().run(
        decisions=[decision(size=1.25)],
        rows=rows(),
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
    )

    assert result.status == "unsupported"
    assert "leveraged_target_weight" in result.unsupported_semantics


def test_vectorbtpro_evaluation_backend_fails_when_simultaneous_gross_exposure_exceeds_one(
    monkeypatch: pytest.MonkeyPatch,
):
    install_fake_vbt(monkeypatch)
    overlapping = [
        decision(size=0.75),
        decision(size=0.75),
    ]

    result = VectorBTProEvaluationBackend().run(
        decisions=overlapping,
        rows=rows(),
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
    )

    assert result.status == "failed"
    assert "portfolio_target_weight_exceeds_one" in result.warnings[0]


def test_vectorbtpro_evaluation_backend_real_smoke_if_installed():
    if os.environ.get("RUN_VECTORBTPRO_SMOKE") != "1":
        pytest.skip("set RUN_VECTORBTPRO_SMOKE=1 to run real VectorBT Pro smoke test")
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    pytest.importorskip("vectorbtpro")

    result = VectorBTProEvaluationBackend().run(
        decisions=[decision(size=0.25)],
        rows=rows(),
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
    )

    assert result.status == "completed"
    assert result.metrics["trade_count"] >= 1
    assert result.tables is not None
    assert "scenario_id" in result.tables.portfolio_path.columns
