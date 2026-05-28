from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from quant_strategies.datetime_utils import parse_aware_datetime
from quant_strategies.engine import EVIDENCE_SCHEMA_VERSION
from quant_strategies.evidence_semantics import artifact_trust_tier_for_profile, smoke_score_metric_semantics
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
    jsonl_path = result_dir / "strategy_input_rows.jsonl"
    write_jsonl(jsonl_path, rows)
    return _file_sha256(jsonl_path)


def write_decision_records(result_dir: Path, decisions: list[Any]) -> None:
    lines = [_canonical_json_line(decision) for decision in decisions]
    (result_dir / "decision_records.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""))


def write_engine_request(result_dir: Path, request_json: str) -> None:
    (result_dir / "engine_request.json").write_text(request_json)


def write_evidence(result_dir: Path, evidence_json: str) -> None:
    (result_dir / "evidence.json").write_text(evidence_json)


def evidence_quality(
    config: RunConfig,
    rows: list[dict[str, Any]],
    *,
    causality_verified: bool = False,
) -> dict[str, Any]:
    total = len(rows)
    present = 0
    invalid = 0
    for row in rows:
        value = row.get("available_at")
        if value is None:
            continue
        parsed, _ = parse_aware_datetime(value)
        if parsed is None:
            invalid += 1
            continue
        present += 1
    fraction = None if total == 0 else present / total
    if total > 0 and present == total:
        status = "complete"
    elif invalid > 0:
        status = "invalid"
    elif present > 0:
        status = "partial"
    else:
        status = "missing"
    coverage: dict[str, Any] = {
        "field": "available_at",
        "present": present,
        "total": total,
        "fraction": fraction,
    }
    if invalid:
        coverage["invalid"] = invalid
    payload = {
        "data_availability_status": status,
        "availability_coverage": coverage,
        "row_contract": row_contract_status(config, rows),
    }
    payload.update(_causality_evidence(status, causality_verified=causality_verified))
    return payload


def with_causality_verification(
    evidence_quality_payload: Mapping[str, Any],
    *,
    causality_verified: bool,
) -> dict[str, Any]:
    payload = dict(evidence_quality_payload)
    payload.update(
        _causality_evidence(
            payload.get("data_availability_status"),
            causality_verified=causality_verified,
        )
    )
    return payload


def _causality_evidence(
    data_availability_status: object,
    *,
    causality_verified: bool,
) -> dict[str, Any]:
    if data_availability_status == "complete":
        verified = causality_verified
        warnings = [] if verified else ["runner_causality_not_verified"]
    elif data_availability_status == "invalid":
        verified = False
        warnings = ["available_at_invalid", "runner_causality_not_verified"]
    elif data_availability_status == "partial":
        verified = False
        warnings = ["available_at_partial", "runner_causality_not_verified"]
    else:
        verified = False
        warnings = ["available_at_missing", "runner_causality_not_verified"]
    return {
        "causality_verified": verified,
        "evidence_quality_warnings": warnings,
    }


def row_contract_status(config: RunConfig, rows: list[dict[str, Any]]) -> dict[str, Any]:
    required_fields = _required_row_fields(config)
    if not rows:
        return {
            "data_kind": config.data.kind,
            "status": "not_evaluated",
            "required_fields": list(required_fields),
            "missing_required_fields": {},
            "timestamp_status": "empty",
            "duplicate_key_count": 0,
            "funding_event_missing_fields": {},
            "freshness_status": "not_evaluated",
            "quant_data_feedback": ["row_contract_not_evaluated:no_rows"],
        }
    missing_required_fields = {
        field: count
        for field in required_fields
        if (count := sum(1 for row in rows if row.get(field) is None)) > 0
    }
    duplicate_key_count = _duplicate_key_count(rows)
    timestamp_status = _timestamp_status(rows)
    funding_event_missing_fields = _funding_event_missing_fields(config, rows)
    feedback = _row_contract_feedback(
        missing_required_fields=missing_required_fields,
        duplicate_key_count=duplicate_key_count,
        timestamp_status=timestamp_status,
        funding_event_missing_fields=funding_event_missing_fields,
    )
    return {
        "data_kind": config.data.kind,
        "status": "passed" if not feedback else "failed",
        "required_fields": list(required_fields),
        "missing_required_fields": missing_required_fields,
        "timestamp_status": timestamp_status,
        "duplicate_key_count": duplicate_key_count,
        "funding_event_missing_fields": funding_event_missing_fields,
        "freshness_status": "not_evaluated",
        "quant_data_feedback": feedback,
    }


def write_data_manifest(
    result_dir: Path,
    config: RunConfig,
    rows: list[dict[str, Any]],
    *,
    strategy_input_rows_jsonl_sha256: str | None,
    normalized_rows_hash: str,
    evidence_quality_payload: dict[str, Any] | None = None,
) -> None:
    quality = evidence_quality_payload or evidence_quality(config, rows)
    payload = {
        "artifact_profile": config.output.artifact_profile,
        "artifact_trust_tier": artifact_trust_tier_for_profile(config.output.artifact_profile),
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
        "metric_semantics": smoke_score_metric_semantics(config.data.kind),
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
        "artifact_trust_tier": artifact_trust_tier_for_profile(artifact_profile),
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


def _canonical_json_line(value: Any) -> str:
    if hasattr(value, "model_dump"):
        payload = value.model_dump(mode="json")
    else:
        payload = json_safe_value(value)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


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


def _required_row_fields(config: RunConfig) -> tuple[str, ...]:
    fields = ["symbol", "timestamp", "open", "high", "low", "close"]
    if config.data.kind == "crypto_perp_funding":
        fields.append("has_funding_event")
    if config.data.kind == "forex_with_quotes" and config.fill_model.price == "quote":
        fields.extend(["bid", "ask", "mid"])
    return tuple(fields)


def _duplicate_key_count(rows: list[dict[str, Any]]) -> int:
    seen: set[tuple[str, object]] = set()
    duplicates = 0
    for row in rows:
        key = (str(row.get("symbol", "")), row.get("timestamp"))
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)
    return duplicates


def _timestamp_status(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "empty"
    aware = 0
    invalid = 0
    for row in rows:
        if _is_aware_timestamp(row.get("timestamp")):
            aware += 1
        else:
            invalid += 1
    if aware == len(rows):
        return "aware"
    if invalid == len(rows):
        return "invalid_or_naive"
    return "mixed"


def _is_aware_timestamp(value: object) -> bool:
    if isinstance(value, datetime):
        return value.tzinfo is not None and value.utcoffset() is not None
    if isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return False
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    return False


def _funding_event_missing_fields(config: RunConfig, rows: list[dict[str, Any]]) -> dict[str, int]:
    if config.data.kind != "crypto_perp_funding":
        return {}
    fields = ("funding_timestamp", "funding_rate")
    missing: dict[str, int] = {}
    for field in fields:
        count = sum(
            1
            for row in rows
            if row.get("has_funding_event") is True and row.get(field) is None
        )
        if count:
            missing[field] = count
    return missing


def _row_contract_feedback(
    *,
    missing_required_fields: dict[str, int],
    duplicate_key_count: int,
    timestamp_status: str,
    funding_event_missing_fields: dict[str, int],
) -> list[str]:
    feedback = [
        f"missing_required_field:{field}:{count}"
        for field, count in sorted(missing_required_fields.items())
    ]
    feedback.extend(
        f"missing_funding_event_field:{field}:{count}"
        for field, count in sorted(funding_event_missing_fields.items())
    )
    if duplicate_key_count:
        feedback.append(f"duplicate_symbol_timestamp_keys:{duplicate_key_count}")
    if timestamp_status not in {"aware", "empty"}:
        feedback.append(f"timestamp_status:{timestamp_status}")
    return feedback


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
