from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import math

from quant_strategies.engine.models import (
    Bar,
    EvaluationRequest,
    GateResult,
    ScreeningResult,
    Side,
    Trade,
    ValidationConfig,
    ValidationReport,
)


class EvaluationError(ValueError):
    """Raised when an evaluation request cannot be screened causally."""


def screen(request: EvaluationRequest) -> ScreeningResult:
    bars_by_symbol = _bars_by_symbol(request.bars)
    if not bars_by_symbol:
        raise EvaluationError("bars are required")

    trades: list[Trade] = []
    for signal in request.spec.signals:
        symbol_bars = bars_by_symbol.get(signal.symbol)
        if not symbol_bars:
            raise EvaluationError(f"missing bars for signal symbol: {signal.symbol}")
        decision_index = _decision_index(symbol_bars, signal.decision_time)
        entry_index = decision_index + request.fill_model.entry_lag_bars
        exit_index = entry_index + signal.hold_bars + request.fill_model.exit_lag_bars
        if entry_index >= len(symbol_bars):
            raise EvaluationError(f"entry fill is outside available bars: {signal.symbol}")
        if exit_index >= len(symbol_bars):
            raise EvaluationError(f"exit fill is outside available bars: {signal.symbol}")

        entry_bar = symbol_bars[entry_index]
        exit_bar = symbol_bars[exit_index]
        entry_price = _fill_price(entry_bar, request.fill_model.price, signal.side, is_entry=True)
        exit_price = _fill_price(exit_bar, request.fill_model.price, signal.side, is_entry=False)
        direction = 1.0 if signal.side is Side.LONG else -1.0
        gross_return = direction * ((exit_price - entry_price) / entry_price) * signal.weight
        funding_return = _funding_return(
            symbol_bars,
            entry_bar.timestamp,
            exit_bar.timestamp,
            signal.side,
            signal.weight,
        )
        cost_return = (request.cost_model.round_trip_bps / 10_000.0) * signal.weight
        net_return = gross_return + funding_return - cost_return
        trades.append(
            Trade(
                symbol=signal.symbol,
                side=signal.side,
                decision_time=signal.decision_time,
                entry_time=entry_bar.timestamp,
                exit_time=exit_bar.timestamp,
                entry_price=entry_price,
                exit_price=exit_price,
                weight=signal.weight,
                gross_return=gross_return,
                funding_return=funding_return,
                cost_return=cost_return,
                net_return=net_return,
            )
        )

    gross_total = sum(trade.gross_return for trade in trades)
    funding_total = sum(trade.funding_return for trade in trades)
    cost_total = sum(trade.cost_return for trade in trades)
    net_total = sum(trade.net_return for trade in trades)
    return ScreeningResult(
        strategy_id=request.spec.strategy_id,
        trade_count=len(trades),
        gross_return=gross_total,
        funding_return=funding_total,
        net_return=net_total,
        cost_return=cost_total,
        trades=tuple(trades),
    )


def validate(
    request: EvaluationRequest,
    config: ValidationConfig | None = None,
) -> ValidationReport:
    validation_config = config or ValidationConfig()
    gates: list[GateResult] = []
    try:
        screening_result = screen(request)
    except EvaluationError as exc:
        return ValidationReport(
            strategy_id=request.spec.strategy_id,
            passed=False,
            gates=(GateResult(name="valid_inputs", passed=False, detail=str(exc)),),
            screening_result=None,
        )

    gates.append(GateResult(name="valid_inputs", passed=True, detail="screening completed"))
    gates.append(
        GateResult(
            name="min_trades",
            passed=screening_result.trade_count >= validation_config.min_trades,
            detail=f"{screening_result.trade_count} >= {validation_config.min_trades}",
        )
    )
    if validation_config.require_positive_gross:
        gates.append(
            GateResult(
                name="positive_gross",
                passed=screening_result.gross_return > 0,
                detail=f"gross_return={screening_result.gross_return:.12g}",
            )
        )
    if validation_config.require_positive_net:
        gates.append(
            GateResult(
                name="positive_net",
                passed=screening_result.net_return > 0,
                detail=f"net_return={screening_result.net_return:.12g}",
            )
        )

    return ValidationReport(
        strategy_id=request.spec.strategy_id,
        passed=all(gate.passed for gate in gates),
        gates=tuple(gates),
        screening_result=screening_result,
    )


def _bars_by_symbol(bars: tuple[Bar, ...]) -> dict[str, tuple[Bar, ...]]:
    grouped: dict[str, list[Bar]] = defaultdict(list)
    for bar in bars:
        grouped[bar.symbol].append(bar)

    result: dict[str, tuple[Bar, ...]] = {}
    for symbol, symbol_bars in grouped.items():
        ordered = sorted(symbol_bars, key=lambda bar: bar.timestamp)
        seen = set()
        for bar in ordered:
            if bar.timestamp in seen:
                raise EvaluationError(f"duplicate bar timestamp for {symbol}: {bar.timestamp.isoformat()}")
            seen.add(bar.timestamp)
        result[symbol] = tuple(ordered)
    return result


def _decision_index(bars: tuple[Bar, ...], decision_time) -> int:
    for index, bar in enumerate(bars):
        if bar.timestamp == decision_time:
            return index
    raise EvaluationError(f"decision_time does not match a bar timestamp: {decision_time.isoformat()}")


def _fill_price(bar: Bar, field: str, side: Side, *, is_entry: bool) -> float:
    if field == "open":
        return bar.open
    if field == "close":
        return bar.close

    if bar.bid is None or bar.ask is None:
        raise EvaluationError(f"quote fill requires bid and ask: {bar.symbol} at {bar.timestamp.isoformat()}")
    if side is Side.LONG:
        return bar.ask if is_entry else bar.bid
    return bar.bid if is_entry else bar.ask


def _funding_return(
    bars: tuple[Bar, ...],
    entry_time: datetime,
    exit_time: datetime,
    side: Side,
    weight: float,
) -> float:
    rates_by_timestamp: dict[datetime, float] = {}
    for bar in bars:
        if not bar.has_funding_event:
            continue
        if bar.funding_timestamp is None or bar.funding_rate is None:
            raise EvaluationError(f"incomplete funding event: {bar.symbol} at {bar.timestamp.isoformat()}")
        if not entry_time < bar.funding_timestamp <= exit_time:
            continue
        existing = rates_by_timestamp.get(bar.funding_timestamp)
        if existing is not None and not math.isclose(existing, bar.funding_rate, rel_tol=0.0, abs_tol=1e-15):
            raise EvaluationError(f"conflicting funding rates at {bar.funding_timestamp.isoformat()}")
        rates_by_timestamp[bar.funding_timestamp] = bar.funding_rate

    direction = 1.0 if side is Side.LONG else -1.0
    return sum(-direction * rate for rate in rates_by_timestamp.values()) * weight
