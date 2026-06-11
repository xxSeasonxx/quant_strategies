"""Strategy: simple_momentum

Source / provenance:
internal_note: examples/simple_momentum/strategy.py documents this internal
quick-run diagnostic strategy. It is a deterministic test fixture, not an external
paper or production alpha source.

Market rationale:
A one-bar positive close-to-close move can be used as a minimal causal long
signal for testing the research harness.

Required observables:
Symbol, timestamp, and close price for ordered bars.

Decision rule:
While flat, go long a weight-of-NAV target on the first bar whose close exceeds
the prior close, then declare an explicit flat (zero) target max_hold_bars bars
later so the held position closes on the target book itself rather than an engine
hold horizon. Re-arm once flat and repeat across the window so the NAV path
carries enough at-risk return bars to score.

Assumptions:
The signal is gated on each bar's available_at, not its timestamp: the long
becomes actionable on the first bar at or after the signal bar's available_at, so
decision_time always lands on a real, already-available bar and the configured
fill model enters on the following bar. A scheduled flat declares no observation
because it is a hold-horizon policy exit, not a data-driven signal.

Falsifier:
If the harness cannot evaluate this deterministic positive-momentum toy rule
without lookahead or schema errors, the harness is broken.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from quant_strategies.decisions import (
    InstrumentRef,
    ObservationRef,
    TargetDecision,
)


def validate_params(params: Mapping[str, object]) -> dict[str, object]:
    weight = float(params.get("weight", 1.0))
    if not math.isfinite(weight) or weight <= 0.0:
        raise ValueError("weight must be finite and positive")
    max_hold_bars = int(params.get("max_hold_bars", 1))
    if max_hold_bars < 1:
        raise ValueError("max_hold_bars must be >= 1")
    return {"weight": weight, "max_hold_bars": max_hold_bars}


def generate_decisions(
    bars: Sequence[Mapping[str, object]],
    params: Mapping[str, object],
) -> list[TargetDecision]:
    validated = validate_params(params)
    weight = float(validated["weight"])
    max_hold_bars = int(validated["max_hold_bars"])
    decisions: list[TargetDecision] = []

    index = 1
    while index < len(bars):
        if float(bars[index]["close"]) <= float(bars[index - 1]["close"]):
            index += 1
            continue
        symbol = str(bars[index]["symbol"])
        signal_time = bars[index]["timestamp"]

        # Act on the first real bar at or after the signal's availability, so
        # decision_time lands on a bar and is never look-ahead.
        entry_index = _first_bar_at_or_after(bars, index + 1, bars[index]["available_at"])
        if entry_index is None:
            break
        exit_index = entry_index + max_hold_bars
        if exit_index >= len(bars):
            break

        decisions.append(
            TargetDecision(
                strategy_id="simple_momentum",
                instrument=InstrumentRef(kind="equity_or_etf", symbol=symbol),
                decision_time=bars[entry_index]["timestamp"],
                as_of_time=signal_time,
                target=weight,
                observations=(
                    ObservationRef(
                        symbol=symbol,
                        timestamp=bars[index - 1]["timestamp"],
                        field="close",
                        source="strategy_input",
                    ),
                    ObservationRef(
                        symbol=symbol,
                        timestamp=signal_time,
                        field="close",
                        source="strategy_input",
                    ),
                ),
            )
        )
        decisions.append(
            TargetDecision(
                strategy_id="simple_momentum",
                instrument=InstrumentRef(kind="equity_or_etf", symbol=symbol),
                decision_time=bars[exit_index]["timestamp"],
                as_of_time=bars[entry_index]["timestamp"],
                target=0.0,
            )
        )
        index = exit_index + 1

    return decisions


def _first_bar_at_or_after(
    bars: Sequence[Mapping[str, object]],
    start: int,
    available_at: object,
) -> int | None:
    for index in range(start, len(bars)):
        if bars[index]["timestamp"] >= available_at:
            return index
    return None
