"""Strategy: fx_triangular_residual_reversion

Source / provenance:
Internal residual-reversion hypothesis derived from FX triangular
arbitrage/law-of-one-price microstructure literature, especially Akram, Rime,
and Sarno (2008), "Arbitrage in the Foreign Exchange Market: Turning on the
Microscope", Journal of International Economics, DOI
10.1016/j.jinteco.2008.07.004. This file is not a direct paper replication.

Market rationale:
Large one-minute deviations between an FX cross and its USD-leg synthetic value
can mark short-lived pressure that mean-reverts.

Required observables:
Symbol, timestamp, and close price for one-minute FX bars covering each
triangle leg.

Decision rule:
Compute triangular log residuals from completed closes, score the current
residual against prior residuals only, attribute the recent residual move to
the largest aligned leg, and trade that leg toward residual mean reversion after
the residual's as-of bar can be observed.

Assumptions:
Close prices and quote fields are sufficiently aligned across triangle legs;
market data availability is represented by the runner's `available_at` field
when present, and the next-bar quote fill is the earliest causal execution used
by the runner config.

Falsifier:
If broad fixed-parameter residual signals do not produce positive gross return
before spread and slippage, reject this one-minute residual proxy before tuning.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
import math
from statistics import fmean, pstdev
from typing import Any

from quant_strategies.decisions import (
    ExitPolicy,
    InstrumentRef,
    ObservationRef,
    PositionTarget,
    StrategyDecision,
)


__all__ = ["generate_decisions", "validate_params"]

_Triangle = tuple[str, str, int, str, int]

_REQUIRED_FIELDS = {"symbol", "timestamp", "close"}
_EXIT_CONTROL_KEYS = ("take_profit_bps", "stop_loss_bps", "trailing_stop_bps")
_PARAM_KEYS = {
    "triangle_set",
    "zscore_window_bars",
    "zscore_window_minutes",
    "min_zscore_observations",
    "entry_zscore",
    "min_abs_residual_bps",
    "attribution_bars",
    "attribution_minutes",
    "decision_lag_minutes",
    "crossing_only",
    "weight",
    "max_hold_bars",
    *_EXIT_CONTROL_KEYS,
}
_OUTSIDE_VIEW_8_TRIANGLES: tuple[_Triangle, ...] = (
    ("EURJPY", "EURUSD", 1, "USDJPY", 1),
    ("GBPJPY", "GBPUSD", 1, "USDJPY", 1),
    ("AUDJPY", "AUDUSD", 1, "USDJPY", 1),
    ("NZDJPY", "NZDUSD", 1, "USDJPY", 1),
    ("CADJPY", "USDJPY", 1, "USDCAD", -1),
    ("EURGBP", "EURUSD", 1, "GBPUSD", -1),
    ("EURAUD", "EURUSD", 1, "AUDUSD", -1),
    ("AUDNZD", "AUDUSD", 1, "NZDUSD", -1),
)
_ADDITIONAL_AVAILABLE_TRIANGLES: tuple[_Triangle, ...] = (
    ("EURCAD", "EURUSD", 1, "USDCAD", 1),
    ("EURCHF", "EURUSD", 1, "USDCHF", 1),
    ("GBPAUD", "GBPUSD", 1, "AUDUSD", -1),
)


def validate_params(params: Mapping[str, object]) -> dict[str, object]:
    _reject_unknown_params(params, _PARAM_KEYS)
    triangle_set = str(params.get("triangle_set", "outside_view_8"))
    _triangles_for(triangle_set)

    parsed: dict[str, object] = {
        "triangle_set": triangle_set,
        "zscore_window_bars": _positive_int(
            _param_or_alias(params, "zscore_window_bars", "zscore_window_minutes", 240),
            "zscore_window_bars",
        ),
        "min_zscore_observations": _positive_int(
            params.get("min_zscore_observations", 120),
            "min_zscore_observations",
        ),
        "entry_zscore": _positive_float(params.get("entry_zscore", 2.5), "entry_zscore"),
        "min_abs_residual_bps": _non_negative_float(
            params.get("min_abs_residual_bps", 1.0),
            "min_abs_residual_bps",
        ),
        "attribution_bars": _positive_int(
            _param_or_alias(params, "attribution_bars", "attribution_minutes", 5),
            "attribution_bars",
        ),
        "decision_lag_minutes": _non_negative_int(
            params.get("decision_lag_minutes", 1),
            "decision_lag_minutes",
        ),
        "crossing_only": _bool_param(params.get("crossing_only", True), "crossing_only"),
        "weight": _positive_float(params.get("weight", 1.0), "weight"),
        "max_hold_bars": _positive_int(params.get("max_hold_bars", 30), "max_hold_bars"),
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
    zscore_window_bars = int(parsed["zscore_window_bars"])
    min_zscore_observations = int(parsed["min_zscore_observations"])
    entry_zscore = float(parsed["entry_zscore"])
    min_abs_residual_bps = float(parsed["min_abs_residual_bps"])
    attribution_bars = int(parsed["attribution_bars"])
    decision_lag_minutes = int(parsed["decision_lag_minutes"])
    crossing_only = bool(parsed["crossing_only"])
    weight = float(parsed["weight"])
    max_hold_bars = int(parsed["max_hold_bars"])
    exit_controls = {name: parsed[name] for name in _EXIT_CONTROL_KEYS if name in parsed}

    close_by_key, timestamps, symbols = _close_table(bars)

    candidates: dict[tuple[str, datetime], list[dict[str, Any]]] = {}
    for triangle in _triangles_for(str(parsed["triangle_set"])):
        if not set(_triangle_symbols(triangle)).issubset(symbols):
            continue
        points = _residual_points(triangle, timestamps, close_by_key)
        _collect_candidates(
            triangle,
            points,
            close_by_key,
            zscore_window_bars,
            min_zscore_observations,
            entry_zscore,
            min_abs_residual_bps,
            attribution_bars,
            crossing_only,
            candidates,
        )

    decisions: list[StrategyDecision] = []
    for symbol, as_of_time in sorted(candidates, key=lambda key: (key[1], key[0])):
        entries = candidates[(symbol, as_of_time)]
        score = sum(float(entry["signal"]) * float(entry["strength"]) for entry in entries)
        if abs(score) <= 1e-12:
            continue
        representative = max(entries, key=lambda entry: abs(float(entry["strength"])))
        observations = _unique_observations(
            observation
            for entry in entries
            for observation in entry["observations"]
        )
        decision_time = as_of_time + timedelta(minutes=decision_lag_minutes)
        decisions.append(
            StrategyDecision(
                strategy_id="fx_triangular_residual_quote",
                instrument=InstrumentRef(kind="fx_pair", symbol=symbol),
                decision_time=decision_time,
                as_of_time=as_of_time,
                target=PositionTarget(
                    direction="long" if score > 0.0 else "short",
                    sizing_kind="target_weight",
                    size=weight,
                ),
                exit_policy=ExitPolicy(max_hold_bars=max_hold_bars, **exit_controls),
                observations=observations,
                metadata={
                    "residual_zscore": representative["residual_zscore"],
                    "residual_bps": representative["residual_bps"],
                    "attribution_score": sum(float(entry["attribution_score"]) for entry in entries),
                    "signal_family": "fx_triangular_residual_reversion",
                },
            )
        )
    return decisions


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


def _param_or_alias(params: Mapping[str, object], canonical: str, alias: str, default: object) -> object:
    if canonical in params:
        return params[canonical]
    if alias in params:
        return params[alias]
    return default


def _reject_unknown_params(params: Mapping[str, object], allowed: set[str]) -> None:
    unknown = sorted(set(params).difference(allowed))
    if unknown:
        raise ValueError(f"unknown params: {', '.join(unknown)}")


def _close_table(
    bars: Sequence[Mapping[str, object]],
) -> tuple[dict[tuple[str, datetime], float], list[datetime], set[str]]:
    close_by_key: dict[tuple[str, datetime], float] = {}
    timestamps: set[datetime] = set()
    symbols: set[str] = set()

    for row in bars:
        symbol = str(row["symbol"])
        timestamp = _as_datetime(row["timestamp"])
        close = _positive_finite_float(row["close"])
        if close is None:
            continue
        key = (symbol, timestamp)
        if key in close_by_key:
            raise ValueError(f"duplicate close row for {symbol} at {timestamp}")
        close_by_key[key] = close
        timestamps.add(timestamp)
        symbols.add(symbol)

    return close_by_key, sorted(timestamps), symbols


def _collect_candidates(
    triangle: _Triangle,
    points: list[dict[str, Any]],
    close_by_key: dict[tuple[str, datetime], float],
    zscore_window_bars: int,
    min_zscore_observations: int,
    entry_zscore: float,
    min_abs_residual_bps: float,
    attribution_bars: int,
    crossing_only: bool,
    candidates: dict[tuple[str, datetime], list[dict[str, Any]]],
) -> None:
    prior_extreme_sign = 0
    residuals = [point["residual"] for point in points]
    for index, point in enumerate(points):
        history = residuals[max(0, index - zscore_window_bars) : index]
        if len(history) < min_zscore_observations:
            prior_extreme_sign = 0
            continue
        std = pstdev(history)
        if not math.isfinite(std) or std <= 0.0:
            prior_extreme_sign = 0
            continue

        residual_z = (point["residual"] - fmean(history)) / std
        residual_bps = point["residual"] * 10_000.0
        extreme_sign = _extreme_sign(residual_z, residual_bps, entry_zscore, min_abs_residual_bps)
        if extreme_sign == 0:
            prior_extreme_sign = 0
            continue

        selected = _select_reversion_leg(triangle, points, index, extreme_sign, attribution_bars)
        if selected is None:
            prior_extreme_sign = extreme_sign
            continue

        symbol, signal, attribution_score = selected
        as_of_time = point["timestamp"]
        if (symbol, as_of_time) not in close_by_key:
            prior_extreme_sign = extreme_sign
            continue
        if not (crossing_only and prior_extreme_sign == extreme_sign):
            candidates.setdefault((symbol, as_of_time), []).append(
                {
                    "signal": signal,
                    "strength": abs(float(residual_z)),
                    "residual_zscore": float(residual_z),
                    "residual_bps": float(residual_bps),
                    "attribution_score": attribution_score,
                    "observations": _triangle_observations(
                        triangle=triangle,
                        points=points,
                        current_index=index,
                        zscore_window_bars=zscore_window_bars,
                        attribution_bars=attribution_bars,
                    ),
                }
            )
        prior_extreme_sign = extreme_sign


def _triangle_observations(
    *,
    triangle: _Triangle,
    points: list[dict[str, Any]],
    current_index: int,
    zscore_window_bars: int,
    attribution_bars: int,
) -> tuple[ObservationRef, ...]:
    symbols = _triangle_symbols(triangle)
    history_start = max(0, current_index - zscore_window_bars)
    attribution_index = max(0, current_index - attribution_bars)
    point_indexes = set(range(history_start, current_index + 1))
    point_indexes.add(attribution_index)
    return tuple(
        ObservationRef(symbol=symbol, timestamp=points[index]["timestamp"], field="close", source="strategy_input")
        for index in sorted(point_indexes)
        for symbol in symbols
    )


def _unique_observations(observations: Sequence[ObservationRef]) -> tuple[ObservationRef, ...]:
    unique: dict[tuple[str, datetime, str | None, str | None], ObservationRef] = {}
    for observation in observations:
        key = (observation.symbol, observation.timestamp, observation.field, observation.source)
        unique.setdefault(key, observation)
    return tuple(unique[key] for key in sorted(unique))


def _residual_points(
    triangle: _Triangle,
    timestamps: list[datetime],
    close_by_key: dict[tuple[str, datetime], float],
) -> list[dict[str, Any]]:
    direct, leg_a, leg_a_sign, leg_b, leg_b_sign = triangle
    points: list[dict[str, Any]] = []
    for timestamp in timestamps:
        direct_close = close_by_key.get((direct, timestamp))
        leg_a_close = close_by_key.get((leg_a, timestamp))
        leg_b_close = close_by_key.get((leg_b, timestamp))
        if direct_close is None or leg_a_close is None or leg_b_close is None:
            continue
        logs = {
            direct: math.log(direct_close),
            leg_a: math.log(leg_a_close),
            leg_b: math.log(leg_b_close),
        }
        points.append(
            {
                "timestamp": timestamp,
                "logs": logs,
                "residual": logs[direct] - (leg_a_sign * logs[leg_a] + leg_b_sign * logs[leg_b]),
            }
        )
    return points


def _select_reversion_leg(
    triangle: _Triangle,
    points: list[dict[str, Any]],
    index: int,
    residual_sign: int,
    attribution_bars: int,
) -> tuple[str, int, float] | None:
    direct, leg_a, leg_a_sign, leg_b, leg_b_sign = triangle
    current = points[index]
    prior = points[max(0, index - attribution_bars)]
    current_logs = current["logs"]
    prior_logs = prior["logs"]
    contributions = (
        ("direct", direct, 1, current_logs[direct] - prior_logs[direct]),
        ("synthetic", leg_a, leg_a_sign, -leg_a_sign * (current_logs[leg_a] - prior_logs[leg_a])),
        ("synthetic", leg_b, leg_b_sign, -leg_b_sign * (current_logs[leg_b] - prior_logs[leg_b])),
    )
    aligned = [item for item in contributions if item[3] * residual_sign > 0.0]
    if not aligned:
        return None

    leg_type, symbol, synthetic_sign, contribution = max(aligned, key=lambda item: abs(item[3]))
    attribution_score = abs(float(contribution)) * 10_000.0
    if leg_type == "direct":
        return symbol, -residual_sign, attribution_score
    return symbol, residual_sign * synthetic_sign, attribution_score


def _extreme_sign(
    residual_z: float,
    residual_bps: float,
    entry_zscore: float,
    min_abs_residual_bps: float,
) -> int:
    if abs(residual_z) < entry_zscore or abs(residual_bps) < min_abs_residual_bps:
        return 0
    return 1 if residual_z > 0.0 else -1


def _triangles_for(triangle_set: str) -> tuple[_Triangle, ...]:
    if triangle_set == "outside_view_8":
        return _OUTSIDE_VIEW_8_TRIANGLES
    if triangle_set == "all_available":
        return _OUTSIDE_VIEW_8_TRIANGLES + _ADDITIONAL_AVAILABLE_TRIANGLES
    raise ValueError("triangle_set must be 'outside_view_8' or 'all_available'")


def _triangle_symbols(triangle: _Triangle) -> tuple[str, str, str]:
    return triangle[0], triangle[1], triangle[3]


def _as_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"expected datetime timestamp, got {type(value).__name__}")
    return value


def _positive_finite_float(value: object) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        return None
    return parsed
