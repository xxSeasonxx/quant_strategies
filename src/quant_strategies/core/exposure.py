from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from quant_strategies.core.config import FillModelConfig
from quant_strategies.data_contract import NormalizedRows
from quant_strategies.decisions import StrategyDecision

_EXPOSURE_TOLERANCE = 1e-12


@dataclass(frozen=True)
class ExposureWindow:
    symbol: str
    entry_time: datetime
    exit_time: datetime
    target_weight: float


def exposure_admissibility_violations(
    decisions: Sequence[StrategyDecision],
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
    fill_model: FillModelConfig,
) -> tuple[str, ...]:
    violations: list[str] = []
    windows: list[ExposureWindow] = []
    timestamps_by_symbol = _timestamps_by_symbol(rows)

    for index, decision in enumerate(decisions):
        if decision.target.sizing_kind != "target_weight":
            continue
        if decision.target.direction not in {"long", "short"}:
            continue
        size = float(decision.target.size)
        if size > 1.0 + _EXPOSURE_TOLERANCE:
            violations.append(
                "leveraged_target_weight:"
                f"decision[{index}]:{decision.instrument.symbol}:size={size:g}"
            )
            continue
        window = _exposure_window(decision, timestamps_by_symbol, fill_model)
        if window is not None:
            windows.append(window)

    gross_violation = _gross_exposure_violation(windows)
    if gross_violation is not None:
        violations.append(gross_violation)
    return tuple(dict.fromkeys(violations))


def _timestamps_by_symbol(
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
) -> dict[str, tuple[datetime, ...]]:
    projection = rows.projection_rows() if isinstance(rows, NormalizedRows) else rows
    grouped: dict[str, list[datetime]] = {}
    for row in projection:
        symbol = row.get("symbol")
        timestamp = row.get("timestamp")
        if isinstance(symbol, str) and _is_aware_datetime(timestamp):
            grouped.setdefault(symbol, []).append(timestamp)
    return {
        symbol: tuple(sorted(dict.fromkeys(timestamps))) for symbol, timestamps in grouped.items()
    }


def _exposure_window(
    decision: StrategyDecision,
    timestamps_by_symbol: Mapping[str, tuple[datetime, ...]],
    fill_model: FillModelConfig,
) -> ExposureWindow | None:
    symbol = decision.instrument.symbol
    timestamps = timestamps_by_symbol.get(symbol, ())
    try:
        decision_index = timestamps.index(decision.decision_time)
    except ValueError:
        return None
    entry_index = decision_index + fill_model.entry_lag_bars
    exit_index = entry_index + decision.exit_policy.max_hold_bars + fill_model.exit_lag_bars
    if entry_index >= len(timestamps) or exit_index >= len(timestamps):
        return None
    return ExposureWindow(
        symbol=symbol,
        entry_time=timestamps[entry_index],
        exit_time=timestamps[exit_index],
        target_weight=abs(float(decision.target.size)),
    )


def _gross_exposure_violation(windows: Sequence[ExposureWindow]) -> str | None:
    gross = 0.0
    events: list[tuple[datetime, int, float]] = []
    for window in windows:
        events.append((window.exit_time, 0, -window.target_weight))
        events.append((window.entry_time, 1, window.target_weight))
    for timestamp, _event_order, delta in sorted(events, key=lambda item: (item[0], item[1])):
        gross += delta
        if gross < _EXPOSURE_TOLERANCE:
            gross = 0.0
        if gross > 1.0 + _EXPOSURE_TOLERANCE:
            return f"portfolio_target_weight_exceeds_one:{timestamp.isoformat()}:{gross:g}"
    return None


def _is_aware_datetime(value: object) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )
