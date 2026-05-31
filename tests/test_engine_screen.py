from __future__ import annotations

from datetime import datetime, timezone

import pytest

from quant_strategies.engine import Bar, CostModel, EvaluationRequest, FillModel, Side, StrategySpec, screen
from quant_strategies.engine.evaluation import EvaluationError

from engine_helpers import bars_for, decision_for


DECISION = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)


def quote_bars_for(symbol: str, quotes: list[tuple[float, float]]) -> tuple[Bar, ...]:
    return tuple(
        Bar(
            symbol=symbol,
            timestamp=DECISION.replace(minute=30 + index),
            open=(bid + ask) / 2.0,
            high=ask,
            low=bid,
            close=(bid + ask) / 2.0,
            bid=bid,
            ask=ask,
            mid=(bid + ask) / 2.0,
        )
        for index, (bid, ask) in enumerate(quotes)
    )


def funding_bars_for(symbol: str) -> tuple[Bar, ...]:
    return (
        Bar(symbol=symbol, timestamp=DECISION, open=100.0, high=100.0, low=100.0, close=100.0),
        Bar(
            symbol=symbol,
            timestamp=DECISION.replace(minute=31),
            open=100.0,
            high=100.0,
            low=100.0,
            close=100.0,
            funding_timestamp=DECISION.replace(minute=31),
            funding_rate=0.05,
            has_funding_event=True,
        ),
        Bar(
            symbol=symbol,
            timestamp=DECISION.replace(minute=32),
            open=100.0,
            high=100.0,
            low=100.0,
            close=100.0,
            funding_timestamp=DECISION.replace(minute=32),
            funding_rate=0.001,
            has_funding_event=True,
        ),
        Bar(
            symbol=symbol,
            timestamp=DECISION.replace(minute=33),
            open=110.0,
            high=110.0,
            low=110.0,
            close=110.0,
        ),
    )


