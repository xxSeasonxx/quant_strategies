from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.runner.config import CostModelConfig, FillModelConfig
from quant_strategies.runner.decision_adapter import decisions_to_signal_rows
from quant_strategies.runner.engine_runner import build_request, evaluate_request, request_json
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
        }
        if quotes:
            row.update({"bid": close - 0.01, "ask": close + 0.01, "mid": close})
        rows.append(row)
    return rows


def signal(index: int = 1, *, max_hold_bars: int = 1) -> dict[str, object]:
    return {
        "symbol": "SPY",
        "decision_time": datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=index),
        "side": "long",
        "weight": 1.0,
        "max_hold_bars": max_hold_bars,
    }


def decision(
    *,
    direction: str = "long",
    sizing_kind: str = "target_weight",
    size: float = 0.5,
) -> StrategyDecision:
    timestamp = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    return StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="equity_or_etf", symbol="SPY"),
        decision_time=timestamp,
        as_of_time=timestamp,
        target=PositionTarget(direction=direction, sizing_kind=sizing_kind, size=size),
        exit_policy=ExitPolicy(
            max_hold_bars=3,
            stop_loss_bps=100.0,
            take_profit_bps=200.0,
        ),
        metadata={"source": "test"},
    )


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
    assert request.bars[0].funding_rate is None
    assert request.spec.signals[0].decision_time == signal()["decision_time"]


def test_decisions_to_signal_rows_preserves_engine_fields():
    rows = decisions_to_signal_rows([decision()])

    assert rows == [
        {
            "symbol": "SPY",
            "decision_time": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
            "as_of_time": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
            "side": "long",
            "weight": 0.5,
            "max_hold_bars": 3,
            "stop_loss_bps": 100.0,
            "take_profit_bps": 200.0,
            "metadata": {"source": "test"},
        }
    ]


def test_decisions_to_signal_rows_converts_nested_metadata_for_engine_request():
    timestamp = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    nested_decision = StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="equity_or_etf", symbol="SPY"),
        decision_time=timestamp,
        as_of_time=timestamp,
        target=PositionTarget(direction="long", sizing_kind="target_weight", size=0.5),
        exit_policy=ExitPolicy(max_hold_bars=3),
        metadata={"outer": {"items": [{"x": 1}]}},
    )
    rows = [
        {
            "symbol": "SPY",
            "timestamp": timestamp + timedelta(days=index),
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
        }
        for index in range(5)
    ]

    signal_rows = decisions_to_signal_rows([nested_decision])
    request = build_request(
        strategy_id="demo",
        rows=rows,
        signals=signal_rows,
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )

    assert signal_rows[0]["metadata"] == {"outer": {"items": [{"x": 1}]}}
    assert request.spec.signals[0].metadata == {"outer": {"items": [{"x": 1}]}}


def test_decisions_to_signal_rows_rejects_flat_targets():
    with pytest.raises(RequestBuildError, match="flat target"):
        decisions_to_signal_rows([decision(direction="flat", size=0.0)])


def test_decisions_to_signal_rows_rejects_non_target_weight():
    with pytest.raises(RequestBuildError, match="target_weight"):
        decisions_to_signal_rows([decision(sizing_kind="notional")])


def test_build_request_preserves_funding_fields_for_engine_accounting():
    rows = bars(100.0, 100.0, 100.0, 110.0)
    rows[2].update(
        {
            "funding_timestamp": rows[2]["timestamp"],
            "funding_rate": 0.001,
            "has_funding_event": True,
        }
    )

    request = build_request(
        strategy_id="demo",
        rows=rows,
        signals=[signal(index=0, max_hold_bars=2)],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )

    assert request.bars[2].funding_timestamp == rows[2]["timestamp"]
    assert request.bars[2].funding_rate == 0.001
    assert request.bars[2].has_funding_event is True
    run = evaluate_request(request, mode="screen")
    assert run.screen_summary["trades"][0]["funding_return"] == pytest.approx(-0.001)
    assert run.screen_summary["trades"][0]["net_return"] == pytest.approx(0.099)


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


