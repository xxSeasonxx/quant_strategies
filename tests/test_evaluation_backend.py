from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import pytest

from quant_strategies.core.config import CostModelConfig, FillModelConfig
from quant_strategies.core.portfolio_foundation import (
    BookWalkResult,
    FeasibilityVerdict,
    FundingEvent,
    PortfolioPathPoint,
    RoundTrip,
)
from quant_strategies.decisions import InstrumentRef, TargetDecision
from quant_strategies.evaluation._spine_metrics import spine_metric_payload, spine_trace_tables
from quant_strategies.evaluation.backends import EvaluationBackend, PreparedEvaluationBackend
from quant_strategies.evaluation.config import EvaluationMetricsConfig
from quant_strategies.evaluation.metrics import SHARED_ACCOUNTING_MODEL
from quant_strategies.evaluation.scenarios import EvaluationScenario
from quant_strategies.evaluation.spine_backend import SpineEvaluationBackend

ANNUALIZED_RISK_METRICS = ("annualized_return", "volatility", "sharpe", "sortino", "calmar")

AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)


def rows() -> list[dict[str, Any]]:
    return [
        {"symbol": "BTC-PERP", "timestamp": AS_OF, "close": 100.0, "has_funding_event": False},
        {"symbol": "BTC-PERP", "timestamp": DECISION, "close": 101.0, "has_funding_event": False},
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
            "close": 102.0,
            "has_funding_event": False,
        },
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 3, tzinfo=UTC),
            "close": 103.0,
            "has_funding_event": False,
        },
    ]


def decision(*, symbol: str = "BTC-PERP", target: float = 1.0):
    return TargetDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol=symbol),
        decision_time=DECISION,
        as_of_time=AS_OF,
        target=target,
    )


def flat(symbol: str = "BTC-PERP", *, when: datetime):
    return TargetDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol=symbol),
        decision_time=when,
        as_of_time=when,
        target=0.0,
    )


def scenario(**overrides: Any) -> EvaluationScenario:
    base = {
        "scenario_id": "w/realistic_costs/base_fill",
        "window_id": "w",
        "cost_scenario": "realistic_costs",
        "fill_scenario": "base_fill",
        "cost_model": CostModelConfig(fee_bps_per_side=1.0, slippage_bps_per_side=2.0),
        "fill_model": FillModelConfig(price="close", entry_lag_bars=1, exit_lag_bars=0),
    }
    base.update(overrides)
    return EvaluationScenario(**base)


# --- one shared book on every surface; no data-kind routing ------------------


def test_spine_backend_is_the_single_named_accounting_model():
    backend = SpineEvaluationBackend()

    assert backend.name == SHARED_ACCOUNTING_MODEL
    assert backend.name != "project_perp_ledger_v1"


def test_spine_backend_satisfies_evaluation_backend_protocols():
    backend = SpineEvaluationBackend()

    assert isinstance(backend, EvaluationBackend)
    assert isinstance(backend, PreparedEvaluationBackend)


def test_spine_backend_has_no_data_kind_routing_hook():
    # The retired data-kind naming hook must be gone: one model identity for all kinds.
    backend = SpineEvaluationBackend()

    assert not hasattr(backend, "name_for_data_kind")


# --- completed evaluation through the netted book ----------------------------


def test_spine_backend_returns_metrics_and_tables_for_a_long_round_trip():
    decisions = [decision(target=1.0), flat(when=datetime(2026, 1, 1, 0, 2, tzinfo=UTC))]

    result = SpineEvaluationBackend().run(
        decisions=decisions,
        rows=rows(),
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
    )

    assert result.status == "completed"
    assert result.backend == SHARED_ACCOUNTING_MODEL
    assert result.scenario_id == "w/realistic_costs/base_fill"
    assert result.metrics["funding_model"] == SHARED_ACCOUNTING_MODEL
    assert result.metrics["trade_count"] == 1
    assert result.metrics["funding_cashflow_total"] == pytest.approx(0.0)
    assert result.metrics["funding_event_count"] == 0
    assert math.isfinite(float(result.metrics["total_return"]))
    assert float(result.metrics["max_drawdown"]) <= 0.0
    assert result.tables is not None
    assert not result.tables.portfolio_path.empty
    assert "period_return" in result.tables.portfolio_path.columns
    assert not result.tables.trades.empty
    assert list(result.tables.target_positions["event"]) == ["entry", "exit"]
    assert result.tables.funding_cashflows.empty


