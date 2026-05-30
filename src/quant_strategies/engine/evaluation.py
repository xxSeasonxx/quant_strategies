from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from quant_strategies.decisions import StrategyDecision
from quant_strategies.engine.bar_index import (
    IndexedBars,
    attach_bar_index,
    attached_bar_index,
    build_bar_index,
)
from quant_strategies.engine.executable import (
    ExecutableDecision as _ExecutableDecision,
    executable_decision,
)
from quant_strategies.funding import funding_return_over_window
from quant_strategies.engine.models import (
    Bar,
    EvaluationRequest,
    ExitReason,
    FillModel,
    GatingConfig,
    GatingReport,
    GateResult,
    ScreeningResult,
    Side,
    SmokeScore,
    Trade,
)


class EvaluationError(ValueError):
    """Raised when an evaluation request cannot be screened causally."""


@dataclass(frozen=True)
class _ExitSelection:
    exit_bar: Bar
    reason: ExitReason


def screen(request: EvaluationRequest) -> ScreeningResult:
    indexed = _request_bar_index(request)
    if not indexed.bars_by_symbol:
        raise EvaluationError("bars are required")

    trades: list[Trade] = []
    for decision in request.spec.decisions:
        executable = _executable_decision(decision)
        symbol_bars = indexed.bars_by_symbol.get(executable.symbol)
        if not symbol_bars:
            raise EvaluationError(f"missing bars for decision symbol: {executable.symbol}")
        decision_index = _decision_index(indexed, executable.symbol, decision.decision_time)
        entry_index = decision_index + request.fill_model.entry_lag_bars
        if entry_index >= len(symbol_bars):
            raise EvaluationError(f"entry fill is outside available bars: {executable.symbol}")

        entry_bar = symbol_bars[entry_index]
        entry_price = _fill_price(entry_bar, request.fill_model.price, executable.side, is_entry=True)
        exit_selection = _select_exit(
            symbol_bars,
            executable,
            entry_index,
            entry_price,
            request.fill_model,
        )
        exit_bar = exit_selection.exit_bar
        exit_price = _fill_price(exit_bar, request.fill_model.price, executable.side, is_entry=False)
        direction = 1.0 if executable.side is Side.LONG else -1.0
        gross_return = direction * ((exit_price - entry_price) / entry_price) * executable.weight
        funding_return = _funding_return(
            indexed,
            executable.symbol,
            entry_bar.timestamp,
            exit_bar.timestamp,
            executable.side,
            executable.weight,
        )
        cost_return = (request.cost_model.round_trip_bps / 10_000.0) * executable.weight
        net_return = gross_return + funding_return - cost_return
        trades.append(
            Trade(
                decision_id=decision.decision_id,
                symbol=executable.symbol,
                side=executable.side,
                decision_time=decision.decision_time,
                entry_time=entry_bar.timestamp,
                exit_time=exit_bar.timestamp,
                entry_price=entry_price,
                exit_price=exit_price,
                exit_reason=exit_selection.reason,
                weight=executable.weight,
                gross_return=gross_return,
                funding_return=funding_return,
                cost_return=cost_return,
                net_return=net_return,
                decision_metadata=executable.metadata,
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


def gate_screen(
    request: EvaluationRequest,
    config: GatingConfig | None = None,
) -> GatingReport:
    gating_config = config or GatingConfig()
    gates: list[GateResult] = []
    try:
        screening_result = screen(request)
    except EvaluationError as exc:
        return GatingReport(
            strategy_id=request.spec.strategy_id,
            passed=False,
            gates=(GateResult(name="valid_inputs", passed=False, detail=str(exc)),),
            screening_result=None,
        )

    gates.append(GateResult(name="valid_inputs", passed=True, detail="screening completed"))
    gates.append(
        GateResult(
            name="min_trades",
            passed=screening_result.trade_count >= gating_config.min_trades,
            detail=f"{screening_result.trade_count} >= {gating_config.min_trades}",
        )
    )
    if gating_config.require_positive_gross:
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
    if gating_config.require_positive_net:
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

    return GatingReport(
        strategy_id=request.spec.strategy_id,
        passed=all(gate.passed for gate in gates),
        gates=tuple(gates),
        screening_result=screening_result,
    )


def _index_bars(bars: tuple[Bar, ...]) -> IndexedBars:
    return build_bar_index(bars, error_factory=EvaluationError)


def _request_bar_index(request: EvaluationRequest) -> IndexedBars:
    indexed = attached_bar_index(request)
    if indexed is not None:
        return indexed
    indexed = _index_bars(request.bars)
    attach_bar_index(request, indexed)
    return indexed


def _decision_index(indexed: IndexedBars, symbol: str, decision_time: datetime) -> int:
    position = indexed.positions_by_symbol.get(symbol, {}).get(decision_time)
    if position is not None:
        return position
    raise EvaluationError(f"decision_time does not match a bar timestamp: {decision_time.isoformat()}")


def _select_exit(
    bars: tuple[Bar, ...],
    executable: _ExecutableDecision,
    entry_index: int,
    entry_price: float,
    fill_model: FillModel,
) -> _ExitSelection:
    last_trigger_index = entry_index + executable.decision.exit_policy.max_hold_bars
    last_exit_index = last_trigger_index + fill_model.exit_lag_bars
    if last_exit_index >= len(bars):
        raise EvaluationError(f"exit fill is outside available bars: {executable.symbol}")

    best_return_bps = 0.0
    for trigger_index in range(entry_index + 1, last_trigger_index + 1):
        trigger_bar = bars[trigger_index]
        trigger_price = _fill_price(trigger_bar, fill_model.price, executable.side, is_entry=False)
        side_return_bps = _side_return_bps(entry_price, trigger_price, executable.side)
        if side_return_bps > best_return_bps:
            best_return_bps = side_return_bps

        reason = _exit_reason(executable.decision, side_return_bps, best_return_bps)
        if reason is None and trigger_index == last_trigger_index:
            reason = "max_hold"
        if reason is None:
            continue

        exit_index = trigger_index + fill_model.exit_lag_bars
        return _ExitSelection(
            exit_bar=bars[exit_index],
            reason=reason,
        )

    raise EvaluationError(f"exit fill is outside available bars: {executable.symbol}")


def _side_return_bps(entry_price: float, current_price: float, side: Side) -> float:
    direction = 1.0 if side is Side.LONG else -1.0
    return direction * ((current_price - entry_price) / entry_price) * 10_000.0


def _exit_reason(decision: StrategyDecision, side_return_bps: float, best_return_bps: float) -> ExitReason | None:
    exit_policy = decision.exit_policy
    if exit_policy.stop_loss_bps is not None and side_return_bps <= -exit_policy.stop_loss_bps:
        return "stop_loss"
    if exit_policy.take_profit_bps is not None and side_return_bps >= exit_policy.take_profit_bps:
        return "take_profit"
    if (
        exit_policy.trailing_stop_bps is not None
        and best_return_bps > 0.0
        and best_return_bps - side_return_bps >= exit_policy.trailing_stop_bps
    ):
        return "trailing_stop"
    return None


def _executable_decision(decision: StrategyDecision) -> _ExecutableDecision:
    return executable_decision(decision, error_factory=EvaluationError)


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
    indexed: IndexedBars,
    symbol: str,
    entry_time: datetime,
    exit_time: datetime,
    side: Side,
    weight: float,
) -> float:
    if not indexed.has_funding_events:
        return 0.0

    def _events():
        for bar in indexed.funding_events_by_symbol.get(symbol, ()):
            if bar.funding_timestamp is None or bar.funding_rate is None:
                raise EvaluationError(
                    f"incomplete funding event: {bar.symbol} at {bar.timestamp.isoformat()}"
                )
            yield bar.funding_timestamp, bar.funding_rate

    direction_sign = 1.0 if side is Side.LONG else -1.0
    return funding_return_over_window(
        _events(),
        entry_time=entry_time,
        exit_time=exit_time,
        direction_sign=direction_sign,
        weight=weight,
        conflict_error=lambda ts: EvaluationError(
            f"conflicting funding rates at {ts.isoformat()}"
        ),
    )