def test_runner_bar_index_builds_positions_by_symbol():
    from quant_strategies.runner.engine_runner import _build_bar_index

    request = build_request(
        strategy_id="demo",
        rows=bars(100.0, 101.0, 102.0, 104.0),
        signals=[signal()],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )

    indexed = _build_bar_index(request.bars)

    assert indexed.positions_by_symbol["SPY"][request.bars[0].timestamp] == 0
    assert indexed.positions_by_symbol["SPY"][request.bars[1].timestamp] == 1


def test_runner_bar_index_rejects_duplicate_symbol_timestamp():
    from quant_strategies.runner.engine_runner import _build_bar_index

    request = build_request(
        strategy_id="demo",
        rows=bars(100.0, 101.0, 102.0, 104.0),
        signals=[signal()],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )
    duplicate_bars = request.bars + (request.bars[0],)

    with pytest.raises(RequestBuildError, match="duplicate bar timestamp"):
        _build_bar_index(duplicate_bars)


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


def test_build_request_preserves_exit_controls_and_flat_signal_metadata():
    raw_signal = signal(index=0, max_hold_bars=5)
    raw_signal.update(
        {
            "max_hold_bars": 2,
            "take_profit_bps": 150.0,
            "stop_loss_bps": 75.0,
            "trailing_stop_bps": 50.0,
            "metadata": {"source": "explicit"},
            "funding_pressure_bps": 3.25,
            "entry_return_extension_bps": 42.0,
        }
    )

    request = build_request(
        strategy_id="demo",
        rows=bars(100.0, 100.0, 102.0, 101.0),
        signals=[raw_signal],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )

    engine_signal = request.spec.signals[0]
    assert engine_signal.max_hold_bars == 2
    assert engine_signal.take_profit_bps == 150.0
    assert engine_signal.stop_loss_bps == 75.0
    assert engine_signal.trailing_stop_bps == 50.0
    assert engine_signal.metadata == {
        "entry_return_extension_bps": 42.0,
        "funding_pressure_bps": 3.25,
        "source": "explicit",
    }
    assert '"funding_pressure_bps": 3.25' in request_json(request)


def test_build_request_rejects_duplicate_flat_and_nested_metadata_keys():
    raw_signal = signal()
    raw_signal.update({"metadata": {"funding_pressure_bps": 1.0}, "funding_pressure_bps": 2.0})

    with pytest.raises(RequestBuildError, match="duplicate signal metadata key"):
        build_request(
            strategy_id="demo",
            rows=bars(100.0, 101.0, 102.0, 103.0),
            signals=[raw_signal],
            fill_model=close_fill(),
            cost_model=zero_cost(),
        )


def test_build_request_uses_max_hold_and_exit_lag_for_fillability():
    with pytest.raises(RequestBuildError, match="exit fill is outside"):
        build_request(
            strategy_id="demo",
            rows=bars(100.0, 100.0, 101.0),
            signals=[{**signal(index=0, max_hold_bars=1), "max_hold_bars": 2}],
            fill_model=FillModelConfig(price="close", entry_lag_bars=1, exit_lag_bars=1),
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


def test_evaluate_request_can_skip_evidence_and_trade_serialization():
    request = build_request(
        strategy_id="demo",
        rows=bars(100.0, 101.0, 102.0, 104.0),
        signals=[signal()],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )

    screen_run = evaluate_request(request, mode="screen", include_evidence=False)
    validate_run = evaluate_request(request, mode="validate", include_evidence=False)

    assert screen_run.evidence_json == ""
    assert "trades" not in screen_run.screen_summary
    assert validate_run.evidence_json == ""
    assert validate_run.validate_summary["screening_result"]["trade_count"] == 1
    assert "trades" not in validate_run.validate_summary["screening_result"]
