from __future__ import annotations

import pytest

from quant_strategies.runner.economic_metrics import (
    diagnostic_slices,
    summary_metrics,
)


def trade(
    net_return: float,
    *,
    symbol: str = "SPY",
    side: str = "long",
    exit_reason: str = "max_hold",
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "side": side,
        "exit_reason": exit_reason,
        "net_return": net_return,
    }


def trade_result(
    *,
    gross: float,
    funding: float = 0.0,
    cost: float = 0.0,
    net: float | None = None,
) -> dict[str, object]:
    return {
        "sum_signed_trade_activity_gross": gross,
        "sum_signed_trade_activity_funding": funding,
        "sum_signed_trade_activity_cost": cost,
        "sum_signed_trade_activity_net": gross + funding - cost if net is None else net,
    }


def test_summary_metrics_for_no_trades_emit_zero_counts_and_null_rates():
    metrics = summary_metrics([], trade_result(gross=0.0))

    assert metrics == {
        "schema_version": "quant_strategies.runner.economic_metrics/v1",
        "basis": "engine_trade_ledger",
        "trade_count": 0,
        "winning_trade_count": 0,
        "losing_trade_count": 0,
        "flat_trade_count": 0,
        "hit_rate": None,
        "average_trade_net": None,
        "average_win_net": None,
        "average_loss_net": None,
        "profit_factor": None,
        "cost_share_of_abs_gross": None,
        "funding_share_of_abs_gross": None,
    }


def test_summary_metrics_for_mixed_trades_and_signed_components():
    metrics = summary_metrics(
        [trade(0.03), trade(-0.01), trade(0.0)],
        trade_result(gross=0.10, funding=-0.005, cost=0.02, net=0.075),
    )

    assert metrics["trade_count"] == 3
    assert metrics["winning_trade_count"] == 1
    assert metrics["losing_trade_count"] == 1
    assert metrics["flat_trade_count"] == 1
    assert metrics["hit_rate"] == pytest.approx(1 / 3)
    assert metrics["average_trade_net"] == pytest.approx(0.02 / 3)
    assert metrics["average_win_net"] == pytest.approx(0.03)
    assert metrics["average_loss_net"] == pytest.approx(-0.01)
    assert metrics["profit_factor"] == pytest.approx(3.0)
    assert metrics["cost_share_of_abs_gross"] == pytest.approx(0.2)
    assert metrics["funding_share_of_abs_gross"] == pytest.approx(-0.05)


def test_summary_metrics_for_all_winners_do_not_emit_infinite_profit_factor():
    metrics = summary_metrics(
        [trade(0.01), trade(0.02)],
        trade_result(gross=0.03),
    )

    assert metrics["hit_rate"] == 1.0
    assert metrics["average_trade_net"] == pytest.approx(0.015)
    assert metrics["average_win_net"] == pytest.approx(0.015)
    assert metrics["average_loss_net"] is None
    assert metrics["profit_factor"] is None


def test_summary_metrics_for_all_losers_emit_zero_profit_factor():
    metrics = summary_metrics(
        [trade(-0.01), trade(-0.03)],
        trade_result(gross=-0.04),
    )

    assert metrics["hit_rate"] == 0.0
    assert metrics["average_trade_net"] == pytest.approx(-0.02)
    assert metrics["average_win_net"] is None
    assert metrics["average_loss_net"] == pytest.approx(-0.02)
    assert metrics["profit_factor"] == 0.0


def test_summary_metrics_null_cost_and_funding_shares_when_gross_is_zero():
    metrics = summary_metrics(
        [trade(0.01), trade(-0.01)],
        trade_result(gross=0.0, funding=0.004, cost=0.002, net=0.002),
    )

    assert metrics["cost_share_of_abs_gross"] is None
    assert metrics["funding_share_of_abs_gross"] is None


def test_diagnostic_slices_group_economic_summaries_and_distribution():
    slices = diagnostic_slices(
        [
            trade(0.03, symbol="SPY", side="long", exit_reason="max_hold"),
            trade(-0.01, symbol="SPY", side="short", exit_reason="stop_loss"),
            trade(0.0, symbol="QQQ", side="long", exit_reason="max_hold"),
        ]
    )

    assert slices["schema_version"] == "quant_strategies.runner.economic_slices/v1"
    assert slices["basis"] == "engine_trade_ledger"
    assert slices["by_symbol"]["SPY"]["count"] == 2
    assert slices["by_symbol"]["SPY"]["winning_trade_count"] == 1
    assert slices["by_symbol"]["SPY"]["losing_trade_count"] == 1
    assert slices["by_symbol"]["SPY"]["hit_rate"] == pytest.approx(0.5)
    assert slices["by_symbol"]["QQQ"]["flat_trade_count"] == 1
    assert slices["by_direction"]["long"]["count"] == 2
    assert slices["by_exit_reason"]["stop_loss"]["average_loss_net"] == pytest.approx(-0.01)
    assert slices["win_loss_distribution"] == {
        "largest_win_net": 0.03,
        "largest_loss_net": -0.01,
        "median_trade_net": 0.0,
        "sum_positive_net": 0.03,
        "sum_negative_net": -0.01,
    }
