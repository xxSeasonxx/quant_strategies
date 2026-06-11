from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from quant_strategies.core.config import (
    CapacityModelConfig,
    CostModelConfig,
    DataConfig,
    FillModelConfig,
)
from quant_strategies.core.portfolio_foundation import (
    PortfolioFoundationConfig,
    RunPortfolioFoundation,
    build_portfolio_foundation,
)
from quant_strategies.decisions import InstrumentRef, RiskRule, TargetDecision
from quant_strategies.runner.economic_metrics import (
    RunEconomics,
    RunTrade,
    build_run_economics,
)

START = datetime(2024, 1, 1, tzinfo=UTC)


def ts(index: int) -> datetime:
    return START + timedelta(days=index)


def bar_rows(*closes: float, symbol: str = "SPY") -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, close in enumerate(closes):
        rows.append(
            {
                "symbol": symbol,
                "timestamp": ts(index),
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1_000.0,
                "vwap": close,
                "num_trades": 100,
                "available_at": ts(index),
            }
        )
    return rows


def target(
    decision_index: int,
    weight: float,
    *,
    symbol: str = "SPY",
    risk_rule: RiskRule | None = None,
) -> TargetDecision:
    decision_time = ts(decision_index)
    return TargetDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="equity_or_etf", symbol=symbol),
        decision_time=decision_time,
        as_of_time=decision_time,
        target=weight,
        risk_rule=risk_rule,
    )


def foundation_for(
    rows: list[dict[str, object]],
    decisions: list[TargetDecision],
    *,
    fee_bps_per_side: float = 1.0,
    impact_coefficient_bps: float = 0.0,
) -> RunPortfolioFoundation:
    return build_portfolio_foundation(
        rows=rows,
        decisions=decisions,
        data=DataConfig(
            kind="bars",
            dataset="equity_1min",
            symbols=("SPY",),
            start=START.date(),
            end=ts(len(rows) - 1).date(),
        ),
        fill_model=FillModelConfig(price="close", entry_lag_bars=1),
        cost_model=CostModelConfig(fee_bps_per_side=fee_bps_per_side, slippage_bps_per_side=0.0),
        capacity_model=CapacityModelConfig(
            mode="adv_impact",
            portfolio_notional=1_000.0,
            adv_lookback_bars=3,
            adv_min_observations=1,
            max_bar_participation=1.0,
            max_adv_participation=1.0,
            impact_coefficient_bps=impact_coefficient_bps,
            impact_exponent=1.0,
        ),
        config=PortfolioFoundationConfig(subwindows=1, trial_count=5),
    )


def test_build_run_economics_derives_typed_ledger_from_the_book_walk():
    # Enter long at the first decision, close two bars later -> one closed round trip.
    rows = bar_rows(100.0, 100.0, 102.0, 104.0, 105.0)
    decisions = [target(0, 1.0), target(2, 0.0)]

    economics = build_run_economics(foundation_for(rows, decisions))

    assert isinstance(economics, RunEconomics)
    assert economics.schema_version == "quant_strategies.runner.economic_metrics/v1"
    assert economics.basis == "portfolio_book_round_trip_attribution"
    assert economics.trade_count == 1
    assert isinstance(economics.trades[0], RunTrade)
    trade = economics.trades[0]
    assert trade.symbol == "SPY"
    assert trade.side == "long"
    assert trade.decision_time.tzinfo is not None
    # The per-trade ledger is a derived attribution view: net = gross + funding - cost.
    assert trade.net_return == pytest.approx(
        trade.gross_return + trade.funding_return - trade.cost_return
    )


def test_run_economics_attributes_market_impact_as_cost_component():
    rows = bar_rows(100.0, 100.0, 100.0, 100.0)
    economics = build_run_economics(
        foundation_for(
            rows,
            [target(0, 0.5), target(2, 0.0)],
            fee_bps_per_side=0.0,
            impact_coefficient_bps=100.0,
        )
    )

    trade = economics.trades[0]
    assert trade.impact_return > 0.0
    assert trade.cost_return == pytest.approx(trade.impact_return)
    assert trade.net_return == pytest.approx(
        trade.gross_return + trade.funding_return - trade.cost_return
    )
    summary = economics.summary_payload()
    assert summary["sum_impact_return"] == pytest.approx(trade.impact_return)
    assert summary["impact_share_of_abs_gross"] is None


