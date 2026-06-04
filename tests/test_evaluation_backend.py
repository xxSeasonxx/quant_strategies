from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import quant_strategies.evaluation._portfolio_common as common_module
import quant_strategies.evaluation.vectorbtpro_backend as backend_module
import quant_strategies.evaluation.project_perp_ledger as perp_module
from quant_strategies.core.config import CostModelConfig, FillModelConfig
from quant_strategies.decisions import DecisionIntent, ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.evaluation.vectorbtpro_backend import VectorBTProEvaluationBackend
from quant_strategies.evaluation.backends import (
    DataKindNamedEvaluationBackend,
    EvaluationBackend,
    PreparedEvaluationBackend,
)
from quant_strategies.evaluation.config import EvaluationMetricsConfig
from quant_strategies.evaluation.dependencies import EvaluationDependencies
from quant_strategies.evaluation.scenarios import EvaluationScenario


ANNUALIZED_RISK_METRICS = ("annualized_return", "volatility", "sharpe", "sortino", "calmar")


def test_vectorbtpro_backend_remains_public_compatibility_adapter():
    from quant_strategies.evaluation.vectorbtpro_backend import VectorBTProEvaluationBackend as imported

    assert imported is VectorBTProEvaluationBackend


def test_vectorbtpro_backend_satisfies_evaluation_backend_protocols():
    backend = VectorBTProEvaluationBackend()

    assert isinstance(backend, EvaluationBackend)
    assert isinstance(backend, PreparedEvaluationBackend)
    assert isinstance(backend, DataKindNamedEvaluationBackend)


def test_evaluation_metric_semantics_label_nav_metrics_as_portfolio_evidence():
    from quant_strategies.evaluation.metrics import MetricValue, evaluation_metric_semantics

    semantics = evaluation_metric_semantics()

    assert MetricValue == float | int | str | bool | None
    assert semantics["total_return"]["base"] == "portfolio NAV path"
    assert "project_perp_ledger_v1" in str(semantics["total_return"]["backend"])
    assert "includes funding cashflows for crypto_perp_funding" in str(semantics["total_return"]["cost_scope"])
    assert semantics["funding_cashflow_total"]["base"] == "funding_cashflows trace table"
    assert semantics["funding_event_count"]["unit"] == "count"
    assert semantics["funding_model"]["null_when"].startswith("never")
    assert (
        semantics["total_return"]["not_authority"]
        == "not validation, promotion, paper trading, or live trading authority"
    )
    assert "net_return" not in semantics
    assert "turnover" not in semantics


def test_evaluation_backend_split_keeps_project_perp_ledger_in_dedicated_module():
    backend = VectorBTProEvaluationBackend()

    assert common_module.prepared_decision_windows
    assert perp_module.run_perp_ledger
    assert backend.name_for_data_kind("crypto_perp_funding") == perp_module.PROJECT_PERP_FUNDING_MODEL


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
    assert common_module.observed_returns([math.nan, 0.01, -0.02]) == [0.01, -0.02]
    assert common_module.observed_returns([0.0, math.nan, 0.03]) == [0.03]


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

    payload = backend_module._portfolio_metrics(FakePortfolio(), annualization, min_annualized_samples=4)
    metrics = payload.metrics

    assert payload.warnings == ()
    assert metrics["annualized_return"] == pytest.approx(annualized_return)
    assert metrics["volatility"] == pytest.approx(volatility)
    assert metrics["sharpe"] == pytest.approx((mean_return * annualization) / volatility)
    assert metrics["sortino"] == pytest.approx((mean_return * annualization) / downside_deviation)
    assert metrics["calmar"] == pytest.approx(annualized_return / abs(-0.04))
    assert metrics["worst_period_return"] == pytest.approx(-0.02)
    assert metrics["return_total_count_excluding_initial"] == 4
    assert metrics["return_sample_count"] == 4
    assert metrics["return_nonfinite_count"] == 0


def test_portfolio_metrics_fail_when_max_drawdown_is_positive():
    class FakeTrades:
        def count(self):
            return 1

        def win_rate(self):
            return 1.0

        def profit_factor(self):
            return 2.0

    class FakePortfolio:
        trades = FakeTrades()

        def value(self):
            return [100.0, 101.0]

        def returns(self):
            return [0.0, 0.01]

        def get_total_return(self):
            return 0.01

        def get_max_drawdown(self):
            return 0.05

    with pytest.raises(ValueError, match="invalid_required_metric:max_drawdown"):
        backend_module._portfolio_metrics(FakePortfolio(), 252, min_annualized_samples=2)


