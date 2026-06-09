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
_SIGNAL_MODES = {
    "profile_value_test",
    "asia_range_sweep_reversal",
    "two_stage_sweep_retest",
    "sweep_mid_reclaim",
    "asia_range_acceptance",
    "value_reentry_poc_magnet",
    "opening_drive_failure",
    "opening_drive_continuation",
    "poc_reclaim",
    "inside_value_rotation",
}
_RANGE_FILTERS = {"any", "compressed", "wide"}
_PAIR_GROUPS = {"all", "xxxusd", "usdbase"}
_LONDON_PHASES = {"all", "sweep", "acceptance", "cleanup"}
_EXIT_MODELS = {"fixed_bps", "range_fraction", "poc_target", "asia_mid_target", "opposite_value_target"}
_PARAM_KEYS = {
    "signal_mode",
    "range_filter",
    "pair_group",
    "london_phase",
    "exit_model",
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
    "setup_lookback_bars",
    "opening_drive_bars",
    "break_buffer_bps",
    "min_distance_to_poc_bps",
    "asia_range_min_bps",
    "asia_range_max_bps",
    "require_activity",
    "require_spread_filter",
    "target_range_fraction",
    "stop_range_fraction",
    "min_take_profit_bps",
    "min_stop_loss_bps",
    "max_take_profit_bps",
    "max_stop_loss_bps",
    "stop_buffer_bps",
    "weight",
    "max_hold_bars",
    *_EXIT_CONTROL_KEYS,
}


