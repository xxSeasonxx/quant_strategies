from __future__ import annotations

from datetime import UTC, datetime, timedelta
from statistics import NormalDist
from types import SimpleNamespace

import pytest

from quant_strategies.core.config import CostModelConfig, DataConfig, FillModelConfig
from quant_strategies.core.portfolio_foundation import (
    PortfolioFoundationConfig,
    build_portfolio_foundation,
    compute_return_statistics,
)
from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision


def bar_rows(*closes: float) -> list[dict[str, object]]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        {
            "symbol": "SPY",
            "timestamp": start + timedelta(days=index),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "available_at": start + timedelta(days=index),
        }
        for index, close in enumerate(closes)
    ]


def decision(
    decision_time: datetime,
    *,
    symbol: str = "SPY",
    direction: str = "long",
    weight: float = 1.0,
    hold_bars: int = 1,
) -> StrategyDecision:
    return StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="equity_or_etf", symbol=symbol),
        decision_time=decision_time,
        as_of_time=decision_time,
        target=PositionTarget(
            direction=direction,
            sizing_kind="target_weight",
            size=weight,
        ),
        exit_policy=ExitPolicy(max_hold_bars=hold_bars),
    )


def executed_trade(
    rows: list[dict[str, object]],
    *,
    entry_index: int,
    exit_index: int,
    symbol: str = "SPY",
    side: str = "long",
    weight: float = 1.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        side=side,
        weight=weight,
        entry_time=rows[entry_index]["timestamp"],
        exit_time=rows[exit_index]["timestamp"],
        entry_price=rows[entry_index]["close"],
        exit_price=rows[exit_index]["close"],
    )


def test_compute_return_statistics_reports_dsr_inputs_and_missing_trial_warning():
    stats = compute_return_statistics(
        [0.01, -0.005, 0.02, 0.0],
        trial_count=None,
        benchmark_sharpe=0.0,
    )

    assert stats.return_sample_count == 4
    assert stats.effective_sample_size is not None
    assert stats.sharpe is not None
    assert stats.sharpe_standard_error is not None
    assert stats.skew is not None
    assert stats.kurtosis is not None
    assert stats.dsr is None
    assert "missing_trial_count" in stats.warnings
    assert stats.dsr_inputs is not None
    assert stats.dsr_inputs.sample_length == 4
    assert stats.dsr_inputs.trial_count is None


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
    assert stats.dsr_inputs.benchmark_sharpe == pytest.approx(0.0)
    expected_threshold = stats.sharpe_standard_error * (
        (1.0 - 0.5772156649015329) * NormalDist().inv_cdf(1.0 - (1.0 / 12.0))
        + 0.5772156649015329 * NormalDist().inv_cdf(1.0 - (1.0 / (12.0 * 2.718281828459045)))
    )
    assert stats.dsr_inputs.deflated_sharpe_threshold == pytest.approx(expected_threshold)
    assert stats.dsr_inputs.formula == "bailey_lopez_de_prado_expected_max_sharpe"


def test_compute_return_statistics_sparse_missing_trial_count_reports_both_warnings():
    stats = compute_return_statistics([0.01], trial_count=None, benchmark_sharpe=0.0)

    assert stats.dsr is None
    assert set(stats.warnings) == {"insufficient_return_sample", "missing_trial_count"}


