"""Strategy: crypto_perp_funding_carry_tilt

Source / provenance:
Cross-sectional perpetual funding-carry tilt: rank the perp universe by trailing
realized funding and go short the richest-funding names (longs pay) / long the
cheapest (shorts pay), collecting funding as financing. Schmeling, Schrimpf &
Todorov, "Crypto Carry", BIS Working Papers No. 1087 (2023) / Management Science
2024 (https://www.bis.org/publ/work1087.pdf; ssrn 4268371); He, Manela, Ross & von
Wachter, "Fundamentals of Perpetual Futures", arXiv:2212.06888
(https://arxiv.org/abs/2212.06888). Data fit, conditional-harvest and
beta-neutrality framing:
internal_note: docs/research/crypto/README.md candidate #2 and
docs/research/crypto/01_funding_and_basis.md section 1. Known deviation:
single-venue realized funding is a proxy for the industry OI-weighted composite.

Market rationale:
Perpetual funding is a persistent limits-to-arbitrage premium leveraged longs pay
for convenient leverage; the residual edge after flagship carry is arbitraged away
lives in the alt cross-section and the wide right tail of funding, so harvest is
conditional on the funding cross-section being richly dispersed. High-funding
names are typically high-beta pumping alts, so a naive short-high / long-low book
is a disguised short-beta bet; beta-neutralizing the legs isolates the carry.

Required observables:
Symbol, timezone-aware bar timestamp, available_at, and close for crypto perpetual
bars, plus funding_timestamp, funding_rate, and has_funding_event from the
crypto_perp_1min_with_funding dataset. A row is used only when its available_at is
at or before the emitted decision_time. Funding cashflow itself is applied by the
engine as financing on the net position under the crypto_perp_funding data kind.

Decision rule:
On a fixed funding-aligned rebalance clock, for each name average the last
funding_lookback_events realized funding settlements into a carry level. Trade only
when the cross-sectional spread between the top and bottom carry quantile exceeds
min_funding_spread_bps; otherwise flatten the book and sit out. Short the top
quantile by carry and long the bottom quantile; weight within each leg equally or
by inverse realized volatility, scaled so total gross equals gross_budget. With
beta_neutralize the two legs' gross is split so the inverse-vol-weighted net beta
against the equal-weight universe is zero (trading exact dollar-neutrality for zero
net beta); otherwise the legs are dollar-neutral. Emit one signed weight-of-NAV
target per selected name and a zero target to close any name dropped from the
book, so the standing cross-section rebalances by netting.

Assumptions:
Input bars are timezone-aware and ordered by causal availability through
available_at; a funding settlement is usable only once its available_at is at or
before the shared decision_time (the cross-section's latest signal-bar
availability plus decision_lag_minutes). Beta is a trailing regression of each
name's returns on the equal-weight universe return sampled hourly over the
volatility lookback, falling back to one when degenerate. A zero target that closes
a dropped name is a policy exit and declares no observation.

Falsifier:
If net return after realistic costs and ADV/impact capacity is not positive out of
sample, if the edge vanishes once the legs are beta-neutralized (it was short-beta,
not carry), if the richness gate never binds (unconditional harvest equals gated
harvest, so there is no timing edge), or if turnover cost on the thin alt short leg
exceeds the collected spread, reject the thesis rather than adding filters.
"""

import math
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from quant_strategies.decisions import (
    InstrumentRef,
    ObservationRef,
    TargetDecision,
)

__all__ = ["generate_decisions", "validate_params"]

_STRATEGY_ID = "crypto_perp_funding_carry_tilt"
_SOURCE = "crypto_perp_1min_with_funding"
_REQUIRED_FIELDS = {
    "symbol",
    "timestamp",
    "available_at",
    "close",
    "funding_timestamp",
    "funding_rate",
    "has_funding_event",
}
_BETA_SAMPLE_MINUTES = 60
_DEFAULT_PARAMS: dict[str, object] = {
    "funding_lookback_events": 3,
    "quantile_frac": 0.20,
    "weighting": "inv_vol",
    "beta_neutralize": True,
    "rebalance_hours": 8,
    "min_funding_spread_bps": 0.5,
    "min_cross_section": 6,
    "vol_lookback_minutes": 1440,
    "gross_budget": 1.0,
    "decision_lag_minutes": 1,
}


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
    carry_bps: float
    funding_events: tuple[_FundingEvent, ...]
    volatility: float | None


@dataclass(frozen=True)
class _Selection:
    candidate: _Candidate
    side: int
    target: float