def validate_params(params: Mapping[str, object]) -> dict[str, object]:
    _reject_unknown_params(params, _PARAM_KEYS)
    signal_mode = str(params.get("signal_mode", "profile_value_test"))
    if signal_mode not in _SIGNAL_MODES:
        raise ValueError(f"signal_mode must be one of: {', '.join(sorted(_SIGNAL_MODES))}")
    range_filter = str(params.get("range_filter", "any"))
    if range_filter not in _RANGE_FILTERS:
        raise ValueError(f"range_filter must be one of: {', '.join(sorted(_RANGE_FILTERS))}")
    pair_group = str(params.get("pair_group", "all"))
    if pair_group not in _PAIR_GROUPS:
        raise ValueError(f"pair_group must be one of: {', '.join(sorted(_PAIR_GROUPS))}")
    london_phase = str(params.get("london_phase", "all"))
    if london_phase not in _LONDON_PHASES:
        raise ValueError(f"london_phase must be one of: {', '.join(sorted(_LONDON_PHASES))}")
    exit_model = str(params.get("exit_model", "fixed_bps"))
    if exit_model not in _EXIT_MODELS:
        raise ValueError(f"exit_model must be one of: {', '.join(sorted(_EXIT_MODELS))}")
    parsed: dict[str, object] = {
        "signal_mode": signal_mode,
        "range_filter": range_filter,
        "pair_group": pair_group,
        "london_phase": london_phase,
        "exit_model": exit_model,
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
        "setup_lookback_bars": _positive_int(
            params.get("setup_lookback_bars", 60),
            "setup_lookback_bars",
        ),
        "opening_drive_bars": _positive_int(
            params.get("opening_drive_bars", 30),
            "opening_drive_bars",
        ),
        "break_buffer_bps": _non_negative_float(
            params.get("break_buffer_bps", 0.0),
            "break_buffer_bps",
        ),
        "min_distance_to_poc_bps": _non_negative_float(
            params.get("min_distance_to_poc_bps", 0.0),
            "min_distance_to_poc_bps",
        ),
        "asia_range_min_bps": _non_negative_float(
            params.get("asia_range_min_bps", 0.0),
            "asia_range_min_bps",
        ),
        "asia_range_max_bps": _non_negative_float(
            params.get("asia_range_max_bps", 10_000.0),
            "asia_range_max_bps",
        ),
        "require_activity": _bool_param(
            params.get("require_activity", True),
            "require_activity",
        ),
        "require_spread_filter": _bool_param(
            params.get("require_spread_filter", True),
            "require_spread_filter",
        ),
        "target_range_fraction": _positive_float(
            params.get("target_range_fraction", 0.5),
            "target_range_fraction",
        ),
        "stop_range_fraction": _positive_float(
            params.get("stop_range_fraction", 0.35),
            "stop_range_fraction",
        ),
        "min_take_profit_bps": _positive_float(
            params.get("min_take_profit_bps", 3.0),
            "min_take_profit_bps",
        ),
        "min_stop_loss_bps": _positive_float(
            params.get("min_stop_loss_bps", 3.0),
            "min_stop_loss_bps",
        ),
        "max_take_profit_bps": _positive_float(
            params.get("max_take_profit_bps", 80.0),
            "max_take_profit_bps",
        ),
        "max_stop_loss_bps": _positive_float(
            params.get("max_stop_loss_bps", 80.0),
            "max_stop_loss_bps",
        ),
        "stop_buffer_bps": _non_negative_float(
            params.get("stop_buffer_bps", 1.0),
            "stop_buffer_bps",
        ),
        "weight": _positive_float(params.get("weight", 0.25), "weight"),
        "max_hold_bars": _positive_int(params.get("max_hold_bars", 180), "max_hold_bars"),
    }
    if int(parsed["asia_end_hour"]) == 24 and int(parsed["asia_start_hour"]) < 24:
        raise ValueError("asia_end_hour=24 is only supported for overnight windows")
    if int(parsed["decision_start_hour"]) >= int(parsed["decision_end_hour"]):
        raise ValueError("decision_end_hour must be greater than decision_start_hour")
    if float(parsed["asia_range_min_bps"]) > float(parsed["asia_range_max_bps"]):
        raise ValueError("asia_range_min_bps must be <= asia_range_max_bps")
    if float(parsed["min_take_profit_bps"]) > float(parsed["max_take_profit_bps"]):
        raise ValueError("min_take_profit_bps must be <= max_take_profit_bps")
    if float(parsed["min_stop_loss_bps"]) > float(parsed["max_stop_loss_bps"]):
        raise ValueError("min_stop_loss_bps must be <= max_stop_loss_bps")
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
    if str(parsed["signal_mode"]) != "profile_value_test":
        return _generate_structural_decisions(rows, parsed)

    rows_by_symbol = _rows_by_symbol(rows)
    decisions: list[StrategyDecision] = []
    emitted: set[tuple[str, object, str, str]] = set()
    for symbol, symbol_rows in sorted(rows_by_symbol.items()):
        if not _pair_allowed(symbol, parsed):
            continue
        decision_timestamps = {_timestamp(item) for item in symbol_rows}
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
            if not _phase_allowed(timestamp, parsed):
                continue
            if not _valid_quote(row):
                continue
            if _decision_timestamp(row, parsed) not in decision_timestamps:
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


def _generate_structural_decisions(
    rows: Sequence[Mapping[str, object]],
    params: Mapping[str, object],
) -> list[StrategyDecision]:
    rows_by_symbol = _rows_by_symbol(rows)
    decisions: list[StrategyDecision] = []
    emitted: set[tuple[str, object, str, str]] = set()
    for symbol, symbol_rows in sorted(rows_by_symbol.items()):
        if not _pair_allowed(symbol, params):
            continue
        decision_timestamps = {_timestamp(item) for item in symbol_rows}
        rows_by_date = _rows_by_date(symbol_rows)
        decision_rows_by_date = _decision_rows_by_date(symbol_rows, params)
        profile_cache: dict[date, tuple[list[Mapping[str, object]], dict[str, float]] | None] = {}
        index_by_key = {(_timestamp(row), str(row["symbol"])): index for index, row in enumerate(symbol_rows)}
        for current in symbol_rows:
            timestamp = _timestamp(current)
            if not _in_hour_window(
                timestamp,
                int(params["decision_start_hour"]),
                int(params["decision_end_hour"]),
            ):
                continue
            if not _phase_allowed(timestamp, params):
                continue
            if not _valid_quote(current):
                continue
            if _decision_timestamp(current, params) not in decision_timestamps:
                continue

            profile_key = timestamp.date()
            if profile_key not in profile_cache:
                profile_cache[profile_key] = _session_profile(rows_by_date, timestamp, params)
            cached_profile = profile_cache[profile_key]
            if cached_profile is None:
                continue
            profile_rows, profile = cached_profile
            if not _range_filter_allowed(profile, params):
                continue

            decision_day_rows = decision_rows_by_date.get(profile_key, [])
            if not decision_day_rows:
                continue
            index = index_by_key[(timestamp, symbol)]
            structural = _structural_decision(
                symbol,
                symbol_rows,
                decision_day_rows,
                index,
                profile_rows,
                profile,
                params,
                emitted,
            )
            if structural is not None:
                decisions.append(structural)
    return sorted(decisions, key=lambda item: (item.decision_time, item.instrument.symbol))


