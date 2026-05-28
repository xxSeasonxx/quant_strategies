from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import math

from quant_strategies.engine.models import (
    Bar,
    EvaluationRequest,
    ExitReason,
    FillModel,
    GateResult,
    ScreeningResult,
    Side,
    SmokeScore,
    Signal,
    Trade,
    ValidationConfig,
    ValidationReport,
)


class EvaluationError(ValueError):
    """Raised when an evaluation request cannot be screened causally."""


@dataclass(frozen=True)
class _ExitSelection:
    exit_bar: Bar
    reason: ExitReason


@dataclass(frozen=True)
class _IndexedBars:
    bars_by_symbol: dict[str, tuple[Bar, ...]]
    positions_by_symbol: dict[str, dict[datetime, int]]
    funding_events_by_symbol: dict[str, tuple[Bar, ...]]
    has_funding_events: bool


def screen(request: EvaluationRequest) -> ScreeningResult:
    indexed = _index_bars(request.bars)
    if not indexed.bars_by_symbol:
        raise EvaluationError("bars are required")

    trades: list[Trade] = []
    for signal in request.spec.signals:
        symbol_bars = indexed.bars_by_symbol.get(signal.symbol)
        if not symbol_bars:
            raise EvaluationError(f"missing bars for signal symbol: {signal.symbol}")
        decision_index = _decision_index(indexed, signal.symbol, signal.decision_time)
        entry_index = decision_index + request.fill_model.entry_lag_bars
        if entry_index >= len(symbol_bars):
            raise EvaluationError(f"entry fill is outside available bars: {signal.symbol}")

        entry_bar = symbol_bars[entry_index]
        entry_price = _fill_price(entry_bar, request.fill_model.price, signal.side, is_entry=True)
        exit_selection = _select_exit(
            symbol_bars,
            signal,
            entry_index,
            entry_price,
            request.fill_model,
        )
        exit_bar = exit_selection.exit_bar
        exit_price = _fill_price(exit_bar, request.fill_model.price, signal.side, is_entry=False)
        direction = 1.0 if signal.side is Side.LONG else -1.0
        gross_return = direction * ((exit_price - entry_price) / entry_price) * signal.weight
        funding_return = _funding_return(
            indexed,
            signal.symbol,
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
                exit_reason=exit_selection.reason,
                weight=signal.weight,
                gross_return=gross_return,
                funding_return=funding_return,
                cost_return=cost_return,
                net_return=net_return,
                signal_metadata=signal.metadata,
            )
        )

    gross_total = sum(trade.gross_return for trade in trades)
    funding_total = sum(trade.funding_return for trade in trades)
    cost_total = sum(trade.cost_return for trade in trades)
    net_total = sum(trade.net_return for trade in trades)
    return ScreeningResult(
        strategy_id=request.spec.strategy_id,
        trade_count=len(trades),
        smoke_score=SmokeScore(
            sum_signed_trade_activity_gross=gross_total,
            sum_signed_trade_activity_funding=funding_total,
            sum_signed_trade_activity_cost=cost_total,
            sum_signed_trade_activity_net=net_total,
        ),
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
                passed=screening_result.smoke_score.sum_signed_trade_activity_gross > 0,
                detail=(
                    "sum_signed_trade_activity_gross="
                    f"{screening_result.smoke_score.sum_signed_trade_activity_gross:.12g}"
                ),
            )
        )
    if validation_config.require_positive_net:
        gates.append(
            GateResult(
                name="positive_net",
                passed=screening_result.smoke_score.sum_signed_trade_activity_net > 0,
                detail=(
                    "sum_signed_trade_activity_net="
                    f"{screening_result.smoke_score.sum_signed_trade_activity_net:.12g}"
                ),
            )
        )

    return ValidationReport(
        strategy_id=request.spec.strategy_id,
        passed=all(gate.passed for gate in gates),
        gates=tuple(gates),
        screening_result=screening_result,
    )


