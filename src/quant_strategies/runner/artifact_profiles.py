from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from quant_strategies.decisions import StrategyDecision
from quant_strategies.evidence_semantics import artifact_trust_tier_for_profile, smoke_score_metric_semantics
from quant_strategies.runner.config import RunConfig


SUMMARY_SAMPLE_SIZE = 5


def normalized_rows_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for line in iter_canonical_row_lines(rows):
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def canonical_rows_jsonl(rows: Sequence[Mapping[str, Any]]) -> str:
    lines = list(canonical_row_lines(rows))
    return "\n".join(lines) + ("\n" if lines else "")


def canonical_row_lines(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(iter_canonical_row_lines(rows))


def iter_canonical_row_lines(rows: Iterable[Mapping[str, Any]]) -> Iterable[str]:
    for row in rows:
        yield canonical_row_line(row)


def canonical_row_line(row: Mapping[str, Any]) -> str:
    return json.dumps(json_safe_value(row), sort_keys=True, separators=(",", ":"), allow_nan=False)


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
        "artifact_trust_tier": artifact_trust_tier_for_profile("summary"),
        "strategy_id": config.strategy_id,
        "rows": _rows_profile_payload(
            config,
            rows,
            normalized_rows_hash=normalized_rows_hash,
            row_ranges=row_ranges,
        ),
        "decisions": _decision_summary(decisions),
        "engine": json_safe_value(engine),
        "metric_semantics": smoke_score_metric_semantics(config.data.kind),
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