def _session_profile(
    rows_by_date: Mapping[date, Sequence[Mapping[str, object]]],
    timestamp: datetime,
    params: Mapping[str, object],
) -> tuple[list[Mapping[str, object]], dict[str, float]] | None:
    profile_rows = _profile_rows_from_dates(rows_by_date, timestamp, params)
    if len(profile_rows) < int(params["min_profile_bars"]):
        return None
    profile = _activity_profile(
        profile_rows,
        profile_bin_count=int(params["profile_bin_count"]),
        value_area_fraction=float(params["value_area_fraction"]),
    )
    if profile is None:
        return None
    asia_high = max(float(row["high"]) for row in profile_rows)
    asia_low = min(float(row["low"]) for row in profile_rows)
    asia_mid = (asia_high + asia_low) / 2.0
    if asia_high <= asia_low or asia_mid <= 0.0:
        return None
    enriched = {
        **profile,
        "asia_high": asia_high,
        "asia_low": asia_low,
        "asia_mid": asia_mid,
        "asia_range_bps": (asia_high - asia_low) / asia_mid * 10_000.0,
    }
    return profile_rows, enriched


def _range_filter_allowed(profile: Mapping[str, float], params: Mapping[str, object]) -> bool:
    range_bps = float(profile["asia_range_bps"])
    if range_bps < float(params["asia_range_min_bps"]):
        return False
    if range_bps > float(params["asia_range_max_bps"]):
        return False
    mode = str(params["range_filter"])
    if mode == "compressed":
        return range_bps <= float(params["asia_range_max_bps"])
    if mode == "wide":
        return range_bps >= float(params["asia_range_min_bps"])
    return True


def _structural_decision(
    symbol: str,
    rows: Sequence[Mapping[str, object]],
    day_rows: Sequence[Mapping[str, object]],
    index: int,
    profile_rows: Sequence[Mapping[str, object]],
    profile: Mapping[str, float],
    params: Mapping[str, object],
    emitted: set[tuple[str, object, str, str]],
) -> StrategyDecision | None:
    mode = str(params["signal_mode"])
    current = rows[index]
    if mode == "asia_range_sweep_reversal":
        return _asia_range_sweep_reversal(
            symbol, rows, day_rows, index, profile_rows, profile, params, emitted
        )
    if mode == "two_stage_sweep_retest":
        return _two_stage_sweep_retest(
            symbol, rows, day_rows, index, profile_rows, profile, params, emitted
        )
    if mode == "sweep_mid_reclaim":
        return _sweep_mid_reclaim(
            symbol, rows, day_rows, index, profile_rows, profile, params, emitted
        )
    if mode == "asia_range_acceptance":
        return _asia_range_acceptance(
            symbol, rows, day_rows, index, profile_rows, profile, params, emitted
        )
    if mode == "value_reentry_poc_magnet":
        return _value_reentry_poc_magnet(
            symbol, rows, day_rows, index, profile_rows, profile, params, emitted
        )
    if mode == "opening_drive_failure":
        return _opening_drive_failure(
            symbol, day_rows, current, profile_rows, profile, params, emitted
        )
    if mode == "opening_drive_continuation":
        return _opening_drive_continuation(
            symbol, day_rows, current, profile_rows, profile, params, emitted
        )
    if mode == "poc_reclaim":
        return _poc_reclaim(symbol, day_rows, current, profile_rows, profile, params, emitted)
    if mode == "inside_value_rotation":
        return _inside_value_rotation(
            symbol, day_rows, current, profile_rows, profile, params, emitted
        )
    raise ValueError(f"unsupported structural mode: {mode}")


