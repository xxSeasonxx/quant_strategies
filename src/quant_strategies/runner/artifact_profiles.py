from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from quant_strategies.core.serialization import json_safe_value, normalized_rows_sha256
from quant_strategies.decisions import StrategyDecision
from quant_strategies.evidence_semantics import replayable_from_artifacts_for_profile, trade_result_metric_semantics
from quant_strategies.runner.config import RunConfig


SUMMARY_SAMPLE_SIZE = 5


def summary_profile_payload(
    *,
    config: RunConfig,
    rows: Sequence[Mapping[str, Any]],
    decisions: Sequence[StrategyDecision],
    engine: Mapping[str, Any],
    normalized_rows_hash: str | None = None,
    row_ranges: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "artifact_profile": "summary",
        "replayable_from_artifacts": replayable_from_artifacts_for_profile("summary"),
        "strategy_id": config.strategy_id,
        "quick_checks": config.output.quick_checks,
        "rows": _rows_profile_payload(
            config,
            rows,
            normalized_rows_hash=normalized_rows_hash,
            row_ranges=row_ranges,
        ),
        "decisions": _decision_summary(decisions),
        "engine": json_safe_value(engine),
        "metric_semantics": trade_result_metric_semantics(config.data.kind),
    }


def write_summary_profile_artifact(
    result_dir: Path,
    *,
    config: RunConfig,
    rows: Sequence[Mapping[str, Any]],
    decisions: Sequence[StrategyDecision],
    engine: Mapping[str, Any],
    normalized_rows_hash: str | None = None,
    row_ranges: Mapping[str, Mapping[str, Any]] | None = None,
) -> Path:
    path = result_dir / "artifact_profile_summary.json"
    payload = summary_profile_payload(
        config=config,
        rows=rows,
        decisions=decisions,
        engine=engine,
        normalized_rows_hash=normalized_rows_hash,
        row_ranges=row_ranges,
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


def _rows_profile_payload(
    config: RunConfig,
    rows: Sequence[Mapping[str, Any]],
    *,
    normalized_rows_hash: str | None,
    row_ranges: Mapping[str, Mapping[str, Any]] | None,
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
        "by_symbol": dict(row_ranges) if row_ranges is not None else row_ranges_by_symbol(rows),
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


def _iso_or_none(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
