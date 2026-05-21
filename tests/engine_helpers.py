from __future__ import annotations

from datetime import datetime, timedelta, timezone

from quant_strategies.engine import Bar


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
