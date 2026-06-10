from __future__ import annotations

from datetime import UTC, datetime, timedelta

from quant_strategies.core.config import CostModelConfig, DataConfig, FillModelConfig
from quant_strategies.core.engine_runner import EngineRun, evaluate_foundation
from quant_strategies.core.portfolio_foundation import (
    PortfolioFoundationConfig,
    build_portfolio_foundation,
)
from quant_strategies.decisions import InstrumentRef, TargetDecision
from quant_strategies.runner.economic_metrics import build_run_economics

START = datetime(2024, 1, 1, tzinfo=UTC)


def _rows(*closes: float) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, close in enumerate(closes):
        timestamp = START + timedelta(days=index)
        rows.append(
            {
                "symbol": "SPY",
                "timestamp": timestamp,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "available_at": timestamp,
            }
        )
    return rows


def _data_config(end_index: int) -> DataConfig:
    return DataConfig(
        kind="bars",
        dataset="equity_1min",
        symbols=("SPY",),
        start=START.date(),
        end=(START + timedelta(days=end_index)).date(),
    )


def _target(decision_index: int, weight: float) -> TargetDecision:
    decision_time = START + timedelta(days=decision_index)
    return TargetDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="equity_or_etf", symbol="SPY"),
        decision_time=decision_time,
        as_of_time=decision_time,
        target=weight,
    )


def _foundation(rows, decisions, *, end_index: int):
    return build_portfolio_foundation(
        rows=rows,
        decisions=decisions,
        data=_data_config(end_index),
        fill_model=FillModelConfig(price="close", entry_lag_bars=1),
        cost_model=CostModelConfig(fee_bps_per_side=1.0, slippage_bps_per_side=0.0),
        config=PortfolioFoundationConfig(subwindows=1, trial_count=5),
    )


def test_evaluate_foundation_summarizes_the_book_walk():
    # enter long at bar 1, flatten at bar 3 -> one closed round trip.
    rows = _rows(100.0, 100.0, 110.0, 110.0)
    decisions = [_target(0, 1.0), _target(2, 0.0)]
    foundation = _foundation(rows, decisions, end_index=3)

    economics = build_run_economics(foundation)
    engine_run = evaluate_foundation(
        economics,
        feasible=foundation.feasible,
        mode="gate",
        include_diagnostics=True,
    )

    assert isinstance(engine_run, EngineRun)
    assert engine_run.feasible is True
    assert engine_run.passed is True
    assert engine_run.trade_count == 1
    # nav_attribution is the book's realized attribution, reconciling with the ledger.
    assert engine_run.nav_attribution["sum_net_return"] == economics.sum_net_return
    assert engine_run.nav_attribution["sum_gross_return"] == economics.sum_gross_return
    assert len(engine_run.diagnostic_trades) == 1
    trade = engine_run.diagnostic_trades[0]
    assert trade["symbol"] == "SPY"
    assert trade["side"] == "long"
    assert trade["exit_reason"] == "signal"


def test_evaluate_foundation_excludes_diagnostic_trades_when_not_requested():
    rows = _rows(100.0, 100.0, 110.0, 110.0)
    decisions = [_target(0, 1.0), _target(2, 0.0)]
    foundation = _foundation(rows, decisions, end_index=3)

    engine_run = evaluate_foundation(
        build_run_economics(foundation),
        feasible=foundation.feasible,
        mode="screen",
        include_diagnostics=False,
    )

    assert engine_run.diagnostic_trades == ()
    assert engine_run.mode == "screen"


def test_evaluate_foundation_reports_net_attribution_reconciling_with_ledger():
    rows = _rows(100.0, 100.0, 110.0, 110.0)
    decisions = [_target(0, 1.0), _target(2, 0.0)]
    foundation = _foundation(rows, decisions, end_index=3)
    economics = build_run_economics(foundation)

    engine_run = evaluate_foundation(economics, feasible=True, mode="gate")

    ledger_net = sum(trade.net_return for trade in economics.trades)
    assert engine_run.nav_attribution["sum_net_return"] == ledger_net
