"""Strategy: crypto_perp_funding_crowding_reversal_stateful_rebalance

Source / provenance:
Internal crowding-reversal hypothesis derived from crypto perpetual futures
funding-rate mechanism literature, especially Ackerer, Hugonnier, and Jermann
(2024), "Perpetual Futures Pricing", NBER Working Paper 32936, DOI
10.3386/w32936, and Zhang (2026), "Funding Rate Mechanism in Perpetual
Futures", SSRN 6185958, DOI 10.2139/ssrn.6185958. This file is not a direct
paper replication.

Market rationale:
Recent same-direction perpetual funding pressure and price extension can mark
crowded positioning that mean-reverts over the next configured max holding
window. Repeated same-symbol signals are state updates, not independent trade
tickets, so this bench variant suppresses new same-symbol entries until the
active target window has exited.

Required observables:
Symbol, timestamp, close, funding timestamp, funding rate, and funding-event
flag for crypto perpetual bars.

Signal rule:
On a sparse as-of cadence, use completed prior closes and funding events at or
before the as-of time. Emit decisions after the as-of bar can be observed. Short
the strongest positive funding plus positive return tail, and optionally long
the strongest negative funding plus negative return tail. This simplified
variant trades repeated long tranches when summed recent funding pressure is
negative enough and price has extended down. It concentrates exposure in the
higher-edge non-BTC long book, uses a 100-minute cadence, requires stronger
funding pressure only during market-wide selloff regimes, and lets DOGE/LINK/ETH
hold longer than ADA to test whether higher-edge symbols have a slower
mean-reversion payoff. ADA remains the 8-hour coverage sleeve.

Assumptions:
Funding timestamps are known no later than the as-of time, market data
availability is represented by the runner's `available_at` field when present,
and the completed prior close rather than the as-of close drives return
extension.

Falsifier:
If explicit same-symbol state suppression removes the broad candidate's edge or
leaves too few trades for the sample gate, the old result was likely an
overlapping-ticket artifact rather than a tradable rebalance rule.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
import math
from typing import Any

from quant_strategies.decisions import ExitPolicy, InstrumentRef, ObservationRef, PositionTarget, StrategyDecision

__all__ = ["validate_params", "generate_decisions"]

_STRATEGY_ID = "crypto_perp_funding_crowding_reversal_stateful_rebalance"
_REQUIRED_FIELDS = {"symbol", "timestamp", "close", "funding_timestamp", "funding_rate", "has_funding_event"}
_EXCLUDED_LONG_SYMBOLS = frozenset({"BTC-PERP"})
_EXTENDED_HOLD_LONG_SYMBOLS = frozenset({"DOGE-PERP", "ETH-PERP", "LINK-PERP"})
_LONG_WEIGHT_MULTIPLIER = 1.5
_ADA_LATEST_NEGATIVE_FUNDING_BPS = 0.25


class _SymbolRows:
    __slots__ = (
        "timestamps",
        "timestamp_to_index",
        "closes_by_timestamp",
        "conflicting_close_timestamps",
        "funding_event_rows",
        "funding_event_times",
        "latest_timestamp",
    )

    def __init__(
        self,
        *,
        timestamps: tuple[datetime, ...],
        timestamp_to_index: dict[datetime, int],
        closes_by_timestamp: dict[datetime, float],
        conflicting_close_timestamps: frozenset[datetime],
        funding_event_rows: tuple[tuple[datetime, datetime, float], ...],
        funding_event_times: tuple[datetime, ...],
        latest_timestamp: datetime,
    ) -> None:
        self.timestamps = timestamps
        self.timestamp_to_index = timestamp_to_index
        self.closes_by_timestamp = closes_by_timestamp
        self.conflicting_close_timestamps = conflicting_close_timestamps
        self.funding_event_rows = funding_event_rows
        self.funding_event_times = funding_event_times
        self.latest_timestamp = latest_timestamp


def validate_params(params: Mapping[str, object]) -> dict[str, object]:
    validated = dict(params)
    _validate_scalar_params(validated)
    return validated


def _generate_signal_payloads(
    bars: Sequence[Mapping[str, object]],
    params: Mapping[str, object],
) -> list[dict[str, object]]:
    if not bars:
        return []
    _require_fields(bars, _REQUIRED_FIELDS)
    _validate_scalar_params(params)

    funding_lookback_events = _positive_int(params.get("funding_lookback_events", 3), "funding_lookback_events")
    return_lookback_minutes = _positive_int(params.get("return_lookback_minutes", 240), "return_lookback_minutes")
    decision_interval_minutes = _positive_int(params.get("decision_interval_minutes", 480), "decision_interval_minutes")
    decision_lag_minutes = _non_negative_int(params.get("decision_lag_minutes", 1), "decision_lag_minutes")
    top_n = _positive_int(params.get("top_n", 1), "top_n")
    min_cross_section = _positive_int(params.get("min_cross_section", 4), "min_cross_section")
    min_abs_funding_bps = _non_negative_float(params.get("min_abs_funding_bps", 1.0), "min_abs_funding_bps")
    min_abs_return_bps = _non_negative_float(params.get("min_abs_return_bps", 25.0), "min_abs_return_bps")
    max_short_return_extension_bps = _non_negative_float(
        params.get("max_short_return_extension_bps", 0.0),
        "max_short_return_extension_bps",
    )
    include_positive_funding_shorts = _bool_param(
        params.get("include_positive_funding_shorts", True),
        "include_positive_funding_shorts",
    )
    include_negative_funding_longs = _bool_param(
        params.get("include_negative_funding_longs", True),
        "include_negative_funding_longs",
    )
    min_same_sign_funding_events = _non_negative_int(
        params.get("min_same_sign_funding_events", 0),
        "min_same_sign_funding_events",
    )
    min_latest_abs_funding_bps = _non_negative_float(
        params.get("min_latest_abs_funding_bps", 0.0),
        "min_latest_abs_funding_bps",
    )
    volatility_lookback_minutes = _non_negative_int(
        params.get("volatility_lookback_minutes", 0),
        "volatility_lookback_minutes",
    )
    min_abs_return_z = _non_negative_float(params.get("min_abs_return_z", 0.0), "min_abs_return_z")
    recent_return_lookback_minutes = _non_negative_int(
        params.get("recent_return_lookback_minutes", 0),
        "recent_return_lookback_minutes",
    )
    max_recent_same_direction_return_bps = _non_negative_float(
        params.get("max_recent_same_direction_return_bps", 0.0),
        "max_recent_same_direction_return_bps",
    )
    min_idiosyncratic_return_bps = _non_negative_float(
        params.get("min_idiosyncratic_return_bps", 0.0),
        "min_idiosyncratic_return_bps",
    )
    min_short_idiosyncratic_return_bps = _non_negative_float(
        params.get("min_short_idiosyncratic_return_bps", min_idiosyncratic_return_bps),
        "min_short_idiosyncratic_return_bps",
    )
    min_long_idiosyncratic_return_bps = _non_negative_float(
        params.get("min_long_idiosyncratic_return_bps", min_idiosyncratic_return_bps),
        "min_long_idiosyncratic_return_bps",
    )
    symbol_cooldown_minutes = _non_negative_int(
        params.get("symbol_cooldown_minutes", 0),
        "symbol_cooldown_minutes",
    )
    min_tail_count = _positive_int(params.get("min_tail_count", 1), "min_tail_count")
    balance_sides = _bool_param(params.get("balance_sides", False), "balance_sides")
    selection_score = str(params.get("selection_score", "funding"))
    if selection_score not in {"funding", "return", "product"}:
        raise ValueError("selection_score must be one of: funding, return, product")
    require_exit_horizon = _bool_param(params.get("require_exit_horizon", False), "require_exit_horizon")
    weight = float(params.get("weight", 1.0))
    hold_bars = _positive_int(params.get("hold_bars", params.get("hold_minutes", 480)), "hold_bars")
    short_hold_bars = _positive_int(params.get("short_hold_bars", hold_bars), "short_hold_bars")
    long_hold_bars = _positive_int(params.get("long_hold_bars", hold_bars), "long_hold_bars")
    high_extension_short_return_bps = _non_negative_float(
        params.get("high_extension_short_return_bps", 0.0),
        "high_extension_short_return_bps",
    )
    high_extension_short_hold_bars = _positive_int(
        params.get("high_extension_short_hold_bars", short_hold_bars),
        "high_extension_short_hold_bars",
    )
    state_mode = str(params.get("state_mode", "suppress_until_exit"))
    if state_mode not in {"off", "suppress_until_exit"}:
        raise ValueError("state_mode must be one of: off, suppress_until_exit")
    overlap_exit_buffer_bars = _non_negative_int(
        params.get("overlap_exit_buffer_bars", 2),
        "overlap_exit_buffer_bars",
    )
    exit_controls = _exit_controls(params)
    required_exit_horizon_bars = max(
        short_hold_bars,
        long_hold_bars,
        high_extension_short_hold_bars if high_extension_short_return_bps > 0.0 else short_hold_bars,
    )

    rows_by_symbol = _rows_by_symbol(bars, need_timestamp_index=require_exit_horizon)
    as_of_times = sorted(
        {
            timestamp
            for rows in rows_by_symbol.values()
            for timestamp in rows.timestamps
            if _is_long_decision_time(timestamp, decision_interval_minutes, params)
        }
    )

    signals: list[dict[str, object]] = []
    last_signal_time_by_symbol: dict[str, datetime] = {}
    active_until_by_symbol: dict[str, datetime] = {}
    for as_of_time in as_of_times:
        candidates = _decision_candidates(
            rows_by_symbol,
            as_of_time,
            funding_lookback_events,
            return_lookback_minutes,
            volatility_lookback_minutes,
            recent_return_lookback_minutes,
        )
        if len(candidates) < min_cross_section:
            continue
        market_return_bps = sum(candidate["return_extension_bps"] for candidate in candidates) / len(candidates)
        decision_time = as_of_time + timedelta(minutes=decision_lag_minutes)
        candidates = _filter_exit_horizon(
            candidates,
            rows_by_symbol,
            decision_time,
            required_exit_horizon_bars,
            require_exit_horizon,
        )

        positive_tail = [
            candidate
            for candidate in candidates
            if include_positive_funding_shorts
            and candidate["funding_pressure_bps"] >= min_abs_funding_bps
            and candidate["return_extension_bps"] >= min_abs_return_bps
            and _passes_max_short_return_extension(candidate, max_short_return_extension_bps)
            and candidate["funding_same_sign_events"] >= min_same_sign_funding_events
            and abs(candidate["latest_funding_bps"]) >= min_latest_abs_funding_bps
            and _passes_return_z(candidate, min_abs_return_z)
            and _passes_recent_cooloff(candidate, "short", max_recent_same_direction_return_bps)
            and _passes_idiosyncratic_return(candidate, "short", market_return_bps, min_short_idiosyncratic_return_bps)
        ]
        negative_tail = [
            candidate
            for candidate in candidates
            if _passes_long_funding_pressure(candidate, _regime_funding_threshold(min_abs_funding_bps, market_return_bps))
            and candidate["return_extension_bps"] <= -min_abs_return_bps
            and abs(candidate["latest_funding_bps"]) >= min_latest_abs_funding_bps
            and _passes_return_z(candidate, min_abs_return_z)
            and _passes_recent_cooloff(candidate, "long", max_recent_same_direction_return_bps)
            and _passes_idiosyncratic_return(candidate, "long", market_return_bps, min_long_idiosyncratic_return_bps)
            and candidate["symbol"] not in _EXCLUDED_LONG_SYMBOLS
            and _passes_symbol_latest_funding(candidate)
        ]
        if len(positive_tail) < min_tail_count:
            positive_tail = []
        if len(negative_tail) < min_tail_count:
            negative_tail = []

        selected_shorts: list[dict[str, Any]] = []
        selected_longs = _selected_tail(negative_tail, "long", selection_score, top_n) if include_negative_funding_longs else []
        selected_longs = [
            candidate
            for candidate in selected_longs
            if _passes_symbol_session_start_gate(candidate["symbol"], as_of_time, params)
        ]
        if balance_sides:
            balanced_count = min(len(selected_shorts), len(selected_longs))
            selected_shorts = selected_shorts[:balanced_count]
            selected_longs = selected_longs[:balanced_count]

        for candidate in selected_shorts:
            hold = _candidate_hold_bars(
                candidate,
                "short",
                short_hold_bars,
                long_hold_bars,
                high_extension_short_return_bps,
                high_extension_short_hold_bars,
            )
            if _passes_symbol_cooldown(
                candidate["symbol"],
                decision_time,
                last_signal_time_by_symbol,
                symbol_cooldown_minutes,
            ) and _passes_state_gate(
                candidate["symbol"],
                decision_time,
                active_until_by_symbol,
                state_mode,
            ):
                signals.append(
                    _signal(
                        candidate,
                        decision_time,
                        as_of_time,
                        "short",
                        weight,
                        hold,
                        exit_controls,
                        state_mode,
                    )
                )
                last_signal_time_by_symbol[candidate["symbol"]] = decision_time
                _record_active_window(
                    candidate["symbol"],
                    decision_time,
                    max(hold, short_hold_bars),
                    overlap_exit_buffer_bars,
                    active_until_by_symbol,
                    state_mode,
                )
        if include_negative_funding_longs:
            for candidate in selected_longs:
                hold = _candidate_hold_bars(
                    candidate,
                    "long",
                    short_hold_bars,
                    _symbol_long_hold_bars(candidate["symbol"], short_hold_bars, long_hold_bars),
                    high_extension_short_return_bps,
                    high_extension_short_hold_bars,
                )
                if _passes_symbol_cooldown(
                    candidate["symbol"],
                    decision_time,
                    last_signal_time_by_symbol,
                    symbol_cooldown_minutes,
                ):
                    signals.append(
                        _signal(
                            candidate,
                            decision_time,
                            as_of_time,
                            "long",
                            weight * _LONG_WEIGHT_MULTIPLIER,
                            hold,
                            exit_controls,
                            state_mode,
                        )
                    )
                    last_signal_time_by_symbol[candidate["symbol"]] = decision_time
                    _record_active_window(
                        candidate["symbol"],
                        decision_time,
                        hold,
                        overlap_exit_buffer_bars,
                        active_until_by_symbol,
                        state_mode,
                    )

    return signals


def generate_decisions(bars: Sequence[Mapping[str, object]], params: Mapping[str, object]) -> list[StrategyDecision]:
    decisions: list[StrategyDecision] = []
    for signal in _generate_signal_payloads(bars, params):
        side = str(signal["side"])
        if side not in {"long", "short"}:
            raise ValueError(f"unsupported decision side: {side}")
        decisions.append(
            StrategyDecision(
                strategy_id=_STRATEGY_ID,
                instrument=InstrumentRef(kind="crypto_perp", symbol=str(signal["symbol"])),
                decision_time=_as_datetime(signal["decision_time"]),
                as_of_time=_as_datetime(signal["as_of_time"]),
                target=PositionTarget(
                    direction=side,
                    sizing_kind="target_weight",
                    size=float(signal["weight"]),
                ),
                exit_policy=ExitPolicy(
                    max_hold_bars=_positive_int(signal.get("max_hold_bars", signal["hold_bars"]), "max_hold_bars"),
                    take_profit_bps=_optional_positive_float(signal.get("take_profit_bps"), "take_profit_bps"),
                    stop_loss_bps=_optional_positive_float(signal.get("stop_loss_bps"), "stop_loss_bps"),
                    trailing_stop_bps=_optional_positive_float(signal.get("trailing_stop_bps"), "trailing_stop_bps"),
                ),
                observations=tuple(signal.get("observations", ())),
                metadata={
                    "funding_pressure_bps": signal.get("funding_pressure_bps"),
                    "entry_return_extension_bps": signal.get("entry_return_extension_bps"),
                    "signal_family": signal.get("signal_family"),
                    "state_mode": signal.get("state_mode"),
                },
            )
        )
    return decisions


def _require_fields(bars: Sequence[Mapping[str, object]], required: set[str]) -> None:
    for index, row in enumerate(bars):
        if all(field in row for field in required):
            continue
        missing = required.difference(row.keys())
        if missing:
            raise ValueError(f"bar {index} missing required fields: {sorted(missing)}")


def _validate_scalar_params(params: Mapping[str, object]) -> None:
    _positive_int(params.get("funding_lookback_events", 3), "funding_lookback_events")
    _positive_int(params.get("return_lookback_minutes", 240), "return_lookback_minutes")
    _positive_int(params.get("decision_interval_minutes", 480), "decision_interval_minutes")
    _non_negative_int(params.get("decision_lag_minutes", 1), "decision_lag_minutes")
    _positive_int(params.get("top_n", 1), "top_n")
    _positive_int(params.get("min_cross_section", 4), "min_cross_section")
    _non_negative_float(params.get("min_abs_funding_bps", 1.0), "min_abs_funding_bps")
    _non_negative_float(params.get("min_abs_return_bps", 25.0), "min_abs_return_bps")
    _non_negative_float(params.get("max_short_return_extension_bps", 0.0), "max_short_return_extension_bps")
    _bool_param(params.get("include_positive_funding_shorts", True), "include_positive_funding_shorts")
    _bool_param(params.get("include_negative_funding_longs", True), "include_negative_funding_longs")
    _non_negative_int(params.get("min_same_sign_funding_events", 0), "min_same_sign_funding_events")
    _non_negative_float(params.get("min_latest_abs_funding_bps", 0.0), "min_latest_abs_funding_bps")
    _non_negative_int(params.get("volatility_lookback_minutes", 0), "volatility_lookback_minutes")
    _non_negative_float(params.get("min_abs_return_z", 0.0), "min_abs_return_z")
    _non_negative_int(params.get("recent_return_lookback_minutes", 0), "recent_return_lookback_minutes")
    _non_negative_float(
        params.get("max_recent_same_direction_return_bps", 0.0),
        "max_recent_same_direction_return_bps",
    )
    min_idiosyncratic_return_bps = _non_negative_float(
        params.get("min_idiosyncratic_return_bps", 0.0),
        "min_idiosyncratic_return_bps",
    )
    _non_negative_float(
        params.get("min_short_idiosyncratic_return_bps", min_idiosyncratic_return_bps),
        "min_short_idiosyncratic_return_bps",
    )
    _non_negative_float(
        params.get("min_long_idiosyncratic_return_bps", min_idiosyncratic_return_bps),
        "min_long_idiosyncratic_return_bps",
    )
    _non_negative_int(params.get("symbol_cooldown_minutes", 0), "symbol_cooldown_minutes")
    _positive_int(params.get("min_tail_count", 1), "min_tail_count")
    _bool_param(params.get("balance_sides", False), "balance_sides")
    selection_score = str(params.get("selection_score", "funding"))
    if selection_score not in {"funding", "return", "product"}:
        raise ValueError("selection_score must be one of: funding, return, product")
    _bool_param(params.get("require_exit_horizon", False), "require_exit_horizon")
    weight = float(params.get("weight", 1.0))
    if not math.isfinite(weight) or weight <= 0.0:
        raise ValueError("weight must be finite and positive")
    hold_bars = _positive_int(params.get("hold_bars", params.get("hold_minutes", 480)), "hold_bars")
    short_hold_bars = _positive_int(params.get("short_hold_bars", hold_bars), "short_hold_bars")
    _positive_int(params.get("long_hold_bars", hold_bars), "long_hold_bars")
    _non_negative_float(params.get("high_extension_short_return_bps", 0.0), "high_extension_short_return_bps")
    _positive_int(
        params.get("high_extension_short_hold_bars", short_hold_bars),
        "high_extension_short_hold_bars",
    )
    state_mode = str(params.get("state_mode", "suppress_until_exit"))
    if state_mode not in {"off", "suppress_until_exit"}:
        raise ValueError("state_mode must be one of: off, suppress_until_exit")
    _non_negative_int(params.get("overlap_exit_buffer_bars", 2), "overlap_exit_buffer_bars")
    _exit_controls(params)


def _positive_int(value: object, name: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _non_negative_int(value: object, name: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise ValueError(f"{name} must be non-negative")
    return parsed


def _non_negative_float(value: object, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return parsed


def _optional_positive_float(value: object, name: str) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return parsed


def _exit_controls(params: Mapping[str, object]) -> dict[str, object]:
    controls: dict[str, object] = {}
    for name in ("take_profit_bps", "stop_loss_bps", "trailing_stop_bps"):
        value = _optional_positive_float(params.get(name), name)
        if value is not None:
            controls[name] = value
    return controls


def _bool_param(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _rows_by_symbol(
    bars: Sequence[Mapping[str, object]],
    *,
    need_timestamp_index: bool = True,
) -> dict[str, _SymbolRows]:
    rows_by_symbol: dict[str, list[tuple[datetime, float | None, datetime | None, float | None, bool]]] = {}
    for row in bars:
        symbol = str(row["symbol"])
        rows_by_symbol.setdefault(symbol, []).append(
            (
                _as_datetime(row["timestamp"]),
                _finite_float(row["close"]),
                _optional_datetime(row["funding_timestamp"]),
                _finite_float(row["funding_rate"]),
                bool(row["has_funding_event"]),
            )
        )

    indexed: dict[str, _SymbolRows] = {}
    for symbol, rows in rows_by_symbol.items():
        rows.sort(key=lambda item: item[0])
        timestamps: list[datetime] = []
        closes_by_timestamp: dict[datetime, float] = {}
        conflicting_close_timestamps: set[datetime] = set()
        funding_event_rows: list[tuple[datetime, datetime, float]] = []

        for timestamp, close, funding_time, funding_rate, has_funding_event in rows:
            timestamps.append(timestamp)

            if close is not None:
                if timestamp in closes_by_timestamp:
                    existing_close = closes_by_timestamp[timestamp]
                    if not math.isclose(existing_close, float(close), rel_tol=0.0, abs_tol=1e-12):
                        conflicting_close_timestamps.add(timestamp)
                else:
                    closes_by_timestamp[timestamp] = float(close)

            if has_funding_event and funding_time is not None and funding_rate is not None:
                funding_event_rows.append((timestamp, funding_time, funding_rate))

        funding_rate_by_time: dict[datetime, float] = {}
        for _, funding_time, funding_rate in funding_event_rows:
            existing_rate = funding_rate_by_time.get(funding_time)
            if existing_rate is not None and not math.isclose(
                existing_rate,
                funding_rate,
                rel_tol=0.0,
                abs_tol=1e-15,
            ):
                raise ValueError(f"conflicting duplicate funding rates at {funding_time.isoformat()}")
            funding_rate_by_time[funding_time] = funding_rate

        funding_events_by_time = tuple(
            sorted(
                (
                    (funding_time, row_timestamp, funding_rate)
                    for row_timestamp, funding_time, funding_rate in funding_event_rows
                ),
                key=lambda item: (item[0], item[1]),
            )
        )

        indexed[symbol] = _SymbolRows(
            timestamps=tuple(timestamps),
            timestamp_to_index={timestamp: index for index, timestamp in enumerate(timestamps)}
            if need_timestamp_index
            else {},
            closes_by_timestamp=closes_by_timestamp,
            conflicting_close_timestamps=frozenset(conflicting_close_timestamps),
            funding_event_rows=funding_events_by_time,
            funding_event_times=tuple(item[0] for item in funding_events_by_time),
            latest_timestamp=timestamps[-1],
        )
    return indexed


def _filter_exit_horizon(
    candidates: list[dict[str, Any]],
    rows_by_symbol: dict[str, _SymbolRows],
    decision_time: datetime,
    hold_bars: int,
    require_exit_horizon: bool,
) -> list[dict[str, Any]]:
    if not require_exit_horizon:
        return candidates
    return [
        candidate
        for candidate in candidates
        if _has_exit_horizon(rows_by_symbol[candidate["symbol"]], decision_time, hold_bars)
    ]


def _has_exit_horizon(rows: _SymbolRows, decision_time: datetime, hold_bars: int) -> bool:
    decision_index = rows.timestamp_to_index.get(decision_time)
    if decision_index is None:
        return False
    return decision_index + hold_bars < len(rows.timestamps)


def _decision_candidates(
    rows_by_symbol: dict[str, _SymbolRows],
    decision_time: datetime,
    funding_lookback_events: int,
    return_lookback_minutes: int,
    volatility_lookback_minutes: int,
    recent_return_lookback_minutes: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    observed_time = decision_time - timedelta(minutes=1)
    base_time = decision_time - timedelta(minutes=return_lookback_minutes)

    for symbol, rows in rows_by_symbol.items():
        observed_close = _exact_close_at(rows, observed_time)
        base_close = _exact_close_at(rows, base_time)
        funding_stats = _funding_pressure_stats(rows, decision_time, funding_lookback_events)
        if (
            observed_close is None
            or base_close is None
            or observed_close <= 0.0
            or base_close <= 0.0
            or funding_stats is None
        ):
            continue
        return_extension_bps = (observed_close / base_close - 1.0) * 10_000.0
        candidates.append(
            {
                "symbol": symbol,
                "funding_pressure_bps": funding_stats["funding_pressure_bps"],
                "funding_same_sign_events": funding_stats["funding_same_sign_events"],
                "latest_funding_bps": funding_stats["latest_funding_bps"],
                "return_extension_bps": return_extension_bps,
                "return_z": _realized_return_z(
                    rows,
                    observed_time,
                    return_lookback_minutes,
                    volatility_lookback_minutes,
                    return_extension_bps,
                ),
                "recent_return_bps": _recent_return_bps(rows, observed_time, recent_return_lookback_minutes),
                "observation_points": (
                    (observed_time, "close"),
                    (base_time, "close"),
                    *((timestamp, "funding_rate") for timestamp in funding_stats["funding_observation_timestamps"]),
                ),
            }
        )
    return candidates


def _exact_close_at(rows: _SymbolRows, timestamp: datetime) -> float | None:
    if timestamp in rows.conflicting_close_timestamps:
        raise ValueError(f"conflicting duplicate close rows at {timestamp.isoformat()}")
    return rows.closes_by_timestamp.get(timestamp)


def _funding_pressure_stats(
    rows: _SymbolRows,
    decision_time: datetime,
    funding_lookback_events: int,
) -> dict[str, float | int | tuple[datetime, ...]] | None:
    end = bisect_right(rows.funding_event_times, decision_time)
    recent: list[tuple[datetime, datetime, float]] = []
    seen_funding_times: set[datetime] = set()
    for index in range(end - 1, -1, -1):
        funding_time, row_timestamp, funding_rate = rows.funding_event_rows[index]
        if row_timestamp > decision_time or funding_time in seen_funding_times:
            continue
        seen_funding_times.add(funding_time)
        recent.append((funding_time, row_timestamp, funding_rate))
        if len(recent) == funding_lookback_events:
            break

    if len(recent) < funding_lookback_events:
        return None
    recent.reverse()
    recent_rates = [rate for _, _, rate in recent]
    funding_pressure_bps = sum(recent_rates) * 10_000.0
    pressure_sign = _sign(funding_pressure_bps)
    return {
        "funding_pressure_bps": funding_pressure_bps,
        "funding_same_sign_events": sum(1 for rate in recent_rates if _sign(rate) == pressure_sign),
        "latest_funding_bps": recent_rates[-1] * 10_000.0,
        "funding_observation_timestamps": tuple(row_timestamp for _, row_timestamp, _ in recent),
    }


def _recent_return_bps(rows: _SymbolRows, observed_time: datetime, lookback_minutes: int) -> float | None:
    if lookback_minutes <= 0:
        return None
    observed_close = _exact_close_at(rows, observed_time)
    base_close = _exact_close_at(rows, observed_time - timedelta(minutes=lookback_minutes))
    if observed_close is None or base_close is None or observed_close <= 0.0 or base_close <= 0.0:
        return None
    return (observed_close / base_close - 1.0) * 10_000.0


def _realized_return_z(
    rows: _SymbolRows,
    observed_time: datetime,
    return_lookback_minutes: int,
    volatility_lookback_minutes: int,
    return_extension_bps: float,
) -> float | None:
    if volatility_lookback_minutes <= 0:
        return None

    returns: list[float] = []
    start_time = observed_time - timedelta(minutes=volatility_lookback_minutes)
    previous_close = _exact_close_at(rows, start_time)
    if previous_close is None or previous_close <= 0.0:
        return None
    for offset in range(1, volatility_lookback_minutes + 1):
        timestamp = start_time + timedelta(minutes=offset)
        close = _exact_close_at(rows, timestamp)
        if close is None or close <= 0.0:
            return None
        returns.append(math.log(close / previous_close))
        previous_close = close

    if len(returns) < 2:
        return None
    mean_return = sum(returns) / len(returns)
    variance = sum((value - mean_return) ** 2 for value in returns) / len(returns)
    horizon_vol_bps = math.sqrt(variance) * math.sqrt(return_lookback_minutes) * 10_000.0
    if horizon_vol_bps <= 0.0:
        return None
    return return_extension_bps / horizon_vol_bps


def _passes_return_z(candidate: Mapping[str, Any], min_abs_return_z: float) -> bool:
    if min_abs_return_z <= 0.0:
        return True
    value = candidate.get("return_z")
    return isinstance(value, float) and abs(value) >= min_abs_return_z


def _passes_recent_cooloff(
    candidate: Mapping[str, Any],
    side: str,
    max_recent_same_direction_return_bps: float,
) -> bool:
    if max_recent_same_direction_return_bps <= 0.0:
        return True
    value = candidate.get("recent_return_bps")
    if not isinstance(value, float):
        return False
    if side == "short":
        return value <= max_recent_same_direction_return_bps
    return value >= -max_recent_same_direction_return_bps


def _passes_idiosyncratic_return(
    candidate: Mapping[str, Any],
    side: str,
    market_return_bps: float,
    min_idiosyncratic_return_bps: float,
) -> bool:
    if min_idiosyncratic_return_bps <= 0.0:
        return True
    idiosyncratic_return_bps = float(candidate["return_extension_bps"]) - market_return_bps
    if side == "short":
        return idiosyncratic_return_bps >= min_idiosyncratic_return_bps
    return idiosyncratic_return_bps <= -min_idiosyncratic_return_bps


def _passes_max_short_return_extension(
    candidate: Mapping[str, Any],
    max_short_return_extension_bps: float,
) -> bool:
    if max_short_return_extension_bps <= 0.0:
        return True
    return float(candidate["return_extension_bps"]) <= max_short_return_extension_bps


def _passes_long_funding_pressure(
    candidate: Mapping[str, Any],
    min_abs_funding_bps: float,
) -> bool:
    return float(candidate["funding_pressure_bps"]) <= -min_abs_funding_bps


def _passes_long_candidate(
    candidate: Mapping[str, Any],
    min_abs_funding_bps: float,
    min_abs_return_bps: float,
    min_latest_abs_funding_bps: float,
    min_abs_return_z: float,
    max_recent_same_direction_return_bps: float,
    market_return_bps: float,
    min_long_idiosyncratic_return_bps: float,
) -> bool:
    return (
        _passes_long_funding_pressure(candidate, min_abs_funding_bps)
        and candidate["return_extension_bps"] <= -min_abs_return_bps
        and abs(candidate["latest_funding_bps"]) >= min_latest_abs_funding_bps
        and _passes_return_z(candidate, min_abs_return_z)
        and _passes_recent_cooloff(candidate, "long", max_recent_same_direction_return_bps)
        and _passes_idiosyncratic_return(candidate, "long", market_return_bps, min_long_idiosyncratic_return_bps)
        and candidate["symbol"] not in _EXCLUDED_LONG_SYMBOLS
    )


def _symbol_funding_threshold(symbol: object, min_abs_funding_bps: float) -> float:
    if symbol == "ADA-PERP":
        return min_abs_funding_bps
    return max(min_abs_funding_bps, 1.5)


def _regime_funding_threshold(min_abs_funding_bps: float, market_return_bps: float) -> float:
    if market_return_bps <= -90.0:
        return max(min_abs_funding_bps, 1.5)
    return min_abs_funding_bps


def _symbol_long_hold_bars(symbol: object, short_hold_bars: int, long_hold_bars: int) -> int:
    if str(symbol) in _EXTENDED_HOLD_LONG_SYMBOLS:
        return long_hold_bars
    return short_hold_bars


def _passes_symbol_latest_funding(candidate: Mapping[str, Any]) -> bool:
    if candidate["symbol"] != "ADA-PERP":
        return True
    return float(candidate["latest_funding_bps"]) <= -_ADA_LATEST_NEGATIVE_FUNDING_BPS


def _candidate_hold_bars(
    candidate: Mapping[str, Any],
    side: str,
    short_hold_bars: int,
    long_hold_bars: int,
    high_extension_short_return_bps: float,
    high_extension_short_hold_bars: int,
) -> int:
    if side == "long":
        return long_hold_bars
    return short_hold_bars


def _selected_tail(
    candidates: list[dict[str, Any]],
    side: str,
    selection_score: str,
    top_n: int,
) -> list[dict[str, Any]]:
    if selection_score == "product":
        return sorted(
            candidates,
            key=lambda item: (
                -abs(item["funding_pressure_bps"] * item["return_extension_bps"]),
                -abs(item["funding_pressure_bps"]),
                -abs(item["return_extension_bps"]),
                item["symbol"],
            ),
        )[:top_n]
    if selection_score == "return":
        return sorted(
            candidates,
            key=lambda item: (
                -abs(item["return_extension_bps"]),
                -abs(item["funding_pressure_bps"]),
                item["symbol"],
            ),
        )[:top_n]
    if side == "short":
        return sorted(
            candidates,
            key=lambda item: (-item["funding_pressure_bps"], -item["return_extension_bps"], item["symbol"]),
        )[:top_n]
    return sorted(
        candidates,
        key=lambda item: (item["funding_pressure_bps"], item["return_extension_bps"], item["symbol"]),
    )[:top_n]


def _passes_symbol_cooldown(
    symbol: str,
    decision_time: datetime,
    last_signal_time_by_symbol: Mapping[str, datetime],
    symbol_cooldown_minutes: int,
) -> bool:
    if symbol_cooldown_minutes <= 0:
        return True
    last_signal_time = last_signal_time_by_symbol.get(symbol)
    if last_signal_time is None:
        return True
    return decision_time - last_signal_time >= timedelta(minutes=symbol_cooldown_minutes)


def _passes_state_gate(
    symbol: str,
    decision_time: datetime,
    active_until_by_symbol: Mapping[str, datetime],
    state_mode: str,
) -> bool:
    if state_mode == "off":
        return True
    active_until = active_until_by_symbol.get(symbol)
    return active_until is None or decision_time > active_until


def _record_active_window(
    symbol: str,
    decision_time: datetime,
    hold_bars: int,
    overlap_exit_buffer_bars: int,
    active_until_by_symbol: dict[str, datetime],
    state_mode: str,
) -> None:
    if state_mode == "off":
        return
    active_until_by_symbol[symbol] = decision_time + timedelta(minutes=hold_bars + overlap_exit_buffer_bars)


def _sign(value: float) -> int:
    if value > 0.0:
        return 1
    if value < 0.0:
        return -1
    return 0


def _is_decision_time(timestamp: datetime, decision_interval_minutes: int, params: Mapping[str, object]) -> bool:
    session_start_hour = int(params.get("session_start_hour", 0))
    session_end_hour = int(params.get("session_end_hour", 24))
    if timestamp.second or timestamp.microsecond:
        return False
    if not session_start_hour <= timestamp.hour < session_end_hour:
        return False
    minute_of_day = timestamp.hour * 60 + timestamp.minute
    return minute_of_day % decision_interval_minutes == 0


def _is_long_decision_time(timestamp: datetime, decision_interval_minutes: int, params: Mapping[str, object]) -> bool:
    if _is_decision_time(timestamp, decision_interval_minutes, params):
        return True
    if decision_interval_minutes < 8:
        return False
    session_start_hour = int(params.get("session_start_hour", 0))
    session_end_hour = int(params.get("session_end_hour", 24))
    if timestamp.second or timestamp.microsecond:
        return False
    if not session_start_hour <= timestamp.hour < session_end_hour:
        return False
    minute_of_day = timestamp.hour * 60 + timestamp.minute
    interval = 100
    return interval > 0 and minute_of_day % interval == 0


def _passes_symbol_session_start_gate(symbol: object, timestamp: datetime, params: Mapping[str, object]) -> bool:
    if str(symbol) != "ADA-PERP":
        return True
    session_start_hour = int(params.get("session_start_hour", 0))
    session_start_minute = session_start_hour * 60
    minute_of_day = timestamp.hour * 60 + timestamp.minute
    return not (session_start_minute <= minute_of_day <= session_start_minute + 100)


def _signal(
    candidate: Mapping[str, Any],
    decision_time: datetime,
    as_of_time: datetime,
    side: str,
    weight: float,
    hold_bars: int,
    exit_controls: Mapping[str, object],
    state_mode: str,
) -> dict[str, object]:
    symbol = str(candidate["symbol"])
    payload: dict[str, object] = {
        "symbol": symbol,
        "decision_time": decision_time,
        "as_of_time": as_of_time,
        "side": side,
        "weight": weight,
        "hold_bars": hold_bars,
        "max_hold_bars": hold_bars,
        "funding_pressure_bps": candidate["funding_pressure_bps"],
        "entry_return_extension_bps": candidate["return_extension_bps"],
        "signal_family": _STRATEGY_ID,
        "state_mode": state_mode,
        "observations": tuple(
            ObservationRef(symbol=symbol, timestamp=timestamp, field=field, source="quant_data")
            for timestamp, field in candidate.get("observation_points", ())
        ),
    }
    payload.update(exit_controls)
    return payload


def _as_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"expected datetime timestamp, got {type(value).__name__}")
    return value


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return _as_datetime(value)


def _finite_float(value: object) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    if not math.isfinite(parsed):
        return None
    return parsed