def validate_params(params: Mapping[str, object]) -> dict[str, object]:
    """Validate the bounded funding-carry-tilt parameters."""

    unknown = set(params) - set(_DEFAULT_PARAMS)
    if unknown:
        raise ValueError(f"unknown params: {sorted(unknown)}")

    merged = {**_DEFAULT_PARAMS, **dict(params)}
    validated: dict[str, object] = {
        "funding_lookback_events": _positive_int(
            merged["funding_lookback_events"], "funding_lookback_events"
        ),
        "quantile_frac": _quantile_frac(merged["quantile_frac"]),
        "weighting": _weighting(merged["weighting"]),
        "beta_neutralize": _bool_param(merged["beta_neutralize"], "beta_neutralize"),
        "rebalance_hours": _rebalance_hours(merged["rebalance_hours"]),
        "min_funding_spread_bps": _non_negative_float(
            merged["min_funding_spread_bps"], "min_funding_spread_bps"
        ),
        "min_cross_section": _positive_int(merged["min_cross_section"], "min_cross_section"),
        "vol_lookback_minutes": _positive_int(
            merged["vol_lookback_minutes"], "vol_lookback_minutes"
        ),
        "gross_budget": _positive_float(merged["gross_budget"], "gross_budget"),
        "decision_lag_minutes": _non_negative_int(
            merged["decision_lag_minutes"], "decision_lag_minutes"
        ),
    }
    if _param_int(validated, "min_cross_section") < 2:
        raise ValueError("min_cross_section must be >= 2 for a long-short book")
    return validated


def generate_decisions(
    bars: Sequence[Mapping[str, object]], params: Mapping[str, object]
) -> list[TargetDecision]:
    """Emit standing cross-sectional funding-carry-tilt target decisions."""

    if not bars:
        return []
    validated = validate_params(params)
    rows_by_symbol = _rows_by_symbol(bars)
    if len(rows_by_symbol) < _param_int(validated, "min_cross_section"):
        return []

    signal_times = _rebalance_times(rows_by_symbol, _param_int(validated, "rebalance_hours"))
    lag = _param_int(validated, "decision_lag_minutes")
    active: set[str] = set()
    decisions: list[TargetDecision] = []

    for signal_time in signal_times:
        candidates = _candidates_at_signal_time(rows_by_symbol, signal_time, validated)
        cross_section_available_at = (
            max(candidate.signal_row.available_at for candidate in candidates)
            if candidates
            else None
        )
        selections = (
            _select_and_size(candidates, rows_by_symbol, signal_time, validated)
            if len(candidates) >= _param_int(validated, "min_cross_section")
            else []
        )

        if not selections:
            # No tradeable book this rebalance: flatten anything still held.
            if active and cross_section_available_at is not None:
                decision_time = cross_section_available_at + timedelta(minutes=lag)
                for symbol in sorted(active):
                    decisions.append(
                        _flat_decision(symbol, decision_time, cross_section_available_at)
                    )
                active = set()
            continue

        assert cross_section_available_at is not None
        decision_time = cross_section_available_at + timedelta(minutes=lag)
        selected_symbols = {selection.candidate.symbol for selection in selections}
        for symbol in sorted(active - selected_symbols):
            decisions.append(_flat_decision(symbol, decision_time, cross_section_available_at))
        for selection in selections:
            candidate = selection.candidate
            decisions.append(
                TargetDecision(
                    strategy_id=_STRATEGY_ID,
                    instrument=InstrumentRef(kind="crypto_perp", symbol=candidate.symbol),
                    decision_time=decision_time,
                    as_of_time=candidate.signal_row.timestamp,
                    target=selection.target,
                    observations=_observations(candidate),
                    metadata={
                        "signal_family": _STRATEGY_ID,
                        "carry_bps": candidate.carry_bps,
                        "side": "long" if selection.side > 0 else "short",
                    },
                )
            )
        active = selected_symbols

    return sorted(
        decisions,
        key=lambda decision: (
            decision.decision_time,
            decision.instrument.symbol,
            decision.target,
        ),
    )


def _flat_decision(symbol: str, decision_time: datetime, as_of_time: datetime) -> TargetDecision:
    return TargetDecision(
        strategy_id=_STRATEGY_ID,
        instrument=InstrumentRef(kind="crypto_perp", symbol=symbol),
        decision_time=decision_time,
        as_of_time=as_of_time,
        target=0.0,
        metadata={"exit_reason": "deselected"},
    )


