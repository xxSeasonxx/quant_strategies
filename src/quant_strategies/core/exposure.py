from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from quant_strategies.core.config import FillModelConfig
from quant_strategies.data_contract import NormalizedRows
from quant_strategies.decisions import TargetDecision

_EXPOSURE_TOLERANCE = 1e-12


def exposure_admissibility_violations(
    decisions: Sequence[TargetDecision],
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
    fill_model: FillModelConfig,
) -> tuple[str, ...]:
    """Flag standing target books whose intended gross would exceed one unit of NAV.

    The decision is a standing, signed weight-of-NAV target per instrument (``0`` =
    flat). Same-symbol exposure nets by construction, so intended gross is the sum of
    the absolute standing target weights as the book steps through each decision time.
    A book whose intended gross crosses 1.0 at any decision is flagged here; the
    authoritative fail-closed budget verdict lives in the portfolio book
    (``portfolio_foundation``). This advisory mirrors that intent on the validation
    surface without rebuilding the netted accounting.
    """
    _ = (rows, fill_model)
    violations: list[str] = []
    standing: dict[str, float] = {}
    ordered = sorted(enumerate(decisions), key=lambda item: (item[1].decision_time, item[0]))
    for index, decision in ordered:
        symbol = decision.instrument.symbol
        weight = float(decision.target)
        if weight == 0.0:
            standing.pop(symbol, None)
        else:
            standing[symbol] = weight
        gross = sum(abs(value) for value in standing.values())
        if gross > 1.0 + _EXPOSURE_TOLERANCE:
            violations.append(
                "portfolio_target_weight_exceeds_one:"
                f"decision[{index}]:{decision.decision_time.isoformat()}:{gross:g}"
            )
    return tuple(dict.fromkeys(violations))
