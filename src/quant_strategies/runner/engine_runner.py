from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from quant_strategies.engine import (
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


_RESERVED_SIGNAL_FIELDS = {
    "symbol",
    "decision_id",
    "decision_time",
    "as_of_time",
    "side",
    "weight",
    "max_hold_bars",
    "take_profit_bps",
    "stop_loss_bps",
    "trailing_stop_bps",
    "metadata",
}


@dataclass(frozen=True)
class EngineRun:
    mode: EngineMode
    screen_summary: dict[str, Any] | None
    validate_summary: dict[str, Any] | None
    evidence_json: str
    passed: bool | None


@dataclass(frozen=True)
class _BarIndex:
    bars_by_symbol: dict[str, tuple[Bar, ...]]
    positions_by_symbol: dict[str, dict[datetime, int]]


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
        fill_model=FillModel(**fill_model.model_dump(exclude={"allow_same_bar_close_fill"})),
        cost_model=CostModel(**cost_model.model_dump()),
    )
    _assert_fillable(request)
    return request


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

        report = validate(request)
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
            mode="validate",
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


def _bar_from_row(row: dict[str, Any]) -> Bar:
    try:
        payload = {
            "symbol": row["symbol"],
            "timestamp": _as_datetime(row["timestamp"], "timestamp"),
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


def _signal_from_row(row: dict[str, Any]) -> Signal:
    try:
        payload = {
            "decision_id": row.get("decision_id"),
            "symbol": row["symbol"],
            "decision_time": _as_datetime(row["decision_time"], "decision_time"),
            "side": row["side"],
            "weight": row.get("weight", 1.0),
            "max_hold_bars": row["max_hold_bars"],
            "metadata": _signal_metadata(row),
        }
        for field in ("take_profit_bps", "stop_loss_bps", "trailing_stop_bps"):
            if field in row and row[field] is not None:
                payload[field] = row[field]
        return Signal(**payload)
    except KeyError as exc:
        field = str(exc.args[0])
        raise RequestBuildError(f"missing required signal field '{field}' for {row.get('symbol', '<unknown>')}") from exc
    except RequestBuildError:
        raise
    except Exception as exc:
        raise RequestBuildError(f"invalid signal for {row.get('symbol')}: {exc}") from exc


def _signal_metadata(row: dict[str, Any]) -> dict[str, Any]:
    raw_metadata = row.get("metadata", {})
    if raw_metadata is None:
        metadata: dict[str, Any] = {}
    elif isinstance(raw_metadata, dict):
        metadata = dict(raw_metadata)
    else:
        raise RequestBuildError(f"signal metadata must be a mapping for {row.get('symbol', '<unknown>')}")

    for key in sorted(set(row).difference(_RESERVED_SIGNAL_FIELDS)):
        if key in metadata:
            raise RequestBuildError(f"duplicate signal metadata key '{key}' for {row.get('symbol', '<unknown>')}")
        metadata[key] = row[key]
    return metadata


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

    for signal in request.spec.signals:
        symbol_bars = indexed.bars_by_symbol.get(signal.symbol)
        if not symbol_bars:
            raise RequestBuildError(f"missing bars for signal symbol: {signal.symbol}")
        decision_index = _decision_index(indexed, signal)
        entry_index = decision_index + request.fill_model.entry_lag_bars
        last_trigger_index = entry_index + signal.max_hold_bars
        last_exit_index = last_trigger_index + request.fill_model.exit_lag_bars
        if entry_index >= len(symbol_bars):
            raise RequestBuildError(f"entry fill is outside available bars: {signal.symbol}")
        if last_exit_index >= len(symbol_bars):
            raise RequestBuildError(f"exit fill is outside available bars: {signal.symbol}")
        if request.fill_model.price == "quote":
            _assert_quote_fill_bar(symbol_bars[entry_index], "entry")
            for trigger_index in range(entry_index + 1, last_trigger_index + 1):
                _assert_quote_fill_bar(symbol_bars[trigger_index], "trigger")
                exit_index = trigger_index + request.fill_model.exit_lag_bars
                _assert_quote_fill_bar(symbol_bars[exit_index], "exit")


def _build_bar_index(bars: tuple[Bar, ...]) -> _BarIndex:
    grouped: dict[str, list[Bar]] = {}
    for bar in bars:
        grouped.setdefault(bar.symbol, []).append(bar)

    bars_by_symbol: dict[str, tuple[Bar, ...]] = {}
    positions_by_symbol: dict[str, dict[datetime, int]] = {}
    for symbol, symbol_bars in grouped.items():
        ordered = sorted(symbol_bars, key=lambda bar: bar.timestamp)
        positions: dict[datetime, int] = {}
        for index, bar in enumerate(ordered):
            if bar.timestamp in positions:
                raise RequestBuildError(f"duplicate bar timestamp for {symbol}: {bar.timestamp.isoformat()}")
            positions[bar.timestamp] = index
        bars_by_symbol[symbol] = tuple(ordered)
        positions_by_symbol[symbol] = positions
    return _BarIndex(bars_by_symbol=bars_by_symbol, positions_by_symbol=positions_by_symbol)


def _decision_index(indexed: _BarIndex, signal: Signal) -> int:
    position = indexed.positions_by_symbol.get(signal.symbol, {}).get(signal.decision_time)
    if position is not None:
        return position
    raise RequestBuildError(f"decision_time does not match a bar timestamp: {signal.decision_time.isoformat()}")


def _assert_quote_fill_bar(bar: Bar, fill_name: str) -> None:
    if bar.bid is None or bar.ask is None:
        raise RequestBuildError(
            f"quote fill requires bid and ask on {fill_name} bar: "
            f"{bar.symbol} at {bar.timestamp.isoformat()}"
        )