def _asia_range_sweep_reversal(
    symbol: str,
    rows: Sequence[Mapping[str, object]],
    day_rows: Sequence[Mapping[str, object]],
    index: int,
    profile_rows: Sequence[Mapping[str, object]],
    profile: Mapping[str, float],
    params: Mapping[str, object],
    emitted: set[tuple[str, object, str, str]],
) -> StrategyDecision | None:
    current = rows[index]
    close = float(current["close"])
    high_boundary = _buffer_up(float(profile["asia_high"]), params)
    low_boundary = _buffer_down(float(profile["asia_low"]), params)
    recent = _recent_rows(rows, index, params)
    direction: str | None = None
    boundary: float | None = None
    if recent and max(float(row["high"]) for row in recent) > high_boundary and close < float(profile["asia_high"]):
        direction = "short"
        boundary = float(profile["asia_high"])
    elif recent and min(float(row["low"]) for row in recent) < low_boundary and close > float(profile["asia_low"]):
        direction = "long"
        boundary = float(profile["asia_low"])
    if direction is None:
        return None
    return _structural_emit(
        symbol, direction, "asia_range_sweep_reversal", current, profile_rows, recent, day_rows, profile, params, emitted, boundary
    )


def _two_stage_sweep_retest(
    symbol: str,
    rows: Sequence[Mapping[str, object]],
    day_rows: Sequence[Mapping[str, object]],
    index: int,
    profile_rows: Sequence[Mapping[str, object]],
    profile: Mapping[str, float],
    params: Mapping[str, object],
    emitted: set[tuple[str, object, str, str]],
) -> StrategyDecision | None:
    current = rows[index]
    recent = _recent_rows(rows, index, params)
    sweep = _latest_sweep(recent, profile, params)
    if sweep is None:
        return None
    side, sweep_index = sweep
    post_sweep = [*recent[sweep_index + 1 :], current]
    if len(post_sweep) < 3:
        return None
    direction: str | None = None
    boundary: float | None = None
    if side == "high":
        reentered = any(float(row["close"]) < float(profile["asia_high"]) for row in post_sweep[:-1])
        retested = any(float(row["high"]) >= float(profile["asia_high"]) for row in post_sweep[1:-1])
        failed_now = float(current["close"]) < float(profile["asia_high"])
        if reentered and retested and failed_now:
            direction = "short"
            boundary = float(profile["asia_high"])
    elif side == "low":
        reentered = any(float(row["close"]) > float(profile["asia_low"]) for row in post_sweep[:-1])
        retested = any(float(row["low"]) <= float(profile["asia_low"]) for row in post_sweep[1:-1])
        failed_now = float(current["close"]) > float(profile["asia_low"])
        if reentered and retested and failed_now:
            direction = "long"
            boundary = float(profile["asia_low"])
    if direction is None:
        return None
    return _structural_emit(
        symbol,
        direction,
        "two_stage_sweep_retest",
        current,
        profile_rows,
        post_sweep,
        day_rows,
        profile,
        params,
        emitted,
        boundary,
    )


