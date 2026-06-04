from __future__ import annotations

import math
import numbers
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from quant_strategies.evaluation.metrics import finite_metric_or_none
from quant_strategies.evaluation.results import PreparedPortfolioInputs
from quant_strategies.evaluation.scenarios import EvaluationScenario


@dataclass(frozen=True)
class ReturnCoverage:
    observed: tuple[float, ...]
    total_count: int
    sample_count: int
    nonfinite_count: int


def prepared_decision_windows(
    prepared: PreparedPortfolioInputs,
    scenario: EvaluationScenario,
) -> list[dict[str, Any]]:
    entry_lag = fill_lag(scenario, "entry_lag_bars", default=1)
    exit_lag = fill_lag(scenario, "exit_lag_bars", default=0)
    windows: list[dict[str, Any]] = []

    for item, decision_idx in zip(prepared.decisions, prepared.decision_positions, strict=True):
        symbol = item.instrument.symbol
        symbol_index = prepared.symbol_indexes[symbol]

        entry_idx = decision_idx + entry_lag
        if entry_idx >= len(symbol_index):
            raise ValueError(f"unfillable_entry:{symbol}:{item.decision_time.isoformat()}")
        entry_time = symbol_index[entry_idx]

        exit_idx = entry_idx + item.exit_policy.max_hold_bars + exit_lag
        if exit_idx >= len(symbol_index):
            raise ValueError(f"unfillable_exit:{symbol}:{item.decision_time.isoformat()}")
        exit_time = symbol_index[exit_idx]

        windows.append(
            {
                "decision": item,
                "symbol": symbol,
                "entry_idx": entry_idx,
                "exit_idx": exit_idx,
                "entry_time": entry_time,
                "exit_time": exit_time,
                "allow_same_symbol_touching": prepared.data_kind == "crypto_perp_funding",
            }
        )

    validate_max_gross_target_weight(windows)
    validate_duplicate_signals(windows)
    validate_overlapping_symbol_windows(windows)
    return windows


def validate_max_gross_target_weight(windows: list[dict[str, Any]]) -> float:
    max_gross = 0.0
    gross = 0.0
    events: list[tuple[Any, int, float]] = []
    for window in windows:
        weight = abs(float(window["decision"].target.size))
        events.append((window["exit_time"], 0, -weight))
        events.append((window["entry_time"], 1, weight))
    for timestamp, _event_order, delta in sorted(events, key=lambda item: (item[0], item[1])):
        gross += delta
        if gross < 1e-12:
            gross = 0.0
        max_gross = max(max_gross, gross)
        if gross > 1.0 + 1e-12:
            raise ValueError(f"portfolio_target_weight_exceeds_one:{timestamp.isoformat()}:{gross}")
    return max_gross


def validate_duplicate_signals(windows: list[dict[str, Any]]) -> None:
    entry_signals: set[tuple[str, Any]] = set()
    exit_signals: set[tuple[str, Any]] = set()
    for window in windows:
        symbol = window["symbol"]
        entry_time = window["entry_time"]
        exit_time = window["exit_time"]
        entry_key = (symbol, entry_time)
        if entry_key in entry_signals:
            raise ValueError(f"duplicate_entry_signal:{symbol}:{entry_time.isoformat()}")
        exit_key = (symbol, exit_time)
        if exit_key in exit_signals:
            raise ValueError(f"duplicate_exit_signal:{symbol}:{exit_time.isoformat()}")
        entry_signals.add(entry_key)
        exit_signals.add(exit_key)


def validate_overlapping_symbol_windows(windows: list[dict[str, Any]]) -> None:
    previous_by_symbol: dict[str, dict[str, Any]] = {}
    sorted_windows = sorted(windows, key=lambda item: (item["symbol"], item["entry_idx"], item["exit_idx"]))
    for window in sorted_windows:
        symbol = window["symbol"]
        previous = previous_by_symbol.get(symbol)
        if previous is None:
            previous_by_symbol[symbol] = window
            continue
        allow_touching = bool(window.get("allow_same_symbol_touching"))
        windows_overlap = (
            window["entry_idx"] < previous["exit_idx"]
            if allow_touching
            else window["entry_idx"] <= previous["exit_idx"]
        )
        if windows_overlap:
            raise ValueError(
                f"overlapping_decision_window:{symbol}:"
                f"{window['entry_time'].isoformat()}:{window['exit_time'].isoformat()}"
            )
        if window["exit_idx"] > previous["exit_idx"]:
            previous_by_symbol[symbol] = window


def index_position(pd: Any, index: Any, value: Any) -> int | None:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    position = index.get_indexer([timestamp])[0]
    if position == -1:
        return None
    return int(position)


