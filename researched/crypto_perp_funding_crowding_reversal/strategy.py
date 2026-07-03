"""Crypto perp funding crowding reversal.

Thesis:
Realized same-sign funding pressure plus same-direction price extension can mark
crowded perp positioning. After the signal bar is observable, the strategy takes
the other side of the crowded move and exits through an explicit fixed-horizon
flat target.
"""

from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any, cast

from quant_strategies.decisions import (
    InstrumentRef,
    ObservationRef,
    RiskRule,
    TargetDecision,
)

__all__ = ["generate_decisions", "validate_params"]

_STRATEGY_ID = "crypto_perp_funding_crowding_reversal"
_REQUIRED_FIELDS = {
    "symbol",
    "timestamp",
    "available_at",
    "close",
    "funding_timestamp",
    "funding_rate",
    "has_funding_event",
}
_DEFAULT_PARAMS: dict[str, object] = {
    "funding_lookback_events": 5,
    "funding_decay": 0.0,
    "return_lookback_minutes": 120,
    "decision_interval_minutes": 240,
    "entry_twap_bars": 1,
    "exit_twap_bars": 0,
    "decision_lag_minutes": 1,
    "session_start_hour": 0,
    "session_end_hour": 24,
    "top_n": 5,
    "min_cross_section": 4,
    "min_abs_funding_bps": 1.0,
    "min_abs_return_bps": 0.0,
    "include_positive_funding_shorts": True,
    "include_negative_funding_longs": True,
    "min_same_sign_funding_events": 3,
    "min_latest_abs_funding_bps": 0.0,
    "recent_return_lookback_minutes": 60,
    "max_recent_same_direction_return_bps": 250.0,
    "min_idiosyncratic_return_bps": 2.5,
    "idiosyncratic_mode": "raw",
    "min_idiosyncratic_sigma": 0.5,
    "selection_score": "combined",
    "cross_section_reference": "mean",
    "weighting": "equal",
    "dislocation_weight_power": 1.0,
    "vol_lookback_minutes": 1440,
    "long_hold_minutes": 720,
    "short_hold_minutes": 480,
    "hold_vol_scaling": 0.0,
    "hold_dislocation_scaling": 0.0,
    "take_profit_frac": 0.0,
}

_HOLD_MIN_MINUTES = 120
_HOLD_MAX_MINUTES = 1440


@dataclass(frozen=True)
class _BarRow:
    symbol: str
    timestamp: datetime
    available_at: datetime
    close: float


@dataclass(frozen=True)
class _FundingEvent:
    timestamp: datetime
    bar_timestamp: datetime
    available_at: datetime
    rate: float


@dataclass(frozen=True)
class _SymbolRows:
    bars: tuple[_BarRow, ...]
    timestamps: tuple[datetime, ...]
    funding_events: tuple[_FundingEvent, ...]
    funding_available_at: tuple[datetime, ...]


@dataclass(frozen=True)
class _Candidate:
    symbol: str
    signal_row: _BarRow
    lookback_row: _BarRow
    funding_events: tuple[_FundingEvent, ...]
    funding_pressure_bps: float
    latest_funding_bps: float
    same_sign_funding_events: int
    return_extension_bps: float
    recent_return_bps: float
    volatility: float | None = None
    recent_row: _BarRow | None = None


@dataclass(frozen=True)
class _Selection:
    candidate: _Candidate
    side: int
    score: float
    idiosyncratic: float = 0.0


