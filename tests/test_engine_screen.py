from __future__ import annotations

from datetime import datetime, timezone

import pytest

from quant_strategies.engine import Bar, CostModel, EvaluationRequest, FillModel, Side, Signal, StrategySpec, screen
from quant_strategies.engine.evaluation import EvaluationError

from engine_helpers import bars_for


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


def test_screen_uses_declared_fill_timing_without_decision_bar_lookahead():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="timing_check",
            signals=(Signal(symbol="BTC", decision_time=DECISION, side=Side.LONG, hold_bars=1),),
        ),
        bars=bars_for("BTC", [999.0, 100.0, 110.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    result = screen(request)

    assert result.trades[0].entry_price == 100.0
    assert result.trades[0].exit_price == 110.0
    assert result.gross_return == pytest.approx(0.10)
    assert "max_drawdown" not in result.model_dump()


def test_screen_long_and_short_pnl_signs_are_correct():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="sign_check",
            signals=(
                Signal(symbol="LONG", decision_time=DECISION, side=Side.LONG, hold_bars=1),
                Signal(symbol="SHORT", decision_time=DECISION, side=Side.SHORT, hold_bars=1),
            ),
        ),
        bars=bars_for("LONG", [100.0, 100.0, 110.0]) + bars_for("SHORT", [100.0, 100.0, 90.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    result = screen(request)

    assert result.trade_count == 2
    assert [trade.gross_return for trade in result.trades] == pytest.approx([0.10, 0.10])
    assert result.gross_return == pytest.approx(0.20)


def test_screen_costs_reduce_net_returns():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="cost_check",
            signals=(Signal(symbol="BTC", decision_time=DECISION, side=Side.LONG, hold_bars=1),),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 110.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
        cost_model=CostModel(fee_bps_per_side=10.0, slippage_bps_per_side=5.0),
    )

    result = screen(request)

    assert result.gross_return == pytest.approx(0.10)
    assert result.cost_return == pytest.approx(0.003)
    assert result.net_return == pytest.approx(0.097)


def test_screen_applies_funding_cashflows_after_entry_through_exit():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="funding_check",
            signals=(
                Signal(symbol="BTC-PERP", decision_time=DECISION, side=Side.LONG, hold_bars=2),
                Signal(symbol="ETH-PERP", decision_time=DECISION, side=Side.SHORT, hold_bars=2),
            ),
        ),
        bars=funding_bars_for("BTC-PERP") + funding_bars_for("ETH-PERP"),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    result = screen(request)

    assert [trade.gross_return for trade in result.trades] == pytest.approx([0.10, -0.10])
    assert [trade.funding_return for trade in result.trades] == pytest.approx([-0.001, 0.001])
    assert [trade.net_return for trade in result.trades] == pytest.approx([0.099, -0.099])
    assert result.gross_return == pytest.approx(0.0)
    assert result.funding_return == pytest.approx(0.0)
    assert result.net_return == pytest.approx(0.0)


def test_screen_weight_scales_return_exposure():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="weight_check",
            signals=(Signal(symbol="BTC", decision_time=DECISION, side=Side.LONG, weight=0.5, hold_bars=1),),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 110.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    result = screen(request)

    assert result.trades[0].weight == 0.5
    assert result.gross_return == pytest.approx(0.05)


def test_screen_quote_long_uses_ask_entry_and_bid_exit():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="quote_long",
            signals=(Signal(symbol="EURUSD", decision_time=DECISION, side=Side.LONG, hold_bars=1),),
        ),
        bars=quote_bars_for("EURUSD", [(99.9, 100.0), (100.0, 100.1), (110.0, 110.1)]),
        fill_model=FillModel(price="quote", entry_lag_bars=1),
    )

    result = screen(request)

    assert result.trades[0].entry_price == 100.1
    assert result.trades[0].exit_price == 110.0
    assert result.gross_return == pytest.approx((110.0 - 100.1) / 100.1)


def test_screen_quote_short_uses_bid_entry_and_ask_exit():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="quote_short",
            signals=(Signal(symbol="EURUSD", decision_time=DECISION, side=Side.SHORT, hold_bars=1),),
        ),
        bars=quote_bars_for("EURUSD", [(99.9, 100.0), (100.0, 100.1), (90.0, 90.1)]),
        fill_model=FillModel(price="quote", entry_lag_bars=1),
    )

    result = screen(request)

    assert result.trades[0].entry_price == 100.0
    assert result.trades[0].exit_price == 90.1
    assert result.gross_return == pytest.approx((100.0 - 90.1) / 100.0)


def test_screen_quote_fill_fails_closed_without_selected_quotes():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="missing_quotes",
            signals=(Signal(symbol="EURUSD", decision_time=DECISION, side=Side.LONG, hold_bars=1),),
        ),
        bars=bars_for("EURUSD", [100.0, 101.0, 102.0]),
        fill_model=FillModel(price="quote", entry_lag_bars=1),
    )

    with pytest.raises(EvaluationError, match="quote fill requires bid and ask"):
        screen(request)