def test_build_portfolio_foundation_slices_windows_and_counts_closed_trades_by_exit_time():
    rows = bar_rows(100.0, 101.0, 103.0, 102.0, 104.0, 105.0)
    decisions = [
        decision(rows[0]["timestamp"], hold_bars=1),
        decision(rows[3]["timestamp"], hold_bars=1),
    ]

    foundation = build_portfolio_foundation(
        rows=rows,
        decisions=decisions,
        executed_trades=[
            executed_trade(rows, entry_index=1, exit_index=2),
            executed_trade(rows, entry_index=4, exit_index=5),
        ],
        data=DataConfig(
            kind="bars",
            dataset="equity_1min",
            symbols=("SPY",),
            start=datetime(2024, 1, 1).date(),
            end=datetime(2024, 1, 6).date(),
        ),
        fill_model=FillModelConfig(price="close", entry_lag_bars=1),
        cost_model=CostModelConfig(fee_bps_per_side=0.0, slippage_bps_per_side=0.0),
        config=PortfolioFoundationConfig(subwindows=2, trial_count=5, benchmark_sharpe=0.0),
    )

    payload = foundation.matrix_payload()
    realistic = payload["scenarios"]["realistic_costs"]
    stressed = payload["scenarios"]["cost_stress"]

    assert foundation.evidence_class == "quick_run_portfolio_foundation_diagnostic"
    assert len(realistic["subwindows"]) == 2
    assert len(stressed["subwindows"]) == 2
    assert realistic["subwindows"][0]["closed_trade_count"] == 1
    assert realistic["subwindows"][1]["closed_trade_count"] == 1
    assert realistic["subwindows"][0]["max_symbol_concentration"] == pytest.approx(1.0)
    assert "period_returns" not in realistic["subwindows"][0]


def test_build_portfolio_foundation_does_not_double_count_open_notional():
    rows = bar_rows(100.0, 100.0, 100.0)
    decisions = [decision(rows[0]["timestamp"], hold_bars=1)]

    foundation = build_portfolio_foundation(
        rows=rows,
        decisions=decisions,
        executed_trades=[executed_trade(rows, entry_index=1, exit_index=2)],
        data=DataConfig(
            kind="bars",
            dataset="equity_1min",
            symbols=("SPY",),
            start=datetime(2024, 1, 1).date(),
            end=datetime(2024, 1, 3).date(),
        ),
        fill_model=FillModelConfig(price="close", entry_lag_bars=1),
        cost_model=CostModelConfig(fee_bps_per_side=0.0, slippage_bps_per_side=0.0),
        config=PortfolioFoundationConfig(subwindows=1, trial_count=5, benchmark_sharpe=0.0),
    )

    subwindow = foundation.matrix_payload()["scenarios"]["realistic_costs"]["subwindows"][0]
    assert subwindow["max_drawdown"] == pytest.approx(0.0)
    assert subwindow["sharpe"] is None


def test_build_portfolio_foundation_reports_every_configured_subwindow_even_when_empty():
    rows = bar_rows(100.0, 101.0, 102.0)

    foundation = build_portfolio_foundation(
        rows=rows,
        decisions=[],
        executed_trades=[],
        data=DataConfig(
            kind="bars",
            dataset="equity_1min",
            symbols=("SPY",),
            start=datetime(2024, 1, 1).date(),
            end=datetime(2024, 1, 3).date(),
        ),
        fill_model=FillModelConfig(price="close", entry_lag_bars=1),
        cost_model=CostModelConfig(fee_bps_per_side=0.0, slippage_bps_per_side=0.0),
        config=PortfolioFoundationConfig(subwindows=6, trial_count=None, benchmark_sharpe=0.0),
    )

    subwindows = foundation.matrix_payload()["scenarios"]["realistic_costs"]["subwindows"]
    assert len(subwindows) == 6
    assert {item["window_id"] for item in subwindows} == {
        "train_1",
        "train_2",
        "train_3",
        "train_4",
        "train_5",
        "train_6",
    }
    assert any("missing_trial_count" in item["warnings"] for item in subwindows)


def test_build_portfolio_foundation_cost_stress_changes_nonzero_cost_path():
    rows = bar_rows(100.0, 100.0, 90.0, 80.0)
    decisions = [decision(rows[0]["timestamp"], hold_bars=2)]

    foundation = build_portfolio_foundation(
        rows=rows,
        decisions=decisions,
        executed_trades=[executed_trade(rows, entry_index=1, exit_index=3)],
        data=DataConfig(
            kind="bars",
            dataset="equity_1min",
            symbols=("SPY",),
            start=datetime(2024, 1, 1).date(),
            end=datetime(2024, 1, 4).date(),
        ),
        fill_model=FillModelConfig(price="close", entry_lag_bars=1),
        cost_model=CostModelConfig(fee_bps_per_side=10.0, slippage_bps_per_side=10.0),
        config=PortfolioFoundationConfig(
            subwindows=1,
            trial_count=5,
            benchmark_sharpe=0.0,
            cost_stress_multiplier=2.0,
        ),
    )

    payload = foundation.matrix_payload()
    realistic = payload["scenarios"]["realistic_costs"]["subwindows"][0]
    stressed = payload["scenarios"]["cost_stress"]["subwindows"][0]
    assert stressed["max_drawdown"] < realistic["max_drawdown"]