def validate_params(params: Mapping[str, object]) -> dict[str, object]:
    """Validate the bounded thesis parameters used by the strategy."""

    unknown = set(params) - set(_DEFAULT_PARAMS)
    if unknown:
        raise ValueError(f"unknown params: {sorted(unknown)}")

    merged = {**_DEFAULT_PARAMS, **dict(params)}
    validated: dict[str, object] = {
        "funding_lookback_events": _positive_int(
            merged["funding_lookback_events"], "funding_lookback_events"
        ),
        "funding_decay": _non_negative_float(
            merged["funding_decay"], "funding_decay"
        ),
        "return_lookback_minutes": _positive_int(
            merged["return_lookback_minutes"], "return_lookback_minutes"
        ),
        "decision_interval_minutes": _positive_int(
            merged["decision_interval_minutes"], "decision_interval_minutes"
        ),
        "entry_twap_bars": _positive_int(
            merged["entry_twap_bars"], "entry_twap_bars"
        ),
        "exit_twap_bars": _non_negative_int(
            merged["exit_twap_bars"], "exit_twap_bars"
        ),
        "decision_lag_minutes": _non_negative_int(
            merged["decision_lag_minutes"], "decision_lag_minutes"
        ),
        "session_start_hour": _hour(merged["session_start_hour"], "session_start_hour"),
        "session_end_hour": _session_end_hour(merged["session_end_hour"]),
        "top_n": _positive_int(merged["top_n"], "top_n"),
        "min_cross_section": _positive_int(
            merged["min_cross_section"], "min_cross_section"
        ),
        "min_abs_funding_bps": _non_negative_float(
            merged["min_abs_funding_bps"], "min_abs_funding_bps"
        ),
        "min_abs_return_bps": _non_negative_float(
            merged["min_abs_return_bps"], "min_abs_return_bps"
        ),
        "include_positive_funding_shorts": _bool_param(
            merged["include_positive_funding_shorts"],
            "include_positive_funding_shorts",
        ),
        "include_negative_funding_longs": _bool_param(
            merged["include_negative_funding_longs"],
            "include_negative_funding_longs",
        ),
        "min_same_sign_funding_events": _non_negative_int(
            merged["min_same_sign_funding_events"], "min_same_sign_funding_events"
        ),
        "min_latest_abs_funding_bps": _non_negative_float(
            merged["min_latest_abs_funding_bps"], "min_latest_abs_funding_bps"
        ),
        "recent_return_lookback_minutes": _non_negative_int(
            merged["recent_return_lookback_minutes"],
            "recent_return_lookback_minutes",
        ),
        "max_recent_same_direction_return_bps": _non_negative_float(
            merged["max_recent_same_direction_return_bps"],
            "max_recent_same_direction_return_bps",
        ),
        "min_idiosyncratic_return_bps": _non_negative_float(
            merged["min_idiosyncratic_return_bps"],
            "min_idiosyncratic_return_bps",
        ),
        "idiosyncratic_mode": _idiosyncratic_mode(merged["idiosyncratic_mode"]),
        "min_idiosyncratic_sigma": _non_negative_float(
            merged["min_idiosyncratic_sigma"], "min_idiosyncratic_sigma"
        ),
        "selection_score": _selection_score(merged["selection_score"]),
        "cross_section_reference": _cross_section_reference(
            merged["cross_section_reference"]
        ),
        "dislocation_weight_power": _positive_float(
            merged["dislocation_weight_power"], "dislocation_weight_power"
        ),
        "weighting": _weighting(merged["weighting"]),
        "vol_lookback_minutes": _positive_int(
            merged["vol_lookback_minutes"], "vol_lookback_minutes"
        ),
        "long_hold_minutes": _positive_int(
            merged["long_hold_minutes"], "long_hold_minutes"
        ),
        "short_hold_minutes": _positive_int(
            merged["short_hold_minutes"], "short_hold_minutes"
        ),
        "hold_vol_scaling": _non_negative_float(
            merged["hold_vol_scaling"], "hold_vol_scaling"
        ),
        "hold_dislocation_scaling": _non_negative_float(
            merged["hold_dislocation_scaling"], "hold_dislocation_scaling"
        ),
        "take_profit_frac": _non_negative_float(
            merged["take_profit_frac"], "take_profit_frac"
        ),
    }
    if _param_int(validated, "session_start_hour") >= _param_int(
        validated, "session_end_hour"
    ):
        raise ValueError("session_start_hour must be < session_end_hour")
    if not (
        validated["include_positive_funding_shorts"]
        or validated["include_negative_funding_longs"]
    ):
        raise ValueError("at least one side must be enabled")
    return validated


