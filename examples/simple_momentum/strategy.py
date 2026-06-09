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
Emit the first long target decision at the current bar timestamp when the
current close is greater than the previous close.

Assumptions:
The configured fill model enters after the decision bar, so a close-derived
signal is not filled on the same close unless explicitly opted in.

Falsifier:
If the harness cannot evaluate this deterministic positive-momentum toy rule
without lookahead or schema errors, the harness is broken.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from quant_strategies.decisions import (
    ExitPolicy,
    InstrumentRef,
    ObservationRef,
    PositionTarget,
    StrategyDecision,
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
) -> list[StrategyDecision]:
    validated = validate_params(params)
    weight = float(validated["weight"])
    max_hold_bars = int(validated["max_hold_bars"])
    decisions: list[StrategyDecision] = []

    for index in range(1, len(bars)):
        previous_close = float(bars[index - 1]["close"])
        current_close = float(bars[index]["close"])
        if current_close > previous_close:
            symbol = str(bars[index]["symbol"])
            timestamp = bars[index]["timestamp"]
            decisions.append(
                StrategyDecision(
                    strategy_id="simple_momentum",
                    instrument=InstrumentRef(
                        kind="equity_or_etf",
                        symbol=symbol,
                    ),
                    decision_time=timestamp,
                    as_of_time=timestamp,
                    target=PositionTarget(
                        direction="long",
                        sizing_kind="target_weight",
                        size=weight,
                    ),
                    exit_policy=ExitPolicy(max_hold_bars=max_hold_bars),
                    observations=(
                        ObservationRef(
                            symbol=symbol,
                            timestamp=bars[index - 1]["timestamp"],
                            field="close",
                            source="strategy_input",
                        ),
                        ObservationRef(
                            symbol=symbol,
                            timestamp=timestamp,
                            field="close",
                            source="strategy_input",
                        ),
                    ),
                )
            )
            break

    return decisions