def test_portfolio_metrics_null_annualized_family_when_return_sample_is_too_short():
    class FakeTrades:
        def count(self):
            return 1

        def win_rate(self):
            return 1.0

        def profit_factor(self):
            return math.inf

    class FakePortfolio:
        trades = FakeTrades()

        def value(self):
            return [100.0, 101.0, 100.5]

        def returns(self):
            return [0.0, 0.01, -0.004950495]

        def get_total_return(self):
            return 0.005

        def get_max_drawdown(self):
            return -0.004950495

    payload = backend_module._portfolio_metrics(FakePortfolio(), 252, min_annualized_samples=4)
    metrics = payload.metrics

    for name in ANNUALIZED_RISK_METRICS:
        assert metrics[name] is None
    assert metrics["total_return"] == pytest.approx(0.005)
    assert metrics["ending_value"] == pytest.approx(100.5)
    assert metrics["max_drawdown"] == pytest.approx(-0.004950495)
    assert metrics["return_sample_count"] == 2
    assert metrics["return_total_count_excluding_initial"] == 2
    assert metrics["return_nonfinite_count"] == 0
    assert metrics["worst_period_return"] == pytest.approx(-0.004950495)
    assert "annualized_metrics_insufficient_samples:2:min_required=4" in payload.warnings


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

    no_trade_metrics = backend_module._portfolio_metrics(FakePortfolio(NoTradeStats()), 252).metrics
    no_loss_metrics = backend_module._portfolio_metrics(FakePortfolio(NoLossTradeStats()), 252).metrics

    for name in ("annualized_return", "volatility", "sharpe", "sortino", "calmar"):
        assert no_trade_metrics[name] is None
        assert no_loss_metrics[name] is None
    assert no_trade_metrics["worst_period_return"] is None
    assert no_trade_metrics["win_rate"] is None
    assert no_trade_metrics["profit_factor"] is None
    assert no_loss_metrics["win_rate"] == pytest.approx(1.0)
    assert no_loss_metrics["profit_factor"] is None


def test_portfolio_metrics_emit_return_coverage_and_null_annualized_metrics_for_nonfinite_returns():
    class FakeTrades:
        def count(self):
            return 1

        def win_rate(self):
            return 1.0

        def profit_factor(self):
            return math.inf

    class FakePortfolio:
        trades = FakeTrades()

        def value(self):
            return [100.0, 101.0, 102.0, 103.0]

        def returns(self):
            return [0.0, math.nan, math.inf, 0.01]

        def get_total_return(self):
            return 0.03

        def get_max_drawdown(self):
            return -0.01

    payload = backend_module._portfolio_metrics(FakePortfolio(), 252)

    assert payload.metrics["return_total_count_excluding_initial"] == 3
    assert payload.metrics["return_sample_count"] == 1
    assert payload.metrics["return_nonfinite_count"] == 2
    assert payload.metrics["annualized_return"] is None
    assert payload.metrics["volatility"] is None
    assert payload.metrics["sharpe"] is None
    assert payload.metrics["sortino"] is None
    assert payload.metrics["calmar"] is None
    assert payload.metrics["worst_period_return"] is None
    assert "return_coverage_nonfinite:2" in payload.warnings


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
    assert result.metrics["funding_cashflow_total"] == pytest.approx(0.0)
    assert result.metrics["funding_event_count"] == 0
    assert result.metrics["funding_model"] == "none"
    assert result.metrics["worst_period_return"] == pytest.approx(0.0)
    assert result.tables is not None
    assert not result.tables.portfolio_path.empty
    assert result.tables.trades.empty
    assert result.tables.target_positions.empty
    assert result.tables.target_exposure_summary.empty
    assert result.tables.funding_cashflows.empty
    assert captured["close_columns"] == ["BTC-PERP"]


@pytest.mark.parametrize(
    ("failing_method", "expected_warning"),
    [
        ("get_total_return", "metric_extraction_failed:total_return:metrics unavailable"),
        ("value", "metric_extraction_failed:ending_value:metrics unavailable"),
    ],
)
def test_vectorbtpro_evaluation_backend_fails_when_required_metric_accessor_raises(
    monkeypatch: pytest.MonkeyPatch,
    failing_method: str,
    expected_warning: str,
):
    pd = pytest.importorskip("pandas")

    class FakeTrades:
        def count(self):
            return 1

        @property
        def records_readable(self):
            return pd.DataFrame({"Trade Id": [1], "Column": ["BTC-PERP"]})

    class FakePortfolio:
        trades = FakeTrades()

        def value(self):
            if failing_method == "value":
                raise RuntimeError("metrics unavailable")
            return pd.Series([100.0, 101.0])

        def returns(self):
            return pd.Series([0.0, 0.01])

        def drawdowns(self):
            return pd.Series([0.0, -0.01])

        def get_total_return(self):
            if failing_method == "get_total_return":
                raise RuntimeError("metrics unavailable")
            return 0.01

        def get_max_drawdown(self):
            return -0.01

    fake_vbt = SimpleNamespace(Portfolio=SimpleNamespace(from_signals=lambda close, **kwargs: FakePortfolio()))
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

    assert result.status == "failed"
    assert result.metrics == {}
    assert result.tables is None
    assert expected_warning in result.warnings