def _sweep_mid_reclaim(
    symbol: str,
    rows: Sequence[Mapping[str, object]],
    day_rows: Sequence[Mapping[str, object]],
    index: int,
    profile_rows: Sequence[Mapping[str, object]],
    profile: Mapping[str, float],
    params: Mapping[str, object],
    emitted: set[tuple[str, object, str, str]],
) -> StrategyDecision | None:
    current = rows[index]
    previous = rows[index - 1] if index > 0 and _timestamp(rows[index - 1]).date() == _timestamp(current).date() else None
    if previous is None:
        return None
    recent = _recent_rows(rows, index, params)
    sweep = _latest_sweep(recent, profile, params)
    if sweep is None:
        return None
    side, sweep_index = sweep
    post_sweep = [*recent[sweep_index + 1 :], current]
    mid = float(profile["asia_mid"])
    direction: str | None = None
    boundary: float | None = None
    if side == "high" and float(previous["close"]) >= mid > float(current["close"]):
        direction = "short"
        boundary = float(profile["asia_high"])
    elif side == "low" and float(previous["close"]) <= mid < float(current["close"]):
        direction = "long"
        boundary = float(profile["asia_low"])
    if direction is None:
        return None
    return _structural_emit(
        symbol,
        direction,
        "sweep_mid_reclaim",
        current,
        profile_rows,
        post_sweep,
        day_rows,
        profile,
        params,
        emitted,
        boundary,
    )


def _asia_range_acceptance(
    symbol: str,
    rows: Sequence[Mapping[str, object]],
    day_rows: Sequence[Mapping[str, object]],
    index: int,
    profile_rows: Sequence[Mapping[str, object]],
    profile: Mapping[str, float],
    params: Mapping[str, object],
    emitted: set[tuple[str, object, str, str]],
) -> StrategyDecision | None:
    confirm = int(params["acceptance_confirm_bars"])
    if index + 1 < confirm:
        return None
    sequence = rows[index - confirm + 1 : index + 1]
    if not all(_valid_quote(row) for row in sequence):
        return None
    high_boundary = _buffer_up(float(profile["asia_high"]), params)
    low_boundary = _buffer_down(float(profile["asia_low"]), params)
    direction: str | None = None
    boundary: float | None = None
    if all(float(row["close"]) > high_boundary for row in sequence):
        direction = "long"
        boundary = float(profile["asia_high"])
    elif all(float(row["close"]) < low_boundary for row in sequence):
        direction = "short"
        boundary = float(profile["asia_low"])
    if direction is None:
        return None
    return _structural_emit(
        symbol, direction, "asia_range_acceptance", rows[index], profile_rows, sequence, day_rows, profile, params, emitted, boundary
    )


def _value_reentry_poc_magnet(
    symbol: str,
    rows: Sequence[Mapping[str, object]],
    day_rows: Sequence[Mapping[str, object]],
    index: int,
    profile_rows: Sequence[Mapping[str, object]],
    profile: Mapping[str, float],
    params: Mapping[str, object],
    emitted: set[tuple[str, object, str, str]],
) -> StrategyDecision | None:
    current = rows[index]
    close = float(current["close"])
    if not float(profile["val"]) <= close <= float(profile["vah"]):
        return None
    if _distance_bps(close, float(profile["poc"])) < float(params["min_distance_to_poc_bps"]):
        return None
    recent = _recent_rows(rows, index, params)
    direction: str | None = None
    boundary: float | None = None
    if recent and max(float(row["high"]) for row in recent) > float(profile["vah"]) and close > float(profile["poc"]):
        direction = "short"
        boundary = float(profile["vah"])
    elif recent and min(float(row["low"]) for row in recent) < float(profile["val"]) and close < float(profile["poc"]):
        direction = "long"
        boundary = float(profile["val"])
    if direction is None:
        return None
    return _structural_emit(
        symbol, direction, "value_reentry_poc_magnet", current, profile_rows, recent, day_rows, profile, params, emitted, boundary
    )


