from __future__ import annotations

import json
import re
import shutil
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_strategies.data_contract import NormalizedRows, RowContractMode
from quant_strategies.engine import EVIDENCE_SCHEMA_VERSION
from quant_strategies.evidence_semantics import artifact_trust_tier_for_profile, smoke_score_metric_semantics
from quant_strategies.provenance import (
    artifact_hashes,
    git_identity,
    package_versions,
    python_identity,
)
from quant_strategies.runner.config import RunConfig
from quant_strategies.runner.artifact_profiles import (
    canonical_row_line,
    json_safe_value,
)


ROW_CONTRACT_ISSUE_SAMPLE_SIZE = 25


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


def write_strategy_input_rows(result_dir: Path, rows: Sequence[Mapping[str, Any]]) -> str:
    jsonl_path = result_dir / "strategy_input_rows.jsonl"
    return write_jsonl(jsonl_path, rows)


def write_decision_records(result_dir: Path, decisions: list[Any]) -> None:
    lines = [_canonical_json_line(decision) for decision in decisions]
    (result_dir / "decision_records.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""))


def write_engine_request(result_dir: Path, request_json: str) -> None:
    (result_dir / "engine_request.json").write_text(request_json)


def write_evidence(result_dir: Path, evidence_json: str) -> None:
    (result_dir / "evidence.json").write_text(evidence_json)


def evidence_quality(
    config: RunConfig,
    rows: Sequence[Mapping[str, Any]] | NormalizedRows,
    *,
    causality_verified: bool = False,
) -> dict[str, Any]:
    return compact_evidence_quality(
        _normalized_rows(config, rows).evidence_quality(causality_verified=causality_verified)
    )


def with_causality_verification(
    evidence_quality_payload: Mapping[str, Any],
    *,
    causality_verified: bool,
) -> dict[str, Any]:
    payload = compact_evidence_quality(evidence_quality_payload)
    payload.update(
        _causality_evidence(
            payload.get("data_availability_status"),
            causality_verified=causality_verified,
        )
    )
    return payload


def compact_evidence_quality(evidence_quality_payload: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(evidence_quality_payload)
    row_contract = payload.get("row_contract")
    if isinstance(row_contract, Mapping):
        payload["row_contract"] = _compact_row_contract(row_contract)
    return payload


def _compact_row_contract(row_contract: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(row_contract)
    issues = payload.get("issues")
    if not isinstance(issues, list):
        return payload

    issue_count = payload.get("issue_count")
    if not isinstance(issue_count, int):
        issue_count = len(issues)
    payload["issue_count"] = issue_count
    if len(issues) <= ROW_CONTRACT_ISSUE_SAMPLE_SIZE:
        payload["issue_sample_count"] = len(issues)
        payload["issues_truncated"] = issue_count > len(issues)
        return payload

    payload["issues"] = issues[:ROW_CONTRACT_ISSUE_SAMPLE_SIZE]
    payload["issue_sample_count"] = ROW_CONTRACT_ISSUE_SAMPLE_SIZE
    payload["issues_truncated"] = True
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


def row_contract_status(
    config: RunConfig,
    rows: Sequence[Mapping[str, Any]] | NormalizedRows,
) -> dict[str, Any]:
    return _compact_row_contract(_normalized_rows(config, rows).row_contract_summary())


def write_data_manifest(
    result_dir: Path,
    config: RunConfig,
    rows: Sequence[Mapping[str, Any]] | NormalizedRows,
    *,
    normalized_rows: NormalizedRows | None = None,
    evidence_quality_payload: dict[str, Any] | None = None,
) -> None:
    normalized = _normalized_rows(config, rows, normalized_rows=normalized_rows)
    quality = compact_evidence_quality(
        evidence_quality_payload or normalized.evidence_quality(causality_verified=False)
    )
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
            "total": len(normalized),
            "by_symbol": normalized.ranges_by_symbol,
        },
        "normalized_rows_sha256": normalized.normalized_rows_sha256,
        "metric_semantics": smoke_score_metric_semantics(config.data.kind),
        "metadata_field_coverage": normalized.metadata_field_coverage,
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


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("w") as handle:
        for row in rows:
            line = canonical_row_line(row)
            handle.write(line + "\n")
            digest.update(line.encode("utf-8"))
            digest.update(b"\n")
    return digest.hexdigest()


def _canonical_json_line(value: Any) -> str:
    if hasattr(value, "model_dump"):
        payload = value.model_dump(mode="json")
    else:
        payload = json_safe_value(value)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _normalized_rows(
    config: RunConfig,
    rows: Sequence[Mapping[str, Any]] | NormalizedRows,
    *,
    normalized_rows: NormalizedRows | None = None,
) -> NormalizedRows:
    if normalized_rows is not None:
        return normalized_rows
    if isinstance(rows, NormalizedRows):
        return rows
    return NormalizedRows.from_rows(config, rows, mode=RowContractMode.SEARCH)


def _artifact_hashes(result_dir: Path) -> dict[str, dict[str, str]]:
    return artifact_hashes(
        result_dir,
        exclude_names={"run_manifest.json", "summary.json"},
        recursive=False,
    )


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