def test_run_economics_summary_and_slices_payloads_match_the_new_contract():
    rows = bar_rows(100.0, 100.0, 102.0, 104.0, 105.0)
    economics = build_run_economics(foundation_for(rows, [target(0, 1.0), target(2, 0.0)]))

    summary = economics.summary_payload()
    assert set(summary) == {
        "schema_version",
        "basis",
        "trade_count",
        "winning_trade_count",
        "losing_trade_count",
        "flat_trade_count",
        "hit_rate",
        "average_trade_net",
        "average_win_net",
        "average_loss_net",
        "profit_factor",
        "cost_share_of_abs_gross",
        "funding_share_of_abs_gross",
        "impact_share_of_abs_gross",
        "sum_gross_return",
        "sum_funding_return",
        "sum_cost_return",
        "sum_impact_return",
        "sum_net_return",
    }
    assert summary["schema_version"] == "quant_strategies.runner.economic_metrics/v1"
    assert summary["basis"] == "portfolio_book_round_trip_attribution"
    assert summary["trade_count"] == 1

    slices = economics.slices_payload()
    assert slices["schema_version"] == "quant_strategies.runner.economic_slices/v1"
    assert slices["basis"] == "portfolio_book_round_trip_attribution"
    assert slices["by_symbol"]["SPY"]["count"] == 1
    assert "impact_sum" in slices["by_symbol"]["SPY"]
    assert slices["by_direction"]["long"]["count"] == 1
    assert set(slices["win_loss_distribution"]) == {
        "largest_win_net",
        "largest_loss_net",
        "median_trade_net",
        "sum_positive_net",
        "sum_negative_net",
    }


def test_run_economics_payloads_are_immutable_mappings():
    rows = bar_rows(100.0, 100.0, 102.0, 104.0, 105.0)
    economics = build_run_economics(foundation_for(rows, [target(0, 1.0), target(2, 0.0)]))

    with pytest.raises(TypeError):
        economics.by_symbol["SPY"]["count"] = 2  # type: ignore[index]
    with pytest.raises(TypeError):
        economics.win_loss_distribution["sum_positive_net"] = 0.0  # type: ignore[index]


def test_run_economics_ledger_reconciles_with_realized_nav_pnl():
    # One model of money (design D4): the derived ledger sums reconcile with the
    # book walk's realized NAV PnL.
    rows = bar_rows(100.0, 100.0, 102.0, 104.0, 105.0)
    foundation = foundation_for(rows, [target(0, 1.0), target(2, 0.0)])

    economics = build_run_economics(foundation)

    ledger_net = sum(trade.net_return for trade in economics.trades)
    assert economics.sum_net_return == pytest.approx(ledger_net)
    assert economics.sum_net_return == pytest.approx(
        economics.sum_gross_return + economics.sum_funding_return - economics.sum_cost_return
    )


def test_run_economics_attributes_a_declared_stop_loss_exit():
    # A declared stop-loss the book enforces on the net position closes the round trip
    # as a stop_loss exit. Enter at fill bar (idx1=100), hold one flat bar (idx2=100),
    # then a >5% drop at idx3 trips the stop.
    rows = bar_rows(100.0, 100.0, 100.0, 90.0)
    decisions = [target(0, 1.0, risk_rule=RiskRule(stop_loss=0.05))]

    economics = build_run_economics(foundation_for(rows, decisions))

    assert economics.trade_count == 1
    trade = economics.trades[0]
    assert trade.exit_reason == "stop_loss"
    assert trade.side == "long"
    assert economics.by_exit_reason["stop_loss"]["count"] == 1


def test_build_run_economics_for_no_round_trips_emits_zero_counts_and_null_rates():
    # A standing long with no close over enough at-risk bars is feasible but has no
    # closed round trip, so the derived ledger is empty.
    rows = bar_rows(100.0, 101.0, 102.0, 104.0, 105.0)
    economics = build_run_economics(foundation_for(rows, [target(0, 1.0)]))

    assert economics.trade_count == 0
    assert economics.hit_rate is None
    assert economics.average_trade_net is None
    assert economics.profit_factor is None
    assert economics.summary_payload()["trade_count"] == 0
