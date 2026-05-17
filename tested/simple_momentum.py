"""Strategy: simple_momentum

Thesis:
A one-bar positive close-to-close move can be used as a minimal causal long
signal for testing the research harness.

Required observables:
Symbol, timestamp, and close price for ordered bars.

Signal rule:
For each bar after the first, emit a long signal at the current bar timestamp
when the current close is greater than the previous close.

Falsifier:
If the harness cannot evaluate this deterministic positive-momentum toy rule
without lookahead or schema errors, the harness is broken.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def generate_signals(bars: Sequence[Mapping[str, object]], params: Mapping[str, object]) -> list[dict[str, object]]:
    weight = float(params.get("weight", 1.0))
    hold_bars = int(params.get("hold_bars", 1))
    signals: list[dict[str, object]] = []

    for index in range(1, len(bars)):
        previous_close = float(bars[index - 1]["close"])
        current_close = float(bars[index]["close"])
        if current_close > previous_close:
            signals.append(
                {
                    "symbol": str(bars[index]["symbol"]),
                    "decision_time": bars[index]["timestamp"],
                    "side": "long",
                    "weight": weight,
                    "hold_bars": hold_bars,
                }
            )

    return signals
