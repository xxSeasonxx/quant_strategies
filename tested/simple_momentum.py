"""Strategy: simple_momentum

Source / provenance:
Internal runner smoke strategy for this repository. It is a deterministic test
fixture, not an external paper or production alpha source.

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

from collections.abc import Mapping, Sequence

from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision


def generate_decisions(
    bars: Sequence[Mapping[str, object]],
    params: Mapping[str, object],
) -> list[StrategyDecision]:
    weight = float(params.get("weight", 1.0))
    hold_bars = int(params.get("hold_bars", 1))
    decisions: list[StrategyDecision] = []

    for index in range(1, len(bars)):
        previous_close = float(bars[index - 1]["close"])
        current_close = float(bars[index]["close"])
        if current_close > previous_close:
            timestamp = bars[index]["timestamp"]
            decisions.append(
                StrategyDecision(
                    strategy_id="simple_momentum",
                    instrument=InstrumentRef(
                        kind="equity_or_etf",
                        symbol=str(bars[index]["symbol"]),
                    ),
                    decision_time=timestamp,
                    as_of_time=timestamp,
                    target=PositionTarget(
                        direction="long",
                        sizing_kind="target_weight",
                        size=weight,
                    ),
                    exit_policy=ExitPolicy(max_hold_bars=hold_bars),
                )
            )
            break

    return decisions
