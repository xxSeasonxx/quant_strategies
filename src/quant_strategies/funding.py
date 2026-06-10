from __future__ import annotations

import math

FUNDING_RATE_ABS_TOLERANCE = 1e-12


def funding_rates_match(first: float, second: float) -> bool:
    return math.isclose(first, second, rel_tol=0.0, abs_tol=FUNDING_RATE_ABS_TOLERANCE)
