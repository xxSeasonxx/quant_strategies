from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from quant_strategies.decisions import StrategyDecision
from quant_strategies.provenance import text_sha256
from quant_strategies.runner.config import RunConfig


SUMMARY_SAMPLE_SIZE = 5


def normalized_rows_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        json.dumps(json_safe_value(row), sort_keys=True, separators=(",", ":"), allow_nan=False)
        for row in rows
    ]
    return text_sha256("\n".join(lines) + ("\n" if lines else ""))


def summary_profile_payload(
    *,
    config: RunConfig,
    rows: Sequence[Mapping[str, Any]],
    decisions: Sequence[StrategyDecision],
    signals: Sequence[Mapping[str, Any]],
    engine: Mapping[str, Any],
    normalized_rows_hash: str | None = None,
) -> dict[str, Any]:
    return {
        "artifact_profile": "summary",
        "strategy_id": config.strategy_id,
        "rows": _row_summary(config, rows, normalized_rows_hash=normalized_rows_hash),
        "decisions": _decision_summary(decisions),
        "signals": _signal_summary(signals),
        "engine": json_safe_value(engine),
    }


def write_summary_profile_artifact(
    result_dir: Path,
    *,
    config: RunConfig,
    rows: Sequence[Mapping[str, Any]],
    decisions: Sequence[StrategyDecision],
    signals: Sequence[Mapping[str, Any]],
    engine: Mapping[str, Any],
    normalized_rows_hash: str | None = None,
) -> Path:
    path = result_dir / "artifact_profile_summary.json"
    payload = summary_profile_payload(
        config=config,
        rows=rows,
        decisions=decisions,
        signals=signals,
        engine=engine,
        normalized_rows_hash=normalized_rows_hash,
    )
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return path


def row_ranges_by_symbol(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    by_symbol: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("symbol", ""))
        timestamp = row.get("timestamp")
        summary = by_symbol.setdefault(
            symbol,
            {"count": 0, "min_timestamp": None, "max_timestamp": None},
        )
        summary["count"] += 1
        if timestamp is None:
            continue
        if summary["min_timestamp"] is None or timestamp < summary["min_timestamp"]:
            summary["min_timestamp"] = timestamp
        if summary["max_timestamp"] is None or timestamp > summary["max_timestamp"]:
            summary["max_timestamp"] = timestamp

    for summary in by_symbol.values():
        summary["min_timestamp"] = json_safe_value(summary["min_timestamp"])
        summary["max_timestamp"] = json_safe_value(summary["max_timestamp"])
    return dict(sorted(by_symbol.items()))


def json_safe_value(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if hasattr(value, "item") and callable(value.item):
        try:
            return json_safe_value(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, Mapping):
        return {str(key): json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe_value(item) for item in value]
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return str(value)
    return value


def _row_summary(
    config: RunConfig,
    rows: Sequence[Mapping[str, Any]],
    *,
    normalized_rows_hash: str | None,
) -> dict[str, Any]:
    sample = [json_safe_value(row) for row in rows[:SUMMARY_SAMPLE_SIZE]]
    return {
        "kind": config.data.kind,
        "dataset": config.data.dataset,
        "symbols": list(config.data.symbols),
        "start": config.data.start.isoformat(),
        "end": config.data.end.isoformat(),
        "row_count": len(rows),
        "sample_count": len(sample),
        "sample": sample,
        "normalized_rows_sha256": normalized_rows_hash or normalized_rows_sha256(rows),
        "by_symbol": row_ranges_by_symbol(rows),
    }


def _decision_summary(decisions: Sequence[StrategyDecision]) -> dict[str, Any]:
    symbols = Counter(item.instrument.symbol for item in decisions)
    directions = Counter(item.target.direction for item in decisions)
    instrument_kinds = Counter(item.instrument.kind for item in decisions)
    intents = Counter(item.intent.action for item in decisions)
    sizing_kinds = Counter(item.target.sizing_kind for item in decisions)
    decision_times = [item.decision_time for item in decisions]
    return {
        "count": len(decisions),
        "by_symbol": dict(sorted(symbols.items())),
        "by_direction": dict(sorted(directions.items())),
        "by_instrument_kind": dict(sorted(instrument_kinds.items())),
        "by_intent": dict(sorted(intents.items())),
        "by_sizing_kind": dict(sorted(sizing_kinds.items())),
        "min_decision_time": _iso_or_none(min(decision_times) if decision_times else None),
        "max_decision_time": _iso_or_none(max(decision_times) if decision_times else None),
    }


def _signal_summary(signals: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    symbols = Counter(str(item.get("symbol", "")) for item in signals)
    sides = Counter(str(item.get("side", "")) for item in signals)
    return {
        "count": len(signals),
        "by_symbol": dict(sorted(symbols.items())),
        "by_side": dict(sorted(sides.items())),
    }


def _iso_or_none(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