def test_spine_backend_emits_no_trade_evidence_for_zero_decisions():
    result = SpineEvaluationBackend().run(
        decisions=[],
        rows=rows(),
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
    )

    assert result.status == "completed"
    assert result.metrics["trade_count"] == 0
    assert result.metrics["total_return"] == pytest.approx(0.0)
    assert result.metrics["win_rate"] is None
    assert result.metrics["profit_factor"] is None
    assert result.metrics["funding_model"] == SHARED_ACCOUNTING_MODEL
    assert result.tables is not None
    assert result.tables.trades.empty
    assert result.tables.target_positions.empty
    assert result.tables.funding_cashflows.empty


def test_spine_backend_accepts_leveraged_intent_but_fails_closed_on_budget_breach():
    # Two same-bar 0.75 targets -> intended gross 1.5 > 1.0 budget. The decision shape
    # is accepted; the typed feasibility verdict makes the scenario fail (never clamped).
    leveraged = [
        decision(symbol="BTC-PERP", target=0.75),
        decision(symbol="ETH-PERP", target=0.75),
    ]
    eth_rows = [{**row, "symbol": "ETH-PERP", "close": row["close"] * 2.0} for row in rows()]

    result = SpineEvaluationBackend().run(
        decisions=leveraged,
        rows=[*rows(), *eth_rows],
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
    )

    assert result.status == "failed"
    assert any(
        "feasibility_breach:leverage_budget_breach" in warning for warning in result.warnings
    )
    assert result.tables is None


def test_spine_backend_models_funding_for_crypto_perp_kind():
    funding_rows = rows()
    funding_rows.append(
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 4, tzinfo=UTC),
            "close": 104.0,
            "funding_timestamp": datetime(2026, 1, 1, 0, 4, tzinfo=UTC),
            "funding_rate": 0.0003,
            "has_funding_event": True,
        }
    )
    # Flat decision_time 0:03 fills at 0:04 (entry_lag 1); the 0:04 funding event is
    # charged on the still-open net position before that bar's flatten.
    decisions = [decision(target=1.0), flat(when=datetime(2026, 1, 1, 0, 3, tzinfo=UTC))]

    result = SpineEvaluationBackend().run(
        decisions=decisions,
        rows=funding_rows,
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
        data_kind="crypto_perp_funding",
    )

    assert result.status == "completed"
    assert result.metrics["funding_model"] == SHARED_ACCOUNTING_MODEL
    assert result.metrics["funding_event_count"] == 1
    assert result.metrics["funding_cashflow_total"] != 0.0
    assert result.tables is not None
    assert not result.tables.funding_cashflows.empty
    assert list(result.tables.funding_cashflows["asset"]) == ["BTC-PERP"]


def test_spine_backend_run_prepared_reuses_window_inputs_across_scenarios():
    backend = SpineEvaluationBackend()
    decisions = [decision(target=0.5), flat(when=datetime(2026, 1, 1, 0, 2, tzinfo=UTC))]
    prepared = backend.prepare_inputs(decisions=decisions, rows=rows())

    base = scenario()
    stress = scenario(
        scenario_id="w/stress_costs/base_fill",
        cost_scenario="stress_costs",
        cost_model=CostModelConfig(fee_bps_per_side=7.0, slippage_bps_per_side=11.0),
    )
    results = [
        backend.run_prepared(
            prepared=prepared,
            scenario=item,
            metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
        )
        for item in (base, stress)
    ]

    assert [result.status for result in results] == ["completed", "completed"]
    # Higher costs erode the realized total return.
    assert float(results[1].metrics["total_return"]) < float(results[0].metrics["total_return"])


# --- metric semantics + helpers ----------------------------------------------


def test_evaluation_metric_semantics_label_the_single_shared_model():
    from quant_strategies.evaluation.metrics import MetricValue, evaluation_metric_semantics

    semantics = evaluation_metric_semantics()

    assert MetricValue == float | int | str | bool | None
    assert semantics["total_return"]["base"] == "portfolio NAV path"
    assert SHARED_ACCOUNTING_MODEL in str(semantics["total_return"]["backend"])
    assert "project_perp_ledger_v1" not in str(semantics["total_return"]["backend"])
    assert semantics["funding_model"]["null_when"].startswith("never")
    assert SHARED_ACCOUNTING_MODEL in semantics["funding_model"]["null_when"]
    assert (
        semantics["total_return"]["not_authority"]
        == "not validation, promotion, paper trading, or live trading authority"
    )