def generate_decisions(
    bars: Sequence[Mapping[str, object]], params: Mapping[str, object]
) -> list[TargetDecision]:
    """Emit standing crypto-perp target decisions for the funding reversal thesis."""

    if not bars:
        return []
    validated = validate_params(params)
    rows_by_symbol = _rows_by_symbol(bars)
    if len(rows_by_symbol) < _param_int(validated, "min_cross_section"):
        return []

    signal_times = _cadence_signal_times(rows_by_symbol, validated)
    n_universe = len(rows_by_symbol)
    weighting = _param_str(validated, "weighting")
    twap_bars = _param_int(validated, "entry_twap_bars")
    exit_twap_bars = _param_int(validated, "exit_twap_bars") or twap_bars
    take_profit_frac = _param_float(validated, "take_profit_frac")
    risk_rule = (
        RiskRule(take_profit=take_profit_frac) if take_profit_frac > 0.0 else None
    )
    active_until: dict[str, datetime] = {}
    decisions: list[TargetDecision] = []

    for signal_time in signal_times:
        candidates = [
            candidate
            for rows in rows_by_symbol.values()
            if (
                candidate := _candidate_at_signal_time(
                    rows,
                    signal_time,
                    funding_lookback_events=_param_int(
                        validated, "funding_lookback_events"
                    ),
                    funding_decay=_param_float(validated, "funding_decay"),
                    return_lookback_minutes=_param_int(
                        validated, "return_lookback_minutes"
                    ),
                    recent_return_lookback_minutes=_param_int(
                        validated, "recent_return_lookback_minutes"
                    ),
                    vol_lookback_minutes=_param_int(
                        validated, "vol_lookback_minutes"
                    ),
                )
            )
            is not None
        ]
        if len(candidates) < _param_int(validated, "min_cross_section"):
            continue

        market_return_bps = _cross_section_reference_bps(
            [candidate.return_extension_bps for candidate in candidates],
            _param_str(validated, "cross_section_reference"),
        )
        selections = _select_candidates(candidates, market_return_bps, validated)
        if not selections:
            continue
        magnitudes = _selection_targets(
            selections,
            n_universe,
            weighting,
            _param_float(validated, "dislocation_weight_power"),
        )
        reference_volatility = _reference_volatility(selections)
        reference_idiosyncratic = _reference_idiosyncratic(selections)

        cross_section_available_at = max(
            candidate.signal_row.available_at for candidate in candidates
        )
        earliest_decision_time = cross_section_available_at + timedelta(
            minutes=_param_int(validated, "decision_lag_minutes")
        )

        decision_time = earliest_decision_time
        for selection, magnitude in zip(selections, magnitudes):
            candidate = selection.candidate
            symbol = candidate.symbol
            if (
                active_until.get(symbol, datetime.min.replace(tzinfo=timezone.utc))
                >= decision_time
            ):
                continue

            base_hold = (
                _param_int(validated, "long_hold_minutes")
                if selection.side > 0
                else _param_int(validated, "short_hold_minutes")
            )
            if _param_float(validated, "hold_vol_scaling") > 0.0:
                hold_minutes = _scaled_hold_minutes(
                    base_hold,
                    candidate.volatility,
                    reference_volatility,
                    _param_float(validated, "hold_vol_scaling"),
                )
            elif _param_float(validated, "hold_dislocation_scaling") > 0.0:
                hold_minutes = _conviction_scaled_hold(
                    base_hold,
                    selection.idiosyncratic,
                    reference_idiosyncratic,
                    _param_float(validated, "hold_dislocation_scaling"),
                )
            else:
                hold_minutes = base_hold
            exit_time = decision_time + timedelta(minutes=hold_minutes)

            target = selection.side * magnitude
            decisions.extend(
                _ramped_decisions(
                    symbol=symbol,
                    entry_time=decision_time,
                    exit_time=exit_time,
                    target=target,
                    twap_bars=twap_bars,
                    exit_twap_bars=exit_twap_bars,
                    entry_as_of=candidate.signal_row.timestamp,
                    risk_rule=risk_rule,
                    observations=_observations(candidate),
                    metadata={
                        "signal_family": _STRATEGY_ID,
                        "funding_pressure_bps": candidate.funding_pressure_bps,
                        "latest_funding_bps": candidate.latest_funding_bps,
                        "return_extension_bps": candidate.return_extension_bps,
                        "recent_return_bps": candidate.recent_return_bps,
                        "market_return_bps": market_return_bps,
                        "side": "long" if selection.side > 0 else "short",
                        "selection_score": selection.score,
                    },
                )
            )
            active_until[symbol] = exit_time + timedelta(minutes=exit_twap_bars - 1)

    return sorted(
        decisions,
        key=lambda decision: (
            decision.decision_time,
            decision.instrument.symbol,
            decision.target,
        ),
    )