def _opening_drive_failure(
    symbol: str,
    day_rows: Sequence[Mapping[str, object]],
    current: Mapping[str, object],
    profile_rows: Sequence[Mapping[str, object]],
    profile: Mapping[str, float],
    params: Mapping[str, object],
    emitted: set[tuple[str, object, str, str]],
) -> StrategyDecision | None:
    opening, after_open = _opening_context(day_rows, current, params)
    if opening is None or not after_open:
        return None
    opening_high = max(float(row["high"]) for row in opening)
    opening_low = min(float(row["low"]) for row in opening)
    close = float(current["close"])
    direction: str | None = None
    boundary: float | None = None
    if opening_high > _buffer_up(float(profile["asia_high"]), params) and close < opening_low:
        direction = "short"
        boundary = opening_low
    elif opening_low < _buffer_down(float(profile["asia_low"]), params) and close > opening_high:
        direction = "long"
        boundary = opening_high
    if direction is None:
        return None
    return _structural_emit(
        symbol, direction, "opening_drive_failure", current, profile_rows, [*opening, *after_open], day_rows, profile, params, emitted, boundary
    )


def _opening_drive_continuation(
    symbol: str,
    day_rows: Sequence[Mapping[str, object]],
    current: Mapping[str, object],
    profile_rows: Sequence[Mapping[str, object]],
    profile: Mapping[str, float],
    params: Mapping[str, object],
    emitted: set[tuple[str, object, str, str]],
) -> StrategyDecision | None:
    opening, after_open = _opening_context(day_rows, current, params)
    if opening is None or not after_open:
        return None
    opening_high = max(float(row["high"]) for row in opening)
    opening_low = min(float(row["low"]) for row in opening)
    close = float(current["close"])
    direction: str | None = None
    boundary: float | None = None
    if opening_high > _buffer_up(float(profile["asia_high"]), params) and close > opening_high:
        direction = "long"
        boundary = opening_high
    elif opening_low < _buffer_down(float(profile["asia_low"]), params) and close < opening_low:
        direction = "short"
        boundary = opening_low
    if direction is None:
        return None
    return _structural_emit(
        symbol, direction, "opening_drive_continuation", current, profile_rows, [*opening, *after_open], day_rows, profile, params, emitted, boundary
    )


def _poc_reclaim(
    symbol: str,
    day_rows: Sequence[Mapping[str, object]],
    current: Mapping[str, object],
    profile_rows: Sequence[Mapping[str, object]],
    profile: Mapping[str, float],
    params: Mapping[str, object],
    emitted: set[tuple[str, object, str, str]],
) -> StrategyDecision | None:
    previous = _previous_day_row(day_rows, current)
    if previous is None:
        return None
    poc = float(profile["poc"])
    direction: str | None = None
    if float(previous["close"]) <= poc < float(current["close"]):
        direction = "long"
    elif float(previous["close"]) >= poc > float(current["close"]):
        direction = "short"
    if direction is None:
        return None
    return _structural_emit(
        symbol, direction, "poc_reclaim", current, profile_rows, [previous, current], day_rows, profile, params, emitted, poc
    )


def _inside_value_rotation(
    symbol: str,
    day_rows: Sequence[Mapping[str, object]],
    current: Mapping[str, object],
    profile_rows: Sequence[Mapping[str, object]],
    profile: Mapping[str, float],
    params: Mapping[str, object],
    emitted: set[tuple[str, object, str, str]],
) -> StrategyDecision | None:
    previous = _previous_day_row(day_rows, current)
    if previous is None:
        return None
    close = float(current["close"])
    if not float(profile["val"]) <= close <= float(profile["vah"]):
        return None
    poc = float(profile["poc"])
    direction: str | None = None
    if float(previous["close"]) <= poc < close:
        direction = "long"
    elif float(previous["close"]) >= poc > close:
        direction = "short"
    if direction is None:
        return None
    return _structural_emit(
        symbol, direction, "inside_value_rotation", current, profile_rows, [previous, current], day_rows, profile, params, emitted, poc
    )