def test_finite_metric_or_none_rejects_nan_inf_and_booleans():
    from quant_strategies.evaluation.metrics import finite_metric_or_none

    assert finite_metric_or_none(1) == 1.0
    assert finite_metric_or_none(1.5) == 1.5
    assert finite_metric_or_none(math.nan) is None
    assert finite_metric_or_none(math.inf) is None
    assert finite_metric_or_none(-math.inf) is None
    assert finite_metric_or_none(True) is None
    assert finite_metric_or_none("1.0") is None


# --- spine -> metric projection ----------------------------------------------


def _walk_from_returns(period_returns: list[float], *, drawdowns: list[float]) -> BookWalkResult:
    values = [100.0]
    for ret in period_returns[1:]:
        values.append(values[-1] * (1.0 + ret))
    path = tuple(
        PortfolioPathPoint(
            timestamp=AS_OF,
            portfolio_value=value,
            period_return=ret,
            at_risk=index > 0,
            drawdown=drawdown,
            gross_exposure=1.0,
            net_exposure=1.0,
            concentration=1.0,
        )
        for index, (value, ret, drawdown) in enumerate(
            zip(values, period_returns, drawdowns, strict=True)
        )
    )
    return BookWalkResult(
        path=path,
        round_trips=(),
        feasibility=FeasibilityVerdict(feasible=True),
        final_nav=values[-1],
        realized_pnl=0.0,
    )


def test_spine_metric_payload_uses_explicit_annualized_formulas():
    period_returns = [0.0, 0.02, -0.01, 0.03, -0.02]
    drawdowns = [0.0, 0.0, -0.01, 0.0, -0.02]
    walk = _walk_from_returns(period_returns, drawdowns=drawdowns)
    observed = period_returns[1:]
    annualization = 12
    total_return = walk.final_nav / 100.0 - 1.0
    annualized_return = ((1.0 + total_return) ** (annualization / len(observed))) - 1.0
    mean_return = sum(observed) / len(observed)
    sample_variance = sum((value - mean_return) ** 2 for value in observed) / (len(observed) - 1)
    volatility = math.sqrt(sample_variance) * math.sqrt(annualization)
    downside = math.sqrt(((-0.01) ** 2 + (-0.02) ** 2) / len(observed)) * math.sqrt(annualization)

    payload = spine_metric_payload(
        walk, annualization_periods_per_year=annualization, min_annualized_samples=4
    )
    metrics = payload.metrics

    assert payload.warnings == ()
    assert metrics["annualized_return"] == pytest.approx(annualized_return)
    assert metrics["volatility"] == pytest.approx(volatility)
    assert metrics["sharpe"] == pytest.approx((mean_return * annualization) / volatility)
    assert metrics["sortino"] == pytest.approx((mean_return * annualization) / downside)
    assert metrics["calmar"] == pytest.approx(annualized_return / abs(-0.02))
    assert metrics["worst_period_return"] == pytest.approx(-0.02)
    assert metrics["return_total_count_excluding_initial"] == 4
    assert metrics["return_sample_count"] == 4
    assert metrics["return_nonfinite_count"] == 0


def test_spine_metric_payload_nulls_annualized_family_when_sample_is_too_short():
    walk = _walk_from_returns([0.0, 0.01, -0.004950495], drawdowns=[0.0, 0.0, -0.004950495])

    payload = spine_metric_payload(
        walk, annualization_periods_per_year=252, min_annualized_samples=4
    )
    metrics = payload.metrics

    for name in ANNUALIZED_RISK_METRICS:
        assert metrics[name] is None
    assert metrics["return_sample_count"] == 2
    assert metrics["worst_period_return"] == pytest.approx(-0.004950495)
    assert "annualized_metrics_insufficient_samples:2:min_required=4" in payload.warnings


def _walk_with_at_risk_flags(
    period_returns: list[float], at_risk_flags: list[bool]
) -> BookWalkResult:
    values = [100.0]
    for ret in period_returns[1:]:
        values.append(values[-1] * (1.0 + ret))
    path = tuple(
        PortfolioPathPoint(
            timestamp=AS_OF,
            portfolio_value=value,
            period_return=ret,
            at_risk=flag,
            drawdown=0.0,
            gross_exposure=1.0 if flag else 0.0,
            net_exposure=1.0 if flag else 0.0,
            concentration=1.0 if flag else 0.0,
        )
        for value, ret, flag in zip(values, period_returns, at_risk_flags, strict=True)
    )
    return BookWalkResult(
        path=path,
        round_trips=(),
        feasibility=FeasibilityVerdict(feasible=True),
        final_nav=values[-1],
        realized_pnl=0.0,
    )