def _candidates_at_signal_time(
    rows_by_symbol: Mapping[str, _SymbolRows],
    signal_time: datetime,
    params: Mapping[str, object],
) -> list[_Candidate]:
    lookback_events = _param_int(params, "funding_lookback_events")
    vol_lookback_minutes = _param_int(params, "vol_lookback_minutes")
    candidates: list[_Candidate] = []
    for rows in rows_by_symbol.values():
        signal_index = bisect_right(rows.timestamps, signal_time) - 1
        if signal_index < 0:
            continue
        signal_row = rows.bars[signal_index]
        funding_index = bisect_right(rows.funding_available_at, signal_row.available_at)
        if funding_index < lookback_events:
            continue
        events = rows.funding_events[funding_index - lookback_events : funding_index]
        carry_bps = sum(event.rate for event in events) / len(events) * 10_000.0
        candidates.append(
            _Candidate(
                symbol=signal_row.symbol,
                signal_row=signal_row,
                carry_bps=carry_bps,
                funding_events=events,
                volatility=_realized_volatility(rows, signal_index, vol_lookback_minutes),
            )
        )
    return candidates


def _select_and_size(
    candidates: Sequence[_Candidate],
    rows_by_symbol: Mapping[str, _SymbolRows],
    signal_time: datetime,
    params: Mapping[str, object],
) -> list[_Selection]:
    """Pick the carry quantiles and size the two legs into signed targets.

    Returns an empty list when the universe cannot form disjoint quantiles or the
    cross-sectional funding spread is below the richness gate, which the caller
    treats as "flatten and sit out".
    """

    ranked = sorted(candidates, key=lambda candidate: candidate.carry_bps, reverse=True)
    n = len(ranked)
    quantile_frac = _param_float(params, "quantile_frac")
    k = max(1, int(quantile_frac * n))
    k = min(k, n // 2)
    if k < 1:
        return []

    shorts = ranked[:k]
    longs = ranked[n - k :]
    spread_bps = _leg_mean_carry(shorts) - _leg_mean_carry(longs)
    if spread_bps < _param_float(params, "min_funding_spread_bps"):
        return []

    weighting = _param_str(params, "weighting")
    long_weights = _leg_weights(longs, weighting)
    short_weights = _leg_weights(shorts, weighting)

    gross_budget = _param_float(params, "gross_budget")
    gross_long, gross_short = _leg_gross_split(
        longs=longs,
        shorts=shorts,
        long_weights=long_weights,
        short_weights=short_weights,
        gross_budget=gross_budget,
        beta_neutralize=_param_bool(params, "beta_neutralize"),
        betas=(
            _regression_betas(
                rows_by_symbol,
                [candidate.symbol for candidate in ranked],
                signal_time,
                _param_int(params, "vol_lookback_minutes"),
            )
            if _param_bool(params, "beta_neutralize")
            else None
        ),
    )

    selections: list[_Selection] = []
    for candidate, weight in zip(longs, long_weights):
        selections.append(_Selection(candidate=candidate, side=1, target=gross_long * weight))
    for candidate, weight in zip(shorts, short_weights):
        selections.append(_Selection(candidate=candidate, side=-1, target=-gross_short * weight))
    return selections


def _leg_mean_carry(leg: Sequence[_Candidate]) -> float:
    return sum(candidate.carry_bps for candidate in leg) / len(leg)


def _leg_weights(leg: Sequence[_Candidate], weighting: str) -> list[float]:
    """Within-leg weights summing to 1: equal, or inverse realized volatility.

    Inverse-vol reshapes the leg toward risk parity; names with unknown volatility
    take the leg's mean inverse-vol, and a degenerate leg falls back to equal.
    """

    count = len(leg)
    if weighting == "equal":
        return [1.0 / count] * count
    inverse = [1.0 / candidate.volatility if candidate.volatility else None for candidate in leg]
    known = [value for value in inverse if value is not None]
    if not known:
        return [1.0 / count] * count
    fill = sum(known) / len(known)
    filled = [value if value is not None else fill for value in inverse]
    total = sum(filled)
    return [value / total for value in filled]


def _leg_gross_split(
    *,
    longs: Sequence[_Candidate],
    shorts: Sequence[_Candidate],
    long_weights: Sequence[float],
    short_weights: Sequence[float],
    gross_budget: float,
    beta_neutralize: bool,
    betas: Mapping[str, float] | None,
) -> tuple[float, float]:
    """Gross budget split across the long and short legs.

    Dollar-neutral (equal halves) unless ``beta_neutralize`` is set and both legs
    have positive weighted beta, in which case the split zeroes the inverse-vol-
    weighted net beta (``gross_long * beta_long == gross_short * beta_short``).
    """

    half = gross_budget / 2.0
    if not beta_neutralize or betas is None:
        return half, half
    beta_long = sum(
        weight * betas.get(candidate.symbol, 1.0) for candidate, weight in zip(longs, long_weights)
    )
    beta_short = sum(
        weight * betas.get(candidate.symbol, 1.0)
        for candidate, weight in zip(shorts, short_weights)
    )
    if beta_long <= 0.0 or beta_short <= 0.0:
        return half, half
    gross_long = gross_budget * beta_short / (beta_long + beta_short)
    gross_short = gross_budget * beta_long / (beta_long + beta_short)
    return gross_long, gross_short


def _regression_betas(
    rows_by_symbol: Mapping[str, _SymbolRows],
    symbols: Sequence[str],
    signal_time: datetime,
    lookback_minutes: int,
) -> dict[str, float]:
    """Trailing beta of each name's return on the equal-weight universe return.

    Returns are sampled every ``_BETA_SAMPLE_MINUTES`` over the lookback ending at
    the signal time (causal: each sample is the last close at or before the sample
    time). The market is the equal-weight cross-section of the sampled names.
    Names with too little history, or a degenerate market, get beta 1.0.
    """

    steps = lookback_minutes // _BETA_SAMPLE_MINUTES
    default = dict.fromkeys(symbols, 1.0)
    if steps < 4:
        return default
    sample_times = [
        signal_time - timedelta(minutes=_BETA_SAMPLE_MINUTES * i) for i in range(steps, -1, -1)
    ]
    returns: dict[str, list[float]] = {}
    for symbol in symbols:
        rows = rows_by_symbol[symbol]
        closes: list[float] = []
        for sample_time in sample_times:
            index = bisect_right(rows.timestamps, sample_time) - 1
            if index < 0:
                closes = []
                break
            closes.append(rows.bars[index].close)
        if len(closes) >= 4:
            returns[symbol] = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]
    if len(returns) < 2:
        return default
    length = min(len(series) for series in returns.values())
    if length < 3:
        return default
    trimmed = {symbol: series[-length:] for symbol, series in returns.items()}
    market = [sum(series[k] for series in trimmed.values()) / len(trimmed) for k in range(length)]
    market_mean = sum(market) / length
    market_var = sum((value - market_mean) ** 2 for value in market) / (length - 1)
    if market_var <= 0.0:
        return default
    betas: dict[str, float] = {}
    for symbol in symbols:
        series = trimmed.get(symbol)
        if series is None:
            betas[symbol] = 1.0
            continue
        series_mean = sum(series) / length
        covariance = sum(
            (series[k] - series_mean) * (market[k] - market_mean) for k in range(length)
        ) / (length - 1)
        betas[symbol] = covariance / market_var
    return betas


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
    returns = [window[i].close / window[i - 1].close - 1.0 for i in range(1, len(window))]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    vol = math.sqrt(variance)
    return vol if vol > 0.0 else None


