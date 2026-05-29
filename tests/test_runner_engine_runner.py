from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from quant_strategies.data_contract import NormalizedRows
from quant_strategies.decisions import (
    DecisionIntent,
    ExitPolicy,
    InstrumentRef,
    PositionTarget,
    StrategyDecision,
)
from quant_strategies.decisions.extended_ontology import (
    DecisionIntent as ExtendedDecisionIntent,
    FutureRef,
    InstrumentLeg,
    MultiLegInstrumentRef,
    OptionRef,
    PositionTarget as ExtendedPositionTarget,
    StrategyDecision as ExtendedStrategyDecision,
)
from quant_strategies.runner.config import CostModelConfig, FillModelConfig
from quant_strategies.runner.engine_runner import build_request, evaluate_request, request_json
from quant_strategies.runner.errors import RequestBuildError


START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def config() -> SimpleNamespace:
    return SimpleNamespace(
        data=SimpleNamespace(kind="bars"),
        fill_model=SimpleNamespace(price="close"),
    )


def bars(*closes: float, quotes: bool = False) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, close in enumerate(closes):
        row = {
            "symbol": "SPY",
            "timestamp": START + timedelta(days=index),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
        }
        if quotes:
            row.update({"bid": close - 0.01, "ask": close + 0.01, "mid": close})
        rows.append(row)
    return rows


def decision(
    index: int = 1,
    *,
    direction: str = "long",
    sizing_kind: str = "target_weight",
    size: float = 1.0,
    max_hold_bars: int = 1,
    instrument=None,
    intent=None,
    decision_id: str | None = None,
    metadata: dict[str, object] | None = None,
    take_profit_bps: float | None = None,
    stop_loss_bps: float | None = None,
    trailing_stop_bps: float | None = None,
) -> StrategyDecision:
    timestamp = START + timedelta(days=index)
    intent = intent or DecisionIntent(action="open")
    instrument = instrument or InstrumentRef(kind="equity_or_etf", symbol="SPY")
    is_extended = (
        not isinstance(instrument, InstrumentRef)
        or type(intent) is not DecisionIntent
        or sizing_kind != "target_weight"
    )
    target_cls = ExtendedPositionTarget if is_extended else PositionTarget
    decision_cls = ExtendedStrategyDecision if is_extended else StrategyDecision
    if is_extended and type(intent) is DecisionIntent:
        intent = ExtendedDecisionIntent(action=intent.action)
    return decision_cls(
        decision_id=decision_id,
        strategy_id="demo",
        instrument=instrument,
        intent=intent,
        decision_time=timestamp,
        as_of_time=timestamp,
        target=target_cls(direction=direction, sizing_kind=sizing_kind, size=size),
        exit_policy=ExitPolicy(
            max_hold_bars=max_hold_bars,
            stop_loss_bps=stop_loss_bps,
            take_profit_bps=take_profit_bps,
            trailing_stop_bps=trailing_stop_bps,
        ),
        metadata=metadata or {"source": "test"},
    )


def close_fill() -> FillModelConfig:
    return FillModelConfig(price="close", entry_lag_bars=1, exit_lag_bars=0)


def zero_cost() -> CostModelConfig:
    return CostModelConfig(fee_bps_per_side=0.0, slippage_bps_per_side=0.0)


def test_build_request_converts_rows_to_engine_ohlc_bars_and_decisions():
    source_decision = decision()
    request = build_request(
        strategy_id="demo",
        rows=bars(100.0, 101.0, 102.0, 104.0),
        decisions=[source_decision],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )

    assert request.spec.strategy_id == "demo"
    assert request.bars[0].symbol == "SPY"
    assert request.bars[0].close == 100.0
    assert request.bars[0].funding_rate is None
    assert request.spec.decisions == (source_decision,)


def test_build_request_accepts_normalized_rows_without_timestamp_parsing(monkeypatch: pytest.MonkeyPatch):
    raw_rows = bars(100.0, 101.0, 102.0, 104.0)
    for raw_row in raw_rows:
        raw_row["timestamp"] = raw_row["timestamp"].isoformat().replace("+00:00", "Z")
        for field in ("open", "high", "low", "close"):
            raw_row[field] = str(raw_row[field])
    normalized = NormalizedRows.from_rows(config(), raw_rows, mode="search")
    import quant_strategies.runner.engine_runner as runner_engine_runner

    monkeypatch.setattr(
        runner_engine_runner,
        "_as_datetime",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not parse normalized rows")),
    )

    request = build_request(
        strategy_id="demo",
        rows=normalized,
        decisions=[decision()],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )

    assert request.bars[0].timestamp == START
    assert request.bars[0].open == 100.0


def test_build_request_serializes_decision_metadata_without_signal_rows():
    nested_decision = decision(
        index=0,
        max_hold_bars=3,
        metadata={"outer": {"items": [{"x": 1}]}},
    )
    rows = bars(100.0, 100.0, 100.0, 100.0, 100.0)

    request = build_request(
        strategy_id="demo",
        rows=rows,
        decisions=[nested_decision],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )
    payload = json.loads(request_json(request))

    assert payload["spec"]["decisions"][0]["metadata"] == {"outer": {"items": [{"x": 1}]}}
    assert "signals" not in payload["spec"]