def _ramped_decisions(
    *,
    symbol: str,
    entry_time: datetime,
    exit_time: datetime,
    target: float,
    twap_bars: int,
    exit_twap_bars: int,
    entry_as_of: datetime,
    risk_rule: RiskRule | None,
    observations: tuple[ObservationRef, ...],
    metadata: Mapping[str, object],
) -> list[TargetDecision]:
    """Ramp a position in over ``twap_bars`` and out over ``exit_twap_bars`` bars.

    Each standing target steps the cumulative NAV weight so the engine trades an
    equal delta per bar, spreading entry and exit participation instead of pinning
    one bar against the capacity cap. Entry and exit spread independently, so the
    exit ramp can be lengthened to relieve the synchronized fixed-horizon unwind
    without changing entry timing. ``twap_bars == 1`` reproduces a single-bar
    entry. Entry steps carry the signal-bar ``as_of``; the exit is the
    fixed-horizon unwind scheduled at entry, so its steps carry the entry time as
    ``as_of``.
    """

    decisions: list[TargetDecision] = []
    for step in range(twap_bars):
        decisions.append(
            TargetDecision(
                strategy_id=_STRATEGY_ID,
                instrument=InstrumentRef(kind="crypto_perp", symbol=symbol),
                decision_time=entry_time + timedelta(minutes=step),
                as_of_time=entry_as_of,
                target=target * (step + 1) / twap_bars,
                risk_rule=risk_rule,
                observations=observations,
                metadata=metadata,
            )
        )
    for step in range(exit_twap_bars):
        decisions.append(
            TargetDecision(
                strategy_id=_STRATEGY_ID,
                instrument=InstrumentRef(kind="crypto_perp", symbol=symbol),
                decision_time=exit_time + timedelta(minutes=step),
                as_of_time=entry_time,
                target=target * (exit_twap_bars - 1 - step) / exit_twap_bars,
                metadata={"exit_reason": "fixed_horizon"},
            )
        )
    return decisions


def _rows_by_symbol(bars: Sequence[Mapping[str, object]]) -> dict[str, _SymbolRows]:
    grouped_bars: dict[str, list[_BarRow]] = {}
    grouped_funding: dict[str, list[_FundingEvent]] = {}
    for index, bar in enumerate(bars):
        missing = _REQUIRED_FIELDS - set(bar)
        if missing:
            raise ValueError(f"bar {index} missing fields: {sorted(missing)}")

        symbol = str(bar["symbol"])
        timestamp = _datetime_value(bar["timestamp"], "timestamp")
        available_at = _datetime_value(bar["available_at"], "available_at")
        close = _positive_float(bar["close"], "close")
        grouped_bars.setdefault(symbol, []).append(
            _BarRow(
                symbol=symbol,
                timestamp=timestamp,
                available_at=available_at,
                close=close,
            )
        )

        if _bool_value(bar["has_funding_event"]):
            funding_rate = _finite_float(bar["funding_rate"], "funding_rate")
            funding_timestamp = _datetime_value(
                bar["funding_timestamp"], "funding_timestamp"
            )
            grouped_funding.setdefault(symbol, []).append(
                _FundingEvent(
                    timestamp=funding_timestamp,
                    bar_timestamp=timestamp,
                    available_at=available_at,
                    rate=funding_rate,
                )
            )

    result: dict[str, _SymbolRows] = {}
    for symbol, symbol_bars in grouped_bars.items():
        ordered_bars = tuple(sorted(symbol_bars, key=lambda row: row.timestamp))
        ordered_funding = tuple(
            sorted(grouped_funding.get(symbol, ()), key=lambda event: event.available_at)
        )
        result[symbol] = _SymbolRows(
            bars=ordered_bars,
            timestamps=tuple(row.timestamp for row in ordered_bars),
            funding_events=ordered_funding,
            funding_available_at=tuple(event.available_at for event in ordered_funding),
        )
    return result


def _cadence_signal_times(
    rows_by_symbol: Mapping[str, _SymbolRows], params: Mapping[str, object]
) -> tuple[datetime, ...]:
    interval = _param_int(params, "decision_interval_minutes")
    session_start = _param_int(params, "session_start_hour")
    session_end = _param_int(params, "session_end_hour")
    times = {
        row.timestamp
        for rows in rows_by_symbol.values()
        for row in rows.bars
        if _is_cadence_timestamp(row.timestamp, interval, session_start, session_end)
    }
    return tuple(sorted(times))


def _is_cadence_timestamp(
    timestamp: datetime,
    interval_minutes: int,
    session_start_hour: int,
    session_end_hour: int,
) -> bool:
    if timestamp.hour < session_start_hour or timestamp.hour >= session_end_hour:
        return False
    minute_of_day = timestamp.hour * 60 + timestamp.minute
    return minute_of_day % interval_minutes == 0