def test_screen_accepts_empty_decision_set_as_zero_trade_result():
    request = EvaluationRequest(
        spec=StrategySpec(strategy_id="no_op", decisions=()),
        bars=bars_for("BTC", [100.0, 101.0, 102.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    result = screen(request)

    assert result.trade_count == 0
    assert result.trades == ()
    assert result.trade_result.sum_signed_trade_activity_gross == 0.0
    assert result.trade_result.sum_signed_trade_activity_funding == 0.0
    assert result.trade_result.sum_signed_trade_activity_cost == 0.0
    assert result.trade_result.sum_signed_trade_activity_net == 0.0


def test_screen_uses_declared_fill_timing_without_decision_bar_lookahead():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="timing_check",
            decisions=(decision_for(symbol="BTC", decision_time=DECISION, side=Side.LONG, max_hold_bars=1),),
        ),
        bars=bars_for("BTC", [999.0, 100.0, 110.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    result = screen(request)

    assert result.trades[0].entry_price == 100.0
    assert result.trades[0].exit_price == 110.0
    assert result.trade_result.sum_signed_trade_activity_gross == pytest.approx(0.10)
    assert "max_drawdown" not in result.model_dump()


def test_screen_long_and_short_pnl_signs_are_correct():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="sign_check",
            decisions=(
                decision_for(symbol="LONG", decision_time=DECISION, side=Side.LONG, max_hold_bars=1),
                decision_for(symbol="SHORT", decision_time=DECISION, side=Side.SHORT, max_hold_bars=1),
            ),
        ),
        bars=bars_for("LONG", [100.0, 100.0, 110.0]) + bars_for("SHORT", [100.0, 100.0, 90.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    result = screen(request)

    assert result.trade_count == 2
    assert [trade.gross_return for trade in result.trades] == pytest.approx([0.10, 0.10])
    assert result.trade_result.sum_signed_trade_activity_gross == pytest.approx(0.20)


def test_screen_costs_reduce_net_returns():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="cost_check",
            decisions=(decision_for(symbol="BTC", decision_time=DECISION, side=Side.LONG, max_hold_bars=1),),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 110.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
        cost_model=CostModel(fee_bps_per_side=10.0, slippage_bps_per_side=5.0),
    )

    result = screen(request)

    assert result.trade_result.sum_signed_trade_activity_gross == pytest.approx(0.10)
    assert result.trade_result.sum_signed_trade_activity_cost == pytest.approx(0.003)
    assert result.trade_result.sum_signed_trade_activity_net == pytest.approx(0.097)


def test_screen_applies_funding_cashflows_after_entry_through_exit():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="funding_check",
            decisions=(
                decision_for(symbol="BTC-PERP", decision_time=DECISION, side=Side.LONG, max_hold_bars=2),
                decision_for(symbol="ETH-PERP", decision_time=DECISION, side=Side.SHORT, max_hold_bars=2),
            ),
        ),
        bars=funding_bars_for("BTC-PERP") + funding_bars_for("ETH-PERP"),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    result = screen(request)

    assert [trade.gross_return for trade in result.trades] == pytest.approx([0.10, -0.10])
    assert [trade.funding_return for trade in result.trades] == pytest.approx([-0.001, 0.001])
    assert [trade.net_return for trade in result.trades] == pytest.approx([0.099, -0.099])
    assert result.trade_result.sum_signed_trade_activity_gross == pytest.approx(0.0)
    assert result.trade_result.sum_signed_trade_activity_funding == pytest.approx(0.0)
    assert result.trade_result.sum_signed_trade_activity_net == pytest.approx(0.0)


def test_screen_counts_tiny_duplicate_funding_rate_differences_once():
    bars = (
        Bar(symbol="BTC-PERP", timestamp=DECISION, open=100.0, high=100.0, low=100.0, close=100.0),
        Bar(symbol="BTC-PERP", timestamp=DECISION.replace(minute=31), open=100.0, high=100.0, low=100.0, close=100.0),
        Bar(
            symbol="BTC-PERP",
            timestamp=DECISION.replace(minute=32),
            open=100.0,
            high=100.0,
            low=100.0,
            close=100.0,
            funding_timestamp=DECISION.replace(minute=32),
            funding_rate=0.0002,
            has_funding_event=True,
        ),
        Bar(
            symbol="BTC-PERP",
            timestamp=DECISION.replace(minute=33),
            open=101.0,
            high=101.0,
            low=101.0,
            close=101.0,
            funding_timestamp=DECISION.replace(minute=32),
            funding_rate=0.0002 + 5e-13,
            has_funding_event=True,
        ),
    )
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="funding_duplicate",
            decisions=(decision_for(symbol="BTC-PERP", decision_time=DECISION, side=Side.LONG, max_hold_bars=2),),
        ),
        bars=bars,
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    result = screen(request)

    assert result.trades[0].funding_return == pytest.approx(-0.0002)


def test_screen_rejects_meaningful_duplicate_funding_rate_conflicts():
    bars = (
        Bar(symbol="BTC-PERP", timestamp=DECISION, open=100.0, high=100.0, low=100.0, close=100.0),
        Bar(symbol="BTC-PERP", timestamp=DECISION.replace(minute=31), open=100.0, high=100.0, low=100.0, close=100.0),
        Bar(
            symbol="BTC-PERP",
            timestamp=DECISION.replace(minute=32),
            open=100.0,
            high=100.0,
            low=100.0,
            close=100.0,
            funding_timestamp=DECISION.replace(minute=32),
            funding_rate=0.0002,
            has_funding_event=True,
        ),
        Bar(
            symbol="BTC-PERP",
            timestamp=DECISION.replace(minute=33),
            open=101.0,
            high=101.0,
            low=101.0,
            close=101.0,
            funding_timestamp=DECISION.replace(minute=32),
            funding_rate=0.0003,
            has_funding_event=True,
        ),
    )
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="funding_conflict",
            decisions=(decision_for(symbol="BTC-PERP", decision_time=DECISION, side=Side.LONG, max_hold_bars=2),),
        ),
        bars=bars,
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    with pytest.raises(EvaluationError, match="conflicting funding rates"):
        screen(request)


def test_engine_bar_index_builds_positions_by_symbol():
    from quant_strategies.engine.evaluation import _index_bars

    indexed = _index_bars(bars_for("BTC", [100.0, 101.0, 102.0]))

    assert indexed.positions_by_symbol["BTC"][DECISION] == 0
    assert indexed.positions_by_symbol["BTC"][DECISION.replace(minute=31)] == 1
    assert indexed.has_funding_events is False


def test_engine_bar_index_rejects_duplicate_symbol_timestamp():
    from quant_strategies.engine.evaluation import _index_bars

    duplicate_bars = bars_for("BTC", [100.0, 101.0, 102.0])
    duplicate_bars = duplicate_bars + (duplicate_bars[0],)

    with pytest.raises(EvaluationError, match="duplicate bar timestamp"):
        _index_bars(duplicate_bars)


def test_engine_bar_index_preindexes_funding_events_by_symbol():
    from quant_strategies.engine.evaluation import _index_bars

    indexed = _index_bars(funding_bars_for("BTC-PERP") + bars_for("ETH-PERP", [100.0, 101.0, 102.0]))

    assert indexed.has_funding_events is True
    assert len(indexed.funding_events_by_symbol["BTC-PERP"]) == 2
    assert indexed.funding_events_by_symbol["ETH-PERP"] == ()


def test_screen_weight_scales_return_exposure():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="weight_check",
            decisions=(decision_for(symbol="BTC", decision_time=DECISION, side=Side.LONG, weight=0.5, max_hold_bars=1),),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 110.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    result = screen(request)

    assert result.trades[0].weight == 0.5
    assert result.trade_result.sum_signed_trade_activity_gross == pytest.approx(0.05)


def test_screen_quote_long_uses_ask_entry_and_bid_exit():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="quote_long",
            decisions=(decision_for(symbol="EURUSD", decision_time=DECISION, side=Side.LONG, max_hold_bars=1),),
        ),
        bars=quote_bars_for("EURUSD", [(99.9, 100.0), (100.0, 100.1), (110.0, 110.1)]),
        fill_model=FillModel(price="quote", entry_lag_bars=1),
    )

    result = screen(request)

    assert result.trades[0].entry_price == 100.1
    assert result.trades[0].exit_price == 110.0
    assert result.trade_result.sum_signed_trade_activity_gross == pytest.approx((110.0 - 100.1) / 100.1)


