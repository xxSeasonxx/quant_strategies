from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from quant_strategies.runner.config import CostModelConfig, FillModelConfig
from quant_strategies.runner.engine_runner import build_request, evaluate_request
from quant_strategies.runner.errors import RequestBuildError


def bars(*closes: float, quotes: bool = False) -> list[dict[str, object]]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows: list[dict[str, object]] = []
    for index, close in enumerate(closes):
        row = {
            "symbol": "SPY",
            "timestamp": start + timedelta(days=index),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "funding_rate": 0.0,
        }
        if quotes:
            row.update({"bid": close - 0.01, "ask": close + 0.01, "mid": close})
        rows.append(row)
    return rows


def signal(index: int = 1, *, hold_bars: int = 1) -> dict[str, object]:
    return {
        "symbol": "SPY",
        "decision_time": datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=index),
        "side": "long",
        "weight": 1.0,
        "hold_bars": hold_bars,
    }


def close_fill() -> FillModelConfig:
    return FillModelConfig(price="close", entry_lag_bars=1, exit_lag_bars=0)


def zero_cost() -> CostModelConfig:
    return CostModelConfig(fee_bps_per_side=0.0, slippage_bps_per_side=0.0)


def test_build_request_converts_rows_to_engine_ohlc_bars_and_signals():
    request = build_request(
        strategy_id="demo",
        rows=bars(100.0, 101.0, 102.0, 104.0),
        signals=[signal()],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )

    assert request.spec.strategy_id == "demo"
    assert request.bars[0].symbol == "SPY"
    assert request.bars[0].close == 100.0
    assert not hasattr(request.bars[0], "funding_rate")
    assert request.spec.signals[0].decision_time == signal()["decision_time"]


def test_build_request_rejects_zero_signals():
    with pytest.raises(RequestBuildError, match="no signals"):
        build_request(
            strategy_id="demo",
            rows=bars(100.0, 101.0, 102.0),
            signals=[],
            fill_model=close_fill(),
            cost_model=zero_cost(),
        )


def test_build_request_rejects_missing_decision_bar():
    missing = signal(index=9)

    with pytest.raises(RequestBuildError, match="decision_time"):
        build_request(
            strategy_id="demo",
            rows=bars(100.0, 101.0, 102.0, 104.0),
            signals=[missing],
            fill_model=close_fill(),
            cost_model=zero_cost(),
        )


def test_build_request_translates_missing_required_bar_field():
    bad_rows = bars(100.0, 101.0, 102.0, 104.0)
    del bad_rows[0]["close"]

    with pytest.raises(RequestBuildError, match="missing required bar field 'close'"):
        build_request(
            strategy_id="demo",
            rows=bad_rows,
            signals=[signal()],
            fill_model=close_fill(),
            cost_model=zero_cost(),
        )


def test_build_request_translates_missing_required_signal_field():
    bad_signal = signal()
    del bad_signal["side"]

    with pytest.raises(RequestBuildError, match="missing required signal field 'side'"):
        build_request(
            strategy_id="demo",
            rows=bars(100.0, 101.0, 102.0, 104.0),
            signals=[bad_signal],
            fill_model=close_fill(),
            cost_model=zero_cost(),
        )


def test_build_request_rejects_insufficient_entry_or_exit_bars():
    with pytest.raises(RequestBuildError, match="exit fill is outside"):
        build_request(
            strategy_id="demo",
            rows=bars(100.0, 101.0, 102.0),
            signals=[signal()],
            fill_model=close_fill(),
            cost_model=zero_cost(),
        )


def test_build_request_rejects_quote_fill_without_bid_ask_fields():
    with pytest.raises(RequestBuildError, match="quote fill requires bid and ask"):
        build_request(
            strategy_id="demo",
            rows=bars(100.0, 101.0, 102.0, 104.0),
            signals=[signal()],
            fill_model=FillModelConfig(price="quote", entry_lag_bars=1),
            cost_model=zero_cost(),
        )


def test_evaluate_request_runs_screen_and_validate_apis():
    request = build_request(
        strategy_id="demo",
        rows=bars(100.0, 101.0, 102.0, 104.0),
        signals=[signal()],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )

    screen_run = evaluate_request(request, mode="screen")
    validate_run = evaluate_request(request, mode="validate")

    assert screen_run.screen_summary["trade_count"] == 1
    assert validate_run.passed is True
    assert validate_run.validate_summary["passed"] is True
    assert "validation_report" in validate_run.evidence_json