def _structural_emit(
    symbol: str,
    direction: str,
    rule: str,
    current: Mapping[str, object],
    profile_rows: Sequence[Mapping[str, object]],
    signal_rows: Sequence[Mapping[str, object]],
    day_rows: Sequence[Mapping[str, object]],
    profile: Mapping[str, float],
    params: Mapping[str, object],
    emitted: set[tuple[str, object, str, str]],
    boundary: float | None,
) -> StrategyDecision | None:
    if bool(params["require_activity"]):
        activity = _activity_signal(day_rows, current, params)
        if activity is None or float(activity["zscore"]) < float(params["min_activity_z"]):
            return None
        activity_z = float(activity["zscore"])
        context_rows = _decision_context_rows(day_rows, current, params, activity["baseline_rows"])
    else:
        activity_z = 0.0
        context_rows = _decision_context_rows(day_rows, current, params, ())
    if bool(params["require_spread_filter"]) and not _spread_allowed(day_rows, current, params):
        return None
    key = (symbol, _timestamp(current).date(), rule, direction)
    if key in emitted:
        return None
    emitted.add(key)
    exit_controls = _structural_exit_controls(direction, current, profile, params, boundary)
    return _decision(
        symbol,
        direction,
        current,
        profile_rows,
        signal_rows,
        context_rows,
        profile,
        activity_z,
        rule,
        params,
        boundary,
        exit_controls,
    )


def _recent_rows(
    rows: Sequence[Mapping[str, object]],
    index: int,
    params: Mapping[str, object],
) -> list[Mapping[str, object]]:
    current_time = _timestamp(rows[index])
    start = max(0, index - int(params["setup_lookback_bars"]))
    return [
        row
        for row in rows[start:index]
        if _timestamp(row).date() == current_time.date()
        and _in_hour_window(
            _timestamp(row),
            int(params["decision_start_hour"]),
            int(params["decision_end_hour"]),
        )
        and _valid_quote(row)
    ]


def _latest_sweep(
    recent: Sequence[Mapping[str, object]],
    profile: Mapping[str, float],
    params: Mapping[str, object],
) -> tuple[str, int] | None:
    high_boundary = _buffer_up(float(profile["asia_high"]), params)
    low_boundary = _buffer_down(float(profile["asia_low"]), params)
    candidates: list[tuple[datetime, str, int]] = []
    for index, row in enumerate(recent):
        if float(row["high"]) > high_boundary:
            candidates.append((_timestamp(row), "high", index))
        if float(row["low"]) < low_boundary:
            candidates.append((_timestamp(row), "low", index))
    if not candidates:
        return None
    _, side, index = max(candidates, key=lambda item: item[0])
    return side, index


def _pair_allowed(symbol: str, params: Mapping[str, object]) -> bool:
    group = str(params.get("pair_group", "all"))
    if group == "all":
        return True
    if group == "xxxusd":
        return symbol.endswith("USD") and not symbol.startswith("USD")
    if group == "usdbase":
        return symbol.startswith("USD")
    raise ValueError(f"unsupported pair_group: {group}")


def _phase_allowed(timestamp: datetime, params: Mapping[str, object]) -> bool:
    phase = str(params.get("london_phase", "all"))
    hour = timestamp.hour + timestamp.minute / 60.0
    if phase == "all":
        return True
    if phase == "sweep":
        return 7.0 <= hour < 8.0
    if phase == "acceptance":
        return 8.0 <= hour < 9.0
    if phase == "cleanup":
        return 9.0 <= hour < 10.0
    raise ValueError(f"unsupported london_phase: {phase}")


def _structural_exit_controls(
    direction: str,
    current: Mapping[str, object],
    profile: Mapping[str, float],
    params: Mapping[str, object],
    boundary: float | None,
) -> dict[str, float]:
    model = str(params.get("exit_model", "fixed_bps"))
    if model == "fixed_bps":
        return _exit_controls(params)
    range_bps = float(profile["asia_range_bps"])
    fallback_target = range_bps * float(params["target_range_fraction"])
    fallback_stop = range_bps * float(params["stop_range_fraction"])
    close = float(current["close"])
    target_bps = fallback_target
    stop_bps = fallback_stop
    if model in {"poc_target", "asia_mid_target", "opposite_value_target"}:
        target_level = _target_level(direction, profile, model)
        candidate_target = _favorable_distance_bps(direction, close, target_level)
        if candidate_target is not None:
            target_bps = candidate_target
        candidate_stop = _stop_distance_bps(direction, close, boundary, params)
        if candidate_stop is not None:
            stop_bps = candidate_stop
    elif model != "range_fraction":
        raise ValueError(f"unsupported exit_model: {model}")
    return {
        "take_profit_bps": _clamp(
            target_bps,
            float(params["min_take_profit_bps"]),
            float(params["max_take_profit_bps"]),
        ),
        "stop_loss_bps": _clamp(
            stop_bps,
            float(params["min_stop_loss_bps"]),
            float(params["max_stop_loss_bps"]),
        ),
    }