def test_screen_quote_short_uses_bid_entry_and_ask_exit():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="quote_short",
            decisions=(decision_for(symbol="EURUSD", decision_time=DECISION, side=Side.SHORT, max_hold_bars=1),),
        ),
        bars=quote_bars_for("EURUSD", [(99.9, 100.0), (100.0, 100.1), (90.0, 90.1)]),
        fill_model=FillModel(price="quote", entry_lag_bars=1),
    )

    result = screen(request)

    assert result.trades[0].entry_price == 100.0
    assert result.trades[0].exit_price == 90.1
    assert result.trade_result.sum_signed_trade_activity_gross == pytest.approx((100.0 - 90.1) / 100.0)


def test_screen_quote_fill_fails_closed_without_selected_quotes():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="missing_quotes",
            decisions=(decision_for(symbol="EURUSD", decision_time=DECISION, side=Side.LONG, max_hold_bars=1),),
        ),
        bars=bars_for("EURUSD", [100.0, 101.0, 102.0]),
        fill_model=FillModel(price="quote", entry_lag_bars=1),
    )

    with pytest.raises(EvaluationError, match="quote fill requires bid and ask"):
        screen(request)


def test_screen_max_hold_bars_exits_with_max_hold_reason():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="old_hold",
            decisions=(decision_for(symbol="BTC", decision_time=DECISION, side=Side.LONG, max_hold_bars=2),),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 101.0, 103.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    result = screen(request)
    trade = result.trades[0]

    assert trade.exit_time == DECISION.replace(minute=33)
    assert trade.exit_reason == "max_hold"
    assert trade.gross_return == pytest.approx(0.03)


def test_screen_uses_configured_max_hold_bars():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="max_hold",
            decisions=(
                decision_for(
                    symbol="BTC",
                    decision_time=DECISION,
                    side=Side.LONG,
                    max_hold_bars=1,
                ),
            ),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 102.0, 110.0, 120.0, 130.0, 140.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=32)
    assert trade.exit_reason == "max_hold"
    assert trade.gross_return == pytest.approx(0.02)


def test_screen_exits_on_take_profit_before_max_hold():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="take_profit",
            decisions=(
                decision_for(
                    symbol="BTC",
                    decision_time=DECISION,
                    side=Side.LONG,
                    max_hold_bars=3,
                    take_profit_bps=150.0,
                ),
            ),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 102.0, 101.0, 104.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=32)
    assert trade.exit_reason == "take_profit"
    assert trade.gross_return == pytest.approx(0.02)