def _rebalance_times(
    rows_by_symbol: Mapping[str, _SymbolRows], rebalance_hours: int
) -> tuple[datetime, ...]:
    """Funding-aligned rebalance clock firing every ``rebalance_hours`` hours.

    Uses the union of bar timestamps so the clock only fires where data exists;
    with ``rebalance_hours == 8`` this lands on the 00:00 / 08:00 / 16:00 UTC
    funding settlements.
    """

    interval = rebalance_hours * 60
    times = {
        timestamp
        for rows in rows_by_symbol.values()
        for timestamp in rows.timestamps
        if (timestamp.hour * 60 + timestamp.minute) % interval == 0
    }
    return tuple(sorted(times))


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
        grouped_bars.setdefault(symbol, []).append(
            _BarRow(
                symbol=symbol,
                timestamp=timestamp,
                available_at=available_at,
                close=_positive_float(bar["close"], "close"),
            )
        )
        if _bool_value(bar["has_funding_event"]):
            grouped_funding.setdefault(symbol, []).append(
                _FundingEvent(
                    timestamp=_datetime_value(bar["funding_timestamp"], "funding_timestamp"),
                    bar_timestamp=timestamp,
                    available_at=available_at,
                    rate=_finite_float(bar["funding_rate"], "funding_rate"),
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


def _observations(candidate: _Candidate) -> tuple[ObservationRef, ...]:
    return (
        ObservationRef(
            symbol=candidate.symbol,
            timestamp=candidate.signal_row.timestamp,
            field="close",
            source=_SOURCE,
        ),
        *(
            ObservationRef(
                symbol=candidate.symbol,
                timestamp=event.bar_timestamp,
                field="funding_rate",
                source=_SOURCE,
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
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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


def _quantile_frac(value: object) -> float:
    parsed = _finite_float(value, "quantile_frac")
    if not 0.0 < parsed <= 0.5:
        raise ValueError("quantile_frac must be in (0, 0.5]")
    return parsed


def _weighting(value: object) -> str:
    parsed = str(value)
    if parsed not in {"equal", "inv_vol"}:
        raise ValueError("weighting must be one of: equal, inv_vol")
    return parsed


def _rebalance_hours(value: object) -> int:
    parsed = _int_value(value, "rebalance_hours")
    if parsed < 1 or parsed > 24 or 24 % parsed != 0:
        raise ValueError("rebalance_hours must be a positive divisor of 24")
    return parsed
