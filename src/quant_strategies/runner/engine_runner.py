from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from quant_engine import (
    Bar,
    CostModel,
    EvaluationRequest,
    FillModel,
    Signal,
    StrategySpec,
    build_evidence_packet,
    evidence_json,
    screen,
    validate,
)

from quant_strategies.runner.config import CostModelConfig, FillModelConfig
from quant_strategies.runner.errors import EvaluationRunError, RequestBuildError


EngineMode = Literal["screen", "validate"]


@dataclass(frozen=True)
class EngineRun:
    mode: EngineMode
    screen_summary: dict[str, Any] | None
    validate_summary: dict[str, Any] | None
    evidence_json: str
    passed: bool


def build_request(
    *,
    strategy_id: str,
    rows: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    fill_model: FillModelConfig,
    cost_model: CostModelConfig,
) -> EvaluationRequest:
    if not signals:
        raise RequestBuildError("strategy generated no signals")

    engine_bars = tuple(_bar_from_row(row) for row in rows)
    engine_signals = tuple(_signal_from_row(signal) for signal in signals)
    request = EvaluationRequest(
        spec=StrategySpec(strategy_id=strategy_id, signals=engine_signals),
        bars=engine_bars,
        fill_model=FillModel(**fill_model.model_dump()),
        cost_model=CostModel(**cost_model.model_dump()),
    )
    _assert_fillable(request)
    return request


def evaluate_request(request: EvaluationRequest, *, mode: EngineMode) -> EngineRun:
    try:
        if mode == "screen":
            screen_result = screen(request)
            packet = build_evidence_packet(request, screening_result=screen_result)
            return EngineRun(
                mode="screen",
                screen_summary=screen_result.model_dump(mode="json"),
                validate_summary=None,
                evidence_json=evidence_json(packet),
                passed=True,
            )

        report = validate(request)
        packet = build_evidence_packet(
            request,
            screening_result=report.screening_result,
            validation_report=report,
        )
        return EngineRun(
            mode="validate",
            screen_summary=(
                report.screening_result.model_dump(mode="json") if report.screening_result is not None else None
            ),
            validate_summary=report.model_dump(mode="json"),
            evidence_json=evidence_json(packet),
            passed=report.passed,
        )
    except Exception as exc:
        raise EvaluationRunError(f"engine evaluation failed: {exc}") from exc


def request_json(request: EvaluationRequest) -> str:
    return json.dumps(request.model_dump(mode="json", exclude_none=True), indent=2, sort_keys=True) + "\n"


def bars_for_artifact(request: EvaluationRequest) -> list[dict[str, Any]]:
    return [bar.model_dump(mode="json", exclude_none=True) for bar in request.bars]


def signals_for_artifact(request: EvaluationRequest) -> list[dict[str, Any]]:
    return [signal.model_dump(mode="json") for signal in request.spec.signals]


def _bar_from_row(row: dict[str, Any]) -> Bar:
    payload = {
        "symbol": row["symbol"],
        "timestamp": _as_datetime(row["timestamp"], "timestamp"),
        "open": row["open"],
        "high": row["high"],
        "low": row["low"],
        "close": row["close"],
    }
    for field in ("bid", "ask", "mid"):
        if row.get(field) is not None:
            payload[field] = row[field]
    try:
        return Bar(**payload)
    except Exception as exc:
        raise RequestBuildError(f"invalid engine bar for {row.get('symbol')}: {exc}") from exc


def _signal_from_row(row: dict[str, Any]) -> Signal:
    payload = {
        "symbol": row["symbol"],
        "decision_time": _as_datetime(row["decision_time"], "decision_time"),
        "side": row["side"],
        "weight": row.get("weight", 1.0),
        "hold_bars": row.get("hold_bars", 1),
    }
    try:
        return Signal(**payload)
    except Exception as exc:
        raise RequestBuildError(f"invalid signal for {row.get('symbol')}: {exc}") from exc


def _as_datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise RequestBuildError(f"{field_name} must be a datetime or ISO timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RequestBuildError(f"{field_name} must be timezone-aware")
    return parsed


def _assert_fillable(request: EvaluationRequest) -> None:
    bars_by_symbol: dict[str, list[Bar]] = {}
    for bar in request.bars:
        bars_by_symbol.setdefault(bar.symbol, []).append(bar)
    for symbol_bars in bars_by_symbol.values():
        symbol_bars.sort(key=lambda bar: bar.timestamp)

    for signal in request.spec.signals:
        symbol_bars = bars_by_symbol.get(signal.symbol)
        if not symbol_bars:
            raise RequestBuildError(f"missing bars for signal symbol: {signal.symbol}")
        decision_index = _decision_index(symbol_bars, signal)
        entry_index = decision_index + request.fill_model.entry_lag_bars
        exit_index = entry_index + signal.hold_bars + request.fill_model.exit_lag_bars
        if entry_index >= len(symbol_bars):
            raise RequestBuildError(f"entry fill is outside available bars: {signal.symbol}")
        if exit_index >= len(symbol_bars):
            raise RequestBuildError(f"exit fill is outside available bars: {signal.symbol}")
        if request.fill_model.price == "quote":
            for fill_name, bar in (("entry", symbol_bars[entry_index]), ("exit", symbol_bars[exit_index])):
                if bar.bid is None or bar.ask is None:
                    raise RequestBuildError(
                        f"quote fill requires bid and ask on {fill_name} bar: "
                        f"{bar.symbol} at {bar.timestamp.isoformat()}"
                    )


def _decision_index(symbol_bars: list[Bar], signal: Signal) -> int:
    for index, bar in enumerate(symbol_bars):
        if bar.timestamp == signal.decision_time:
            return index
    raise RequestBuildError(f"decision_time does not match a bar timestamp: {signal.decision_time.isoformat()}")