def test_build_request_rejects_flat_targets():
    with pytest.raises(RequestBuildError, match="flat target"):
        build_request(
            strategy_id="demo",
            rows=bars(100.0, 101.0, 102.0, 104.0),
            decisions=[decision(direction="flat", size=0.0)],
            fill_model=close_fill(),
            cost_model=zero_cost(),
        )


def test_build_request_rejects_non_target_weight():
    with pytest.raises(RequestBuildError, match="target_weight"):
        build_request(
            strategy_id="demo",
            rows=bars(100.0, 101.0, 102.0, 104.0),
            decisions=[decision(sizing_kind="target_notional")],
            fill_model=close_fill(),
            cost_model=zero_cost(),
        )


def test_build_request_rejects_non_open_intent():
    with pytest.raises(RequestBuildError, match="open intent"):
        build_request(
            strategy_id="demo",
            rows=bars(100.0, 101.0, 102.0, 104.0),
            decisions=[decision(intent=ExtendedDecisionIntent(action="close", book_side="sell"))],
            fill_model=close_fill(),
            cost_model=zero_cost(),
        )


@pytest.mark.parametrize(
    ("instrument", "message"),
    [
        (
            FutureRef(
                kind="future",
                symbol="ESM26",
                expiry=datetime(2026, 6, 19, tzinfo=timezone.utc),
                multiplier=50.0,
                settlement="cash",
            ),
            "future instrument",
        ),
        (
            OptionRef(
                kind="option",
                symbol="SPY260116C00450000",
                underlying_symbol="SPY",
                option_type="call",
                strike=450.0,
                expiry=datetime(2026, 1, 16, tzinfo=timezone.utc),
                multiplier=100.0,
                settlement="physical",
            ),
            "option instrument",
        ),
        (
            MultiLegInstrumentRef(
                kind="multi_leg",
                symbol="SPY_QQQ_PAIR",
                legs=(
                    InstrumentLeg(
                        instrument=InstrumentRef(kind="equity_or_etf", symbol="SPY"),
                        direction="long",
                        ratio=1.0,
                    ),
                    InstrumentLeg(
                        instrument=InstrumentRef(kind="equity_or_etf", symbol="QQQ"),
                        direction="short",
                        ratio=1.0,
                    ),
                ),
            ),
            "multi_leg instrument",
        ),
    ],
)
def test_build_request_rejects_unsupported_instrument_shapes(instrument, message):
    with pytest.raises(RequestBuildError, match=message):
        build_request(
            strategy_id="demo",
            rows=bars(100.0, 101.0, 102.0, 104.0),
            decisions=[decision(instrument=instrument)],
            fill_model=close_fill(),
            cost_model=zero_cost(),
        )


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
        decisions=[decision(index=0, max_hold_bars=2)],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )

    assert request.bars[2].funding_timestamp == rows[2]["timestamp"]
    assert request.bars[2].funding_rate == 0.001
    assert request.bars[2].has_funding_event is True
    run = evaluate_request(request, mode="screen")
    assert run.screen_summary["trades"][0]["funding_return"] == pytest.approx(-0.001)
    assert run.screen_summary["trades"][0]["net_return"] == pytest.approx(0.099)


def test_evaluate_request_reuses_request_build_bar_index(monkeypatch: pytest.MonkeyPatch):
    import quant_strategies.engine.bar_index as shared_bar_index
    import quant_strategies.engine.evaluation as evaluation
    import quant_strategies.runner.engine_runner as runner_engine_runner

    build_calls = 0
    original_build_bar_index = shared_bar_index.build_bar_index

    def counting_build_bar_index(*args, **kwargs):
        nonlocal build_calls
        build_calls += 1
        return original_build_bar_index(*args, **kwargs)

    monkeypatch.setattr(runner_engine_runner, "build_bar_index", counting_build_bar_index)
    monkeypatch.setattr(evaluation, "build_bar_index", counting_build_bar_index)

    request = build_request(
        strategy_id="demo",
        rows=bars(100.0, 101.0, 102.0, 104.0),
        decisions=[decision()],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )

    run = evaluate_request(request, mode="screen")

    assert run.screen_summary["trade_count"] == 1
    assert build_calls == 1


def test_build_request_accepts_zero_decisions_as_no_op():
    request = build_request(
        strategy_id="demo",
        rows=bars(100.0, 101.0, 102.0),
        decisions=[],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )

    assert request.spec.decisions == ()
    screen_run = evaluate_request(request, mode="screen")
    assert screen_run.screen_summary["trade_count"] == 0
    assert screen_run.screen_summary["trades"] == []
    assert screen_run.screen_summary["smoke_score"] == {
        "sum_signed_trade_activity_gross": 0.0,
        "sum_signed_trade_activity_funding": 0.0,
        "sum_signed_trade_activity_cost": 0.0,
        "sum_signed_trade_activity_net": 0.0,
    }
    validate_run = evaluate_request(request, mode="gate")
    assert validate_run.passed is False
    assert validate_run.validate_summary["screening_result"]["trade_count"] == 0