@pytest.mark.parametrize(
    ("metric_method", "expected_warning"),
    [
        ("get_total_return", "invalid_required_metric:total_return"),
        ("get_max_drawdown", "invalid_required_metric:max_drawdown"),
    ],
)
def test_vectorbtpro_evaluation_backend_fails_when_required_metric_is_nonfinite(
    monkeypatch: pytest.MonkeyPatch,
    metric_method: str,
    expected_warning: str,
):
    pd = pytest.importorskip("pandas")

    class FakeTrades:
        def count(self):
            return 1

        @property
        def records_readable(self):
            return pd.DataFrame({"Trade Id": [1], "Column": ["BTC-PERP"]})

    class FakePortfolio:
        trades = FakeTrades()

        def value(self):
            return pd.Series([100.0, 101.0])

        def returns(self):
            return pd.Series([0.0, 0.01])

        def drawdowns(self):
            return pd.Series([0.0, -0.01])

        def get_total_return(self):
            return math.inf if metric_method == "get_total_return" else 0.01

        def get_max_drawdown(self):
            return math.nan if metric_method == "get_max_drawdown" else -0.01

    fake_vbt = SimpleNamespace(Portfolio=SimpleNamespace(from_signals=lambda close, **kwargs: FakePortfolio()))
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

    assert result.status == "failed"
    assert result.metrics == {}
    assert expected_warning in result.warnings


@pytest.mark.parametrize("portfolio_values", [[100.0, 101.0, math.nan], [100.0, 101.0, math.inf], []])
def test_vectorbtpro_evaluation_backend_fails_when_final_portfolio_value_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
    portfolio_values: list[float],
):
    pd = pytest.importorskip("pandas")

    class FakeTrades:
        def count(self):
            return 1

        @property
        def records_readable(self):
            return pd.DataFrame({"Trade Id": [1], "Column": ["BTC-PERP"]})

    class FakePortfolio:
        trades = FakeTrades()

        def value(self):
            return pd.Series(portfolio_values, dtype=float)

        def returns(self):
            return pd.Series([0.0, 0.01, 0.01])

        def drawdowns(self):
            return pd.Series([0.0, -0.01, -0.01])

        def get_total_return(self):
            return 0.01

        def get_max_drawdown(self):
            return -0.01

    fake_vbt = SimpleNamespace(Portfolio=SimpleNamespace(from_signals=lambda close, **kwargs: FakePortfolio()))
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

    assert result.status == "failed"
    assert result.metrics == {}
    assert "invalid_required_metric:ending_value" in result.warnings


@pytest.mark.parametrize(
    "portfolio_path",
    [
        {"portfolio_value": [100.0, 101.0, math.nan], "period_return": [0.0, 0.01, 0.01], "drawdown": [0.0, -0.01, -0.01]},
        {"portfolio_value": [100.0, 101.0, math.inf], "period_return": [0.0, 0.01, 0.01], "drawdown": [0.0, -0.01, -0.01]},
        {"portfolio_value": [], "period_return": [], "drawdown": []},
        {"period_return": [0.0, 0.01], "drawdown": [0.0, -0.01]},
    ],
)
def test_perp_ledger_metrics_fail_when_final_portfolio_value_is_invalid(portfolio_path: dict[str, list[float]]):
    pd = pytest.importorskip("pandas")
    portfolio_path = pd.DataFrame(portfolio_path)
    trades = pd.DataFrame({"net_pnl": [1.0]})

    with pytest.raises(ValueError, match="invalid_required_metric:ending_value"):
        perp_module.perp_ledger_metrics(
            portfolio_path,
            trades,
            annualization_periods_per_year=252,
            funding_cashflow_total=0.0,
            funding_event_count=0,
        )


def test_perp_ledger_metrics_fail_when_max_drawdown_is_positive():
    pd = pytest.importorskip("pandas")
    portfolio_path = pd.DataFrame(
        {
            "portfolio_value": [100.0, 101.0],
            "period_return": [0.0, 0.01],
            "drawdown": [0.01, 0.05],
        }
    )
    trades = pd.DataFrame({"net_pnl": [1.0]})

    with pytest.raises(ValueError, match="invalid_required_metric:max_drawdown"):
        perp_module.perp_ledger_metrics(
            portfolio_path,
            trades,
            annualization_periods_per_year=252,
            funding_cashflow_total=0.0,
            funding_event_count=0,
        )