def _candidate_at_signal_time(
    rows: _SymbolRows,
    signal_time: datetime,
    *,
    funding_lookback_events: int,
    funding_decay: float,
    return_lookback_minutes: int,
    recent_return_lookback_minutes: int,
    vol_lookback_minutes: int,
) -> _Candidate | None:
    signal_index = bisect_right(rows.timestamps, signal_time) - 1
    if signal_index < 0:
        return None
    signal_row = rows.bars[signal_index]

    lookback_time = signal_time - timedelta(minutes=return_lookback_minutes)
    lookback_index = bisect_right(rows.timestamps, lookback_time) - 1
    if lookback_index < 0:
        return None
    lookback_row = rows.bars[lookback_index]

    funding_index = bisect_right(rows.funding_available_at, signal_row.available_at)
    if funding_index < funding_lookback_events:
        return None
    funding_events = rows.funding_events[
        funding_index - funding_lookback_events : funding_index
    ]

    funding_pressure_bps = _weighted_funding_pressure_bps(funding_events, funding_decay)
    latest_funding_bps = funding_events[-1].rate * 10_000.0
    sign = 1 if funding_pressure_bps > 0.0 else -1 if funding_pressure_bps < 0.0 else 0
    same_sign_funding_events = (
        sum(1 for event in funding_events if event.rate * sign > 0.0)
        if sign != 0
        else 0
    )
    return_extension_bps = (signal_row.close / lookback_row.close - 1.0) * 10_000.0

    recent_return_bps = 0.0
    recent_row: _BarRow | None = None
    if recent_return_lookback_minutes > 0:
        recent_time = signal_time - timedelta(minutes=recent_return_lookback_minutes)
        recent_index = bisect_right(rows.timestamps, recent_time) - 1
        if recent_index >= 0:
            recent_row = rows.bars[recent_index]
            recent_return_bps = (signal_row.close / recent_row.close - 1.0) * 10_000.0

    return _Candidate(
        symbol=signal_row.symbol,
        signal_row=signal_row,
        lookback_row=lookback_row,
        funding_events=funding_events,
        funding_pressure_bps=funding_pressure_bps,
        latest_funding_bps=latest_funding_bps,
        same_sign_funding_events=same_sign_funding_events,
        return_extension_bps=return_extension_bps,
        recent_return_bps=recent_return_bps,
        volatility=_realized_volatility(rows, signal_index, vol_lookback_minutes),
        recent_row=recent_row,
    )


def _weighted_funding_pressure_bps(
    funding_events: tuple[_FundingEvent, ...], decay: float
) -> float:
    """Summed funding crowding in bps, optionally recency-weighted.

    Events are ordered oldest-to-newest. With ``decay == 0`` every event carries
    weight 1 and this is the plain sum (baseline). With ``decay > 0`` recent
    settlements weigh more (``exp(-decay * age)``, age 0 = newest); weights are
    renormalized to sum to the event count so the crowding *scale* is preserved
    and only its recency *tilt* changes.
    """

    if decay <= 0.0 or len(funding_events) <= 1:
        return sum(event.rate for event in funding_events) * 10_000.0
    count = len(funding_events)
    weights = [math.exp(-decay * (count - 1 - i)) for i in range(count)]
    total = sum(weights)
    scale = count / total
    weighted = sum(
        weights[i] * scale * funding_events[i].rate for i in range(count)
    )
    return weighted * 10_000.0


def _realized_volatility(
    rows: _SymbolRows, signal_index: int, lookback_minutes: int
) -> float | None:
    """Std of 1-minute close-to-close returns over the lookback ending at the signal bar.

    Causal: uses only bars at or before the signal bar. Returns ``None`` when the
    window is too short or degenerate so weighting can fall back to equal.
    """

    lookback_time = rows.bars[signal_index].timestamp - timedelta(minutes=lookback_minutes)
    start = bisect_left(rows.timestamps, lookback_time)
    window = rows.bars[start : signal_index + 1]
    if len(window) < 3:
        return None
    returns = [
        window[i].close / window[i - 1].close - 1.0 for i in range(1, len(window))
    ]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    vol = math.sqrt(variance)
    return vol if vol > 0.0 else None


