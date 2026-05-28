from __future__ import annotations

from datetime import datetime, timedelta, timezone

from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.engine import Bar, Side


def bars_for(symbol: str, closes: list[float]) -> tuple[Bar, ...]:
    start = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    bars = []
    for offset, close in enumerate(closes):
        timestamp = start + timedelta(minutes=offset)
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=timestamp,
                open=close,
                high=close,
                low=close,
                close=close,
            )
        )
    return tuple(bars)


def decision_for(
    symbol: str,
    *,
    decision_time: datetime | None = None,
    side: Side = Side.LONG,
    weight: float = 1.0,
    max_hold_bars: int = 1,
    take_profit_bps: float | None = None,
    stop_loss_bps: float | None = None,
    trailing_stop_bps: float | None = None,
    metadata: dict[str, object] | None = None,
    strategy_id: str = "test_strategy",
) -> StrategyDecision:
    timestamp = decision_time or datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    return StrategyDecision(
        strategy_id=strategy_id,
        instrument=InstrumentRef(kind="equity_or_etf", symbol=symbol),
        decision_time=timestamp,
        as_of_time=timestamp,
        target=PositionTarget(direction=side.value, sizing_kind="target_weight", size=weight),
        exit_policy=ExitPolicy(
            max_hold_bars=max_hold_bars,
            take_profit_bps=take_profit_bps,
            stop_loss_bps=stop_loss_bps,
            trailing_stop_bps=trailing_stop_bps,
        ),
        metadata=metadata or {},
    )
