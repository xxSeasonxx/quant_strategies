from __future__ import annotations

from datetime import UTC, datetime, timedelta

from quant_strategies.decisions import InstrumentRef, RiskRule, TargetDecision


def bars_for(symbol: str, closes: list[float]) -> tuple[dict[str, object], ...]:
    """Minimal OHLC rows (one bar per minute) for the netted-book spine tests."""
    start = datetime(2024, 1, 1, 9, 30, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    for offset, close in enumerate(closes):
        timestamp = start + timedelta(minutes=offset)
        rows.append(
            {
                "symbol": symbol,
                "timestamp": timestamp,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "available_at": timestamp,
            }
        )
    return tuple(rows)


def decision_for(
    symbol: str,
    *,
    decision_time: datetime | None = None,
    target: float = 1.0,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    trailing: float | None = None,
    metadata: dict[str, object] | None = None,
    strategy_id: str = "test_strategy",
) -> TargetDecision:
    """A standing, signed weight-of-NAV target for the netted-book spine.

    ``target`` is the signed weight (``0`` = flat/close); declared price-path exits are
    a :class:`RiskRule` enforced by the book on the net position.
    """
    timestamp = decision_time or datetime(2024, 1, 1, 9, 30, tzinfo=UTC)
    risk_rule = None
    if stop_loss is not None or take_profit is not None or trailing is not None:
        risk_rule = RiskRule(stop_loss=stop_loss, take_profit=take_profit, trailing=trailing)
    return TargetDecision(
        strategy_id=strategy_id,
        instrument=InstrumentRef(kind="equity_or_etf", symbol=symbol),
        decision_time=timestamp,
        as_of_time=timestamp,
        target=target,
        risk_rule=risk_rule,
        metadata=metadata or {},
    )
