from __future__ import annotations

import csv
import json
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from quant_strategies.runner.config import RunConfig


def create_result_dir(config: RunConfig, *, now: datetime | None = None) -> Path:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    base_name = f"{timestamp}-{_safe_name(config.strategy_id)}"
    config.output.results_dir.mkdir(parents=True, exist_ok=True)
    result_dir = config.output.results_dir / base_name
    suffix = 2
    while result_dir.exists():
        result_dir = config.output.results_dir / f"{base_name}-{suffix}"
        suffix += 1
    result_dir.mkdir(parents=True)
    return result_dir


def initialize_run_artifacts(config_path: Path, config: RunConfig, result_dir: Path) -> None:
    shutil.copyfile(config_path, result_dir / "config.toml")
    if config.strategy_path.is_file():
        shutil.copyfile(config.strategy_path, result_dir / "strategy_snapshot.py")


def write_strategy_input_rows(result_dir: Path, rows: list[dict[str, Any]]) -> None:
    preferred_fields = [
        "symbol",
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "bid",
        "ask",
        "mid",
        "funding_timestamp",
        "funding_rate",
        "has_funding_event",
    ]
    write_csv(result_dir / "strategy_input_rows.csv", rows, preferred_fields=preferred_fields)
    write_jsonl(result_dir / "strategy_input_rows.jsonl", rows)


def write_signals(result_dir: Path, signals: list[dict[str, Any]]) -> None:
    write_csv(result_dir / "signals.csv", signals, preferred_fields=["symbol", "decision_time", "side", "weight", "hold_bars"])


def write_engine_request(result_dir: Path, request_json: str) -> None:
    (result_dir / "engine_request.json").write_text(request_json)


def write_evidence(result_dir: Path, evidence_json: str) -> None:
    (result_dir / "evidence.json").write_text(evidence_json)


def write_summary(result_dir: Path, summary: dict[str, Any]) -> None:
    payload = dict(summary)
    payload["artifacts"] = _artifact_names(result_dir, include_summary=True)
    _write_json(result_dir / "summary.json", payload)


def write_notes(result_dir: Path, notes: str) -> None:
    (result_dir / "notes.md").write_text(notes.rstrip() + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(_json_value(row), sort_keys=True) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]], *, preferred_fields: list[str]) -> None:
    fields = _ordered_fields(rows, preferred_fields)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fields})


def _ordered_fields(rows: list[dict[str, Any]], preferred: list[str]) -> list[str]:
    if not rows:
        return preferred
    keys = {key for row in rows for key in row}
    ordered = [key for key in preferred if key in keys]
    ordered.extend(sorted(keys.difference(ordered)))
    return ordered


def _csv_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    return value


def _artifact_names(result_dir: Path, *, include_summary: bool) -> list[str]:
    names = {path.name for path in result_dir.iterdir() if path.is_file()}
    if include_summary:
        names.add("summary.json")
    return sorted(names)


def _safe_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return name or "strategy"