def _select_candidates(
    candidates: Sequence[_Candidate],
    market_return_bps: float,
    params: Mapping[str, object],
) -> list[_Selection]:
    min_funding = _param_float(params, "min_abs_funding_bps")
    min_return = _param_float(params, "min_abs_return_bps")
    min_latest_funding = _param_float(params, "min_latest_abs_funding_bps")
    min_same_sign = _param_int(params, "min_same_sign_funding_events")
    max_recent = _param_float(params, "max_recent_same_direction_return_bps")
    selection_score = _param_str(params, "selection_score")

    # Idiosyncratic dislocation is the name's price extension measured against the
    # cross-section reference. "raw" uses the extension in bps vs the cross-section
    # mean. "vol_normalized" divides each extension by its expected horizon move
    # (per-minute vol × sqrt(horizon)) so the screen is comparable across names of
    # different volatility. "beta_adjusted" subtracts a beta-scaled market move
    # (beta ≈ name_vol / cross-section_vol) rather than the beta=1 mean, so a
    # high-beta name's move is not mistaken for idiosyncratic dislocation.
    mode = _param_str(params, "idiosyncratic_mode")
    return_lookback_minutes = _param_int(params, "return_lookback_minutes")
    betas: dict[str, float] | None = None
    if mode == "vol_normalized":
        min_idio = _param_float(params, "min_idiosyncratic_sigma")
        dislocations = {
            candidate.symbol: _dislocation_sigma(candidate, return_lookback_minutes)
            for candidate in candidates
        }
        known = [value for value in dislocations.values() if value is not None]
        if not known:
            return []
        market_dislocation = sum(known) / len(known)
    else:
        min_idio = _param_float(params, "min_idiosyncratic_return_bps")
        dislocations = {
            candidate.symbol: candidate.return_extension_bps for candidate in candidates
        }
        market_dislocation = market_return_bps
        if mode == "beta_adjusted":
            betas = _cross_section_betas(candidates)

    selections: list[_Selection] = []
    for candidate in candidates:
        dislocation = dislocations[candidate.symbol]
        if dislocation is None:
            continue
        reference = market_dislocation * (
            betas[candidate.symbol] if betas is not None else 1.0
        )
        idio_long = reference - dislocation
        idio_short = dislocation - reference
        if (
            _param_bool(params, "include_negative_funding_longs")
            and candidate.funding_pressure_bps <= -min_funding
            and candidate.return_extension_bps <= -min_return
            and abs(candidate.latest_funding_bps) >= min_latest_funding
            and candidate.same_sign_funding_events >= min_same_sign
            and candidate.recent_return_bps >= -max_recent
            and idio_long >= min_idio
        ):
            selections.append(
                _Selection(
                    candidate=candidate,
                    side=1,
                    score=_score(candidate, idio_long, selection_score),
                    idiosyncratic=idio_long,
                )
            )
        if (
            _param_bool(params, "include_positive_funding_shorts")
            and candidate.funding_pressure_bps >= min_funding
            and candidate.return_extension_bps >= min_return
            and abs(candidate.latest_funding_bps) >= min_latest_funding
            and candidate.same_sign_funding_events >= min_same_sign
            and candidate.recent_return_bps <= max_recent
            and idio_short >= min_idio
        ):
            selections.append(
                _Selection(
                    candidate=candidate,
                    side=-1,
                    score=_score(candidate, idio_short, selection_score),
                    idiosyncratic=idio_short,
                )
            )

    selections.sort(
        key=lambda selection: (
            selection.score,
            abs(selection.candidate.funding_pressure_bps),
            abs(selection.candidate.return_extension_bps),
        ),
        reverse=True,
    )
    return selections[: _param_int(params, "top_n")]


def _selection_targets(
    selections: Sequence[_Selection],
    n_universe: int,
    weighting: str,
    dislocation_weight_power: float = 1.0,
) -> list[float]:
    """Per-selection target magnitudes (before the signed side is applied).

    ``equal`` gives each name ``1/n_universe`` (gross scales with the number of
    active names, unchanged from the equal-weight book). ``inverse_vol`` keeps the
    same average per-name budget but reshapes it across the selected set in
    proportion to ``1/realized_vol`` (risk parity), so gross per decision is
    preserved while high-vol names carry proportionally less. ``dislocation``
    reshapes the same budget in proportion to each name's idiosyncratic
    dislocation magnitude — conviction weighting that leans into the biggest
    capitulations. Both reshaping modes preserve gross per decision and fall back
    to equal weight on a degenerate set.
    """

    base = 1.0 / n_universe
    if weighting == "equal":
        return [base] * len(selections)

    if weighting == "dislocation":
        weights = [
            max(0.0, selection.idiosyncratic) ** dislocation_weight_power
            for selection in selections
        ]
        mean_weight = sum(weights) / len(weights) if weights else 0.0
        if mean_weight <= 0.0:
            return [base] * len(selections)
        return [base * value / mean_weight for value in weights]

    inverse = [
        1.0 / selection.candidate.volatility
        if selection.candidate.volatility
        else None
        for selection in selections
    ]
    known = [value for value in inverse if value is not None]
    if not known:
        return [base] * len(selections)
    fill = sum(known) / len(known)
    inverse = [value if value is not None else fill for value in inverse]
    mean_inverse = sum(inverse) / len(inverse)
    return [base * value / mean_inverse for value in inverse]