def test_build_request_rejects_missing_decision_bar():
    with pytest.raises(RequestBuildError, match="decision_time"):
        build_request(
            strategy_id="demo",
            rows=bars(100.0, 101.0, 102.0, 104.0),
            decisions=[decision(index=9)],
            fill_model=close_fill(),
            cost_model=zero_cost(),
        )


def test_runner_bar_index_builds_positions_by_symbol():
    from quant_strategies.runner.engine_runner import _build_bar_index

    request = build_request(
        strategy_id="demo",
        rows=bars(100.0, 101.0, 102.0, 104.0),
        decisions=[decision()],
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
        decisions=[decision()],
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
            decisions=[decision()],
            fill_model=close_fill(),
            cost_model=zero_cost(),
        )


def test_build_request_rejects_insufficient_entry_or_exit_bars():
    with pytest.raises(RequestBuildError, match="exit fill is outside"):
        build_request(
            strategy_id="demo",
            rows=bars(100.0, 101.0, 102.0),
            decisions=[decision()],
            fill_model=close_fill(),
            cost_model=zero_cost(),
        )


def test_build_request_rejects_quote_fill_without_bid_ask_fields():
    with pytest.raises(RequestBuildError, match="quote fill requires bid and ask"):
        build_request(
            strategy_id="demo",
            rows=bars(100.0, 101.0, 102.0, 104.0),
            decisions=[decision()],
            fill_model=FillModelConfig(price="quote", entry_lag_bars=1),
            cost_model=zero_cost(),
        )


def test_build_request_preserves_exit_controls_and_decision_metadata():
    source_decision = decision(
        index=0,
        decision_id="decision-001",
        max_hold_bars=2,
        take_profit_bps=150.0,
        stop_loss_bps=75.0,
        trailing_stop_bps=50.0,
        metadata={
            "source": "explicit",
            "funding_pressure_bps": 3.25,
            "entry_return_extension_bps": 42.0,
        },
    )

    request = build_request(
        strategy_id="demo",
        rows=bars(100.0, 100.0, 102.0, 101.0),
        decisions=[source_decision],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )

    engine_decision = request.spec.decisions[0]
    assert engine_decision.decision_id == "decision-001"
    assert engine_decision.exit_policy.max_hold_bars == 2
    assert engine_decision.exit_policy.take_profit_bps == 150.0
    assert engine_decision.exit_policy.stop_loss_bps == 75.0
    assert engine_decision.exit_policy.trailing_stop_bps == 50.0
    assert dict(engine_decision.metadata) == {
        "entry_return_extension_bps": 42.0,
        "funding_pressure_bps": 3.25,
        "source": "explicit",
    }
    assert '"funding_pressure_bps": 3.25' in request_json(request)


def test_engine_trades_preserve_decision_id():
    request = build_request(
        strategy_id="demo",
        rows=bars(100.0, 100.0, 102.0),
        decisions=[decision(index=0, max_hold_bars=1, decision_id="decision-join-001")],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )

    run = evaluate_request(request, mode="screen")

    assert run.screen_summary["trades"][0]["decision_id"] == "decision-join-001"


def test_build_request_uses_max_hold_and_exit_lag_for_fillability():
    with pytest.raises(RequestBuildError, match="exit fill is outside"):
        build_request(
            strategy_id="demo",
            rows=bars(100.0, 100.0, 101.0),
            decisions=[decision(index=0, max_hold_bars=2)],
            fill_model=FillModelConfig(price="close", entry_lag_bars=1, exit_lag_bars=1),
            cost_model=zero_cost(),
        )


def test_evaluate_request_runs_screen_and_validate_apis():
    request = build_request(
        strategy_id="demo",
        rows=bars(100.0, 101.0, 102.0, 104.0),
        decisions=[decision()],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )

    screen_run = evaluate_request(request, mode="screen")
    validate_run = evaluate_request(request, mode="gate")

    assert screen_run.screen_summary["trade_count"] == 1
    assert validate_run.passed is True
    assert validate_run.validate_summary["passed"] is True
    assert "validation_report" in validate_run.evidence_json


def test_evaluate_request_can_skip_evidence_and_trade_serialization():
    request = build_request(
        strategy_id="demo",
        rows=bars(100.0, 101.0, 102.0, 104.0),
        decisions=[decision()],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )

    screen_run = evaluate_request(request, mode="screen", include_evidence=False)
    validate_run = evaluate_request(request, mode="gate", include_evidence=False)

    assert screen_run.evidence_json == ""
    assert "trades" not in screen_run.screen_summary
    assert validate_run.evidence_json == ""
    assert validate_run.validate_summary["screening_result"]["trade_count"] == 1
    assert "trades" not in validate_run.validate_summary["screening_result"]