def test_spine_metric_payload_scores_at_risk_bars_only_like_quick_run():
    # Flat (non-at-risk) 0.0 bars must NOT enter the return sample: they would dilute
    # stdev and pad the annualization exponent, making the evaluation sharpe/volatility
    # diverge from the at-risk quick-run statistic on the same NAV path (quant #2).
    period_returns = [0.0, 0.02, 0.0, -0.01, 0.0]
    at_risk_flags = [False, True, False, True, False]  # 2 at-risk bars; 2 flat post-first
    walk = _walk_with_at_risk_flags(period_returns, at_risk_flags)

    payload = spine_metric_payload(
        walk, annualization_periods_per_year=12, min_annualized_samples=2
    )
    metrics = payload.metrics

    # Only the 2 at-risk returns are observed -- not "all 4 bars after the first".
    assert metrics["return_total_count_excluding_initial"] == 2
    assert metrics["return_sample_count"] == 2
    observed = [0.02, -0.01]
    assert metrics["worst_period_return"] == pytest.approx(min(observed))
    mean_return = sum(observed) / len(observed)
    sample_variance = sum((v - mean_return) ** 2 for v in observed) / (len(observed) - 1)
    volatility = math.sqrt(sample_variance) * math.sqrt(12)
    assert metrics["volatility"] == pytest.approx(volatility)
    assert metrics["sharpe"] == pytest.approx((mean_return * 12) / volatility)


def test_spine_metric_payload_fails_when_no_nav_path():
    walk = BookWalkResult(
        path=(),
        round_trips=(),
        feasibility=FeasibilityVerdict(feasible=True),
        final_nav=100.0,
        realized_pnl=0.0,
    )

    with pytest.raises(ValueError, match="invalid_required_metric:ending_value"):
        spine_metric_payload(walk, annualization_periods_per_year=252, min_annualized_samples=2)


def test_spine_trace_tables_project_round_trips_and_funding():
    pd = pytest.importorskip("pandas")
    trip = RoundTrip(
        symbol="BTC-PERP",
        direction="long",
        decision_time=DECISION,
        entry_time=datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
        exit_time=datetime(2026, 1, 1, 0, 3, tzinfo=UTC),
        realized_pnl=1.5,
        gross_cash=2.0,
        funding_cash=-0.2,
        cost_cash=0.3,
        entry_weight=0.5,
        entry_mark=102.0,
        exit_mark=103.0,
        exit_reason="signal",
        decision_id="demo:abc",
    )
    funding = FundingEvent(
        symbol="BTC-PERP",
        timestamp=datetime(2026, 1, 1, 0, 3, tzinfo=UTC),
        funding_rate=0.0003,
        position_units=0.5,
        mark_price=103.0,
        cashflow=-0.2,
    )
    walk = BookWalkResult(
        path=(
            PortfolioPathPoint(
                timestamp=AS_OF,
                portfolio_value=100.0,
                period_return=0.0,
                at_risk=False,
                drawdown=0.0,
                gross_exposure=0.0,
                net_exposure=0.0,
                concentration=0.0,
            ),
        ),
        round_trips=(trip,),
        feasibility=FeasibilityVerdict(feasible=True),
        final_nav=100.0,
        realized_pnl=1.5,
        funding_events=(funding,),
    )

    tables = spine_trace_tables(pd, walk, "w/realistic_costs/base_fill")

    assert list(tables.trades["asset"]) == ["BTC-PERP"]
    assert list(tables.target_positions["event"]) == ["entry", "exit"]
    assert tables.target_exposure_summary.loc[0, "decision_count"] == 1
    assert tables.target_exposure_summary.loc[0, "target_round_trip_turnover"] == pytest.approx(1.0)
    assert list(tables.funding_cashflows["funding_cashflow"]) == [pytest.approx(-0.2)]


def test_spine_backend_real_pandas_smoke():
    pytest.importorskip("pandas")
    decisions = [decision(target=0.25), flat(when=datetime(2026, 1, 1, 0, 2, tzinfo=UTC))]

    result = SpineEvaluationBackend().run(
        decisions=decisions,
        rows=rows(),
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
    )

    assert result.status == "completed"
    assert result.metrics["trade_count"] >= 1
    assert result.tables is not None
    assert "scenario_id" in result.tables.portfolio_path.columns