def _cross_section_betas(candidates: Sequence[_Candidate]) -> dict[str, float]:
    """Per-name beta proxy to the cross-section: ``name_vol / mean_vol``.

    A vol-ratio proxy for market beta (exact under the high cross-perp
    correlation of crowded regimes). Names or a cross-section with unknown
    volatility fall back to beta 1.0, which reproduces the plain-mean reference.
    """

    known = [candidate.volatility for candidate in candidates if candidate.volatility]
    if not known:
        return {candidate.symbol: 1.0 for candidate in candidates}
    market_vol = sum(known) / len(known)
    if market_vol <= 0.0:
        return {candidate.symbol: 1.0 for candidate in candidates}
    return {
        candidate.symbol: (
            candidate.volatility / market_vol if candidate.volatility else 1.0
        )
        for candidate in candidates
    }


def _dislocation_sigma(
    candidate: _Candidate, return_lookback_minutes: int
) -> float | None:
    """Price extension in units of the name's expected move over the lookback.

    Divides the raw extension by ``per_minute_vol * sqrt(horizon)`` (random-walk
    horizon vol), so a dislocation is measured relative to each name's own
    volatility rather than in absolute bps. Returns ``None`` when volatility is
    unknown or degenerate so the name is excluded from vol-normalized screening.
    """

    if not candidate.volatility:
        return None
    scale_bps = candidate.volatility * math.sqrt(return_lookback_minutes) * 10_000.0
    if scale_bps <= 0.0:
        return None
    return candidate.return_extension_bps / scale_bps


def _cross_section_reference_bps(values: Sequence[float], mode: str) -> float:
    """Cross-section reference extension: the mean, or the robust median.

    ``median`` resists the skew a few co-moving extreme names impose on the mean,
    giving a cleaner "typical move" for the idiosyncratic dislocation.
    """

    if not values:
        return 0.0
    if mode == "median":
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2 == 1:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / 2.0
    return sum(values) / len(values)


def _reference_volatility(selections: Sequence[_Selection]) -> float | None:
    """Mean realized volatility across the selected names, or ``None`` if unknown.

    Used as the reference point for risk-time hold scaling so a name is held
    relative to how volatile it is versus the rest of the selected book.
    """

    known = [
        selection.candidate.volatility
        for selection in selections
        if selection.candidate.volatility
    ]
    if not known:
        return None
    return sum(known) / len(known)


def _scaled_hold_minutes(
    base_hold: int,
    volatility: float | None,
    reference_volatility: float | None,
    scaling: float,
) -> int:
    """Hold length, optionally scaled into risk-time.

    ``scaling == 0`` returns the fixed ``base_hold``. Otherwise the hold is
    ``base_hold * (reference_vol / name_vol) ** scaling`` — higher-vol names are
    held shorter — clamped to ``[_HOLD_MIN_MINUTES, _HOLD_MAX_MINUTES]``. Falls
    back to the fixed hold when either volatility is unknown.
    """

    if scaling <= 0.0 or not volatility or not reference_volatility:
        return base_hold
    scaled = base_hold * (reference_volatility / volatility) ** scaling
    return int(min(_HOLD_MAX_MINUTES, max(_HOLD_MIN_MINUTES, scaled)))


def _reference_idiosyncratic(selections: Sequence[_Selection]) -> float | None:
    """Mean positive idiosyncratic dislocation across the selected names."""

    positive = [
        selection.idiosyncratic
        for selection in selections
        if selection.idiosyncratic > 0.0
    ]
    if not positive:
        return None
    return sum(positive) / len(positive)


