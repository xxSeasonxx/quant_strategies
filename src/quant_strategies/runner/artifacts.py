from __future__ import annotations

import csv
import json
import re
import shutil
from datetime import datetime, timezone
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
    if config.strategy_path.exists():
        shutil.copyfile(config.strategy_path, result_dir / "strategy_snapshot.py")


def write_success_artifacts(
    result_dir: Path,
    *,
    bars: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    request_json: str,
    screen_summary: dict[str, Any] | None,
    validate_summary: dict[str, Any] | None,
    evidence_json: str,
    notes: str,
) -> None:
    write_csv(result_dir / "bars.csv", bars, preferred_fields=["symbol", "timestamp", "open", "high", "low", "close", "bid", "ask", "mid"])
    write_csv(result_dir / "signals.csv", signals, preferred_fields=["symbol", "decision_time", "side", "weight", "hold_bars"])
    (result_dir / "request.json").write_text(request_json)
    _write_json(result_dir / "screen_summary.json", screen_summary or {})
    _write_json(result_dir / "validate_summary.json", validate_summary or {})
    (result_dir / "evidence.json").write_text(evidence_json)
    write_notes(result_dir, notes)


def write_notes(result_dir: Path, notes: str) -> None:
    (result_dir / "notes.md").write_text(notes.rstrip() + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]], *, preferred_fields: list[str]) -> None:
    fields = _ordered_fields(rows, preferred_fields)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fields})


def _ordered_fields(rows: list[dict[str, Any]], preferred: list[str]) -> list[str]:
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


def _safe_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return name or "strategy"