def test_screen_exits_on_stop_loss_before_max_hold():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="stop_loss",
            decisions=(
                decision_for(
                    symbol="BTC",
                    decision_time=DECISION,
                    side=Side.LONG,
                    max_hold_bars=3,
                    stop_loss_bps=100.0,
                ),
            ),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 98.0, 99.0, 104.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=32)
    assert trade.exit_reason == "stop_loss"
    assert trade.gross_return == pytest.approx(-0.02)


def test_screen_exits_on_trailing_stop_after_favorable_move():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="trailing_stop",
            decisions=(
                decision_for(
                    symbol="BTC",
                    decision_time=DECISION,
                    side=Side.LONG,
                    max_hold_bars=4,
                    trailing_stop_bps=150.0,
                ),
            ),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 104.0, 102.0, 105.0, 106.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=33)
    assert trade.exit_reason == "trailing_stop"
    assert trade.gross_return == pytest.approx(0.02)


def test_screen_short_take_profit_uses_falling_price():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="short_take_profit",
            decisions=(
                decision_for(
                    symbol="BTC",
                    decision_time=DECISION,
                    side=Side.SHORT,
                    max_hold_bars=3,
                    take_profit_bps=150.0,
                ),
            ),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 98.0, 101.0, 104.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=32)
    assert trade.exit_reason == "take_profit"
    assert trade.gross_return == pytest.approx(0.02)


def test_screen_short_take_profit_uses_simple_return_threshold():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="short_take_profit_threshold",
            decisions=(
                decision_for(
                    symbol="BTC",
                    decision_time=DECISION,
                    side=Side.SHORT,
                    max_hold_bars=3,
                    take_profit_bps=150.0,
                ),
            ),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 98.52, 98.5, 98.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=33)
    assert trade.exit_reason == "take_profit"
    assert trade.gross_return == pytest.approx(0.015)


def test_screen_short_stop_loss_uses_simple_return_threshold():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="short_stop_loss_threshold",
            decisions=(
                decision_for(
                    symbol="BTC",
                    decision_time=DECISION,
                    side=Side.SHORT,
                    max_hold_bars=2,
                    stop_loss_bps=100.0,
                ),
            ),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 101.0, 100.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=32)
    assert trade.exit_reason == "stop_loss"
    assert trade.gross_return == pytest.approx(-0.01)


def test_screen_prioritizes_stop_loss_over_trailing_stop_on_same_trigger_bar():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="priority_stop_loss",
            decisions=(
                decision_for(
                    symbol="BTC",
                    decision_time=DECISION,
                    side=Side.LONG,
                    max_hold_bars=3,
                    stop_loss_bps=50.0,
                    trailing_stop_bps=100.0,
                ),
            ),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 102.0, 99.0, 98.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=33)
    assert trade.exit_reason == "stop_loss"


def test_screen_short_stop_loss_over_trailing_stop_on_same_trigger_bar():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="short_priority_stop_loss",
            decisions=(
                decision_for(
                    symbol="BTC",
                    decision_time=DECISION,
                    side=Side.SHORT,
                    max_hold_bars=3,
                    stop_loss_bps=50.0,
                    trailing_stop_bps=100.0,
                ),
            ),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 98.0, 101.0, 102.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=33)
    assert trade.exit_reason == "stop_loss"


def test_screen_exit_lag_fills_after_trigger_bar():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="exit_lag",
            decisions=(
                decision_for(
                    symbol="BTC",
                    decision_time=DECISION,
                    side=Side.LONG,
                    max_hold_bars=3,
                    take_profit_bps=150.0,
                ),
            ),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 102.0, 101.0, 99.0, 98.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1, exit_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=33)
    assert trade.exit_reason == "take_profit"
    assert trade.exit_price == 101.0


def test_screen_early_exit_shortens_funding_exposure():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="funding_shortened",
            decisions=(
                decision_for(
                    symbol="BTC-PERP",
                    decision_time=DECISION,
                    side=Side.LONG,
                    max_hold_bars=2,
                    take_profit_bps=50.0,
                ),
            ),
        ),
        bars=funding_bars_for("BTC-PERP"),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=33)
    assert trade.exit_reason == "take_profit"
    assert trade.funding_return == pytest.approx(-0.001)
