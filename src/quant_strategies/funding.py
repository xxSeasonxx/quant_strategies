from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from datetime import datetime


FUNDING_RATE_ABS_TOLERANCE = 1e-12


def funding_rates_match(first: float, second: float) -> bool:
    return math.isclose(first, second, rel_tol=0.0, abs_tol=FUNDING_RATE_ABS_TOLERANCE)


def funding_return_over_window(
    events: Iterable[tuple[datetime, float]],
    *,
    entry_time: datetime,
    exit_time: datetime,
    direction_sign: float,
    weight: float,
    conflict_error: Callable[[datetime], Exception],
) -> float:
    """Signed funding cashflow accrued over an open position window.

    Single source of the funding invariants shared by the engine kernel and the
    validation row path: window rule ``entry < ts <= exit``, dedup of duplicate
    timestamps via :func:`funding_rates_match`, and sign ``Σ(-direction * rate) * weight``
    (a long position pays positive funding; a short receives it).

    ``events`` must already be filtered to the relevant symbol and to complete
    funding events; each caller keeps its own incomplete-event validation so its
    error type and message are preserved. ``conflict_error`` builds the exception
    raised when the same timestamp carries non-matching rates.
    """
    rates_by_timestamp: dict[datetime, float] = {}
    for funding_timestamp, funding_rate in events:
        if not entry_time < funding_timestamp <= exit_time:
            continue
        existing = rates_by_timestamp.get(funding_timestamp)
        if existing is not None and not funding_rates_match(existing, funding_rate):
            raise conflict_error(funding_timestamp)
        rates_by_timestamp[funding_timestamp] = funding_rate
    return sum(-direction_sign * rate for rate in rates_by_timestamp.values()) * weight