def test_perp_ledger_metrics_null_annualized_family_when_return_sample_is_too_short():
    pd = pytest.importorskip("pandas")
    portfolio_path = pd.DataFrame(
        {
            "portfolio_value": [100.0, 101.0, 100.5],
            "period_return": [0.0, 0.01, -0.004950495],
            "drawdown": [0.0, 0.0, -0.004950495],
        }
    )
    trades = pd.DataFrame({"net_pnl": [0.5]})

    payload = perp_module.perp_ledger_metrics(
        portfolio_path,
        trades,
        annualization_periods_per_year=252,
        min_annualized_samples=4,
        funding_cashflow_total=0.0,
        funding_event_count=0,
    )
    metrics = payload.metrics

    for name in ANNUALIZED_RISK_METRICS:
        assert metrics[name] is None
    assert metrics["total_return"] == pytest.approx(0.005)
    assert metrics["ending_value"] == pytest.approx(100.5)
    assert metrics["max_drawdown"] == pytest.approx(-0.004950495)
    assert metrics["return_sample_count"] == 2
    assert metrics["return_total_count_excluding_initial"] == 2
    assert metrics["return_nonfinite_count"] == 0
    assert metrics["worst_period_return"] == pytest.approx(-0.004950495)
    assert metrics["funding_cashflow_total"] == pytest.approx(0.0)
    assert metrics["funding_event_count"] == 0
    assert "annualized_metrics_insufficient_samples:2:min_required=4" in payload.warnings


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
    assert result.metrics["funding_cashflow_total"] == pytest.approx(0.0)
    assert result.metrics["funding_event_count"] == 0
    assert result.metrics["funding_model"] == "none"
    assert "sharpe" in result.metrics
    assert result.tables is not None
    assert not result.tables.portfolio_path.empty
    assert not result.tables.trades.empty
    assert not result.tables.target_positions.empty
    assert not result.tables.target_exposure_summary.empty
    assert result.tables.funding_cashflows.empty
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


def test_crypto_perp_funding_unsupported_result_uses_project_ledger_backend_name():
    bad = decision()
    bad = bad.model_copy(update={"exit_policy": ExitPolicy(max_hold_bars=1, stop_loss_bps=100.0)})

    result = VectorBTProEvaluationBackend().run(
        decisions=[bad],
        rows=rows(),
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
        data_kind="crypto_perp_funding",
    )

    assert result.status == "unsupported"
    assert result.backend == "project_perp_ledger_v1"


def test_crypto_perp_funding_prepare_failure_uses_project_ledger_backend_name():
    result = VectorBTProEvaluationBackend().run(
        decisions=[decision()],
        rows=[
            {"symbol": "ETH-PERP", "timestamp": AS_OF, "close": 100.0},
            {"symbol": "ETH-PERP", "timestamp": DECISION, "close": 101.0},
        ],
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
        data_kind="crypto_perp_funding",
    )

    assert result.status == "failed"
    assert result.backend == "project_perp_ledger_v1"


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


def test_max_gross_target_weight_allows_same_timestamp_cross_asset_rollover(
    monkeypatch: pytest.MonkeyPatch,
):
    install_fake_vbt(monkeypatch)
    timestamps = [
        AS_OF,
        DECISION,
        datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 0, 4, tzinfo=timezone.utc),
    ]
    rollover_rows = [
        {"symbol": symbol, "timestamp": timestamp, "close": close}
        for symbol, closes in {
            "BTC-PERP": [100.0, 101.0, 102.0, 103.0, 104.0],
            "ETH-PERP": [200.0, 201.0, 202.0, 203.0, 204.0],
        }.items()
        for timestamp, close in zip(timestamps, closes, strict=True)
    ]
    later_decision_time = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
    rollover = [
        decision(symbol="BTC-PERP", size=1.0),
        decision(symbol="ETH-PERP", size=1.0).model_copy(
            update={"decision_time": later_decision_time, "as_of_time": later_decision_time}
        ),
    ]

    result = VectorBTProEvaluationBackend().run(
        decisions=rollover,
        rows=rollover_rows,
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
    )

    assert result.status == "completed"


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
        common_module.prepared_decision_windows(prepared, scenario())


def test_vectorbtpro_evaluation_backend_real_smoke_if_installed():
    if os.environ.get("RUN_VECTORBTPRO_SMOKE") != "1":
        pytest.skip("set RUN_VECTORBTPRO_SMOKE=1 to run real VectorBT Pro smoke test")
    import pandas  # noqa: F401
    import pyarrow  # noqa: F401
    import vectorbtpro  # noqa: F401

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
