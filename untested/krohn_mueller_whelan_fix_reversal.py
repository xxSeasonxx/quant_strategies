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
For each available one-minute bar at a configured lead time before the Tokyo,
Frankfurt/ECB, or London fix, sell USD via the direct USD pair convention and
use a short fixed holding window to exit just after the fix.

Assumptions:
Input timestamps are timezone-aware and represent UTC-compatible bar times;
quote fill timing is controlled by the runner config, and the quick-run envelope
uses a one-minute observation lag plus one-bar entry lag so decisions two
minutes before the fix enter one minute before the fix.

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
    ExitPolicy,
    InstrumentRef,
    ObservationRef,
    PositionTarget,
    StrategyDecision,
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
) -> list[StrategyDecision]:
    if not bars:
        return []
    _require_fields(bars, _REQUIRED_FIELDS)

    parsed = validate_params(params)
    decision_lead_minutes = int(parsed["decision_lead_minutes"])
    observation_lag_minutes = int(parsed["observation_lag_minutes"])
    weight = float(parsed["weight"])
    max_hold_bars = int(parsed["max_hold_bars"])
    exit_controls = {name: parsed[name] for name in _EXIT_CONTROL_KEYS if name in parsed}

    mid_by_key, local_dates_by_fix, available_symbols = _mid_table(bars)
    basket_symbols = [symbol for symbol in _DEFAULT_USD_BASKET if symbol in available_symbols]

    decisions: list[StrategyDecision] = []
    seen: set[tuple[str, str, datetime]] = set()
    for fix_name, zone_name, local_fix_time in _FIX_SCHEDULE:
        zone = ZoneInfo(zone_name)
        for local_date in sorted(local_dates_by_fix[fix_name]):
            fix_local = datetime.combine(local_date, local_fix_time, tzinfo=zone)
            fix_utc = fix_local.astimezone(UTC)
            decision_time = fix_utc - timedelta(minutes=decision_lead_minutes)
            as_of_time = decision_time - timedelta(minutes=observation_lag_minutes)
            for symbol in basket_symbols:
                if (symbol, as_of_time) not in mid_by_key:
                    continue
                seen_key = (symbol, fix_name, decision_time)
                if seen_key in seen:
                    continue
                seen.add(seen_key)
                decisions.append(
                    _decision(
                        symbol=symbol,
                        decision_time=decision_time,
                        as_of_time=as_of_time,
                        weight=weight,
                        max_hold_bars=max_hold_bars,
                        exit_controls=exit_controls,
                        fix_name=fix_name,
                        fix_local=fix_local,
                        fix_utc=fix_utc,
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


def _reject_unknown_params(params: Mapping[str, object], allowed: set[str]) -> None:
    unknown = sorted(set(params).difference(allowed))
    if unknown:
        raise ValueError(f"unknown params: {', '.join(unknown)}")


def _mid_table(
    bars: Sequence[Mapping[str, object]],
) -> tuple[dict[tuple[str, datetime], float], dict[str, set[date]], set[str]]:
    mid_by_key: dict[tuple[str, datetime], float] = {}
    local_dates_by_fix = {fix_name: set() for fix_name, _, _ in _FIX_SCHEDULE}
    symbols: set[str] = set()

    for row in bars:
        symbol = str(row["symbol"])
        timestamp = _utc_datetime(row["timestamp"])
        mid = _positive_finite_float(row["mid"])
        key = (symbol, timestamp)
        if key in mid_by_key:
            raise ValueError(f"duplicate mid row for {symbol} at {timestamp.isoformat()}")
        mid_by_key[key] = mid
        symbols.add(symbol)
        for fix_name, zone_name, _ in _FIX_SCHEDULE:
            local_dates_by_fix[fix_name].add(timestamp.astimezone(ZoneInfo(zone_name)).date())

    return mid_by_key, local_dates_by_fix, symbols


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


def _decision(
    *,
    symbol: str,
    decision_time: datetime,
    as_of_time: datetime,
    weight: float,
    max_hold_bars: int,
    exit_controls: Mapping[str, object],
    fix_name: str,
    fix_local: datetime,
    fix_utc: datetime,
) -> StrategyDecision:
    return StrategyDecision(
        strategy_id="krohn_mueller_whelan_fix_reversal",
        instrument=InstrumentRef(kind="fx_pair", symbol=symbol),
        decision_time=decision_time,
        as_of_time=as_of_time,
        target=PositionTarget(
            direction=_sell_usd_direction(symbol), sizing_kind="target_weight", size=weight
        ),
        exit_policy=ExitPolicy(max_hold_bars=max_hold_bars, **exit_controls),
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
            "entry_window_minutes": 1,
        },
    )


def _sell_usd_direction(symbol: str) -> str:
    if symbol.endswith("USD"):
        return "long"
    if symbol.startswith("USD"):
        return "short"
    raise ValueError(f"unsupported USD pair convention: {symbol}")