def test_build_portfolio_foundation_requires_executed_trades():
    rows = bar_rows(100.0, 101.0, 102.0)
    decisions = [decision(rows[0]["timestamp"], hold_bars=1)]

    with pytest.raises(ValueError, match="executed_trades_required"):
        build_portfolio_foundation(
            rows=rows,
            decisions=decisions,
            data=DataConfig(
                kind="bars",
                dataset="equity_1min",
                symbols=("SPY",),
                start=datetime(2024, 1, 1).date(),
                end=datetime(2024, 1, 3).date(),
            ),
            fill_model=FillModelConfig(price="close", entry_lag_bars=1),
            cost_model=CostModelConfig(fee_bps_per_side=0.0, slippage_bps_per_side=0.0),
            config=PortfolioFoundationConfig(subwindows=1, trial_count=5, benchmark_sharpe=0.0),
        )


def test_build_portfolio_foundation_dedupes_duplicate_funding_timestamps():
    timestamps = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index) for index in range(4)]
    rows = [
        {
            "symbol": "BTC-PERP",
            "timestamp": timestamp,
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "available_at": timestamp,
            "has_funding_event": index in {2, 3},
            "funding_timestamp": timestamps[2] if index in {2, 3} else None,
            "funding_rate": 0.01 if index in {2, 3} else None,
        }
        for index, timestamp in enumerate(timestamps)
    ]

    foundation = build_portfolio_foundation(
        rows=rows,
        decisions=[
            decision(
                timestamps[0],
                symbol="BTC-PERP",
                hold_bars=2,
            )
        ],
        executed_trades=[
            executed_trade(
                rows,
                entry_index=1,
                exit_index=3,
                symbol="BTC-PERP",
            )
        ],
        data=DataConfig(
            kind="crypto_perp_funding",
            dataset=None,
            symbols=("BTC-PERP",),
            start=datetime(2024, 1, 1).date(),
            end=datetime(2024, 1, 4).date(),
        ),
        fill_model=FillModelConfig(price="close", entry_lag_bars=1),
        cost_model=CostModelConfig(fee_bps_per_side=0.0, slippage_bps_per_side=0.0),
        config=PortfolioFoundationConfig(subwindows=1, trial_count=5, benchmark_sharpe=0.0),
    )

    subwindow = foundation.matrix_payload()["scenarios"]["realistic_costs"]["subwindows"][0]
    assert subwindow["max_drawdown"] == pytest.approx(-0.01)


def test_build_portfolio_foundation_rejects_overlapping_gross_exposure_above_one():
    timestamps = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index) for index in range(3)]
    rows = [
        {
            "symbol": symbol,
            "timestamp": timestamp,
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "available_at": timestamp,
        }
        for symbol in ("SPY", "QQQ")
        for timestamp in timestamps
    ]

    with pytest.raises(ValueError, match="portfolio_target_weight_exceeds_one"):
        build_portfolio_foundation(
            rows=rows,
            decisions=[
                decision(timestamps[0], symbol="SPY"),
                decision(timestamps[0], symbol="QQQ"),
            ],
            executed_trades=[
                executed_trade(rows, entry_index=1, exit_index=2, symbol="SPY"),
                executed_trade(rows, entry_index=4, exit_index=5, symbol="QQQ"),
            ],
            data=DataConfig(
                kind="bars",
                dataset="equity_1min",
                symbols=("SPY", "QQQ"),
                start=datetime(2024, 1, 1).date(),
                end=datetime(2024, 1, 3).date(),
            ),
            fill_model=FillModelConfig(price="close", entry_lag_bars=1),
            cost_model=CostModelConfig(fee_bps_per_side=0.0, slippage_bps_per_side=0.0),
            config=PortfolioFoundationConfig(subwindows=1, trial_count=5, benchmark_sharpe=0.0),
        )
