"""Strategy: crypto_perp_funding_crowding_reversal

Source / provenance:
Internal crowding-reversal hypothesis derived from crypto perpetual futures
funding-rate mechanism literature, especially Ackerer, Hugonnier, and Jermann
(2024), "Perpetual Futures Pricing", NBER Working Paper 32936, DOI
10.3386/w32936, and Zhang (2026), "Funding Rate Mechanism in Perpetual
Futures", SSRN 6185958, DOI 10.2139/ssrn.6185958. This file is not a direct
paper replication.

Market rationale:
Recent same-direction perpetual funding pressure and price extension can mark
crowded positioning that mean-reverts over the next fixed holding window.

Required observables:
Symbol, timestamp, close, funding timestamp, funding rate, and funding-event
flag for crypto perpetual bars.

Decision rule:
On a sparse as-of cadence, use completed prior closes and funding events at or
before the as-of time to rank the cross-section. Short the strongest positive
funding plus positive return tail, and long the strongest negative funding plus
negative return tail, then rebalance the whole netted book to that selection at
every cadence step. The hold horizon equals one decision interval, so a name
that is not reselected at the next step is flattened by an explicit zero target;
a reselected name keeps its standing signed target. Each symbol carries a single
signed weight-of-NAV target that nets by construction, and a target is emitted
only when the desired book differs from the standing book.

Assumptions:
Funding timestamps are known no later than the as-of time, market data
availability is represented by the runner's `available_at` field, and the
completed prior close rather than the as-of close drives return extension. Each
decision lands on the first real bar at or after the as-of bar's availability
(`as_of_time + decision_lag_minutes`, snapped to a bar), so `decision_time` is
never look-ahead; the configured fill model enters on the following bar. A
scheduled flat is a hold-horizon rebalance, not a data-driven signal, so it
declares no observation and is anchored to the cadence as-of bar.

Falsifier:
If the broad fixed basket does not show positive gross reversal return before
costs and funding drag, reject this crowding proxy before tuning filters.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from quant_strategies.decisions import (
    InstrumentRef,
    ObservationRef,
    RiskRule,
    TargetDecision,
)

__all__ = ["generate_decisions", "validate_params"]

_REQUIRED_FIELDS = {
    "symbol",
    "timestamp",
    "close",
    "funding_timestamp",
    "funding_rate",
    "has_funding_event",
}
_EXIT_CONTROL_KEYS = ("take_profit_bps", "stop_loss_bps", "trailing_stop_bps")
_PARAM_KEYS = {
    "funding_lookback_events",
    "return_lookback_minutes",
    "decision_interval_minutes",
    "decision_lag_minutes",
    "top_n",
    "min_cross_section",
    "min_abs_funding_bps",
    "min_abs_return_bps",
    "weight",
    "max_hold_bars",
    "session_start_hour",
    "session_end_hour",
    *_EXIT_CONTROL_KEYS,
}


def validate_params(params: Mapping[str, object]) -> dict[str, object]:
    _reject_unknown_params(params, _PARAM_KEYS)
    session_start_hour = _bounded_int(
        params.get("session_start_hour", 0), "session_start_hour", minimum=0, maximum=23
    )
    session_end_hour = _bounded_int(
        params.get("session_end_hour", 24), "session_end_hour", minimum=1, maximum=24
    )
    if session_start_hour >= session_end_hour:
        raise ValueError("session_end_hour must be greater than session_start_hour")

    parsed: dict[str, object] = {
        "funding_lookback_events": _positive_int(
            params.get("funding_lookback_events", 3),
            "funding_lookback_events",
        ),
        "return_lookback_minutes": _positive_int(
            params.get("return_lookback_minutes", 240),
            "return_lookback_minutes",
        ),
        "decision_interval_minutes": _positive_int(
            params.get("decision_interval_minutes", 480),
            "decision_interval_minutes",
        ),
        "decision_lag_minutes": _non_negative_int(
            params.get("decision_lag_minutes", 1),
            "decision_lag_minutes",
        ),
        "top_n": _positive_int(params.get("top_n", 1), "top_n"),
        "min_cross_section": _positive_int(params.get("min_cross_section", 4), "min_cross_section"),
        "min_abs_funding_bps": _non_negative_float(
            params.get("min_abs_funding_bps", 1.0),
            "min_abs_funding_bps",
        ),
        "min_abs_return_bps": _non_negative_float(
            params.get("min_abs_return_bps", 25.0),
            "min_abs_return_bps",
        ),
        "weight": _positive_float(params.get("weight", 1.0), "weight"),
        "max_hold_bars": _positive_int(params.get("max_hold_bars", 480), "max_hold_bars"),
        "session_start_hour": session_start_hour,
        "session_end_hour": session_end_hour,
    }
    parsed.update(_exit_controls(params))
    return parsed


def generate_decisions(
    bars: Sequence[Mapping[str, object]],
    params: Mapping[str, object],
) -> list[TargetDecision]:
    if not bars:
        return []
    _require_fields(bars, _REQUIRED_FIELDS)

    parsed = validate_params(params)
    funding_lookback_events = int(parsed["funding_lookback_events"])
    return_lookback_minutes = int(parsed["return_lookback_minutes"])
    decision_interval_minutes = int(parsed["decision_interval_minutes"])
    decision_lag_minutes = int(parsed["decision_lag_minutes"])
    top_n = int(parsed["top_n"])
    min_cross_section = int(parsed["min_cross_section"])
    min_abs_funding_bps = float(parsed["min_abs_funding_bps"])
    min_abs_return_bps = float(parsed["min_abs_return_bps"])
    weight = float(parsed["weight"])
    risk_rule = _risk_rule({name: parsed[name] for name in _EXIT_CONTROL_KEYS if name in parsed})

    rows_by_symbol = _rows_by_symbol(bars)
    as_of_times = sorted(
        {
            row["timestamp"]
            for rows in rows_by_symbol.values()
            for row in rows
            if _is_decision_time(row["timestamp"], decision_interval_minutes, parsed)
        }
    )

    decisions: list[TargetDecision] = []
    standing: dict[str, float] = {}
    for as_of_time in as_of_times:
        candidates = _decision_candidates(
            rows_by_symbol,
            as_of_time,
            funding_lookback_events,
            return_lookback_minutes,
        )
        desired: dict[str, dict[str, Any]] = {}
        if len(candidates) >= min_cross_section:
            desired = _desired_book(
                candidates,
                top_n,
                min_abs_funding_bps,
                min_abs_return_bps,
                weight,
            )

        decision_lag = timedelta(minutes=decision_lag_minutes)
        # Names whose standing target must be revised: newly desired ones plus
        # any currently-held name absent from the new selection (flatten to 0.0).
        symbols = set(desired) | {symbol for symbol, target in standing.items() if target != 0.0}
        for symbol in sorted(symbols):
            desired_entry = desired.get(symbol)
            desired_target = float(desired_entry["target"]) if desired_entry is not None else 0.0
            if desired_target == standing.get(symbol, 0.0):
                continue
            decision_time = _first_bar_at_or_after(
                rows_by_symbol.get(symbol, ()), as_of_time + decision_lag
            )
            if decision_time is None:
                # No real bar at/after availability for this symbol; leave its
                # standing target unchanged rather than emit a look-ahead decision.
                continue
            if desired_entry is not None:
                decisions.append(
                    TargetDecision(
                        strategy_id="crypto_perp_funding_crowding_reversal",
                        instrument=InstrumentRef(kind="crypto_perp", symbol=symbol),
                        decision_time=decision_time,
                        as_of_time=as_of_time,
                        target=desired_target,
                        risk_rule=risk_rule,
                        observations=tuple(desired_entry["observations"]),
                        metadata={
                            "funding_pressure_bps": desired_entry["funding_pressure_bps"],
                            "entry_return_extension_bps": desired_entry["return_extension_bps"],
                            "signal_family": "crypto_perp_funding_crowding_reversal",
                        },
                    )
                )
            else:
                decisions.append(
                    TargetDecision(
                        strategy_id="crypto_perp_funding_crowding_reversal",
                        instrument=InstrumentRef(kind="crypto_perp", symbol=symbol),
                        decision_time=decision_time,
                        as_of_time=as_of_time,
                        target=0.0,
                    )
                )
            standing[symbol] = desired_target

    return decisions


def _desired_book(
    candidates: list[dict[str, Any]],
    top_n: int,
    min_abs_funding_bps: float,
    min_abs_return_bps: float,
    weight: float,
) -> dict[str, dict[str, Any]]:
    positive_tail = [
        candidate
        for candidate in candidates
        if candidate["funding_pressure_bps"] >= min_abs_funding_bps
        and candidate["return_extension_bps"] >= min_abs_return_bps
    ]
    negative_tail = [
        candidate
        for candidate in candidates
        if candidate["funding_pressure_bps"] <= -min_abs_funding_bps
        and candidate["return_extension_bps"] <= -min_abs_return_bps
    ]

    desired: dict[str, dict[str, Any]] = {}
    for candidate in sorted(
        positive_tail,
        key=lambda item: (
            -item["funding_pressure_bps"],
            -item["return_extension_bps"],
            item["symbol"],
        ),
    )[:top_n]:
        desired[str(candidate["symbol"])] = {**candidate, "target": -weight}
    for candidate in sorted(
        negative_tail,
        key=lambda item: (
            item["funding_pressure_bps"],
            item["return_extension_bps"],
            item["symbol"],
        ),
    )[:top_n]:
        # A symbol cannot satisfy both tails (funding sign is exclusive), so the
        # short and long selections never collide on the same key.
        desired[str(candidate["symbol"])] = {**candidate, "target": weight}
    return desired


def _require_fields(bars: Sequence[Mapping[str, object]], required: set[str]) -> None:
    for index, row in enumerate(bars):
        missing = required.difference(row.keys())
        if missing:
            raise ValueError(f"bar {index} missing required fields: {sorted(missing)}")


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
    if parsed < minimum or parsed > maximum:
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


def _positive_float(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite and positive")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite and positive") from exc
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return parsed


def _non_negative_float(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite and non-negative")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite and non-negative") from exc
    if not math.isfinite(parsed) or parsed < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return parsed


def _optional_positive_float(value: object, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite and positive")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite and positive") from exc
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return parsed


def _exit_controls(params: Mapping[str, object]) -> dict[str, object]:
    controls: dict[str, object] = {}
    for name in _EXIT_CONTROL_KEYS:
        value = _optional_positive_float(params.get(name), name)
        if value is not None:
            controls[name] = value
    return controls


def _risk_rule(exit_controls: Mapping[str, object]) -> RiskRule | None:
    legs: dict[str, float] = {}
    if "stop_loss_bps" in exit_controls:
        legs["stop_loss"] = float(exit_controls["stop_loss_bps"]) / 1e4
    if "take_profit_bps" in exit_controls:
        legs["take_profit"] = float(exit_controls["take_profit_bps"]) / 1e4
    if "trailing_stop_bps" in exit_controls:
        legs["trailing"] = float(exit_controls["trailing_stop_bps"]) / 1e4
    if not legs:
        return None
    return RiskRule(**legs)


def _reject_unknown_params(params: Mapping[str, object], allowed: set[str]) -> None:
    unknown = sorted(set(params).difference(allowed))
    if unknown:
        raise ValueError(f"unknown params: {', '.join(unknown)}")


def _rows_by_symbol(bars: Sequence[Mapping[str, object]]) -> dict[str, list[dict[str, Any]]]:
    rows_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in bars:
        symbol = str(row["symbol"])
        rows_by_symbol.setdefault(symbol, []).append(
            {
                "symbol": symbol,
                "timestamp": _as_datetime(row["timestamp"]),
                "close": _finite_float(row["close"]),
                "funding_timestamp": _optional_datetime(row["funding_timestamp"]),
                "funding_rate": _finite_float(row["funding_rate"]),
                "has_funding_event": bool(row["has_funding_event"]),
            }
        )
    for rows in rows_by_symbol.values():
        rows.sort(key=lambda item: item["timestamp"])
    return rows_by_symbol


def _decision_candidates(
    rows_by_symbol: dict[str, list[dict[str, Any]]],
    decision_time: datetime,
    funding_lookback_events: int,
    return_lookback_minutes: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    observed_time = decision_time - timedelta(minutes=1)
    base_time = decision_time - timedelta(minutes=return_lookback_minutes)

    for symbol, rows in rows_by_symbol.items():
        observed_close = _exact_close_at(rows, observed_time)
        base_close = _exact_close_at(rows, base_time)
        funding = _funding_pressure(rows, decision_time, funding_lookback_events)
        if (
            observed_close is None
            or base_close is None
            or observed_close <= 0.0
            or base_close <= 0.0
            or funding is None
        ):
            continue
        funding_pressure_bps, funding_observations = funding
        candidates.append(
            {
                "symbol": symbol,
                "funding_pressure_bps": funding_pressure_bps,
                "return_extension_bps": (observed_close / base_close - 1.0) * 10_000.0,
                "observations": (
                    ObservationRef(
                        symbol=symbol, timestamp=base_time, field="close", source="strategy_input"
                    ),
                    ObservationRef(
                        symbol=symbol,
                        timestamp=observed_time,
                        field="close",
                        source="strategy_input",
                    ),
                    *funding_observations,
                ),
            }
        )
    return candidates


def _first_bar_at_or_after(
    rows: Sequence[Mapping[str, Any]],
    needed_time: datetime,
) -> datetime | None:
    for row in rows:
        timestamp = row["timestamp"]
        if timestamp >= needed_time:
            return timestamp
    return None


def _exact_close_at(rows: list[dict[str, Any]], timestamp: datetime) -> float | None:
    closes = [
        row["close"] for row in rows if row["timestamp"] == timestamp and row["close"] is not None
    ]
    if not closes:
        return None
    first = float(closes[0])
    if any(
        not math.isclose(first, float(close), rel_tol=0.0, abs_tol=1e-12) for close in closes[1:]
    ):
        raise ValueError(f"conflicting duplicate close rows at {timestamp.isoformat()}")
    return first


def _funding_pressure(
    rows: list[dict[str, Any]],
    decision_time: datetime,
    funding_lookback_events: int,
) -> tuple[float, tuple[ObservationRef, ...]] | None:
    funding_events: dict[datetime, tuple[datetime, float]] = {}
    for row in rows:
        if row["timestamp"] > decision_time:
            break
        funding_time = row["funding_timestamp"]
        funding_rate = row["funding_rate"]
        if not row["has_funding_event"] or funding_time is None or funding_rate is None:
            continue
        if funding_time > decision_time:
            continue

        existing = funding_events.get(funding_time)
        if existing is not None:
            _, existing_rate = existing
            if not math.isclose(existing_rate, funding_rate, rel_tol=0.0, abs_tol=1e-15):
                raise ValueError(
                    f"conflicting duplicate funding rates at {funding_time.isoformat()}"
                )
        funding_events[funding_time] = (row["timestamp"], funding_rate)

    if len(funding_events) < funding_lookback_events:
        return None
    recent = sorted(funding_events.items(), key=lambda item: (item[0], item[1][0]))[
        -funding_lookback_events:
    ]
    observations = tuple(
        observation
        for _, (row_timestamp, _) in recent
        for observation in (
            ObservationRef(
                symbol=str(rows[0]["symbol"]),
                timestamp=row_timestamp,
                field="funding_timestamp",
                source="strategy_input",
            ),
            ObservationRef(
                symbol=str(rows[0]["symbol"]),
                timestamp=row_timestamp,
                field="funding_rate",
                source="strategy_input",
            ),
            ObservationRef(
                symbol=str(rows[0]["symbol"]),
                timestamp=row_timestamp,
                field="has_funding_event",
                source="strategy_input",
            ),
        )
    )
    return sum(rate for _, (_, rate) in recent) * 10_000.0, observations


def _is_decision_time(
    timestamp: datetime, decision_interval_minutes: int, params: Mapping[str, object]
) -> bool:
    session_start_hour = int(params.get("session_start_hour", 0))
    session_end_hour = int(params.get("session_end_hour", 24))
    if timestamp.second or timestamp.microsecond:
        return False
    if not session_start_hour <= timestamp.hour < session_end_hour:
        return False
    minute_of_day = timestamp.hour * 60 + timestamp.minute
    return minute_of_day % decision_interval_minutes == 0


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