def _conviction_scaled_hold(
    base_hold: int,
    idiosyncratic: float,
    reference_idiosyncratic: float | None,
    scaling: float,
) -> int:
    """Hold length scaled by conviction (idiosyncratic dislocation magnitude).

    ``scaling == 0`` returns the fixed ``base_hold``. Otherwise the hold is
    ``base_hold * (idio / reference_idio) ** scaling`` — bigger capitulations are
    held longer for their bigger, slower bounce — clamped to
    ``[_HOLD_MIN_MINUTES, _HOLD_MAX_MINUTES]``. Falls back to the fixed hold when
    the dislocation reference is unknown or non-positive.
    """

    if scaling <= 0.0 or idiosyncratic <= 0.0 or not reference_idiosyncratic:
        return base_hold
    scaled = base_hold * (idiosyncratic / reference_idiosyncratic) ** scaling
    return int(min(_HOLD_MAX_MINUTES, max(_HOLD_MIN_MINUTES, scaled)))


def _score(
    candidate: _Candidate,
    idiosyncratic_dislocation: float,
    selection_score: str,
) -> float:
    funding_score = abs(candidate.funding_pressure_bps)
    extension_score = max(0.0, idiosyncratic_dislocation)
    if selection_score == "funding":
        return funding_score
    if selection_score == "extension":
        return extension_score
    return funding_score + extension_score


def _observations(candidate: _Candidate) -> tuple[ObservationRef, ...]:
    return (
        ObservationRef(
            symbol=candidate.symbol,
            timestamp=candidate.lookback_row.timestamp,
            field="close",
            source="crypto_perp_1min_with_funding",
        ),
        ObservationRef(
            symbol=candidate.symbol,
            timestamp=candidate.signal_row.timestamp,
            field="close",
            source="crypto_perp_1min_with_funding",
        ),
        *(
            (
                ObservationRef(
                    symbol=candidate.symbol,
                    timestamp=candidate.recent_row.timestamp,
                    field="close",
                    source="crypto_perp_1min_with_funding",
                ),
            )
            if candidate.recent_row is not None
            else ()
        ),
        *(
            ObservationRef(
                symbol=candidate.symbol,
                timestamp=event.bar_timestamp,
                field="funding_rate",
                source="crypto_perp_1min_with_funding",
            )
            for event in candidate.funding_events
        ),
    )


def _param_int(params: Mapping[str, object], key: str) -> int:
    return cast(int, params[key])


def _param_float(params: Mapping[str, object], key: str) -> float:
    return cast(float, params[key])


def _param_bool(params: Mapping[str, object], key: str) -> bool:
    return cast(bool, params[key])


def _param_str(params: Mapping[str, object], key: str) -> str:
    return cast(str, params[key])


def _datetime_value(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError(f"{field_name} must be a datetime or ISO string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _finite_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _positive_float(value: object, name: str) -> float:
    parsed = _finite_float(value, name)
    if parsed <= 0.0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _non_negative_float(value: object, name: str) -> float:
    parsed = _finite_float(value, name)
    if parsed < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return parsed


def _int_value(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _positive_int(value: object, name: str) -> int:
    parsed = _int_value(value, name)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _non_negative_int(value: object, name: str) -> int:
    parsed = _int_value(value, name)
    if parsed < 0:
        raise ValueError(f"{name} must be non-negative")
    return parsed


def _hour(value: object, name: str) -> int:
    parsed = _int_value(value, name)
    if parsed < 0 or parsed > 23:
        raise ValueError(f"{name} must be in [0, 23]")
    return parsed


def _session_end_hour(value: object) -> int:
    parsed = _int_value(value, "session_end_hour")
    if parsed < 1 or parsed > 24:
        raise ValueError("session_end_hour must be in [1, 24]")
    return parsed


def _bool_param(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    raise ValueError("has_funding_event must be boolean")


def _selection_score(value: object) -> str:
    parsed = str(value)
    if parsed not in {"combined", "funding", "extension"}:
        raise ValueError("selection_score must be one of: combined, funding, extension")
    return parsed


def _idiosyncratic_mode(value: object) -> str:
    parsed = str(value)
    if parsed not in {"raw", "vol_normalized", "beta_adjusted"}:
        raise ValueError(
            "idiosyncratic_mode must be one of: raw, vol_normalized, beta_adjusted"
        )
    return parsed


def _cross_section_reference(value: object) -> str:
    parsed = str(value)
    if parsed not in {"mean", "median"}:
        raise ValueError("cross_section_reference must be one of: mean, median")
    return parsed


def _weighting(value: object) -> str:
    parsed = str(value)
    if parsed not in {"equal", "inverse_vol", "dislocation"}:
        raise ValueError("weighting must be one of: equal, inverse_vol, dislocation")
    return parsed
