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
            "null_when": "backend total return is unavailable or non-finite",
        },
        "ending_value": {
            "unit": "portfolio_value",
            "base": "portfolio NAV path",
            "aggregation": "scenario final value",
            "backend": "vectorbtpro",
            "cost_scope": "net of configured fees/slippage; excludes funding, borrow, financing, market impact",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
            "null_when": "portfolio value path is empty or final value is unavailable/non-finite",
        },
        "annualized_return": {
            "unit": "decimal_fraction_per_year",
            "base": "periodic portfolio returns",
            "aggregation": "annualized by explicit config",
            "backend": "vectorbtpro",
            "annualization": "explicit_config.annualization_periods_per_year",
            "cost_scope": "net of configured fees/slippage; excludes funding, borrow, financing, market impact",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
            "null_when": "no observed returns after the synthetic first return, total return is unavailable/non-finite, or total return <= -100%",
        },
        "volatility": {
            "unit": "decimal_fraction_per_year",
            "base": "periodic portfolio returns",
            "aggregation": "sample standard deviation annualized by explicit config",
            "backend": "vectorbtpro",
            "annualization": "explicit_config.annualization_periods_per_year",
            "cost_scope": "net of configured fees/slippage; excludes funding, borrow, financing, market impact",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
            "null_when": "fewer than two observed returns after the synthetic first return",
        },
        "sharpe": {
            "unit": "ratio",
            "base": "periodic portfolio returns",
            "aggregation": "mean return over volatility annualized by explicit config; risk-free rate zero",
            "backend": "vectorbtpro",
            "annualization": "explicit_config.annualization_periods_per_year",
            "cost_scope": "net of configured fees/slippage; excludes funding, borrow, financing, market impact",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
            "null_when": "volatility is unavailable or zero",
        },
        "sortino": {
            "unit": "ratio",
            "base": "periodic portfolio returns",
            "aggregation": "mean return over downside volatility annualized by explicit config; target return zero",
            "backend": "vectorbtpro",
            "annualization": "explicit_config.annualization_periods_per_year",
            "cost_scope": "net of configured fees/slippage; excludes funding, borrow, financing, market impact",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
            "null_when": "downside deviation is unavailable or zero; no downside returns is reported as null rather than infinity",
        },
        "calmar": {
            "unit": "ratio",
            "base": "annualized return and max drawdown",
            "aggregation": "annualized_return / abs(max_drawdown)",
            "backend": "vectorbtpro",
            "annualization": "explicit_config.annualization_periods_per_year",
            "cost_scope": "net of configured fees/slippage; excludes funding, borrow, financing, market impact",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
            "null_when": "annualized return is unavailable, max drawdown is unavailable, or max drawdown is zero",
        },
        "max_drawdown": {
            "unit": "decimal_fraction",
            "base": "portfolio NAV path",
            "aggregation": "minimum drawdown over scenario",
            "backend": "vectorbtpro",
            "cost_scope": "net of configured fees/slippage; excludes funding, borrow, financing, market impact",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
            "null_when": "backend max drawdown is unavailable or non-finite",
        },
        "trade_count": {
            "unit": "count",
            "base": "VectorBT Pro portfolio trade records",
            "aggregation": "scenario total",
            "backend": "vectorbtpro",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
            "null_when": "backend trade records are unavailable",
        },
        "win_rate": {
            "unit": "ratio",
            "base": "VectorBT Pro portfolio trade records",
            "aggregation": "winning trades / all closed trades",
            "backend": "vectorbtpro",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
            "null_when": "backend win-rate is unavailable/non-finite, including no closed trades",
        },
        "profit_factor": {
            "unit": "ratio",
            "base": "VectorBT Pro portfolio trade records",
            "aggregation": "gross profits / abs(gross losses)",
            "backend": "vectorbtpro",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
            "null_when": "backend profit factor is unavailable/non-finite; no losses is reported as null rather than infinity",
        },
        "worst_period_return": {
            "unit": "decimal_fraction",
            "base": "periodic portfolio returns",
            "aggregation": "minimum observed return after the synthetic first return",
            "backend": "vectorbtpro",
            "cost_scope": "net of configured fees/slippage; excludes funding, borrow, financing, market impact",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
            "null_when": "no observed returns after the synthetic first return",
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


def test_portfolio_metrics_use_explicit_annualized_formulas():
    class FakeTrades:
        def count(self):
            return 3

        def win_rate(self):
            return 2 / 3

        def profit_factor(self):
            return 1.75

    class FakePortfolio:
        trades = FakeTrades()

        def value(self):
            return [100.0, 102.0, 101.0, 104.0, 101.92]

        def returns(self):
            return [0.0, 0.02, -0.01, 0.03, -0.02]

        def get_total_return(self):
            return 0.08

        def get_max_drawdown(self):
            return -0.04

    observed_returns = [0.02, -0.01, 0.03, -0.02]
    annualization = 12
    mean_return = sum(observed_returns) / len(observed_returns)
    annualized_return = ((1.0 + 0.08) ** (annualization / len(observed_returns))) - 1.0
    sample_variance = sum((value - mean_return) ** 2 for value in observed_returns) / (len(observed_returns) - 1)
    volatility = math.sqrt(sample_variance) * math.sqrt(annualization)
    downside_deviation = math.sqrt(((-0.01) ** 2 + (-0.02) ** 2) / len(observed_returns)) * math.sqrt(
        annualization
    )

    metrics = backend_module._portfolio_metrics(FakePortfolio(), annualization)

    assert metrics["annualized_return"] == pytest.approx(annualized_return)
    assert metrics["volatility"] == pytest.approx(volatility)
    assert metrics["sharpe"] == pytest.approx((mean_return * annualization) / volatility)
    assert metrics["sortino"] == pytest.approx((mean_return * annualization) / downside_deviation)
    assert metrics["calmar"] == pytest.approx(annualized_return / abs(-0.04))
    assert metrics["worst_period_return"] == pytest.approx(-0.02)


def test_portfolio_metrics_emit_none_for_unavailable_annualized_metrics_and_degenerate_trades():
    class NoTradeStats:
        def count(self):
            return 0

        def win_rate(self):
            return math.nan

        def profit_factor(self):
            return math.nan

    class NoLossTradeStats:
        def count(self):
            return 2

        def win_rate(self):
            return 1.0

        def profit_factor(self):
            return math.inf

    class FakePortfolio:
        def __init__(self, trades):
            self.trades = trades

        def value(self):
            return [100.0]

        def returns(self):
            return [math.nan]

        def get_total_return(self):
            return 0.0

        def get_max_drawdown(self):
            return 0.0

    no_trade_metrics = backend_module._portfolio_metrics(FakePortfolio(NoTradeStats()), 252)
    no_loss_metrics = backend_module._portfolio_metrics(FakePortfolio(NoLossTradeStats()), 252)

    for name in ("annualized_return", "volatility", "sharpe", "sortino", "calmar"):
        assert no_trade_metrics[name] is None
        assert no_loss_metrics[name] is None
    assert no_trade_metrics["worst_period_return"] is None
    assert no_trade_metrics["win_rate"] is None
    assert no_trade_metrics["profit_factor"] is None
    assert no_loss_metrics["win_rate"] == pytest.approx(1.0)
    assert no_loss_metrics["profit_factor"] is None


def test_vectorbtpro_evaluation_backend_emits_no_trade_evidence_for_zero_decisions(
    monkeypatch: pytest.MonkeyPatch,
):
    pd = pytest.importorskip("pandas")

    class NoTradeStats:
        @property
        def records_readable(self):
            return pd.DataFrame()

        def count(self):
            return 0

        def win_rate(self):
            return math.nan

        def profit_factor(self):
            return math.nan

    class FakePortfolio:
        trades = NoTradeStats()

        def value(self):
            return pd.Series([100.0, 100.0, 100.0])

        def returns(self):
            return pd.Series([0.0, 0.0, 0.0])

        def drawdowns(self):
            return pd.Series([0.0, 0.0, 0.0])

        def get_total_return(self):
            return 0.0

        def get_max_drawdown(self):
            return 0.0

    captured = {}

    def from_signals(close, **kwargs):
        captured["close_columns"] = list(close.columns)
        captured["kwargs"] = kwargs
        return FakePortfolio()

    fake_vbt = SimpleNamespace(Portfolio=SimpleNamespace(from_signals=from_signals))
    fake_pyarrow = SimpleNamespace(__name__="pyarrow")
    monkeypatch.setattr(
        backend_module,
        "require_evaluation_dependencies",
        lambda: EvaluationDependencies(pandas=pd, pyarrow=fake_pyarrow, vectorbtpro=fake_vbt),
    )

    result = VectorBTProEvaluationBackend().run(
        decisions=[],
        rows=rows(),
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
    )

    assert result.status == "completed"
    assert result.metrics["total_return"] == pytest.approx(0.0)
    assert result.metrics["trade_count"] == 0
    assert result.metrics["win_rate"] is None
    assert result.metrics["profit_factor"] is None
    assert result.metrics["worst_period_return"] == pytest.approx(0.0)
    assert result.tables is not None
    assert not result.tables.portfolio_path.empty
    assert result.tables.trades.empty
    assert result.tables.target_positions.empty
    assert result.tables.target_exposure_summary.empty
    assert captured["close_columns"] == ["BTC-PERP"]


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

    captured = {"calls": []}

    def from_signals(close, **kwargs):
        call = {"close": close, "close_columns": list(close.columns), "kwargs": kwargs}
        captured["calls"].append(call)
        captured["close_columns"] = call["close_columns"]
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


def test_prepare_inputs_accepts_no_decisions_as_no_trade_evidence(monkeypatch: pytest.MonkeyPatch):
    pd = pytest.importorskip("pandas")
    fake_vbt = SimpleNamespace(Portfolio=SimpleNamespace(from_signals=lambda close, **kwargs: None))
    fake_pyarrow = SimpleNamespace(__name__="pyarrow")
    monkeypatch.setattr(
        backend_module,
        "require_evaluation_dependencies",
        lambda: EvaluationDependencies(pandas=pd, pyarrow=fake_pyarrow, vectorbtpro=fake_vbt),
    )

    prepared = VectorBTProEvaluationBackend().prepare_inputs(decisions=[], rows=rows())

    assert prepared.decisions == ()
    assert list(prepared.close.columns) == ["BTC-PERP"]


def test_run_prepared_reuses_filtered_inputs_for_multiple_scenarios(monkeypatch: pytest.MonkeyPatch):
    pd = pytest.importorskip("pandas")
    captured = install_fake_vbt(monkeypatch)
    extra_rows = rows() + [
        {"symbol": "ETH-PERP", "timestamp": AS_OF, "close": 200.0},
        {"symbol": "ETH-PERP", "timestamp": DECISION, "close": 201.0},
        {"symbol": "ETH-PERP", "timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc), "close": 202.0},
        {"symbol": "ETH-PERP", "timestamp": datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc), "close": 203.0},
    ]
    base_scenario = scenario()
    stress_scenario = base_scenario.model_copy(
        update={
            "scenario_id": "w/stress_costs/base_fill",
            "cost_scenario": "stress_costs",
            "cost_model": CostModelConfig(fee_bps_per_side=7.0, slippage_bps_per_side=11.0),
        }
    )
    backend = VectorBTProEvaluationBackend()

    prepared = backend.prepare_inputs(decisions=[decision()], rows=extra_rows)
    original_close = prepared.close
    original_snapshot = prepared.close.copy(deep=True)
    results = [
        backend.run_prepared(
            prepared=prepared,
            scenario=item,
            metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
        )
        for item in (base_scenario, stress_scenario)
    ]

    assert [result.status for result in results] == ["completed", "completed"]
    assert all(result.tables is not None for result in results)
    assert all(not result.tables.portfolio_path.empty for result in results if result.tables is not None)
    assert all(not result.tables.trades.empty for result in results if result.tables is not None)
    assert list(prepared.close.columns) == ["BTC-PERP"]
    assert "ETH-PERP" not in prepared.close.columns
    assert len(captured["calls"]) == 2
    assert [call["close_columns"] for call in captured["calls"]] == [["BTC-PERP"], ["BTC-PERP"]]
    assert [id(call["close"]) for call in captured["calls"]] == [id(original_close), id(original_close)]
    assert captured["calls"][0]["kwargs"]["fees"] == pytest.approx(0.0001)
    assert captured["calls"][0]["kwargs"]["slippage"] == pytest.approx(0.0002)
    assert captured["calls"][1]["kwargs"]["fees"] == pytest.approx(0.0007)
    assert captured["calls"][1]["kwargs"]["slippage"] == pytest.approx(0.0011)
    assert prepared.close is original_close
    pd.testing.assert_frame_equal(prepared.close, original_snapshot)


def test_run_prepared_reuses_multi_symbol_close_in_decision_order(monkeypatch: pytest.MonkeyPatch):
    pd = pytest.importorskip("pandas")
    captured = install_fake_vbt(monkeypatch)
    timestamps = [
        AS_OF,
        DECISION,
        datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
    ]
    multi_symbol_rows = [
        {"symbol": symbol, "timestamp": timestamp, "close": close}
        for symbol, closes in {
            "QQQ": [100.0, 101.0, 102.0, 103.0],
            "SPY": [200.0, 201.0, 202.0, 203.0],
            "IWM": [300.0, 301.0, 302.0, 303.0],
        }.items()
        for timestamp, close in zip(timestamps, closes, strict=True)
    ]
    decisions = [
        decision(symbol="SPY", size=0.4),
        decision(symbol="QQQ", size=0.4),
    ]
    base_scenario = scenario()
    stress_scenario = base_scenario.model_copy(
        update={
            "scenario_id": "w/stress_costs/base_fill",
            "cost_scenario": "stress_costs",
            "cost_model": CostModelConfig(fee_bps_per_side=7.0, slippage_bps_per_side=11.0),
        }
    )
    backend = VectorBTProEvaluationBackend()

    prepared = backend.prepare_inputs(decisions=decisions, rows=multi_symbol_rows)
    original_close = prepared.close
    original_snapshot = prepared.close.copy(deep=True)
    results = [
        backend.run_prepared(
            prepared=prepared,
            scenario=item,
            metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
        )
        for item in (base_scenario, stress_scenario)
    ]

    assert [result.status for result in results] == ["completed", "completed"]
    assert list(prepared.close.columns) == ["SPY", "QQQ"]
    assert "IWM" not in prepared.close.columns
    assert len(captured["calls"]) == 2
    assert [call["close_columns"] for call in captured["calls"]] == [["SPY", "QQQ"], ["SPY", "QQQ"]]
    assert [id(call["close"]) for call in captured["calls"]] == [id(original_close), id(original_close)]
    assert prepared.close is original_close
    pd.testing.assert_frame_equal(prepared.close, original_snapshot)


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
    assert not result.tables.target_positions.empty
    assert not result.tables.target_exposure_summary.empty
    assert list(result.tables.target_positions["event"]) == ["entry", "exit"]
    assert result.tables.target_positions.loc[0, "asset"] == "BTC-PERP"
    assert result.tables.target_positions.loc[0, "target_weight"] == pytest.approx(1.0)
    assert result.tables.target_positions.loc[1, "target_weight"] == pytest.approx(0.0)
    assert result.tables.target_exposure_summary.loc[0, "decision_count"] == 1
    assert result.tables.target_exposure_summary.loc[0, "target_round_trip_turnover"] == pytest.approx(2.0)
    assert set(captured["close_columns"]) == {"BTC-PERP"}
    assert captured["kwargs"]["cash_sharing"] is True
    assert captured["kwargs"]["group_by"] is True
    assert captured["kwargs"]["size_type"] == "valuepercent"
    assert captured["kwargs"]["init_cash"] == pytest.approx(100.0)
    assert captured["kwargs"]["fees"] == pytest.approx(0.0001)
    assert captured["kwargs"]["slippage"] == pytest.approx(0.0002)
    entry_time = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
    assert captured["kwargs"]["size"].loc[entry_time, "BTC-PERP"] == pytest.approx(1.0)


def test_vectorbtpro_evaluation_backend_accepts_property_paths_and_drawdowns_object(
    monkeypatch: pytest.MonkeyPatch,
):
    pd = pytest.importorskip("pandas")

    class FakeTrades:
        def count(self):
            return 1

        @property
        def records_readable(self):
            return pd.DataFrame({"Trade Id": [1], "Column": ["BTC-PERP"]})

    class FakeDrawdowns:
        @property
        def drawdown(self):
            return pd.Series([0.0, 0.0, -0.019801980198])

    class FakePortfolio:
        trades = FakeTrades()

        def __init__(self, close, **kwargs):
            self.close = close
            self.kwargs = kwargs
            self.value = pd.Series([100.0, 101.0, 99.0])
            self.returns = pd.Series([0.0, 0.01, -0.019801980198])
            self.drawdowns = FakeDrawdowns()

        def get_total_return(self):
            return -0.01

        def get_max_drawdown(self):
            return -0.019801980198

    def from_signals(close, **kwargs):
        return FakePortfolio(close, **kwargs)

    fake_vbt = SimpleNamespace(Portfolio=SimpleNamespace(from_signals=from_signals))
    fake_pyarrow = SimpleNamespace(__name__="pyarrow")
    monkeypatch.setattr(
        backend_module,
        "require_evaluation_dependencies",
        lambda: EvaluationDependencies(pandas=pd, pyarrow=fake_pyarrow, vectorbtpro=fake_vbt),
    )

    result = VectorBTProEvaluationBackend().run(
        decisions=[decision()],
        rows=rows(),
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
    )

    assert result.status == "completed"
    assert result.tables is not None
    assert list(result.tables.portfolio_path["scenario_id"].unique()) == ["w/realistic_costs/base_fill"]
    assert "portfolio_value" in result.tables.portfolio_path.columns
    assert "period_return" in result.tables.portfolio_path.columns
    assert "drawdown" in result.tables.portfolio_path.columns
    assert result.tables.portfolio_path["drawdown"].min() == pytest.approx(-0.019801980198)


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


def test_prepared_decision_windows_reject_same_symbol_overlap_after_different_entries(monkeypatch: pytest.MonkeyPatch):
    install_fake_vbt(monkeypatch)
    overlap_rows = rows() + [
        {"symbol": "BTC-PERP", "timestamp": datetime(2026, 1, 1, 0, 4, tzinfo=timezone.utc), "close": 104.0},
    ]
    later_decision = decision(size=0.4).model_copy(
        update={"decision_time": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)}
    )
    prepared = VectorBTProEvaluationBackend().prepare_inputs(
        decisions=[decision(size=0.4), later_decision],
        rows=overlap_rows,
    )

    with pytest.raises(ValueError, match="^overlapping_decision_window:BTC-PERP:"):
        backend_module._prepared_decision_windows(prepared, scenario())


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
