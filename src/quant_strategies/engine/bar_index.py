from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from quant_strategies.engine.models import Bar


@dataclass(frozen=True)
class IndexedBars:
    bars_by_symbol: dict[str, tuple[Bar, ...]]
    positions_by_symbol: dict[str, dict[datetime, int]]
    funding_events_by_symbol: dict[str, tuple[Bar, ...]]
    has_funding_events: bool


def build_bar_index(
    bars: tuple[Bar, ...],
    *,
    error_factory: Callable[[str], Exception],
) -> IndexedBars:
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
                raise error_factory(f"duplicate bar timestamp for {symbol}: {bar.timestamp.isoformat()}")
            positions[bar.timestamp] = index
            if bar.has_funding_event:
                funding_events.append(bar)
                has_funding_events = True
        bars_by_symbol[symbol] = tuple(ordered)
        positions_by_symbol[symbol] = positions
        funding_events_by_symbol[symbol] = tuple(funding_events)
    return IndexedBars(
        bars_by_symbol=bars_by_symbol,
        positions_by_symbol=positions_by_symbol,
        funding_events_by_symbol=funding_events_by_symbol,
        has_funding_events=has_funding_events,
    )


def attach_bar_index(request: object, indexed: IndexedBars) -> None:
    object.__setattr__(request, "_indexed_bars", indexed)


def attached_bar_index(request: object) -> IndexedBars | None:
    value = getattr(request, "_indexed_bars", None)
    return value if isinstance(value, IndexedBars) else None
