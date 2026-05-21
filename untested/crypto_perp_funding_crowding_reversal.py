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

Signal rule:
On a sparse decision cadence, use completed prior closes and funding events at
or before the decision time. Short the strongest positive funding plus positive
return tail, and long the strongest negative funding plus negative return tail.

Assumptions:
Funding timestamps are available no later than the decision time, and the
completed prior close rather than the decision close drives return extension.

Falsifier:
If the broad fixed basket does not show positive gross reversal return before
costs and funding drag, reject this crowding proxy before tuning filters.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
import math
from typing import Any


__all__ = ["generate_signals"]

_REQUIRED_FIELDS = {"symbol", "timestamp", "close", "funding_timestamp", "funding_rate", "has_funding_event"}


def generate_signals(bars: Sequence[Mapping[str, object]], params: Mapping[str, object]) -> list[dict[str, object]]:
    if not bars:
        return []
    _require_fields(bars, _REQUIRED_FIELDS)

    funding_lookback_events = _positive_int(params.get("funding_lookback_events", 3), "funding_lookback_events")
    return_lookback_minutes = _positive_int(params.get("return_lookback_minutes", 240), "return_lookback_minutes")
    decision_interval_minutes = _positive_int(params.get("decision_interval_minutes", 480), "decision_interval_minutes")
    top_n = _positive_int(params.get("top_n", 1), "top_n")
    min_cross_section = _positive_int(params.get("min_cross_section", 4), "min_cross_section")
    min_abs_funding_bps = _non_negative_float(params.get("min_abs_funding_bps", 1.0), "min_abs_funding_bps")
    min_abs_return_bps = _non_negative_float(params.get("min_abs_return_bps", 25.0), "min_abs_return_bps")
    weight = float(params.get("weight", 1.0))
    hold_bars = int(params.get("hold_bars", params.get("hold_minutes", 480)))

    rows_by_symbol = _rows_by_symbol(bars)
    decision_times = sorted(
        {
            row["timestamp"]
            for rows in rows_by_symbol.values()
            for row in rows
            if _is_decision_time(row["timestamp"], decision_interval_minutes, params)
        }
    )

    signals: list[dict[str, object]] = []
    for decision_time in decision_times:
        candidates = _decision_candidates(
            rows_by_symbol,
            decision_time,
            funding_lookback_events,
            return_lookback_minutes,
        )
        if len(candidates) < min_cross_section:
            continue

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

        for candidate in sorted(
            positive_tail,
            key=lambda item: (-item["funding_pressure_bps"], -item["return_extension_bps"], item["symbol"]),
        )[:top_n]:
            signals.append(_signal(candidate["symbol"], decision_time, "short", weight, hold_bars))
        for candidate in sorted(
            negative_tail,
            key=lambda item: (item["funding_pressure_bps"], item["return_extension_bps"], item["symbol"]),
        )[:top_n]:
            signals.append(_signal(candidate["symbol"], decision_time, "long", weight, hold_bars))

    return signals


def _require_fields(bars: Sequence[Mapping[str, object]], required: set[str]) -> None:
    for index, row in enumerate(bars):
        missing = required.difference(row.keys())
        if missing:
            raise ValueError(f"bar {index} missing required fields: {sorted(missing)}")


def _positive_int(value: object, name: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _non_negative_float(value: object, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return parsed


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
        funding_pressure_bps = _funding_pressure_bps(rows, decision_time, funding_lookback_events)
        if (
            observed_close is None
            or base_close is None
            or observed_close <= 0.0
            or base_close <= 0.0
            or funding_pressure_bps is None
        ):
            continue
        candidates.append(
            {
                "symbol": symbol,
                "funding_pressure_bps": funding_pressure_bps,
                "return_extension_bps": (observed_close / base_close - 1.0) * 10_000.0,
            }
        )
    return candidates


def _exact_close_at(rows: list[dict[str, Any]], timestamp: datetime) -> float | None:
    closes = [row["close"] for row in rows if row["timestamp"] == timestamp and row["close"] is not None]
    if not closes:
        return None
    first = float(closes[0])
    if any(not math.isclose(first, float(close), rel_tol=0.0, abs_tol=1e-12) for close in closes[1:]):
        raise ValueError(f"conflicting duplicate close rows at {timestamp.isoformat()}")
    return first


def _funding_pressure_bps(
    rows: list[dict[str, Any]],
    decision_time: datetime,
    funding_lookback_events: int,
) -> float | None:
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
                raise ValueError(f"conflicting duplicate funding rates at {funding_time.isoformat()}")
        funding_events[funding_time] = (row["timestamp"], funding_rate)

    if len(funding_events) < funding_lookback_events:
        return None
    recent = sorted(funding_events.items(), key=lambda item: (item[0], item[1][0]))[-funding_lookback_events:]
    return sum(rate for _, (_, rate) in recent) * 10_000.0


def _is_decision_time(timestamp: datetime, decision_interval_minutes: int, params: Mapping[str, object]) -> bool:
    session_start_hour = int(params.get("session_start_hour", 0))
    session_end_hour = int(params.get("session_end_hour", 24))
    if timestamp.second or timestamp.microsecond:
        return False
    if not session_start_hour <= timestamp.hour < session_end_hour:
        return False
    minute_of_day = timestamp.hour * 60 + timestamp.minute
    return minute_of_day % decision_interval_minutes == 0


def _signal(symbol: str, decision_time: datetime, side: str, weight: float, hold_bars: int) -> dict[str, object]:
    return {
        "symbol": symbol,
        "decision_time": decision_time,
        "side": side,
        "weight": weight,
        "hold_bars": hold_bars,
    }


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
