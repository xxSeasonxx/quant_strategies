"""Standalone unit tests for the causal, single-account, netted portfolio book.

These exercise the book in isolation (no runner/engine/causality wiring — Phase 1b)
against the ``portfolio-book-spine`` spec: same-symbol netting, decision-bar
weight->quantity then held, same-bar fill-order-independent intended gross, the
``RiskRule`` flatten + re-entry latch, at-risk-bar statistics + min-sample gate, each
fail-closed feasibility verdict, and NAV<->round-trip-ledger reconciliation.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from statistics import stdev

import pytest

from quant_strategies.core.config import CostModelConfig, DataConfig, FillModelConfig
from quant_strategies.core.portfolio_foundation import (
    INITIAL_EQUITY,
    REASON_INSUFFICIENT_SAMPLES,
    REASON_LEVERAGE_BUDGET_BREACH,
    REASON_UNFINANCED_LEVERAGE,
    REASON_ZERO_COST,
    BookWalkResult,
    FeasibilityError,
    PortfolioFoundationConfig,
    _DecisionPlan,
    _RowIndex,
    _walk_book,
    build_portfolio_foundation,
    compute_return_statistics,
)
from quant_strategies.decisions import InstrumentRef, RiskRule, TargetDecision

START = datetime(2024, 1, 1, tzinfo=UTC)


def ts(index: int) -> datetime:
    return START + timedelta(days=index)


def bar_rows(
    *closes: float,
    symbol: str = "SPY",
    funding_at: dict[int, float] | None = None,
) -> list[dict[str, object]]:
    funding_at = funding_at or {}
    rows: list[dict[str, object]] = []
    for index, close in enumerate(closes):
        row: dict[str, object] = {
            "symbol": symbol,
            "timestamp": ts(index),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "available_at": ts(index),
        }
        if index in funding_at:
            row["has_funding_event"] = True
            row["funding_timestamp"] = ts(index)
            row["funding_rate"] = funding_at[index]
        rows.append(row)
    return rows


def ohlc_rows(
    *bars: tuple[float, float, float, float],
    symbol: str = "SPY",
) -> list[dict[str, object]]:
    """Rows with explicit ``(open, high, low, close)`` per bar for intrabar barrier tests
    (``bar_rows`` only builds flat bars where open=high=low=close)."""
    rows: list[dict[str, object]] = []
    for index, (open_, high, low, close) in enumerate(bars):
        rows.append(
            {
                "symbol": symbol,
                "timestamp": ts(index),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "available_at": ts(index),
            }
        )
    return rows


def target(
    decision_index: int,
    weight: float,
    *,
    symbol: str = "SPY",
    kind: str = "equity_or_etf",
    risk_rule: RiskRule | None = None,
) -> TargetDecision:
    decision_time = ts(decision_index)
    return TargetDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind=kind, symbol=symbol),
        decision_time=decision_time,
        as_of_time=decision_time,
        target=weight,
        risk_rule=risk_rule,
    )


def data_config(end_index: int, *, kind: str = "bars", symbols=("SPY",)) -> DataConfig:
    return DataConfig(
        kind=kind,
        dataset="equity_1min" if kind == "bars" else None,
        symbols=tuple(symbols),
        start=START.date(),
        end=ts(end_index).date(),
    )


def walk(
    rows: list[dict[str, object]],
    decisions: list[TargetDecision],
    *,
    kind: str = "bars",
    per_side_cost_fraction: float = 0.0,
    config: PortfolioFoundationConfig | None = None,
    entry_lag_bars: int = 1,
) -> BookWalkResult:
    row_index = _RowIndex(rows)
    plan = _DecisionPlan(
        row_index,
        decisions,
        fill_model=FillModelConfig(price="close", entry_lag_bars=entry_lag_bars),
    )
    return _walk_book(
        row_index,
        plan,
        per_side_cost_fraction=per_side_cost_fraction,
        data_kind=kind,
        config=config or PortfolioFoundationConfig(subwindows=1, trial_count=5),
    )


# --------------------------------------------------------------------------------------
# compute_return_statistics — preserved Sharpe-SE / DSR math (reused, not deleted)
# --------------------------------------------------------------------------------------


def test_compute_return_statistics_reports_dsr_inputs_and_missing_trial_warning():
    values = [0.01, -0.005, 0.02, 0.0]
    stats = compute_return_statistics(values, trial_count=None, benchmark_sharpe=0.0)

    assert stats.return_sample_count == 4
    assert stats.mean_return == pytest.approx(sum(values) / len(values))
    assert stats.return_volatility == pytest.approx(stdev(values))
    assert stats.effective_sample_size is not None
    assert stats.sharpe is not None
    assert stats.sharpe_standard_error is not None
    assert stats.dsr is None
    assert "missing_trial_count" in stats.warnings


def test_compute_return_statistics_computes_finite_dsr_when_inputs_exist():
    stats = compute_return_statistics(
        [0.01, -0.005, 0.02, 0.0, 0.006, -0.002],
        trial_count=12,
        benchmark_sharpe=0.0,
    )
    assert stats.dsr is not None
    assert 0.0 <= stats.dsr <= 1.0
    assert stats.dsr_inputs is not None
    assert stats.dsr_inputs.trial_count == 12


def test_compute_return_statistics_min_sample_gate_blocks_finite_sharpe():
    # Three finite returns but a configured minimum of 5 -> non-scoreable, not a
    # Sharpe from sample count alone.
    stats = compute_return_statistics(
        [0.01, 0.02, -0.01], trial_count=5, benchmark_sharpe=0.0, min_return_sample=5
    )
    assert stats.sharpe is None
    assert stats.return_sample_count == 3
    assert "insufficient_return_sample" in stats.warnings


# --------------------------------------------------------------------------------------
# Same-symbol netting (Requirement: nets same-symbol exposure on one account)
# --------------------------------------------------------------------------------------


def test_repeated_identical_target_is_idempotent_no_stacking():
    # Long 0.5 at d0 (fills d1), then re-emit long 0.5 at d2 (fills d3). The second
    # target must net to a zero delta — no stacking to 1.0 gross.
    rows = bar_rows(100.0, 100.0, 100.0, 100.0, 100.0)
    decisions = [target(0, 0.5), target(2, 0.5)]
    result = walk(rows, decisions, config=PortfolioFoundationConfig(subwindows=1, trial_count=5))

    # Gross exposure holds at 0.5 throughout the held bars, never 1.0.
    held = [point.gross_exposure for point in result.path]
    assert max(held) == pytest.approx(0.5)
    # One open leg, never closed -> no round-trips.
    assert result.round_trips == ()


def test_offsetting_target_nets_and_trades_only_the_delta():
    # Long 1.0 at d0 (fills d1), reduce to long 0.4 at d2 (fills d3). Only the 0.6
    # reduction trades; gross drops to 0.4 with no extra round-trip (still long).
    rows = bar_rows(100.0, 100.0, 100.0, 100.0, 100.0)
    decisions = [target(0, 1.0), target(2, 0.4)]
    result = walk(rows, decisions, config=PortfolioFoundationConfig(subwindows=1, trial_count=5))

    assert result.path[1].gross_exposure == pytest.approx(1.0)
    assert result.path[3].gross_exposure == pytest.approx(0.4)
    # Trimming a same-sign leg is not a closed round-trip.
    assert result.round_trips == ()


def test_target_to_zero_closes_the_net_position_as_one_round_trip():
    rows = bar_rows(100.0, 100.0, 110.0, 110.0, 110.0)
    decisions = [target(0, 1.0), target(2, 0.0)]
    result = walk(rows, decisions, config=PortfolioFoundationConfig(subwindows=1, trial_count=5))

    assert len(result.round_trips) == 1
    trip = result.round_trips[0]
    assert trip.symbol == "SPY"
    assert trip.direction == "long"
    # Entry filled at d1 (price 100), exit filled at d3 (price 110), qty 1.0 of NAV.
    assert trip.realized_pnl == pytest.approx(INITIAL_EQUITY * 0.10)


def quote_bar_rows(
    *bars: tuple[float, float, float],
    symbol: str = "EURUSD",
) -> list[dict[str, object]]:
    """Quote bars as (close, bid, ask); ``mid`` is set to ``close`` for the reference."""
    rows: list[dict[str, object]] = []
    for index, (close, bid, ask) in enumerate(bars):
        rows.append(
            {
                "symbol": symbol,
                "timestamp": ts(index),
                "open": close,
                "high": max(close, ask),
                "low": min(close, bid),
                "close": close,
                "bid": bid,
                "ask": ask,
                "mid": close,
                "available_at": ts(index),
            }
        )
    return rows


def quote_walk(
    rows: list[dict[str, object]],
    decisions: list[TargetDecision],
) -> BookWalkResult:
    row_index = _RowIndex(rows)
    plan = _DecisionPlan(
        row_index,
        decisions,
        fill_model=FillModelConfig(price="quote", entry_lag_bars=1),
    )
    return _walk_book(
        row_index,
        plan,
        per_side_cost_fraction=0.0,
        data_kind="forex_with_quotes",
        config=PortfolioFoundationConfig(subwindows=1, trial_count=5),
    )


def test_quote_fill_close_of_long_crosses_bid_not_ask():
    # price="quote": opening a long lifts the ASK; closing that long SELLS, so it must
    # cross the BID -- not the ask (which would hand a free favorable half-spread on
    # every exit). Keyed on sign(delta), the traded direction (quant review #3).
    rows = quote_bar_rows(
        (100.0, 99.0, 101.0),  # d0
        (100.0, 99.0, 101.0),  # d1 entry fill bar: ask 101
        (110.0, 109.0, 111.0),  # d2
        (110.0, 109.0, 111.0),  # d3 exit fill bar: bid 109
    )
    decisions = [target(0, 1.0, symbol="EURUSD", kind="fx_pair"), target(2, 0.0, symbol="EURUSD")]
    result = quote_walk(rows, decisions)

    assert len(result.round_trips) == 1
    trip = result.round_trips[0]
    # Entry crossed the ask (101); exit crossed the bid (109) -- not 111.
    assert trip.entry_mark == pytest.approx(101.0)
    assert trip.exit_mark == pytest.approx(109.0)


def test_quote_fill_reversal_short_leg_crosses_bid():
    # Reversing long -> short SELLS through zero, so the crossing trade hits the BID.
    rows = quote_bar_rows(
        (100.0, 99.0, 101.0),
        (100.0, 99.0, 101.0),  # d1 entry (long) fills at ask 101
        (110.0, 109.0, 111.0),
        (110.0, 109.0, 111.0),  # d3 reversal fills at bid 109 (selling to flip short)
    )
    decisions = [
        target(0, 1.0, symbol="EURUSD", kind="fx_pair"),
        target(2, -1.0, symbol="EURUSD", kind="fx_pair"),
    ]
    result = quote_walk(rows, decisions)

    assert len(result.round_trips) == 1
    # The closed long leg exits by crossing the bid (the reversal sells).
    assert result.round_trips[0].exit_mark == pytest.approx(109.0)


def test_reversal_records_one_round_trip_and_reopens_short():
    rows = bar_rows(100.0, 100.0, 110.0, 110.0, 110.0)
    # Long 1.0 (fills d1 @100), flip to short 1.0 at d2 (fills d3 @110).
    decisions = [target(0, 1.0), target(2, -1.0)]
    result = walk(rows, decisions, config=PortfolioFoundationConfig(subwindows=1, trial_count=5))

    assert len(result.round_trips) == 1
    assert result.round_trips[0].direction == "long"
    # The reopened leg is short -> net exposure sign flips negative.
    assert result.path[3].net_exposure == pytest.approx(1.0)
    assert result.path[4].gross_exposure == pytest.approx(1.0)


# --------------------------------------------------------------------------------------
# weight -> quantity at the decision bar, then held (Requirement / D1)
# --------------------------------------------------------------------------------------


def test_weight_to_quantity_sized_at_fill_bar_then_held_as_quantity():
    # Long 1.0 at d0 fills at d1 @ price 100 -> qty = 100 NAV / 100 = 1.0 unit.
    # Price then rises to 120 at d2: NAV = 100 + 1.0*(120-100) = 120 (held as qty).
    rows = bar_rows(100.0, 100.0, 120.0)
    decisions = [target(0, 1.0)]
    result = walk(rows, decisions, config=PortfolioFoundationConfig(subwindows=1, trial_count=5))

    assert result.path[0].portfolio_value == pytest.approx(INITIAL_EQUITY)
    assert result.path[1].portfolio_value == pytest.approx(INITIAL_EQUITY)
    assert result.path[2].portfolio_value == pytest.approx(120.0)
    # Weight drifts with price (held as quantity, not constant weight).
    assert result.path[2].gross_exposure == pytest.approx(120.0 / 120.0)


def test_same_bar_intended_gross_is_fill_order_independent():
    # Two symbols targeted at the same decision bar; total intended weight 0.9.
    # Sized against one pre-entry equity snapshot, so measured gross == 0.9
    # regardless of which leg is applied first.
    rows = bar_rows(100.0, 100.0, 100.0, symbol="AAA") + bar_rows(50.0, 50.0, 50.0, symbol="BBB")
    forward = [target(0, 0.5, symbol="AAA"), target(0, 0.4, symbol="BBB")]
    reversed_order = [target(0, 0.4, symbol="BBB"), target(0, 0.5, symbol="AAA")]
    cfg = PortfolioFoundationConfig(subwindows=1, trial_count=5)

    result_a = walk(rows, forward, config=cfg)
    result_b = walk(rows, reversed_order, config=cfg)

    assert result_a.path[1].gross_exposure == pytest.approx(0.9)
    assert result_b.path[1].gross_exposure == pytest.approx(0.9)
    assert result_a.path[1].gross_exposure == pytest.approx(result_b.path[1].gross_exposure)


# --------------------------------------------------------------------------------------
# RiskRule flatten + re-entry latch (Requirement / D2)
# --------------------------------------------------------------------------------------


def test_risk_rule_stop_loss_flattens_at_crossing_bar():
    # Long with a 5% stop. Entry @100 at d1; price drops to 94 at d2 (>5% adverse)
    # -> flattened that bar.
    rows = bar_rows(100.0, 100.0, 94.0, 94.0)
    decisions = [target(0, 1.0, risk_rule=RiskRule(stop_loss=0.05))]
    result = walk(rows, decisions, config=PortfolioFoundationConfig(subwindows=1, trial_count=5))

    assert len(result.round_trips) == 1
    assert result.round_trips[0].exit_time == ts(2)
    # Flat after the stop fires.
    assert result.path[2].gross_exposure == pytest.approx(0.0)
    assert result.path[3].gross_exposure == pytest.approx(0.0)


def test_standing_target_does_not_reenter_until_a_new_target_after_stop():
    # Long 1.0 with stop at d0 (fills d1 @100). Stop fires at d2 (price 94). The
    # SAME standing target must NOT re-enter; re-emitting it at d4 (same weight) is
    # suppressed; only a different target re-enters.
    rows = bar_rows(100.0, 100.0, 94.0, 94.0, 94.0, 94.0, 94.0)
    decisions = [
        target(0, 1.0, risk_rule=RiskRule(stop_loss=0.05)),
        target(4, 1.0, risk_rule=RiskRule(stop_loss=0.05)),  # identical -> suppressed
    ]
    result = walk(rows, decisions, config=PortfolioFoundationConfig(subwindows=1, trial_count=5))

    # Exactly one round-trip; latched flat for the remainder.
    assert len(result.round_trips) == 1
    assert all(point.gross_exposure == pytest.approx(0.0) for point in result.path[2:])


def test_new_different_target_clears_the_latch_and_reenters():
    rows = bar_rows(100.0, 100.0, 94.0, 94.0, 94.0, 94.0, 94.0)
    decisions = [
        target(0, 1.0, risk_rule=RiskRule(stop_loss=0.05)),
        target(4, 0.5),  # different weight -> clears latch, re-enters
    ]
    result = walk(rows, decisions, config=PortfolioFoundationConfig(subwindows=1, trial_count=5))

    assert len(result.round_trips) == 1  # only the stopped leg closed so far
    # Re-entered at d5 (fills the bar after the d4 decision) at weight 0.5.
    assert result.path[5].gross_exposure == pytest.approx(0.5)


def test_take_profit_flattens_at_the_level_not_the_close():
    # Long with a 10% TP. The bar reaches 112 (high >= the 110 level), so the TP fires
    # that bar — but it fills at the *level* (110), never granted the gap-favorable close
    # at 112 (conservative; no gap-favorable bonus). Realized PnL is the 10% level move.
    rows = bar_rows(100.0, 100.0, 112.0, 112.0)
    decisions = [target(0, 1.0, risk_rule=RiskRule(take_profit=0.10))]
    result = walk(rows, decisions, config=PortfolioFoundationConfig(subwindows=1, trial_count=5))

    assert len(result.round_trips) == 1
    assert result.round_trips[0].exit_time == ts(2)
    assert result.round_trips[0].exit_mark == pytest.approx(110.0)
    assert result.round_trips[0].realized_pnl == pytest.approx(INITIAL_EQUITY * 0.10)


def test_stop_fires_on_intrabar_low_even_when_the_close_recovers():
    # The core action-8 fix: a long with a 5% stop. At d2 the bar dips to a low of 94
    # (pierces the 95 stop) but CLOSES back at 99. The close-only model would miss this;
    # the intrabar model fires the stop at the 95 level (open 99 is above it, no gap).
    rows = ohlc_rows(
        (100.0, 100.0, 100.0, 100.0),
        (100.0, 100.0, 100.0, 100.0),
        (99.0, 99.0, 94.0, 99.0),
        (99.0, 99.0, 99.0, 99.0),
    )
    decisions = [target(0, 1.0, risk_rule=RiskRule(stop_loss=0.05))]
    result = walk(rows, decisions, config=PortfolioFoundationConfig(subwindows=1, trial_count=5))

    assert len(result.round_trips) == 1
    assert result.round_trips[0].exit_time == ts(2)
    assert result.round_trips[0].exit_reason == "stop_loss"
    assert result.round_trips[0].exit_mark == pytest.approx(95.0)
    assert result.round_trips[0].realized_pnl == pytest.approx(INITIAL_EQUITY * -0.05)


def test_stop_gap_through_open_fills_at_the_worse_open():
    # A long with a 5% stop (level 95). At d2 the bar GAPS down through the stop: it
    # opens at 92 (already below 95) and trades to a low of 90. The fill is the worse
    # open (92), not the stop level — gap risk the close-only model hid.
    rows = ohlc_rows(
        (100.0, 100.0, 100.0, 100.0),
        (100.0, 100.0, 100.0, 100.0),
        (92.0, 92.0, 90.0, 91.0),
        (91.0, 91.0, 91.0, 91.0),
    )
    decisions = [target(0, 1.0, risk_rule=RiskRule(stop_loss=0.05))]
    result = walk(rows, decisions, config=PortfolioFoundationConfig(subwindows=1, trial_count=5))

    assert len(result.round_trips) == 1
    assert result.round_trips[0].exit_reason == "stop_loss"
    assert result.round_trips[0].exit_mark == pytest.approx(92.0)
    assert result.round_trips[0].realized_pnl == pytest.approx(INITIAL_EQUITY * -0.08)


def test_same_bar_stop_and_target_resolves_to_the_adverse_stop():
    # A long with both a 5% stop (95) and a 5% take-profit (105). At d2 the bar touches
    # both (high 106 >= 105, low 94 <= 95). Intrabar order is unobservable, so the
    # adverse stop wins the tie (conservative).
    rows = ohlc_rows(
        (100.0, 100.0, 100.0, 100.0),
        (100.0, 100.0, 100.0, 100.0),
        (100.0, 106.0, 94.0, 100.0),
        (100.0, 100.0, 100.0, 100.0),
    )
    decisions = [target(0, 1.0, risk_rule=RiskRule(stop_loss=0.05, take_profit=0.05))]
    result = walk(rows, decisions, config=PortfolioFoundationConfig(subwindows=1, trial_count=5))

    assert len(result.round_trips) == 1
    assert result.round_trips[0].exit_reason == "stop_loss"
    assert result.round_trips[0].exit_mark == pytest.approx(95.0)


# --------------------------------------------------------------------------------------
# At-risk statistics + min-sample gate (Requirement: at-risk bars)
# --------------------------------------------------------------------------------------


def test_flat_bars_do_not_inflate_effective_sample_size():
    # Hold while invested, then flat for a long tail after the exit fills. The flat
    # tail (after the position has fully closed) contributes no at-risk returns.
    # Exit target at d3 fills at d4, so [d3,d4] is the last at-risk interval (a 0.0
    # return as price is flat); d5+ are flat and excluded.
    rows = bar_rows(100.0, 100.0, 110.0, 121.0, 121.0, 121.0, 121.0, 121.0, 121.0, 121.0)
    decisions = [target(0, 1.0), target(3, 0.0)]
    result = walk(rows, decisions, config=PortfolioFoundationConfig(subwindows=1, trial_count=5))

    at_risk = [point for point in result.path if point.at_risk]
    # At-risk intervals: d1->d2, d2->d3, and the exit-fill interval d3->d4. None of
    # the long flat tail (d5..d9) is at-risk.
    assert [point.timestamp for point in at_risk] == [ts(2), ts(3), ts(4)]
    assert all(not point.at_risk for point in result.path[5:])


def test_flat_tail_does_not_change_sample_count_vs_short_window():
    # The same trade evaluated over a short window and over a window with a long
    # flat tail yields the same at-risk return sample — the tail is not padded in.
    short = bar_rows(100.0, 100.0, 110.0, 121.0, 121.0)
    long_tail = bar_rows(100.0, 100.0, 110.0, 121.0, 121.0, 121.0, 121.0, 121.0, 121.0)
    decisions_short = [target(0, 1.0), target(3, 0.0)]
    decisions_long = [target(0, 1.0), target(3, 0.0)]

    def sample_count(rows: list[dict[str, object]], end: int) -> int:
        foundation = build_portfolio_foundation(
            rows=rows,
            decisions=decisions_short if end == 4 else decisions_long,
            data=data_config(end),
            fill_model=FillModelConfig(price="close", entry_lag_bars=1),
            cost_model=CostModelConfig(fee_bps_per_side=1.0, slippage_bps_per_side=0.0),
            config=PortfolioFoundationConfig(subwindows=1, trial_count=5),
        )
        full = foundation.matrix_payload()["scenarios"]["realistic_costs"]["full_train"]
        return full["return_sample_count"]

    assert sample_count(short, 4) == sample_count(long_tail, 8)


def test_degenerate_sample_gated_as_non_scoreable_verdict():
    # One at-risk interval only -> below the default minimum of 2 -> insufficient.
    rows = bar_rows(100.0, 100.0, 110.0)
    decisions = [target(0, 1.0)]
    foundation = build_portfolio_foundation(
        rows=rows,
        decisions=decisions,
        data=data_config(2),
        fill_model=FillModelConfig(price="close", entry_lag_bars=1),
        cost_model=CostModelConfig(fee_bps_per_side=1.0, slippage_bps_per_side=0.0),
        config=PortfolioFoundationConfig(subwindows=1, trial_count=5),
    )
    realistic = foundation.matrix_payload()["scenarios"]["realistic_costs"]
    assert realistic["feasibility"]["feasible"] is False
    assert realistic["feasibility"]["reason"] == REASON_INSUFFICIENT_SAMPLES
    assert foundation.feasible is False


# --------------------------------------------------------------------------------------
# Feasibility verdicts (Requirement: fail-closed verdict, never clamp)
# --------------------------------------------------------------------------------------


def test_leverage_budget_breach_fails_closed_with_observed_gross():
    # Two longs summing to gross 1.4 at the same bar, budget 1.0 -> infeasible.
    rows = bar_rows(100.0, 100.0, 100.0, symbol="AAA") + bar_rows(100.0, 100.0, 100.0, symbol="BBB")
    decisions = [target(0, 0.8, symbol="AAA"), target(0, 0.6, symbol="BBB")]
    with pytest.raises(FeasibilityError) as excinfo:
        walk(
            rows,
            decisions,
            config=PortfolioFoundationConfig(
                subwindows=1, trial_count=5, max_gross_exposure=1.0, max_net_exposure=1.0
            ),
        )
    verdict = excinfo.value.verdict
    assert verdict.feasible is False
    assert verdict.reason == REASON_LEVERAGE_BUDGET_BREACH
    assert verdict.observed_gross == pytest.approx(1.4)


def test_net_budget_breach_fails_closed_even_when_gross_allowed():
    # Gross 1.2 within a 1.5 gross budget, but net 1.2 exceeds a 1.0 net budget.
    rows = bar_rows(100.0, 100.0, 100.0, symbol="AAA") + bar_rows(100.0, 100.0, 100.0, symbol="BBB")
    decisions = [target(0, 0.6, symbol="AAA"), target(0, 0.6, symbol="BBB")]
    with pytest.raises(FeasibilityError) as excinfo:
        walk(
            rows,
            decisions,
            config=PortfolioFoundationConfig(
                subwindows=1, trial_count=5, max_gross_exposure=1.5, max_net_exposure=1.0
            ),
        )
    assert excinfo.value.verdict.reason == REASON_LEVERAGE_BUDGET_BREACH
    assert excinfo.value.verdict.observed_net == pytest.approx(1.2)


def test_offsetting_legs_pass_net_budget_but_count_gross():
    # Long AAA 0.6 + short BBB 0.6: gross 1.2, net 0.0. Allowed under net budget 1.0
    # and gross budget 1.5 -> feasible (netting is economically correct).
    rows = bar_rows(100.0, 100.0, 100.0, symbol="AAA") + bar_rows(100.0, 100.0, 100.0, symbol="BBB")
    decisions = [target(0, 0.6, symbol="AAA"), target(0, -0.6, symbol="BBB")]
    result = walk(
        rows,
        decisions,
        config=PortfolioFoundationConfig(
            subwindows=1, trial_count=5, max_gross_exposure=1.5, max_net_exposure=1.0
        ),
    )
    assert result.feasibility.feasible is True
    assert result.path[1].gross_exposure == pytest.approx(1.2)
    assert result.path[1].net_exposure == pytest.approx(0.0)


def test_zero_cost_on_scoreable_run_is_non_scoreable():
    rows = bar_rows(100.0, 100.0, 110.0, 121.0)
    decisions = [target(0, 1.0)]
    foundation = build_portfolio_foundation(
        rows=rows,
        decisions=decisions,
        data=data_config(3),
        fill_model=FillModelConfig(price="close", entry_lag_bars=1),
        cost_model=CostModelConfig(fee_bps_per_side=0.0, slippage_bps_per_side=0.0),
        config=PortfolioFoundationConfig(subwindows=1, trial_count=5),
    )
    realistic = foundation.matrix_payload()["scenarios"]["realistic_costs"]
    assert realistic["feasibility"]["feasible"] is False
    assert realistic["feasibility"]["reason"] == REASON_ZERO_COST


def test_unfinanced_leverage_fails_closed_when_budget_permits_net_above_one():
    # Operator net budget permits 2.0, but equity financing is not modeled, so an
    # intended net of 1.5 is infeasible (unfinanced_leverage) rather than scored
    # with free leverage. This is the residual guard distinct from the budget.
    rows = bar_rows(100.0, 100.0, 100.0)
    decisions = [target(0, 1.5)]
    with pytest.raises(FeasibilityError) as excinfo:
        walk(
            rows,
            decisions,
            kind="bars",
            config=PortfolioFoundationConfig(
                subwindows=1, trial_count=5, max_gross_exposure=2.0, max_net_exposure=2.0
            ),
        )
    verdict = excinfo.value.verdict
    assert verdict.reason == REASON_UNFINANCED_LEVERAGE
    assert verdict.observed_net == pytest.approx(1.5)


def test_equity_fully_invested_with_costs_is_not_a_false_unfinanced_breach():
    # A fully-invested long (intended net 1.0) must stay feasible even though costs
    # shrink NAV below the held notional (live marked net drifts > 1.0). Live drift
    # is a utilization signal, not an infeasibility (D3).
    rows = bar_rows(100.0, 100.0, 110.0, 121.0)
    result = walk(
        rows,
        [target(0, 1.0)],
        kind="bars",
        per_side_cost_fraction=0.01,
        config=PortfolioFoundationConfig(subwindows=1, trial_count=5, max_net_exposure=1.0),
    )
    assert result.feasibility.feasible is True
    assert max(point.net_exposure for point in result.path) > 1.0  # marked drift exists


def test_crypto_perp_is_exempt_from_unfinanced_leverage_verdict():
    # A crypto-perp book may run net leverage above 1.0 because funding is modeled.
    rows = bar_rows(100.0, 100.0, 100.0, 100.0, symbol="BTC-PERP")
    decisions = [target(0, 2.0, symbol="BTC-PERP", kind="crypto_perp")]
    result = walk(
        rows,
        decisions,
        kind="crypto_perp_funding",
        config=PortfolioFoundationConfig(
            subwindows=1, trial_count=5, max_gross_exposure=2.0, max_net_exposure=2.0
        ),
    )
    assert result.feasibility.feasible is True
    assert result.path[1].net_exposure == pytest.approx(2.0)


def test_equity_net_above_one_intent_is_a_leverage_budget_breach_not_unfinanced():
    # An equity book that *intends* net 2.0 is caught by the leverage budget first
    # (the budget is the operator envelope); unfinanced_leverage is the residual
    # guard for kinds permitted above net 1.0 only when financing is modeled.
    rows = bar_rows(100.0, 100.0, 100.0)
    decisions = [target(0, 2.0)]
    with pytest.raises(FeasibilityError) as excinfo:
        walk(
            rows,
            decisions,
            kind="bars",
            config=PortfolioFoundationConfig(
                subwindows=1, trial_count=5, max_gross_exposure=1.0, max_net_exposure=1.0
            ),
        )
    assert excinfo.value.verdict.reason == REASON_LEVERAGE_BUDGET_BREACH


# --------------------------------------------------------------------------------------
# Funding on the net held position (reuses funding.py invariants)
# --------------------------------------------------------------------------------------


def test_funding_charged_on_net_held_position():
    # Long 1.0 perp; a +1% funding event at d2 while held. A long pays funding:
    # cashflow = -qty*mark*rate = -(1.0)*(100)*0.01 = -1.0 -> NAV drops by 1.0.
    rows = bar_rows(100.0, 100.0, 100.0, 100.0, symbol="BTC-PERP", funding_at={2: 0.01})
    decisions = [target(0, 1.0, symbol="BTC-PERP", kind="crypto_perp")]
    result = walk(
        rows,
        decisions,
        kind="crypto_perp_funding",
        config=PortfolioFoundationConfig(subwindows=1, trial_count=5),
    )
    # Entry filled d1 @100 (qty 1.0 NAV-unit = 1.0 contract). Funding at d2.
    assert result.path[2].portfolio_value == pytest.approx(INITIAL_EQUITY - 1.0)


def test_duplicate_funding_timestamps_deduped():
    rows = bar_rows(100.0, 100.0, 100.0, 100.0, symbol="BTC-PERP", funding_at={2: 0.01})
    # Inject a duplicate funding event row at d3 with the SAME funding_timestamp d2.
    rows[3]["has_funding_event"] = True
    rows[3]["funding_timestamp"] = ts(2)
    rows[3]["funding_rate"] = 0.01
    decisions = [target(0, 1.0, symbol="BTC-PERP", kind="crypto_perp")]
    result = walk(
        rows,
        decisions,
        kind="crypto_perp_funding",
        config=PortfolioFoundationConfig(subwindows=1, trial_count=5),
    )
    # Funding applied once, not twice.
    assert result.path[-1].portfolio_value == pytest.approx(INITIAL_EQUITY - 1.0)


# --------------------------------------------------------------------------------------
# NAV <-> round-trip ledger reconciliation (Requirement / D4)
# --------------------------------------------------------------------------------------


def _reconcile(result: BookWalkResult) -> None:
    # When the book ends flat, final NAV - initial equity == Σ round-trip realized PnL.
    assert result.path[-1].gross_exposure == pytest.approx(0.0)
    realized_from_ledger = sum(trip.realized_pnl for trip in result.round_trips)
    assert result.realized_pnl == pytest.approx(realized_from_ledger)
    assert (result.final_nav - INITIAL_EQUITY) == pytest.approx(realized_from_ledger)


def test_nav_reconciles_with_ledger_single_round_trip_with_costs():
    rows = bar_rows(100.0, 100.0, 110.0, 110.0, 110.0)
    decisions = [target(0, 1.0), target(2, 0.0)]
    result = walk(
        rows,
        decisions,
        per_side_cost_fraction=0.001,
        config=PortfolioFoundationConfig(subwindows=1, trial_count=5),
    )
    _reconcile(result)


def test_nav_reconciles_with_ledger_multi_symbol_and_funding():
    aaa = bar_rows(100.0, 100.0, 108.0, 108.0, 108.0, symbol="AAA")
    btc = bar_rows(50.0, 50.0, 55.0, 55.0, 55.0, symbol="BTC-PERP", funding_at={2: 0.01})
    rows = aaa + btc
    decisions = [
        target(0, 0.5, symbol="AAA"),
        target(0, 0.5, symbol="BTC-PERP", kind="crypto_perp"),
        target(3, 0.0, symbol="AAA"),
        target(3, 0.0, symbol="BTC-PERP", kind="crypto_perp"),
    ]
    result = walk(
        rows,
        decisions,
        kind="crypto_perp_funding",
        per_side_cost_fraction=0.0005,
        config=PortfolioFoundationConfig(subwindows=1, trial_count=5),
    )
    _reconcile(result)


def test_nav_reconciles_after_reversal():
    rows = bar_rows(100.0, 100.0, 110.0, 110.0, 105.0, 105.0, 105.0)
    decisions = [target(0, 1.0), target(2, -1.0), target(4, 0.0)]
    result = walk(
        rows,
        decisions,
        per_side_cost_fraction=0.001,
        config=PortfolioFoundationConfig(subwindows=1, trial_count=5),
    )
    assert len(result.round_trips) == 2
    _reconcile(result)


def test_non_flat_ending_book_marks_open_winner_into_nav_not_into_ledger():
    # A long held open at the window boundary: the open winner is in the NAV path
    # but in no closed round-trip. The realized-ledger sum diverges *below* the
    # marked NAV change by exactly the open leg's unrealized PnL, which is why the
    # gated number must be the marked NAV return, not the realized sum (blocker #1).
    rows = bar_rows(100.0, 100.0, 110.0, 110.0)
    result = walk(
        rows,
        [target(0, 1.0)],  # opens long (fills @100), never closed
        config=PortfolioFoundationConfig(subwindows=1, trial_count=5),
    )
    # Not flat at the boundary, and no closed round-trip.
    assert result.path[-1].gross_exposure > 0.0
    assert result.round_trips == ()
    realized_from_ledger = sum(trip.realized_pnl for trip in result.round_trips)
    assert realized_from_ledger == pytest.approx(0.0)
    # qty = 100 NAV / 100 fill = 1.0 unit, marked at last close 110 -> NAV 110.
    assert result.final_nav == pytest.approx(110.0)
    marked_return = (result.final_nav - INITIAL_EQUITY) / INITIAL_EQUITY
    assert marked_return == pytest.approx(0.10)
    # The realized sum (0) is strictly below the marked return (the divergence the
    # gated metric must not collapse to zero).
    assert realized_from_ledger < marked_return * INITIAL_EQUITY


# --------------------------------------------------------------------------------------
# Closed round trips counted by exit time across subwindows (Requirement)
# --------------------------------------------------------------------------------------


def test_closed_round_trips_counted_by_exit_time_per_subwindow():
    # Open before a subwindow boundary, close inside the second subwindow.
    rows = bar_rows(100.0, 101.0, 103.0, 102.0, 104.0, 105.0, 106.0, 107.0)
    decisions = [target(0, 1.0), target(4, 0.0)]
    foundation = build_portfolio_foundation(
        rows=rows,
        decisions=decisions,
        data=data_config(7),
        fill_model=FillModelConfig(price="close", entry_lag_bars=1),
        cost_model=CostModelConfig(fee_bps_per_side=1.0, slippage_bps_per_side=0.0),
        config=PortfolioFoundationConfig(subwindows=2, trial_count=5),
    )
    realistic = foundation.matrix_payload()["scenarios"]["realistic_costs"]
    counts = [sub["closed_trade_count"] for sub in realistic["subwindows"]]
    assert sum(counts) == 1
    assert realistic["full_train"]["closed_trade_count"] == 1


# --------------------------------------------------------------------------------------
# Foundation surface: two scenarios, utilization fields, no raw path traces
# --------------------------------------------------------------------------------------


def test_build_foundation_emits_three_scenarios_and_utilization_fields():
    rows = bar_rows(100.0, 100.0, 110.0, 121.0, 121.0)
    decisions = [target(0, 1.0)]
    foundation = build_portfolio_foundation(
        rows=rows,
        decisions=decisions,
        data=data_config(4),
        fill_model=FillModelConfig(price="close", entry_lag_bars=1),
        cost_model=CostModelConfig(fee_bps_per_side=1.0, slippage_bps_per_side=0.0),
        config=PortfolioFoundationConfig(subwindows=1, trial_count=5, cost_stress_multiplier=2.0),
    )
    payload = foundation.matrix_payload()
    assert set(payload["scenarios"]) == {"realistic_costs", "cost_stress", "fill_stress"}
    full = payload["scenarios"]["realistic_costs"]["full_train"]
    for field in (
        "max_gross_utilization",
        "mean_gross_utilization",
        "max_net_utilization",
        "mean_net_utilization",
    ):
        assert field in full
    assert full["max_gross_utilization"] >= full["mean_gross_utilization"]

    text = __import__("json").dumps(payload)
    for forbidden in ("period_return", "portfolio_value", "navs"):
        assert forbidden not in text


def test_fill_stress_scenario_worsens_barrier_exits_without_touching_realistic():
    # A long stopped out at d3. The fill_stress scenario applies adverse slippage to the
    # barrier exit, so its total_return is strictly worse than realistic_costs — while the
    # realistic (climbed) path is identical whether the knob is set or zeroed out.
    rows = ohlc_rows(
        (100.0, 100.0, 100.0, 100.0),
        (100.0, 100.0, 100.0, 100.0),
        (100.0, 100.0, 100.0, 100.0),
        (96.0, 96.0, 94.0, 96.0),
        (96.0, 96.0, 96.0, 96.0),
    )
    decisions = [target(0, 1.0, risk_rule=RiskRule(stop_loss=0.05))]
    cost_model = CostModelConfig(fee_bps_per_side=1.0, slippage_bps_per_side=0.0)
    kwargs = {
        "rows": rows,
        "decisions": decisions,
        "data": data_config(4),
        "fill_model": FillModelConfig(price="close", entry_lag_bars=1),
        "cost_model": cost_model,
    }

    stressed = build_portfolio_foundation(
        config=PortfolioFoundationConfig(subwindows=1, trial_count=5, fill_stress_fraction=0.01),
        **kwargs,
    ).matrix_payload()["scenarios"]
    assert set(stressed) == {"realistic_costs", "cost_stress", "fill_stress"}
    realistic_return = stressed["realistic_costs"]["full_train"]["total_return"]
    fill_stress_return = stressed["fill_stress"]["full_train"]["total_return"]
    assert fill_stress_return < realistic_return

    # Opting the knob out drops the scenario and leaves the realistic path byte-identical.
    opted_out = build_portfolio_foundation(
        config=PortfolioFoundationConfig(subwindows=1, trial_count=5, fill_stress_fraction=0.0),
        **kwargs,
    ).matrix_payload()["scenarios"]
    assert set(opted_out) == {"realistic_costs", "cost_stress"}
    assert opted_out["realistic_costs"]["full_train"]["total_return"] == pytest.approx(
        realistic_return
    )


def test_build_foundation_reports_every_configured_subwindow_even_when_empty():
    rows = bar_rows(100.0, 101.0, 102.0)
    foundation = build_portfolio_foundation(
        rows=rows,
        decisions=[],
        data=data_config(2),
        fill_model=FillModelConfig(price="close", entry_lag_bars=1),
        cost_model=CostModelConfig(fee_bps_per_side=1.0, slippage_bps_per_side=0.0),
        config=PortfolioFoundationConfig(subwindows=4, trial_count=None),
    )
    subwindows = foundation.matrix_payload()["scenarios"]["realistic_costs"]["subwindows"]
    assert len(subwindows) == 4
    assert {item["window_id"] for item in subwindows} == {
        "train_1",
        "train_2",
        "train_3",
        "train_4",
    }


def test_max_symbol_concentration_from_netted_book():
    aaa = bar_rows(100.0, 100.0, 100.0, symbol="AAA")
    bbb = bar_rows(100.0, 100.0, 100.0, symbol="BBB")
    rows = aaa + bbb
    decisions = [target(0, 0.6, symbol="AAA"), target(0, 0.2, symbol="BBB")]
    foundation = build_portfolio_foundation(
        rows=rows,
        decisions=decisions,
        data=data_config(2, symbols=("AAA", "BBB")),
        fill_model=FillModelConfig(price="close", entry_lag_bars=1),
        cost_model=CostModelConfig(fee_bps_per_side=1.0, slippage_bps_per_side=0.0),
        config=PortfolioFoundationConfig(subwindows=1, trial_count=5),
    )
    full = foundation.matrix_payload()["scenarios"]["realistic_costs"]["full_train"]
    # Concentration = max leg notional / gross notional = 0.6 / 0.8 = 0.75.
    assert full["max_symbol_concentration"] == pytest.approx(0.75)


def test_walk_function_is_importable_and_pure_path_object():
    # Smoke: the low-level walk entry returns the documented result shape.
    rows = bar_rows(100.0, 100.0, 110.0, 110.0)
    result = walk(rows, [target(0, 1.0), target(2, 0.0)])
    assert isinstance(result, BookWalkResult)
    assert isinstance(result.path, tuple)
    assert isinstance(result.round_trips, tuple)
    assert math.isfinite(result.final_nav)
    assert callable(_walk_book)