def _target_level(direction: str, profile: Mapping[str, float], model: str) -> float:
    if model == "poc_target":
        return float(profile["poc"])
    if model == "asia_mid_target":
        return float(profile["asia_mid"])
    if model == "opposite_value_target":
        return float(profile["vah"] if direction == "long" else profile["val"])
    raise ValueError(f"unsupported target model: {model}")


def _favorable_distance_bps(direction: str, close: float, target: float) -> float | None:
    if direction == "long" and target > close:
        return _distance_bps(close, target)
    if direction == "short" and target < close:
        return _distance_bps(close, target)
    return None


def _stop_distance_bps(
    direction: str,
    close: float,
    boundary: float | None,
    params: Mapping[str, object],
) -> float | None:
    if boundary is None:
        return None
    if direction == "long":
        stop_level = boundary * (1.0 - float(params["stop_buffer_bps"]) / 10_000.0)
        if stop_level < close:
            return _distance_bps(close, stop_level)
    if direction == "short":
        stop_level = boundary * (1.0 + float(params["stop_buffer_bps"]) / 10_000.0)
        if stop_level > close:
            return _distance_bps(close, stop_level)
    return None


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def _opening_context(
    day_rows: Sequence[Mapping[str, object]],
    current: Mapping[str, object],
    params: Mapping[str, object],
) -> tuple[list[Mapping[str, object]] | None, list[Mapping[str, object]]]:
    prior = [row for row in day_rows if _timestamp(row) <= _timestamp(current) and _valid_quote(row)]
    opening_count = int(params["opening_drive_bars"])
    if len(prior) <= opening_count:
        return None, []
    return prior[:opening_count], prior[opening_count:]


def _previous_day_row(
    day_rows: Sequence[Mapping[str, object]],
    current: Mapping[str, object],
) -> Mapping[str, object] | None:
    previous = [row for row in day_rows if _timestamp(row) < _timestamp(current) and _valid_quote(row)]
    if not previous:
        return None
    return previous[-1]


def _buffer_up(price: float, params: Mapping[str, object]) -> float:
    return price * (1.0 + float(params["break_buffer_bps"]) / 10_000.0)


def _buffer_down(price: float, params: Mapping[str, object]) -> float:
    return price * (1.0 - float(params["break_buffer_bps"]) / 10_000.0)


def _distance_bps(left: float, right: float) -> float:
    midpoint = (abs(left) + abs(right)) / 2.0
    if midpoint <= 0.0:
        return 0.0
    return abs(left - right) / midpoint * 10_000.0


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
    exit_controls_override: Mapping[str, float] | None = None,
) -> StrategyDecision:
    as_of_time = _timestamp(as_of_row)
    decision_time = _decision_timestamp(as_of_row, params)
    exit_controls = (
        dict(exit_controls_override)
        if exit_controls_override is not None
        else {name: params[name] for name in _EXIT_CONTROL_KEYS if name in params}
    )
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
            "exit_model": str(params.get("exit_model", "fixed_bps")),
            "take_profit_bps": exit_controls.get("take_profit_bps"),
            "stop_loss_bps": exit_controls.get("stop_loss_bps"),
        },
    )


def _decision_timestamp(row: Mapping[str, object], params: Mapping[str, object]) -> datetime:
    return _timestamp(row) + timedelta(minutes=int(params["decision_lag_minutes"]))


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


def _non_negative_float(value: object, name: str) -> float:
    parsed = _finite_float(value, name)
    if parsed < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
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
