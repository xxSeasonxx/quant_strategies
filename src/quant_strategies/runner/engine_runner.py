from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from quant_strategies.data_contract import NormalizedRows
from quant_strategies.decisions import StrategyDecision
from quant_strategies.engine import (
    Bar,
    CostModel,
    EvaluationRequest,
    FillModel,
    StrategySpec,
    build_evidence_packet,
    evidence_json,
    gate_screen,
    screen,
)
from quant_strategies.engine.bar_index import IndexedBars, attach_bar_index, build_bar_index
from quant_strategies.engine.executable import executable_decision

from quant_strategies.runner.config import CostModelConfig, FillModelConfig
from quant_strategies.runner.errors import EvaluationRunError, RequestBuildError


EngineMode = Literal["screen", "gate"]


@dataclass(frozen=True)
class EngineRun:
    mode: EngineMode
    screen_summary: dict[str, Any] | None
    validate_summary: dict[str, Any] | None
    evidence_json: str
    passed: bool | None


def build_request(
    *,
    strategy_id: str,
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
    decisions: list[StrategyDecision],
    fill_model: FillModelConfig,
    cost_model: CostModelConfig,
) -> EvaluationRequest:
    source_rows, normalized_timestamps = _engine_rows(rows)
    engine_bars = tuple(
        _bar_from_row(row, normalized_timestamp=normalized_timestamps)
        for row in source_rows
    )
    request = EvaluationRequest(
        spec=StrategySpec(strategy_id=strategy_id, decisions=tuple(decisions)),
        bars=engine_bars,
        fill_model=FillModel(**fill_model.model_dump(exclude={"allow_same_bar_close_fill"})),
        cost_model=CostModel(**cost_model.model_dump()),
    )
    _assert_fillable(request)
    return request


def assert_supported_decisions(decisions: list[StrategyDecision]) -> None:
    for decision in decisions:
        _decision_symbol(decision)


def evaluate_request(request: EvaluationRequest, *, mode: EngineMode, include_evidence: bool = True) -> EngineRun:
    try:
        if mode == "screen":
            screen_result = screen(request)
            packet = build_evidence_packet(request, screening_result=screen_result) if include_evidence else None
            return EngineRun(
                mode="screen",
                screen_summary=_screen_summary(screen_result, include_trades=include_evidence),
                validate_summary=None,
                evidence_json=evidence_json(packet) if packet is not None else "",
                passed=None,
            )

        report = gate_screen(request)
        packet = (
            build_evidence_packet(
                request,
                screening_result=report.screening_result,
                validation_report=report,
            )
            if include_evidence
            else None
        )
        return EngineRun(
            mode="gate",
            screen_summary=(
                _screen_summary(report.screening_result, include_trades=include_evidence)
                if report.screening_result is not None
                else None
            ),
            validate_summary=_validation_summary(report, include_trades=include_evidence),
            evidence_json=evidence_json(packet) if packet is not None else "",
            passed=report.passed,
        )
    except Exception as exc:
        raise EvaluationRunError(f"engine evaluation failed: {exc}") from exc


def request_json(request: EvaluationRequest) -> str:
    return json.dumps(request.model_dump(mode="json", exclude_none=True), indent=2, sort_keys=True) + "\n"


def _screen_summary(result, *, include_trades: bool) -> dict[str, Any]:
    payload = result.model_dump(mode="json", exclude={"trades"} if not include_trades else None)
    if include_trades:
        return payload
    payload["trade_count"] = result.trade_count
    return payload


def _validation_summary(report, *, include_trades: bool) -> dict[str, Any]:
    payload = report.model_dump(mode="json", exclude={"screening_result": {"trades"}} if not include_trades else None)
    if not include_trades and report.screening_result is not None and isinstance(payload.get("screening_result"), dict):
        payload["screening_result"]["trade_count"] = report.screening_result.trade_count
    return payload


def _engine_rows(
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
) -> tuple[Sequence[Mapping[str, Any]], bool]:
    if isinstance(rows, NormalizedRows):
        return rows.projection_rows(), True
    return rows, False


def _bar_from_row(row: Mapping[str, Any], *, normalized_timestamp: bool = False) -> Bar:
    try:
        payload = {
            "symbol": row["symbol"],
            "timestamp": (
                row["timestamp"]
                if normalized_timestamp
                else _as_datetime(row["timestamp"], "timestamp")
            ),
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
        }
        for field in (
            "bid",
            "ask",
            "mid",
            "funding_timestamp",
            "funding_rate",
            "has_funding_event",
        ):
            if field in row and row[field] is not None:
                payload[field] = row[field]
        return Bar(**payload)
    except KeyError as exc:
        field = str(exc.args[0])
        raise RequestBuildError(f"missing required bar field '{field}' for {row.get('symbol', '<unknown>')}") from exc
    except RequestBuildError:
        raise
    except Exception as exc:
        raise RequestBuildError(f"invalid engine bar for {row.get('symbol')}: {exc}") from exc


def _as_datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RequestBuildError(f"{field_name} must be a valid ISO timestamp") from exc
    else:
        raise RequestBuildError(f"{field_name} must be a datetime or ISO timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RequestBuildError(f"{field_name} must be timezone-aware")
    return parsed


def _assert_fillable(request: EvaluationRequest) -> None:
    indexed = _build_bar_index(request.bars)
    attach_bar_index(request, indexed)

    for decision in request.spec.decisions:
        symbol = _decision_symbol(decision)
        symbol_bars = indexed.bars_by_symbol.get(symbol)
        if not symbol_bars:
            raise RequestBuildError(f"missing bars for decision symbol: {symbol}")
        decision_index = _decision_index(indexed, decision)
        entry_index = decision_index + request.fill_model.entry_lag_bars
        last_trigger_index = entry_index + decision.exit_policy.max_hold_bars
        last_exit_index = last_trigger_index + request.fill_model.exit_lag_bars
        if entry_index >= len(symbol_bars):
            raise RequestBuildError(f"entry fill is outside available bars: {symbol}")
        if last_exit_index >= len(symbol_bars):
            raise RequestBuildError(f"exit fill is outside available bars: {symbol}")
        if request.fill_model.price == "quote":
            _assert_quote_fill_bar(symbol_bars[entry_index], "entry")
            for trigger_index in range(entry_index + 1, last_trigger_index + 1):
                _assert_quote_fill_bar(symbol_bars[trigger_index], "trigger")
                exit_index = trigger_index + request.fill_model.exit_lag_bars
                _assert_quote_fill_bar(symbol_bars[exit_index], "exit")


def _build_bar_index(bars: tuple[Bar, ...]) -> IndexedBars:
    return build_bar_index(bars, error_factory=RequestBuildError)


def _decision_index(indexed: IndexedBars, decision: StrategyDecision) -> int:
    symbol = _decision_symbol(decision)
    position = indexed.positions_by_symbol.get(symbol, {}).get(decision.decision_time)
    if position is not None:
        return position
    raise RequestBuildError(f"decision_time does not match a bar timestamp: {decision.decision_time.isoformat()}")


def _decision_symbol(decision: StrategyDecision) -> str:
    return executable_decision(decision, error_factory=RequestBuildError).symbol


def _assert_quote_fill_bar(bar: Bar, fill_name: str) -> None:
    if bar.bid is None or bar.ask is None:
        raise RequestBuildError(
            f"quote fill requires bid and ask on {fill_name} bar: "
            f"{bar.symbol} at {bar.timestamp.isoformat()}"
        )
