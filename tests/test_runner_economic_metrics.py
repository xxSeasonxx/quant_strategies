from __future__ import annotations

import pytest

from quant_strategies.runner.economic_metrics import (
    diagnostic_slices,
    summary_metrics,
    trade_result_from_engine_summary,
    trades_from_engine_summary,
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


@pytest.mark.parametrize(
    "field,value",
    [
        ("sum_signed_trade_activity_gross", None),
        ("sum_signed_trade_activity_gross", True),
        ("sum_signed_trade_activity_gross", "0.01"),
        ("sum_signed_trade_activity_gross", "not-numeric"),
        ("sum_signed_trade_activity_gross", float("nan")),
        ("sum_signed_trade_activity_cost", None),
        ("sum_signed_trade_activity_cost", True),
        ("sum_signed_trade_activity_cost", "0.01"),
        ("sum_signed_trade_activity_cost", "not-numeric"),
        ("sum_signed_trade_activity_cost", float("inf")),
        ("sum_signed_trade_activity_funding", None),
        ("sum_signed_trade_activity_funding", True),
        ("sum_signed_trade_activity_funding", "0.01"),
        ("sum_signed_trade_activity_funding", "not-numeric"),
        ("sum_signed_trade_activity_funding", float("-inf")),
    ],
)
def test_summary_metrics_rejects_malformed_trade_result_components(field, value):
    result = trade_result(gross=0.01)
    result[field] = value

    with pytest.raises(ValueError):
        summary_metrics([trade(0.01)], result)


@pytest.mark.parametrize(
    "field",
    [
        "sum_signed_trade_activity_gross",
        "sum_signed_trade_activity_cost",
        "sum_signed_trade_activity_funding",
    ],
)
def test_summary_metrics_rejects_missing_trade_result_components(field):
    result = trade_result(gross=0.01)
    result.pop(field)

    with pytest.raises(ValueError):
        summary_metrics([trade(0.01)], result)


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


def test_trades_from_engine_summary_returns_copied_trade_dicts():
    source_trade = trade(0.01)
    engine = {"trade_count": 1, "diagnostic_trades": [source_trade]}

    trades = trades_from_engine_summary(engine)

    assert trades == [source_trade]
    assert trades[0] is not source_trade

    trades[0]["net_return"] = 0.02
    assert source_trade["net_return"] == 0.01


def test_trades_from_engine_summary_accepts_integral_float_trade_count():
    assert trades_from_engine_summary(
        {"trade_count": 1.0, "diagnostic_trades": [trade(0.01)]}
    ) == [trade(0.01)]


def test_trade_result_from_engine_summary_returns_copied_dict():
    source_result = trade_result(gross=0.01)
    engine = {"trade_result": source_result}

    result = trade_result_from_engine_summary(engine)

    assert result == source_result
    assert result is not source_result

    result["sum_signed_trade_activity_gross"] = 0.02
    assert source_result["sum_signed_trade_activity_gross"] == 0.01


@pytest.mark.parametrize(
    "engine",
    [
        {},
        {"diagnostic_trades": "not-a-sequence"},
        {"diagnostic_trades": [trade(0.01), object()]},
    ],
)
def test_trades_from_engine_summary_rejects_malformed_diagnostic_trades(engine):
    with pytest.raises(ValueError):
        trades_from_engine_summary(engine)


@pytest.mark.parametrize(
    "engine",
    [
        {"trade_count": True, "diagnostic_trades": [trade(0.01)]},
        {"trade_count": "not-an-int", "diagnostic_trades": [trade(0.01)]},
        {"trade_count": 1.2, "diagnostic_trades": [trade(0.01)]},
        {"trade_count": 1.9, "diagnostic_trades": [trade(0.01)]},
        {"trade_count": 2, "diagnostic_trades": [trade(0.01)]},
    ],
)
def test_trades_from_engine_summary_rejects_trade_count_mismatch(engine):
    with pytest.raises(ValueError):
        trades_from_engine_summary(engine)


@pytest.mark.parametrize(
    "engine",
    [
        {},
        {"trade_result": "not-a-mapping"},
    ],
)
def test_trade_result_from_engine_summary_rejects_malformed_trade_result(engine):
    with pytest.raises(ValueError):
        trade_result_from_engine_summary(engine)


@pytest.mark.parametrize(
    "bad_trade",
    [
        {"symbol": "SPY", "side": "long", "exit_reason": "max_hold"},
        trade(None),  # type: ignore[arg-type]
        trade(True),  # type: ignore[arg-type]
        trade("0.01"),  # type: ignore[arg-type]
        trade("not-numeric"),  # type: ignore[arg-type]
        trade(float("nan")),
        trade(float("inf")),
    ],
)
def test_summary_metrics_rejects_malformed_net_return(bad_trade):
    with pytest.raises(ValueError):
        summary_metrics([bad_trade], trade_result(gross=0.0))


@pytest.mark.parametrize(
    "bad_trade",
    [
        {"symbol": "SPY", "side": "long", "exit_reason": "max_hold"},
        trade(None),  # type: ignore[arg-type]
        trade(True),  # type: ignore[arg-type]
        trade("0.01"),  # type: ignore[arg-type]
        trade("not-numeric"),  # type: ignore[arg-type]
        trade(float("nan")),
        trade(float("inf")),
    ],
)
def test_diagnostic_slices_rejects_malformed_net_return(bad_trade):
    with pytest.raises(ValueError):
        diagnostic_slices([bad_trade])
