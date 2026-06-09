"""Strategy: fx_session_activity_profile_rejection

Source / provenance:
Internal FX activity-profile hypothesis from docs/research/fx_activity_profile_strategies.md
and FX intraday market-structure evidence including Ito and Hashimoto (2006),
"Intra-day Seasonality in Activities of the Foreign Exchange Markets",
https://www.nber.org/system/files/working_papers/w12413/w12413.pdf, and Cespa,
Gargano, Riddiough, and Sarno (2022), "Foreign Exchange Volume", Review of
Financial Studies, https://doi.org/10.1093/rfs/hhab122.

Market rationale:
The prior Asia session can define an overnight FX balance area. London morning
activity then tests whether price accepts outside that balance or rejects back
inside value. Tick count is used only as quote/update activity, not notional
turnover.

Required observables:
Symbol, timestamp, available_at, OHLC, tick-count volume, bid, ask, mid,
relative spread, and valid quote flag for one-minute FX bars with quotes.

Decision rule:
Build an Asia-session tick-count activity profile, compute POC, 70% value area,
and deterministic HVN/LVN metadata, then trade London-morning acceptance outside
value or failed breaks back inside value after the as-of bar can be observed.

Assumptions:
The `volume` field is an activity proxy, not traded notional; quote fills are
represented by the runner's quote fill model; and all close/profile inputs are
used only after their `available_at` timestamps.

Falsifier:
If this strategy does not beat plain Asia range breakout/reversal baselines
after bid/ask costs and session-window perturbations, reject the activity
profile proxy before tuning richer activity-profile complexity.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta

from quant_strategies.decisions import (
    ExitPolicy,
    InstrumentRef,
    ObservationRef,
    PositionTarget,
    StrategyDecision,
)

__all__ = ["validate_params", "generate_decisions"]

_REQUIRED_FIELDS = {
    "symbol",
    "timestamp",
    "available_at",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "bid",
    "ask",
    "mid",
    "relative_spread",
    "has_quote",
}
_OBSERVATION_FIELDS = ("close", "high", "low", "volume", "relative_spread", "has_quote")
_EXIT_CONTROL_KEYS = ("take_profit_bps", "stop_loss_bps", "trailing_stop_bps")
_PARAM_KEYS = {
    "asia_start_hour",
    "asia_end_hour",
    "decision_start_hour",
    "decision_end_hour",
    "profile_bin_count",
    "value_area_fraction",
    "min_profile_bars",
    "min_activity_observations",
    "activity_window_bars",
    "min_activity_z",
    "max_spread_percentile",
    "acceptance_confirm_bars",
    "rejection_lookback_bars",
    "decision_lag_minutes",
    "enable_acceptance",
    "enable_rejection",
    "use_lvn_boundaries",
    "invert_directions",
    "weight",
    "max_hold_bars",
    *_EXIT_CONTROL_KEYS,
}


def validate_params(params: Mapping[str, object]) -> dict[str, object]:
    _reject_unknown_params(params, _PARAM_KEYS)
    parsed: dict[str, object] = {
        "asia_start_hour": _bounded_int(
            params.get("asia_start_hour", 22), "asia_start_hour", minimum=0, maximum=23
        ),
        "asia_end_hour": _bounded_int(
            params.get("asia_end_hour", 7), "asia_end_hour", minimum=1, maximum=24
        ),
        "decision_start_hour": _bounded_int(
            params.get("decision_start_hour", 7),
            "decision_start_hour",
            minimum=0,
            maximum=23,
        ),
        "decision_end_hour": _bounded_int(
            params.get("decision_end_hour", 10),
            "decision_end_hour",
            minimum=1,
            maximum=24,
        ),
        "profile_bin_count": _bounded_int(
            params.get("profile_bin_count", 40),
            "profile_bin_count",
            minimum=2,
            maximum=500,
        ),
        "value_area_fraction": _bounded_float(
            params.get("value_area_fraction", 0.70),
            "value_area_fraction",
            minimum=0.01,
            maximum=0.99,
        ),
        "min_profile_bars": _positive_int(params.get("min_profile_bars", 360), "min_profile_bars"),
        "min_activity_observations": _positive_int(
            params.get("min_activity_observations", 20),
            "min_activity_observations",
        ),
        "activity_window_bars": _positive_int(
            params.get("activity_window_bars", 120),
            "activity_window_bars",
        ),
        "min_activity_z": _finite_float(params.get("min_activity_z", 1.0), "min_activity_z"),
        "max_spread_percentile": _bounded_float(
            params.get("max_spread_percentile", 0.70),
            "max_spread_percentile",
            minimum=0.0,
            maximum=1.0,
        ),
        "acceptance_confirm_bars": _positive_int(
            params.get("acceptance_confirm_bars", 2),
            "acceptance_confirm_bars",
        ),
        "rejection_lookback_bars": _positive_int(
            params.get("rejection_lookback_bars", 60),
            "rejection_lookback_bars",
        ),
        "decision_lag_minutes": _positive_int(
            params.get("decision_lag_minutes", 1),
            "decision_lag_minutes",
        ),
        "enable_acceptance": _bool_param(
            params.get("enable_acceptance", True), "enable_acceptance"
        ),
        "enable_rejection": _bool_param(params.get("enable_rejection", True), "enable_rejection"),
        "use_lvn_boundaries": _bool_param(
            params.get("use_lvn_boundaries", True),
            "use_lvn_boundaries",
        ),
        "invert_directions": _bool_param(
            params.get("invert_directions", False),
            "invert_directions",
        ),
        "weight": _positive_float(params.get("weight", 0.25), "weight"),
        "max_hold_bars": _positive_int(params.get("max_hold_bars", 180), "max_hold_bars"),
    }
    if int(parsed["asia_end_hour"]) == 24 and int(parsed["asia_start_hour"]) < 24:
        raise ValueError("asia_end_hour=24 is only supported for overnight windows")
    if int(parsed["decision_start_hour"]) >= int(parsed["decision_end_hour"]):
        raise ValueError("decision_end_hour must be greater than decision_start_hour")
    parsed.update(_exit_controls(params))
    return parsed


def generate_decisions(
    rows: Sequence[Mapping[str, object]],
    params: Mapping[str, object],
) -> list[StrategyDecision]:
    if not rows:
        return []
    _require_fields(rows, _REQUIRED_FIELDS)
    parsed = validate_params(params)

    rows_by_symbol = _rows_by_symbol(rows)
    decisions: list[StrategyDecision] = []
    emitted: set[tuple[str, object, str, str]] = set()
    for symbol, symbol_rows in sorted(rows_by_symbol.items()):
        rows_by_date = _rows_by_date(symbol_rows)
        decision_rows_by_date = _decision_rows_by_date(symbol_rows, parsed)
        profile_cache: dict[date, tuple[list[Mapping[str, object]], dict[str, float]] | None] = {}
        for index, row in enumerate(symbol_rows):
            timestamp = _timestamp(row)
            if not _in_hour_window(
                timestamp,
                int(parsed["decision_start_hour"]),
                int(parsed["decision_end_hour"]),
            ):
                continue
            if not _valid_quote(row):
                continue

            profile_key = timestamp.date()
            if profile_key not in profile_cache:
                profile_rows = _profile_rows_from_dates(rows_by_date, timestamp, parsed)
                if len(profile_rows) < int(parsed["min_profile_bars"]):
                    profile_cache[profile_key] = None
                else:
                    profile = _activity_profile(
                        profile_rows,
                        profile_bin_count=int(parsed["profile_bin_count"]),
                        value_area_fraction=float(parsed["value_area_fraction"]),
                    )
                    profile_cache[profile_key] = (
                        None if profile is None else (profile_rows, profile)
                    )
            cached_profile = profile_cache[profile_key]
            if cached_profile is None:
                continue
            profile_rows, profile = cached_profile
            decision_day_rows = decision_rows_by_date.get(profile_key, [])

            if bool(parsed["enable_acceptance"]):
                decisions.extend(
                    _acceptance_decisions(
                        symbol,
                        symbol_rows,
                        decision_day_rows,
                        index,
                        profile_rows,
                        profile,
                        parsed,
                        emitted,
                    )
                )
            if bool(parsed["enable_rejection"]):
                decisions.extend(
                    _rejection_decisions(
                        symbol,
                        symbol_rows,
                        decision_day_rows,
                        index,
                        profile_rows,
                        profile,
                        parsed,
                        emitted,
                    )
                )
    return sorted(decisions, key=lambda item: (item.decision_time, item.instrument.symbol))


def _acceptance_decisions(
    symbol: str,
    rows: Sequence[Mapping[str, object]],
    day_rows: Sequence[Mapping[str, object]],
    index: int,
    profile_rows: Sequence[Mapping[str, object]],
    profile: Mapping[str, float],
    params: Mapping[str, object],
    emitted: set[tuple[str, object, str, str]],
) -> list[StrategyDecision]:
    confirm_bars = int(params["acceptance_confirm_bars"])
    if index + 1 < confirm_bars:
        return []
    sequence = rows[index - confirm_bars + 1 : index + 1]
    if not all(_valid_quote(row) for row in sequence):
        return []
    current = rows[index]
    current_date = _timestamp(current).date()
    previous = rows[index - confirm_bars] if index >= confirm_bars else None
    crossing_row = sequence[0]

    upper_boundary = (
        profile["upper_lvn"]
        if bool(params["use_lvn_boundaries"]) and profile["upper_lvn"] is not None
        else profile["vah"]
    )
    lower_boundary = (
        profile["lower_lvn"]
        if bool(params["use_lvn_boundaries"]) and profile["lower_lvn"] is not None
        else profile["val"]
    )

    direction: str | None = None
    boundary: float | None = None
    if all(float(row["close"]) > upper_boundary for row in sequence) and (
        previous is None or float(previous["close"]) <= upper_boundary
    ):
        direction = "long"
        boundary = upper_boundary
    elif all(float(row["close"]) < lower_boundary for row in sequence) and (
        previous is None or float(previous["close"]) >= lower_boundary
    ):
        direction = "short"
        boundary = lower_boundary
    if direction is None:
        return []

    activity = _activity_signal(day_rows, crossing_row, params)
    if activity is None or activity["zscore"] < float(params["min_activity_z"]):
        return []
    if not _spread_allowed(day_rows, current, params):
        return []

    rule = "acceptance_breakout"
    key = (symbol, current_date, rule, direction)
    if key in emitted:
        return []
    emitted.add(key)
    return [
        _decision(
            symbol,
            direction,
            current,
            profile_rows,
            sequence,
            _decision_context_rows(day_rows, current, params, activity["baseline_rows"]),
            profile,
            activity["zscore"],
            rule,
            params,
            boundary,
        )
    ]


def _rejection_decisions(
    symbol: str,
    rows: Sequence[Mapping[str, object]],
    day_rows: Sequence[Mapping[str, object]],
    index: int,
    profile_rows: Sequence[Mapping[str, object]],
    profile: Mapping[str, float],
    params: Mapping[str, object],
    emitted: set[tuple[str, object, str, str]],
) -> list[StrategyDecision]:
    current = rows[index]
    close = float(current["close"])
    if not profile["val"] <= close <= profile["vah"]:
        return []

    lookback = int(params["rejection_lookback_bars"])
    start = max(0, index - lookback)
    current_time = _timestamp(current)
    recent = [
        row
        for row in rows[start:index]
        if _timestamp(row).date() == current_time.date()
        and _in_hour_window(
            _timestamp(row),
            int(params["decision_start_hour"]),
            int(params["decision_end_hour"]),
        )
    ]
    if not recent:
        return []

    direction: str | None = None
    breach_rows: list[Mapping[str, object]] = []
    breaches: list[tuple[datetime, str, Mapping[str, object]]] = []
    for row in recent:
        if not _valid_quote(row):
            continue
        if float(row["close"]) > profile["vah"]:
            breaches.append((_timestamp(row), "short", row))
        elif float(row["close"]) < profile["val"]:
            breaches.append((_timestamp(row), "long", row))
    if breaches:
        _, direction, latest_breach = max(breaches, key=lambda item: item[0])
        breach_rows = [
            row
            for row in recent
            if (direction == "short" and float(row["close"]) > profile["vah"])
            or (direction == "long" and float(row["close"]) < profile["val"])
        ]
    if direction is None:
        return []

    activity = _activity_signal(day_rows, current, params, baseline_end=_timestamp(latest_breach))
    if activity is None or activity["zscore"] < float(params["min_activity_z"]):
        return []
    if not _spread_allowed(day_rows, current, params):
        return []

    rule = "failed_break_rejection"
    key = (symbol, _timestamp(current).date(), rule, direction)
    if key in emitted:
        return []
    emitted.add(key)
    return [
        _decision(
            symbol,
            direction,
            current,
            profile_rows,
            [*breach_rows, current],
            _decision_context_rows(day_rows, current, params, activity["baseline_rows"]),
            profile,
            activity["zscore"],
            rule,
            params,
            profile["vah"] if direction == "short" else profile["val"],
        )
    ]


def _decision(
    symbol: str,
    direction: str,
    as_of_row: Mapping[str, object],
    profile_rows: Sequence[Mapping[str, object]],
    signal_rows: Sequence[Mapping[str, object]],
    context_rows: Sequence[Mapping[str, object]],
    profile: Mapping[str, float],
    activity_z: float,
    rule: str,
    params: Mapping[str, object],
    boundary: float | None,
) -> StrategyDecision:
    as_of_time = _timestamp(as_of_row)
    decision_time = as_of_time + timedelta(minutes=int(params["decision_lag_minutes"]))
    exit_controls = {name: params[name] for name in _EXIT_CONTROL_KEYS if name in params}
    target_direction = _maybe_invert_direction(direction, params)
    return StrategyDecision(
        strategy_id="fx_session_activity_profile_rejection",
        instrument=InstrumentRef(kind="fx_pair", symbol=symbol),
        decision_time=decision_time,
        as_of_time=as_of_time,
        target=PositionTarget(
            direction=target_direction,
            sizing_kind="target_weight",
            size=float(params["weight"]),
        ),
        exit_policy=ExitPolicy(max_hold_bars=int(params["max_hold_bars"]), **exit_controls),
        observations=_observations(profile_rows, signal_rows, context_rows),
        metadata={
            "signal_family": "fx_session_activity_profile_rejection",
            "rule": rule,
            "session": "london_morning",
            "profile_poc": profile["poc"],
            "profile_vah": profile["vah"],
            "profile_val": profile["val"],
            "profile_upper_lvn": profile["upper_lvn"],
            "profile_lower_lvn": profile["lower_lvn"],
            "profile_upper_hvn": profile["upper_hvn"],
            "profile_lower_hvn": profile["lower_hvn"],
            "profile_boundary": boundary,
            "activity_z": activity_z,
            "relative_spread": float(as_of_row["relative_spread"]),
            "raw_direction": direction,
            "direction_inverted": target_direction != direction,
        },
    )


def _maybe_invert_direction(direction: str, params: Mapping[str, object]) -> str:
    if not bool(params.get("invert_directions", False)):
        return direction
    if direction == "long":
        return "short"
    if direction == "short":
        return "long"
    raise ValueError(f"unsupported direction: {direction}")


def _observations(
    profile_rows: Sequence[Mapping[str, object]],
    signal_rows: Sequence[Mapping[str, object]],
    context_rows: Sequence[Mapping[str, object]],
) -> tuple[ObservationRef, ...]:
    refs: dict[tuple[str, datetime, str], ObservationRef] = {}
    for row in [*profile_rows, *signal_rows, *context_rows]:
        symbol = str(row["symbol"])
        timestamp = _timestamp(row)
        for field in _OBSERVATION_FIELDS:
            refs[(symbol, timestamp, field)] = ObservationRef(
                symbol=symbol,
                timestamp=timestamp,
                field=field,
                source="strategy_input",
            )
    return tuple(refs[key] for key in sorted(refs, key=lambda item: (item[1], item[0], item[2])))


def _profile_rows(
    rows: Sequence[Mapping[str, object]],
    timestamp: datetime,
    params: Mapping[str, object],
) -> list[Mapping[str, object]]:
    return _profile_rows_from_dates(_rows_by_date(rows), timestamp, params)


def _profile_rows_from_dates(
    rows_by_date: Mapping[date, Sequence[Mapping[str, object]]],
    timestamp: datetime,
    params: Mapping[str, object],
) -> list[Mapping[str, object]]:
    asia_start_hour = int(params["asia_start_hour"])
    asia_end_hour = int(params["asia_end_hour"])
    tz = timestamp.tzinfo
    if asia_start_hour >= asia_end_hour:
        start_date = timestamp.date() - timedelta(days=1)
        end_date = timestamp.date()
        session_rows = [
            *rows_by_date.get(start_date, ()),
            *rows_by_date.get(end_date, ()),
        ]
    else:
        start_date = timestamp.date()
        end_date = timestamp.date()
        session_rows = list(rows_by_date.get(start_date, ()))
    start = datetime.combine(start_date, time(asia_start_hour, tzinfo=tz))
    end = datetime.combine(end_date, time(asia_end_hour % 24, tzinfo=tz))
    return [
        row
        for row in session_rows
        if start <= _timestamp(row) < end
        and _timestamp(row) < timestamp
        and _available_at(row) <= timestamp
        and _valid_quote(row)
        and float(row["volume"]) >= 0.0
    ]


def _activity_profile(
    rows: Sequence[Mapping[str, object]],
    *,
    profile_bin_count: int,
    value_area_fraction: float,
) -> dict[str, float] | None:
    lows = [float(row["low"]) for row in rows]
    highs = [float(row["high"]) for row in rows]
    min_price = min(lows)
    max_price = max(highs)
    if not math.isfinite(min_price) or not math.isfinite(max_price):
        return None
    if max_price <= min_price:
        span = max(abs(min_price) * 0.0001, 0.0001)
        min_price -= span
        max_price += span
    width = (max_price - min_price) / profile_bin_count
    volumes = [0.0] * profile_bin_count
    for row in rows:
        low = float(row["low"])
        high = float(row["high"])
        volume = float(row["volume"])
        if volume < 0.0 or not math.isfinite(volume):
            continue
        if high <= low:
            index = _bin_index(float(row["close"]), min_price, width, profile_bin_count)
            volumes[index] += volume
            continue
        row_range = high - low
        for index in range(profile_bin_count):
            bin_low = min_price + index * width
            bin_high = bin_low + width
            overlap = max(0.0, min(high, bin_high) - max(low, bin_low))
            if overlap > 0.0:
                volumes[index] += volume * (overlap / row_range)
    total = sum(volumes)
    if total <= 0.0:
        return None
    poc_index = max(range(profile_bin_count), key=lambda item: (volumes[item], -item))
    low_index = high_index = poc_index
    cumulative = volumes[poc_index]
    target = total * value_area_fraction
    while cumulative < target and (low_index > 0 or high_index < profile_bin_count - 1):
        left_volume = volumes[low_index - 1] if low_index > 0 else -1.0
        right_volume = volumes[high_index + 1] if high_index < profile_bin_count - 1 else -1.0
        if right_volume > left_volume:
            high_index += 1
            cumulative += volumes[high_index]
        else:
            low_index -= 1
            cumulative += volumes[low_index]
    if low_index == high_index and profile_bin_count > 1:
        if low_index > 0:
            low_index -= 1
        if high_index < profile_bin_count - 1:
            high_index += 1
    extrema = _profile_extrema(volumes, poc_index, low_index, high_index, min_price, width)
    return {
        "poc": _bin_center(poc_index, min_price, width),
        "val": _bin_center(low_index, min_price, width),
        "vah": _bin_center(high_index, min_price, width),
        **extrema,
    }


def _profile_extrema(
    volumes: Sequence[float],
    poc_index: int,
    low_index: int,
    high_index: int,
    min_price: float,
    width: float,
) -> dict[str, float | None]:
    lower_indexes = range(0, low_index)
    upper_indexes = range(high_index + 1, len(volumes))
    lower_lvn = _extreme_index(volumes, lower_indexes, highest=False)
    upper_lvn = _extreme_index(volumes, upper_indexes, highest=False)
    lower_hvn = _extreme_index(volumes, range(0, poc_index), highest=True)
    upper_hvn = _extreme_index(volumes, range(poc_index + 1, len(volumes)), highest=True)
    return {
        "lower_lvn": _maybe_bin_center(lower_lvn, min_price, width),
        "upper_lvn": _maybe_bin_center(upper_lvn, min_price, width),
        "lower_hvn": _maybe_bin_center(lower_hvn, min_price, width),
        "upper_hvn": _maybe_bin_center(upper_hvn, min_price, width),
    }


def _extreme_index(
    volumes: Sequence[float],
    indexes: range,
    *,
    highest: bool,
) -> int | None:
    candidates = [index for index in indexes if volumes[index] > 0.0]
    if not candidates:
        candidates = list(indexes)
    if not candidates:
        return None
    if highest:
        return max(candidates, key=lambda index: (volumes[index], -abs(index)))
    return min(candidates, key=lambda index: (volumes[index], abs(index)))


def _activity_signal(
    rows: Sequence[Mapping[str, object]],
    current: Mapping[str, object],
    params: Mapping[str, object],
    *,
    baseline_end: datetime | None = None,
) -> dict[str, object] | None:
    current_time = _timestamp(current)
    baseline_cutoff = baseline_end or current_time
    prior = [
        row
        for row in rows
        if row["symbol"] == current["symbol"]
        and _timestamp(row) < baseline_cutoff
        and _timestamp(row).date() == current_time.date()
        and _in_hour_window(
            _timestamp(row),
            int(params["decision_start_hour"]),
            int(params["decision_end_hour"]),
        )
    ][-int(params["activity_window_bars"]) :]
    if len(prior) < int(params["min_activity_observations"]):
        return None
    values = [float(row["volume"]) for row in prior]
    current_volume = float(current["volume"])
    if (
        not math.isfinite(current_volume)
        or current_volume < 0.0
        or not all(math.isfinite(value) and value >= 0.0 for value in values)
    ):
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    stdev = math.sqrt(variance)
    if stdev <= 1e-12:
        return None
    zscore = (current_volume - mean) / stdev
    if not math.isfinite(zscore):
        return None
    return {"zscore": zscore, "baseline_rows": tuple(prior)}


def _decision_context_rows(
    rows: Sequence[Mapping[str, object]],
    current: Mapping[str, object],
    params: Mapping[str, object],
    activity_baseline_rows: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    current_time = _timestamp(current)
    context = [
        row
        for row in rows
        if row["symbol"] == current["symbol"]
        and _timestamp(row).date() == current_time.date()
        and _timestamp(row) <= current_time
        and _in_hour_window(
            _timestamp(row),
            int(params["decision_start_hour"]),
            int(params["decision_end_hour"]),
        )
    ][-int(params["activity_window_bars"]) :]
    by_key = {(_timestamp(row), str(row["symbol"])): row for row in context}
    for row in activity_baseline_rows:
        by_key.setdefault((_timestamp(row), str(row["symbol"])), row)
    return [by_key[key] for key in sorted(by_key)]


def _spread_allowed(
    rows: Sequence[Mapping[str, object]],
    current: Mapping[str, object],
    params: Mapping[str, object],
) -> bool:
    if not _valid_quote(current):
        return False
    current_time = _timestamp(current)
    prior_spreads = [
        float(row["relative_spread"])
        for row in rows
        if row["symbol"] == current["symbol"]
        and _timestamp(row) < current_time
        and _timestamp(row).date() == current_time.date()
        and _in_hour_window(
            _timestamp(row),
            int(params["decision_start_hour"]),
            int(params["decision_end_hour"]),
        )
        and _valid_quote(row)
    ][-int(params["activity_window_bars"]) :]
    if not prior_spreads:
        percentile = 0.0
    else:
        percentile = sum(1 for value in prior_spreads if value < float(current["relative_spread"]))
        percentile /= len(prior_spreads)
    return percentile <= float(params["max_spread_percentile"])


def _rows_by_symbol(rows: Sequence[Mapping[str, object]]) -> dict[str, list[Mapping[str, object]]]:
    grouped: dict[str, list[Mapping[str, object]]] = {}
    seen: set[tuple[str, datetime]] = set()
    for row in rows:
        symbol = str(row["symbol"])
        timestamp = _timestamp(row)
        key = (symbol, timestamp)
        if key in seen:
            raise ValueError(f"duplicate symbol/timestamp row: {symbol} {timestamp.isoformat()}")
        seen.add(key)
        grouped.setdefault(symbol, []).append(row)
    return {symbol: sorted(items, key=_timestamp) for symbol, items in grouped.items()}


def _rows_by_date(rows: Sequence[Mapping[str, object]]) -> dict[date, list[Mapping[str, object]]]:
    grouped: dict[date, list[Mapping[str, object]]] = {}
    for row in rows:
        grouped.setdefault(_timestamp(row).date(), []).append(row)
    return {key: sorted(items, key=_timestamp) for key, items in grouped.items()}


def _decision_rows_by_date(
    rows: Sequence[Mapping[str, object]],
    params: Mapping[str, object],
) -> dict[date, list[Mapping[str, object]]]:
    grouped: dict[date, list[Mapping[str, object]]] = {}
    start_hour = int(params["decision_start_hour"])
    end_hour = int(params["decision_end_hour"])
    for row in rows:
        timestamp = _timestamp(row)
        if _in_hour_window(timestamp, start_hour, end_hour):
            grouped.setdefault(timestamp.date(), []).append(row)
    return {key: sorted(items, key=_timestamp) for key, items in grouped.items()}


def _valid_quote(row: Mapping[str, object]) -> bool:
    return (
        row.get("has_quote") is True
        and _finite_positive_value(row.get("bid"))
        and _finite_positive_value(row.get("ask"))
        and _finite_positive_value(row.get("mid"))
        and _finite_non_negative_value(row.get("relative_spread"))
        and float(row["ask"]) > float(row["bid"])
    )


def _in_hour_window(timestamp: datetime, start_hour: int, end_hour: int) -> bool:
    hour = timestamp.hour + timestamp.minute / 60.0
    return start_hour <= hour < end_hour


def _timestamp(row: Mapping[str, object]) -> datetime:
    value = row["timestamp"]
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware datetime")
    return value


def _available_at(row: Mapping[str, object]) -> datetime:
    value = row["available_at"]
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("available_at must be timezone-aware datetime")
    return value


def _bin_index(price: float, min_price: float, width: float, count: int) -> int:
    return min(max(int((price - min_price) / width), 0), count - 1)


def _bin_center(index: int, min_price: float, width: float) -> float:
    return min_price + (index + 0.5) * width


def _maybe_bin_center(index: int | None, min_price: float, width: float) -> float | None:
    if index is None:
        return None
    return _bin_center(index, min_price, width)


def _require_fields(rows: Sequence[Mapping[str, object]], required: set[str]) -> None:
    for index, row in enumerate(rows):
        missing = required.difference(row.keys())
        if missing:
            raise ValueError(f"bar {index} missing required fields: {sorted(missing)}")


def _reject_unknown_params(params: Mapping[str, object], allowed: set[str]) -> None:
    unknown = sorted(set(params).difference(allowed))
    if unknown:
        raise ValueError(f"unknown params: {', '.join(unknown)}")


def _positive_int(value: object, name: str) -> int:
    parsed = _integer(value, name)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _non_negative_int(value: object, name: str) -> int:
    parsed = _integer(value, name)
    if parsed < 0:
        raise ValueError(f"{name} must be non-negative")
    return parsed


def _bounded_int(value: object, name: str, *, minimum: int, maximum: int) -> int:
    parsed = _integer(value, name)
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not math.isfinite(parsed) or not parsed.is_integer():
        raise ValueError(f"{name} must be an integer")
    return int(parsed)


def _bool_param(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a bool")
    return value


def _positive_float(value: object, name: str) -> float:
    parsed = _finite_float(value, name)
    if parsed <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return parsed


def _finite_float(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _bounded_float(value: object, name: str, *, minimum: float, maximum: float) -> float:
    parsed = _finite_float(value, name)
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _exit_controls(params: Mapping[str, object]) -> dict[str, float]:
    controls: dict[str, float] = {}
    for name in _EXIT_CONTROL_KEYS:
        if name in params:
            controls[name] = _positive_float(params[name], name)
    return controls


def _finite_positive_value(value: object) -> bool:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(parsed) and parsed > 0.0


def _finite_non_negative_value(value: object) -> bool:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(parsed) and parsed >= 0.0
