from __future__ import annotations

import json
from datetime import datetime, timezone

import quant_strategies.engine as engine
from quant_strategies.engine import (
    Bar,
    EvaluationRequest,
    FillModel,
    Side,
    StrategySpec,
    build_evidence_packet,
    evidence_json,
    gate_screen,
    screen,
)

from engine_helpers import bars_for, decision_for


DECISION = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)


def profitable_request() -> EvaluationRequest:
    return EvaluationRequest(
        spec=StrategySpec(
            strategy_id="deterministic_check",
            decisions=(decision_for(symbol="BTC", decision_time=DECISION, side=Side.LONG, max_hold_bars=1),),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 110.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )


def test_evidence_json_is_deterministic_for_screening_result():
    request = profitable_request()
    first = evidence_json(build_evidence_packet(request, screening_result=screen(request)))
    second = evidence_json(build_evidence_packet(request, screening_result=screen(request)))

    assert first == second
    assert json.loads(first)["schema_version"] == "quant_strategies.engine.evidence/v3"


def test_engine_public_api_uses_gating_names():
    assert hasattr(engine, "gate_screen")
    assert hasattr(engine, "GatingConfig")
    assert hasattr(engine, "GatingReport")
    assert not hasattr(engine, "validate")
    assert not hasattr(engine, "ValidationConfig")
    assert not hasattr(engine, "ValidationReport")


def test_gate_screen_passes_profitable_frozen_candidate():
    report = gate_screen(profitable_request())

    assert report.passed is True
    assert {gate.name: gate.passed for gate in report.gates} == {
        "valid_inputs": True,
        "min_trades": True,
        "positive_gross": True,
        "positive_net": True,
    }


def test_gate_screen_empty_decision_set_fails_smoke_gates_not_inputs():
    request = EvaluationRequest(
        spec=StrategySpec(strategy_id="no_op", decisions=()),
        bars=bars_for("BTC", [100.0, 101.0, 102.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    report = gate_screen(request)

    assert report.passed is False
    assert report.screening_result is not None
    assert report.screening_result.trade_count == 0
    assert {gate.name: gate.passed for gate in report.gates} == {
        "valid_inputs": True,
        "min_trades": False,
        "positive_gross": False,
        "positive_net": False,
    }


def test_gate_screen_fails_closed_when_required_bars_are_missing():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="missing_inputs",
            decisions=(decision_for(symbol="BTC", decision_time=DECISION, side=Side.LONG, max_hold_bars=1),),
        ),
        bars=(),
    )

    report = gate_screen(request)

    assert report.passed is False
    assert report.screening_result is None
    assert [(gate.name, gate.passed) for gate in report.gates] == [("valid_inputs", False)]


def quote_bars() -> tuple[Bar, ...]:
    return (
        Bar(
            symbol="EURUSD",
            timestamp=DECISION,
            open=100.0,
            high=100.1,
            low=99.9,
            close=100.0,
            bid=99.9,
            ask=100.1,
            mid=100.0,
        ),
        Bar(
            symbol="EURUSD",
            timestamp=datetime(2024, 1, 1, 9, 31, tzinfo=timezone.utc),
            open=100.0,
            high=100.1,
            low=99.9,
            close=100.0,
            bid=100.0,
            ask=100.1,
            mid=100.05,
        ),
        Bar(
            symbol="EURUSD",
            timestamp=datetime(2024, 1, 1, 9, 32, tzinfo=timezone.utc),
            open=110.0,
            high=110.1,
            low=109.9,
            close=110.0,
            bid=110.0,
            ask=110.1,
            mid=110.05,
        ),
    )


def quote_request() -> EvaluationRequest:
    return EvaluationRequest(
        spec=StrategySpec(
            strategy_id="quote_evidence",
            decisions=(decision_for(symbol="EURUSD", decision_time=DECISION, side=Side.LONG, max_hold_bars=1),),
        ),
        bars=quote_bars(),
        fill_model=FillModel(price="quote", entry_lag_bars=1),
    )


def test_gate_screen_reports_missing_quote_fills_as_invalid_inputs():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="missing_quote_inputs",
            decisions=(decision_for(symbol="BTC", decision_time=DECISION, side=Side.LONG, max_hold_bars=1),),
        ),
        bars=bars_for("BTC", [100.0, 101.0, 102.0]),
        fill_model=FillModel(price="quote", entry_lag_bars=1),
    )

    report = gate_screen(request)

    assert report.passed is False
    assert report.screening_result is None
    assert [(gate.name, gate.passed) for gate in report.gates] == [("valid_inputs", False)]
    assert "quote fill requires bid and ask" in report.gates[0].detail


def test_evidence_json_serializes_quote_derived_fill_prices():
    request = quote_request()
    payload = evidence_json(build_evidence_packet(request, screening_result=screen(request)))

    parsed = json.loads(payload)

    trade = parsed["screening_result"]["trades"][0]
    assert trade["entry_price"] == 100.1
    assert trade["exit_price"] == 110.0
