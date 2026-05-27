from __future__ import annotations

import csv
import json
import re
import shutil
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_strategies.engine import EVIDENCE_SCHEMA_VERSION
from quant_strategies.provenance import (
    artifact_hashes,
    file_sha256,
    git_identity,
    package_versions,
    python_identity,
)
from quant_strategies.runner.config import RunConfig
from quant_strategies.runner.artifact_profiles import json_safe_value, row_ranges_by_symbol


def create_result_dir(config: RunConfig, *, now: datetime | None = None) -> Path:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    base_name = f"{timestamp}-{_safe_name(config.strategy_id)}"
    config.output.results_dir.mkdir(parents=True, exist_ok=True)
    result_dir = config.output.results_dir / base_name
    suffix = 2
    while True:
        try:
            result_dir.mkdir()
        except FileExistsError:
            result_dir = config.output.results_dir / f"{base_name}-{suffix}"
            suffix += 1
            continue
        return result_dir


def initialize_run_artifacts(config_path: Path, config: RunConfig, result_dir: Path) -> None:
    shutil.copyfile(config_path, result_dir / "config.toml")
    if config.strategy_path.is_file():
        shutil.copyfile(config.strategy_path, result_dir / "strategy_snapshot.py")


def write_strategy_input_rows(result_dir: Path, rows: list[dict[str, Any]]) -> str:
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
    jsonl_path = result_dir / "strategy_input_rows.jsonl"
    write_jsonl(jsonl_path, rows)
    return _file_sha256(jsonl_path)


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
        else json.dumps(json_safe_value(decision), sort_keys=True)
        for decision in decisions
    ]
    (result_dir / "decision_records.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""))


def write_engine_request(result_dir: Path, request_json: str) -> None:
    (result_dir / "engine_request.json").write_text(request_json)


def write_evidence(result_dir: Path, evidence_json: str) -> None:
    (result_dir / "evidence.json").write_text(evidence_json)


def evidence_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    present = sum(1 for row in rows if row.get("available_at") is not None)
    fraction = None if total == 0 else present / total
    if total > 0 and present == total:
        status = "complete"
        warnings = ["runner_causality_not_verified"]
    elif present > 0:
        status = "partial"
        warnings = ["available_at_partial", "runner_causality_not_verified"]
    else:
        status = "missing"
        warnings = ["available_at_missing", "runner_causality_not_verified"]
    return {
        "data_availability_status": status,
        "availability_coverage": {
            "field": "available_at",
            "present": present,
            "total": total,
            "fraction": fraction,
        },
        "causality_verified": False,
        "evidence_quality_warnings": warnings,
    }


def write_data_manifest(
    result_dir: Path,
    config: RunConfig,
    rows: list[dict[str, Any]],
    *,
    strategy_input_rows_jsonl_sha256: str | None,
    normalized_rows_hash: str,
) -> None:
    quality = evidence_quality(rows)
    payload = {
        "artifact_profile": config.output.artifact_profile,
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
            "by_symbol": row_ranges_by_symbol(rows),
        },
        "strategy_input_rows_jsonl_sha256": strategy_input_rows_jsonl_sha256,
        "normalized_rows_sha256": normalized_rows_hash,
        "metadata_field_coverage": _metadata_field_coverage(rows),
        **quality,
    }
    _write_json(result_dir / "data_manifest.json", payload)


def write_run_manifest(
    result_dir: Path,
    *,
    repo_root: Path,
    evidence: dict[str, object],
    artifact_profile: str,
) -> None:
    payload = {
        "repository": _git_identity(repo_root, result_dir),
        "python": python_identity(),
        "packages": _package_versions(["quant-strategies", "quant-data", "pydantic"]),
        "engine": {"evidence_schema": EVIDENCE_SCHEMA_VERSION},
        "artifact_profile": artifact_profile,
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
            handle.write(json.dumps(json_safe_value(row), sort_keys=True) + "\n")


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
        return json.dumps(json_safe_value(value), sort_keys=True)
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


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
    return artifact_hashes(
        result_dir,
        exclude_names={"run_manifest.json", "summary.json"},
        recursive=False,
    )


def _file_sha256(path: Path) -> str:
    return file_sha256(path)


def _package_versions(package_names: list[str]) -> dict[str, str | None]:
    return package_versions(package_names)


def _git_identity(repo_root: Path, result_dir: Path) -> dict[str, Any]:
    return git_identity(repo_root, exclude_paths=(result_dir,))


def _artifact_names(result_dir: Path, *, include_summary: bool) -> list[str]:
    names = {path.name for path in result_dir.iterdir() if path.is_file()}
    if include_summary:
        names.add("summary.json")
    return sorted(names)


def _safe_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return name or "strategy"
