from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from quant_strategies.data_contract import NormalizedRows
from quant_strategies.datetime_utils import parse_aware_datetime
from quant_strategies.decisions import StrategyDecision


def audit_observation_dependencies(
    row_index: dict[tuple[str, datetime], list[Mapping[str, Any]]],
    decisions: list[StrategyDecision],
) -> tuple[str, ...]:
    violations: list[str] = []

    for decision in decisions:
        for observation in decision.observations:
            label = f"{observation.symbol} at {observation.timestamp.isoformat()}"
            if observation.timestamp > decision.as_of_time:
                violations.append(
                    f"observation for {decision.instrument.symbol} references future row {label}"
                )
                continue

            matching_rows = row_index.get((observation.symbol, observation.timestamp), [])
            if not matching_rows:
                violations.append(
                    f"missing observation row for {decision.instrument.symbol}: {label}"
                )
                continue

            for row in matching_rows:
                if observation.field is not None and row.get(observation.field) is None:
                    violations.append(
                        f"missing observation field {observation.field} for {label} "
                        f"used by {decision.instrument.symbol}"
                    )
                if "available_at" not in row or row.get("available_at") is None:
                    violations.append(
                        f"missing available_at for observation {label} used by {decision.instrument.symbol}"
                    )
                    continue
                available_value = row.get("available_at")
                if _is_aware_datetime(available_value):
                    available_at = available_value
                    reason = None
                else:
                    available_at, reason = parse_aware_datetime(available_value)
                if available_at is None:
                    violations.append(
                        f"invalid available_at for observation {label} used by "
                        f"{decision.instrument.symbol}: {reason}"
                    )
                    continue
                if available_at > decision.decision_time:
                    violations.append(
                        f"observation row {label} used by {decision.instrument.symbol} "
                        "was available after decision_time"
                    )

    return tuple(violations)


def observation_row_index(
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
) -> tuple[dict[tuple[str, datetime], list[Mapping[str, Any]]], tuple[str, ...]]:
    if isinstance(rows, NormalizedRows):
        return _normalized_observation_row_index(rows)

    index: dict[tuple[str, datetime], list[Mapping[str, Any]]] = {}
    violations: list[str] = []
    for row in rows:
        symbol = str(row.get("symbol"))
        timestamp, reason = parse_aware_datetime(row.get("timestamp"))
        if timestamp is None:
            violations.append(f"invalid timestamp for {symbol}: {reason}")
            continue
        index.setdefault((symbol, timestamp), []).append(row)
    return index, tuple(violations)


def _normalized_observation_row_index(
    rows: NormalizedRows,
) -> tuple[dict[tuple[str, datetime], list[Mapping[str, Any]]], tuple[str, ...]]:
    index: dict[tuple[str, datetime], list[Mapping[str, Any]]] = {}
    for row in rows.projection_rows():
        symbol = row.get("symbol")
        timestamp = row.get("timestamp")
        if isinstance(symbol, str) and _is_aware_datetime(timestamp):
            index.setdefault((symbol, timestamp), []).append(row)
    return index, ()


def _is_aware_datetime(value: object) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )
