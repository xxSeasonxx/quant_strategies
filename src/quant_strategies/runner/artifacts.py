from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from quant_strategies.engine import EVIDENCE_SCHEMA_VERSION
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
        "available_at",
        "open",
        "high",
        "low",
        "close",
        "bid",
        "ask",
        "mid",
        "funding_timestamp",
        "funding_rate",
        "bar_ingested_at",
        "quote_ingested_at",
        "funding_ingested_at",
        "joined_refreshed_at",
        "has_funding_event",
    ]
    write_csv(result_dir / "strategy_input_rows.csv", rows, preferred_fields=preferred_fields)
    write_jsonl(result_dir / "strategy_input_rows.jsonl", rows)


def write_signals(result_dir: Path, signals: list[dict[str, Any]]) -> None:
    write_csv(
        result_dir / "signals.csv",
        signals,
        preferred_fields=[
            "symbol",
            "decision_time",
            "as_of_time",
            "side",
            "weight",
            "hold_bars",
            "max_hold_bars",
            "take_profit_bps",
            "stop_loss_bps",
            "trailing_stop_bps",
            "funding_pressure_bps",
            "entry_return_extension_bps",
            "residual_zscore",
            "residual_bps",
            "attribution_score",
            "signal_family",
        ],
    )


def write_decision_records(result_dir: Path, decisions: list[Any]) -> None:
    lines = [
        decision.model_dump_json()
        if hasattr(decision, "model_dump_json")
        else json.dumps(_json_value(decision), sort_keys=True)
        for decision in decisions
    ]
    (result_dir / "decision_records.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""))


def write_engine_request(result_dir: Path, request_json: str) -> None:
    (result_dir / "engine_request.json").write_text(request_json)


def write_evidence(result_dir: Path, evidence_json: str) -> None:
    (result_dir / "evidence.json").write_text(evidence_json)


def write_data_manifest(result_dir: Path, config: RunConfig, rows: list[dict[str, Any]]) -> None:
    payload = {
        "data": {
            "kind": config.data.kind,
            "dataset": config.data.dataset,
            "symbols": list(config.data.symbols),
            "start": config.data.start.isoformat(),
            "end": config.data.end.isoformat(),
            "strict": config.data.strict,
        },
        "rows": {
            "total": len(rows),
            "by_symbol": _row_ranges_by_symbol(rows),
        },
        "strategy_input_rows_jsonl_sha256": _file_sha256(result_dir / "strategy_input_rows.jsonl"),
        "metadata_field_coverage": _metadata_field_coverage(rows),
    }
    _write_json(result_dir / "data_manifest.json", payload)


def write_run_manifest(
    result_dir: Path,
    *,
    repo_root: Path,
    evidence: dict[str, object],
) -> None:
    payload = {
        "repository": _git_identity(repo_root, result_dir),
        "python": {"version": sys.version.split()[0]},
        "packages": _package_versions(["quant-strategies", "quant-data", "pydantic"]),
        "engine": {"evidence_schema": EVIDENCE_SCHEMA_VERSION},
        "evidence": evidence,
        "artifacts": _artifact_hashes(result_dir),
    }
    _write_json(result_dir / "run_manifest.json", payload)


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
    if isinstance(value, Mapping | list | tuple):
        return json.dumps(_json_value(value), sort_keys=True)
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    return value


def _row_ranges_by_symbol(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
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
        summary["min_timestamp"] = _json_value(summary["min_timestamp"])
        summary["max_timestamp"] = _json_value(summary["max_timestamp"])
    return dict(sorted(by_symbol.items()))


def _metadata_field_coverage(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    fields = (
        "available_at",
        "bar_ingested_at",
        "quote_ingested_at",
        "funding_ingested_at",
        "joined_refreshed_at",
    )
    coverage: dict[str, dict[str, int]] = {}
    total = len(rows)
    for field in fields:
        if any(field in row for row in rows):
            coverage[field] = {
                "present": sum(1 for row in rows if row.get(field) is not None),
                "total": total,
            }
    return coverage


def _artifact_hashes(result_dir: Path) -> dict[str, dict[str, str]]:
    hashes: dict[str, dict[str, str]] = {}
    for path in sorted(result_dir.iterdir()):
        if not path.is_file() or path.name in {"run_manifest.json", "summary.json"}:
            continue
        hashes[path.name] = {"sha256": _file_sha256(path)}
    return hashes


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_versions(package_names: list[str]) -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in package_names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _git_identity(repo_root: Path, result_dir: Path) -> dict[str, Any]:
    status = _git_output(
        repo_root,
        *_git_scoped_args(repo_root, result_dir, "status", "--porcelain", "--untracked-files=all"),
    )
    diff = _git_output(
        repo_root,
        *_git_scoped_args(repo_root, result_dir, "diff", "--binary", "HEAD"),
    )
    return {
        "commit": _git_output(repo_root, "rev-parse", "HEAD"),
        "short_commit": _git_output(repo_root, "rev-parse", "--short", "HEAD"),
        "dirty": None if status is None else bool(status),
        "status_porcelain_sha256": _text_sha256(status) if status else None,
        "tracked_diff_sha256": _text_sha256(diff) if diff else None,
    }


def _git_scoped_args(repo_root: Path, result_dir: Path, *args: str) -> list[str]:
    try:
        relative_result_dir = result_dir.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return list(args)
    return [*args, "--", ".", f":(exclude){relative_result_dir.as_posix()}"]


def _git_output(repo_root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.rstrip("\n")


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _artifact_names(result_dir: Path, *, include_summary: bool) -> list[str]:
    names = {path.name for path in result_dir.iterdir() if path.is_file()}
    if include_summary:
        names.add("summary.json")
    return sorted(names)


def _safe_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return name or "strategy"