def _index_bars(bars: tuple[Bar, ...]) -> _IndexedBars:
    grouped: dict[str, list[Bar]] = defaultdict(list)
    for bar in bars:
        grouped[bar.symbol].append(bar)

    bars_by_symbol: dict[str, tuple[Bar, ...]] = {}
    positions_by_symbol: dict[str, dict[datetime, int]] = {}
    funding_events_by_symbol: dict[str, tuple[Bar, ...]] = {}
    has_funding_events = False
    for symbol, symbol_bars in grouped.items():
        ordered = sorted(symbol_bars, key=lambda bar: bar.timestamp)
        positions: dict[datetime, int] = {}
        funding_events: list[Bar] = []
        for index, bar in enumerate(ordered):
            if bar.timestamp in positions:
                raise EvaluationError(f"duplicate bar timestamp for {symbol}: {bar.timestamp.isoformat()}")
            positions[bar.timestamp] = index
            if bar.has_funding_event:
                funding_events.append(bar)
                has_funding_events = True
        bars_by_symbol[symbol] = tuple(ordered)
        positions_by_symbol[symbol] = positions
        funding_events_by_symbol[symbol] = tuple(funding_events)
    return _IndexedBars(
        bars_by_symbol=bars_by_symbol,
        positions_by_symbol=positions_by_symbol,
        funding_events_by_symbol=funding_events_by_symbol,
        has_funding_events=has_funding_events,
    )


def _decision_index(indexed: _IndexedBars, symbol: str, decision_time: datetime) -> int:
    position = indexed.positions_by_symbol.get(symbol, {}).get(decision_time)
    if position is not None:
        return position
    raise EvaluationError(f"decision_time does not match a bar timestamp: {decision_time.isoformat()}")


def _select_exit(
    bars: tuple[Bar, ...],
    signal: Signal,
    entry_index: int,
    entry_price: float,
    fill_model: FillModel,
) -> _ExitSelection:
    last_trigger_index = entry_index + signal.max_hold_bars
    last_exit_index = last_trigger_index + fill_model.exit_lag_bars
    if last_exit_index >= len(bars):
        raise EvaluationError(f"exit fill is outside available bars: {signal.symbol}")

    best_return_bps = 0.0
    for trigger_index in range(entry_index + 1, last_trigger_index + 1):
        trigger_bar = bars[trigger_index]
        trigger_price = _fill_price(trigger_bar, fill_model.price, signal.side, is_entry=False)
        side_return_bps = _side_return_bps(entry_price, trigger_price, signal.side)
        if side_return_bps > best_return_bps:
            best_return_bps = side_return_bps

        reason = _exit_reason(signal, side_return_bps, best_return_bps)
        if reason is None and trigger_index == last_trigger_index:
            reason = "max_hold"
        if reason is None:
            continue

        exit_index = trigger_index + fill_model.exit_lag_bars
        return _ExitSelection(
            exit_bar=bars[exit_index],
            reason=reason,
        )

    raise EvaluationError(f"exit fill is outside available bars: {signal.symbol}")


def _side_return_bps(entry_price: float, current_price: float, side: Side) -> float:
    direction = 1.0 if side is Side.LONG else -1.0
    return direction * ((current_price - entry_price) / entry_price) * 10_000.0


def _exit_reason(signal: Signal, side_return_bps: float, best_return_bps: float) -> ExitReason | None:
    if signal.stop_loss_bps is not None and side_return_bps <= -signal.stop_loss_bps:
        return "stop_loss"
    if signal.take_profit_bps is not None and side_return_bps >= signal.take_profit_bps:
        return "take_profit"
    if (
        signal.trailing_stop_bps is not None
        and best_return_bps > 0.0
        and best_return_bps - side_return_bps >= signal.trailing_stop_bps
    ):
        return "trailing_stop"
    return None


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
    indexed: _IndexedBars,
    symbol: str,
    entry_time: datetime,
    exit_time: datetime,
    side: Side,
    weight: float,
) -> float:
    if not indexed.has_funding_events:
        return 0.0

    rates_by_timestamp: dict[datetime, float] = {}
    for bar in indexed.funding_events_by_symbol.get(symbol, ()):
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