def fill_lag(scenario: EvaluationScenario, field: str, *, default: int) -> int:
    value = getattr(scenario.fill_model, field, default)
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"invalid_fill_lag:{field}:{value}")
    float_value = float(value)
    if not math.isfinite(float_value) or not float_value.is_integer() or float_value < 0.0:
        raise ValueError(f"invalid_fill_lag:{field}:{value}")
    return int(float_value)


def cost_bps_fraction(scenario: EvaluationScenario, field: str) -> float:
    value = getattr(scenario.cost_model, field, 0.0)
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"invalid_cost_bps:{field}:{value}")
    float_value = float(value)
    if not math.isfinite(float_value) or float_value < 0.0:
        raise ValueError(f"invalid_cost_bps:{field}:{value}")
    return float_value / 10_000.0


def funding_cashflows_frame(pd: Any, rows: Sequence[Mapping[str, Any]]) -> Any:
    return pd.DataFrame.from_records(
        rows,
        columns=(
            "scenario_id",
            "timestamp",
            "asset",
            "funding_rate",
            "position_units",
            "mark_price",
            "funding_cashflow",
        ),
    )


def target_positions_frame(pd: Any, windows: list[dict[str, Any]], scenario_id: str) -> Any:
    if not windows:
        return pd.DataFrame(
            {
                "scenario_id": [],
                "timestamp": [],
                "asset": [],
                "target_weight": [],
                "event": [],
                "decision_time": [],
                "direction": [],
            }
        )
    return pd.DataFrame(
        [
            record
            for window in windows
            for record in (
                {
                    "scenario_id": scenario_id,
                    "timestamp": window["entry_time"],
                    "asset": window["symbol"],
                    "target_weight": signed_target_weight(window),
                    "event": "entry",
                    "decision_time": window["decision"].decision_time,
                    "direction": window["decision"].target.direction,
                },
                {
                    "scenario_id": scenario_id,
                    "timestamp": window["exit_time"],
                    "asset": window["symbol"],
                    "target_weight": 0.0,
                    "event": "exit",
                    "decision_time": window["decision"].decision_time,
                    "direction": window["decision"].target.direction,
                },
            )
        ]
    )


def target_exposure_summary_frame(pd: Any, windows: list[dict[str, Any]], scenario_id: str) -> Any:
    if not windows:
        return pd.DataFrame(
            {
                "scenario_id": [],
                "asset": [],
                "decision_count": [],
                "target_round_trip_turnover": [],
            }
        )
    by_asset: dict[str, dict[str, float | int | str]] = {}
    for window in windows:
        asset = window["symbol"]
        metrics = by_asset.setdefault(
            asset,
            {
                "scenario_id": scenario_id,
                "asset": asset,
                "decision_count": 0,
                "target_round_trip_turnover": 0.0,
            },
        )
        metrics["decision_count"] = int(metrics["decision_count"]) + 1
        metrics["target_round_trip_turnover"] = float(metrics["target_round_trip_turnover"]) + (
            2.0 * abs(float(window["decision"].target.size))
        )
    return pd.DataFrame(list(by_asset.values()))


def signed_target_weight(window: Mapping[str, Any]) -> float:
    weight = float(window["decision"].target.size)
    return -weight if window["decision"].target.direction == "short" else weight


def required_final_metric(name: str, values: Any | None) -> float:
    sampled_values = series_values(values)
    if not sampled_values:
        raise ValueError(f"invalid_required_metric:{name}")
    metric = finite_metric_or_none(sampled_values[-1])
    if metric is None:
        raise ValueError(f"invalid_required_metric:{name}")
    return metric


def observed_returns(returns: Any | None) -> list[float]:
    return list(return_coverage(returns).observed)


def return_coverage(returns: Any | None) -> ReturnCoverage:
    values = series_values(returns)
    sampled_values = values[1:]
    observed = tuple(
        float(metric)
        for value in sampled_values
        if (metric := finite_metric_or_none(value)) is not None
    )
    return ReturnCoverage(
        observed=observed,
        total_count=len(sampled_values),
        sample_count=len(observed),
        nonfinite_count=len(sampled_values) - len(observed),
    )


def series_values(values: Any | None) -> list[Any]:
    if values is None:
        return []
    if hasattr(values, "tolist"):
        return list(values.tolist())
    if hasattr(values, "to_numpy"):
        raw_values = values.to_numpy()
        if hasattr(raw_values, "ravel"):
            return list(raw_values.ravel())
        return list(raw_values)
    if hasattr(values, "_values"):
        return list(values._values)
    try:
        return list(values)
    except TypeError:
        return []


def sample_stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def downside_deviation(values: Sequence[float], annualization_periods_per_year: int) -> float | None:
    downside_returns = [value for value in values if value < 0.0]
    if not downside_returns:
        return None
    periodic_deviation = math.sqrt(sum(value**2 for value in downside_returns) / len(values))
    annualized_deviation = periodic_deviation * math.sqrt(annualization_periods_per_year)
    return annualized_deviation if annualized_deviation > 0.0 else None
