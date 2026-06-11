"""Strategy: krohn_mueller_whelan_fix_reversal

Source / provenance:
Krohn, Mueller, and Whelan (2024), "Foreign Exchange Fixings and Returns
around the Clock", Journal of Finance 79(1), 541-578, DOI
10.1111/jofi.13306. Earlier working-paper versions include Bank of Canada
Staff Working Paper 2021-48 and SSRN 3521370.

Market rationale:
The paper documents that the U.S. dollar tends to appreciate before the major
Tokyo, Frankfurt/ECB, and London fixes and depreciate after them, creating a
W-shaped intraday pattern in USD returns.

Required observables:
Symbol, UTC bar timestamp, and one-minute mid quote for liquid USD FX pairs.

Decision rule:
For each Tokyo, Frankfurt/ECB, or London fix on each local date, sell USD across
the eligible basket pairs simultaneously at a configured lead time before the
fix, then flatten the whole basket just after the fix. The short-USD book is
sized on a basket budget: each eligible pair takes target = sign * weight /
n_eligible so the simultaneous basket nets to gross approximately equal to net
approximately equal to weight (<= 1.0) instead of stacking one full weight per
pair. Sign follows the direct-pair convention: USD-quote pairs (xxxUSD) go long
the pair (short USD, +weight share); USD-base pairs (USDxxx) go short the pair
(-weight share). The fixed hold horizon is emitted as an explicit flat
(target=0.0) decision per pair at the first real bar at or after
decision_time + max_hold_bars minutes, so the position closes on the target book
itself rather than any engine hold horizon.

Assumptions:
Input timestamps are timezone-aware and represent UTC-compatible bar times;
quote fill timing is controlled by the runner config. The entry's as_of_time is
decision_time minus the observation lag and must be a real, already-available
bar; the computed decision_time is snapped forward to the first real bar for
that pair so it always lands on an actual bar and never looks ahead. The
scheduled flat declares no observation because it is a hold-horizon policy exit,
not a data-driven signal, and reuses the entry's already-available as_of_time.

Falsifier:
If the broad USD basket clock-time rule does not produce positive gross
postfix reversal return before spread and slippage, reject this envelope-clean
fixing proxy before adding filters or tuning windows.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from quant_strategies.decisions import (
    InstrumentRef,
    ObservationRef,
    RiskRule,
    TargetDecision,
)

__all__ = ["generate_decisions", "validate_params"]

_REQUIRED_FIELDS = {"symbol", "timestamp", "mid"}
_EXIT_CONTROL_KEYS = ("take_profit_bps", "stop_loss_bps", "trailing_stop_bps")
_PARAM_KEYS = {
    "decision_lead_minutes",
    "observation_lag_minutes",
    "weight",
    "max_hold_bars",
    *_EXIT_CONTROL_KEYS,
}
_DEFAULT_USD_BASKET = ("AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY")
_FIX_SCHEDULE = (
    ("tokyo", "Asia/Tokyo", time(9, 55)),
    ("frankfurt", "Europe/Berlin", time(14, 15)),
    ("london", "Europe/London", time(16, 0)),
)


def validate_params(params: Mapping[str, object]) -> dict[str, object]:
    _reject_unknown_params(params, _PARAM_KEYS)
    parsed: dict[str, object] = {
        "decision_lead_minutes": _positive_int(
            params.get("decision_lead_minutes", 2),
            "decision_lead_minutes",
        ),
        "observation_lag_minutes": _positive_int(
            params.get("observation_lag_minutes", 1),
            "observation_lag_minutes",
        ),
        "weight": _positive_float(params.get("weight", 1.0), "weight"),
        "max_hold_bars": _positive_int(params.get("max_hold_bars", 2), "max_hold_bars"),
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
    decision_lead_minutes = int(parsed["decision_lead_minutes"])
    observation_lag_minutes = int(parsed["observation_lag_minutes"])
    weight = float(parsed["weight"])
    max_hold_bars = int(parsed["max_hold_bars"])
    risk_rule = _risk_rule({name: parsed[name] for name in _EXIT_CONTROL_KEYS if name in parsed})

    mid_by_key, local_dates_by_fix, available_symbols, timestamps_by_symbol = _mid_table(bars)
    basket_symbols = [symbol for symbol in _DEFAULT_USD_BASKET if symbol in available_symbols]

    decisions: list[TargetDecision] = []
    seen: set[tuple[str, datetime]] = set()
    for fix_name, zone_name, local_fix_time in _FIX_SCHEDULE:
        zone = ZoneInfo(zone_name)
        for local_date in sorted(local_dates_by_fix[fix_name]):
            fix_local = datetime.combine(local_date, local_fix_time, tzinfo=zone)
            fix_utc = fix_local.astimezone(UTC)
            target_decision_time = fix_utc - timedelta(minutes=decision_lead_minutes)
            as_of_time = target_decision_time - timedelta(minutes=observation_lag_minutes)

            eligible = [symbol for symbol in basket_symbols if (symbol, as_of_time) in mid_by_key]
            if not eligible:
                continue
            per_pair_weight = weight / len(eligible)

            for symbol in eligible:
                decision_time = _first_bar_at_or_after(
                    timestamps_by_symbol[symbol], target_decision_time
                )
                if decision_time is None:
                    continue
                entry_key = (symbol, decision_time)
                if entry_key in seen:
                    continue
                seen.add(entry_key)

                flat_time = _first_bar_at_or_after(
                    timestamps_by_symbol[symbol],
                    decision_time + timedelta(minutes=max_hold_bars),
                )
                if flat_time is None or flat_time == decision_time:
                    continue

                signed_target = _sell_usd_sign(symbol) * per_pair_weight
                decisions.append(
                    _entry_decision(
                        symbol=symbol,
                        decision_time=decision_time,
                        as_of_time=as_of_time,
                        target=signed_target,
                        risk_rule=risk_rule,
                        fix_name=fix_name,
                        fix_local=fix_local,
                        fix_utc=fix_utc,
                        per_pair_weight=per_pair_weight,
                    )
                )
                decisions.append(
                    TargetDecision(
                        strategy_id="krohn_mueller_whelan_fix_reversal",
                        instrument=InstrumentRef(kind="fx_pair", symbol=symbol),
                        decision_time=flat_time,
                        as_of_time=as_of_time,
                        target=0.0,
                        metadata={
                            "signal_family": "krohn_mueller_whelan_fix_reversal",
                            "fix_name": fix_name,
                            "leg": "flat",
                        },
                    )
                )

    return sorted(
        decisions, key=lambda decision: (decision.decision_time, decision.instrument.symbol)
    )


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


def _mid_table(
    bars: Sequence[Mapping[str, object]],
) -> tuple[
    dict[tuple[str, datetime], float],
    dict[str, set[date]],
    set[str],
    dict[str, list[datetime]],
]:
    mid_by_key: dict[tuple[str, datetime], float] = {}
    local_dates_by_fix = {fix_name: set() for fix_name, _, _ in _FIX_SCHEDULE}
    symbols: set[str] = set()
    timestamps_by_symbol: dict[str, set[datetime]] = {}

    for row in bars:
        symbol = str(row["symbol"])
        timestamp = _utc_datetime(row["timestamp"])
        mid = _positive_finite_float(row["mid"])
        key = (symbol, timestamp)
        if key in mid_by_key:
            raise ValueError(f"duplicate mid row for {symbol} at {timestamp.isoformat()}")
        mid_by_key[key] = mid
        symbols.add(symbol)
        timestamps_by_symbol.setdefault(symbol, set()).add(timestamp)
        for fix_name, zone_name, _ in _FIX_SCHEDULE:
            local_dates_by_fix[fix_name].add(timestamp.astimezone(ZoneInfo(zone_name)).date())

    sorted_timestamps = {symbol: sorted(stamps) for symbol, stamps in timestamps_by_symbol.items()}
    return mid_by_key, local_dates_by_fix, symbols, sorted_timestamps


def _utc_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"expected datetime timestamp, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _positive_finite_float(value: object) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise ValueError("mid must be finite and positive")
    return parsed


def _first_bar_at_or_after(
    timestamps: Sequence[datetime],
    target: datetime,
) -> datetime | None:
    for timestamp in timestamps:
        if timestamp >= target:
            return timestamp
    return None


def _entry_decision(
    *,
    symbol: str,
    decision_time: datetime,
    as_of_time: datetime,
    target: float,
    risk_rule: RiskRule | None,
    fix_name: str,
    fix_local: datetime,
    fix_utc: datetime,
    per_pair_weight: float,
) -> TargetDecision:
    return TargetDecision(
        strategy_id="krohn_mueller_whelan_fix_reversal",
        instrument=InstrumentRef(kind="fx_pair", symbol=symbol),
        decision_time=decision_time,
        as_of_time=as_of_time,
        target=target,
        risk_rule=risk_rule,
        observations=(
            ObservationRef(
                symbol=symbol,
                timestamp=as_of_time,
                field="mid",
                source="strategy_input",
            ),
        ),
        metadata={
            "signal_family": "krohn_mueller_whelan_fix_reversal",
            "fix_name": fix_name,
            "fix_local_time": fix_local.isoformat(),
            "fix_utc_time": fix_utc.isoformat(),
            "usd_side": "sell",
            "leg": "entry",
            "per_pair_weight": per_pair_weight,
        },
    )


def _sell_usd_sign(symbol: str) -> float:
    if symbol.endswith("USD"):
        return 1.0
    if symbol.startswith("USD"):
        return -1.0
    raise ValueError(f"unsupported USD pair convention: {symbol}")
