from __future__ import annotations

import json
import re
import shutil
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_strategies.data_contract import NormalizedRows, RowContractMode, json_safe_value
from quant_strategies.engine import EVIDENCE_SCHEMA_VERSION
from quant_strategies.evidence_semantics import (
    artifact_trust_tier_for_profile,
    causality_evidence_fields,
    runner_evidence_semantics,
    smoke_score_metric_semantics,
)
from quant_strategies.provenance import (
    artifact_hashes,
    environment_identity,
    source_identity,
)
from quant_strategies.runner.config import RunConfig
from quant_strategies.runner.artifact_profiles import canonical_row_line
from quant_strategies.runner.engine_runner import EngineRun


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
    emitted_replay_verified: bool = False,
    strict_no_emission_verified: bool = False,
) -> dict[str, Any]:
    return compact_evidence_quality(
        _normalized_rows(config, rows).evidence_quality(
            emitted_replay_verified=emitted_replay_verified,
            strict_no_emission_verified=strict_no_emission_verified,
        )
    )


def with_causality_verification(
    evidence_quality_payload: Mapping[str, Any],
    *,
    emitted_replay_verified: bool,
    strict_no_emission_verified: bool,
) -> dict[str, Any]:
    payload = compact_evidence_quality(evidence_quality_payload)
    payload.update(
        causality_evidence_fields(
            payload.get("data_availability_status"),
            emitted_replay_verified=emitted_replay_verified,
            strict_no_emission_verified=strict_no_emission_verified,
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

    payload["issues"] = _stratified_issue_sample(issues, ROW_CONTRACT_ISSUE_SAMPLE_SIZE)
    payload["issue_sample_count"] = ROW_CONTRACT_ISSUE_SAMPLE_SIZE
    payload["issues_truncated"] = True
    return payload


def _stratified_issue_sample(issues: Sequence[Any], sample_size: int) -> list[Any]:
    selected: set[int] = set()
    seen_keys: set[tuple[object, object, object]] = set()
    for index, issue in enumerate(issues):
        key = _issue_sample_key(issue)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        selected.add(index)
        if len(selected) == sample_size:
            return [issues[item] for item in sorted(selected)]

    for index in range(len(issues)):
        if index in selected:
            continue
        selected.add(index)
        if len(selected) == sample_size:
            break
    return [issues[item] for item in sorted(selected)]


def _issue_sample_key(issue: object) -> tuple[object, object, object]:
    if isinstance(issue, Mapping):
        return (
            issue.get("severity"),
            issue.get("reason"),
            issue.get("field"),
        )
    return (None, None, None)


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
        evidence_quality_payload or normalized.evidence_quality()
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
    _write_environment(result_dir, repo_root=repo_root)
    payload = {
        "repository": source_identity(repo_root),
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
    with path.open("wb") as handle:
        for row in rows:
            line = canonical_row_line(row)
            payload = f"{line}\n".encode("utf-8")
            handle.write(payload)
            digest.update(payload)
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
        exclude_names={"run_manifest.json", "summary.json", "environment.json"},
        recursive=False,
    )


def _write_environment(result_dir: Path, *, repo_root: Path) -> None:
    _write_json(
        result_dir / "environment.json",
        environment_identity(
            repo_root,
            package_names=["quant-strategies", "quant-data", "pydantic"],
            exclude_paths=(result_dir,),
        ),
    )


def _artifact_names(result_dir: Path, *, include_summary: bool) -> list[str]:
    names = {path.name for path in result_dir.iterdir() if path.is_file()}
    if include_summary:
        names.add("summary.json")
    return sorted(names)


def _safe_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return name or "strategy"


# --- result/summary/notes shaping (relocated out of the runner orchestrator) ---


def run_result_evidence_fields(evidence_quality: dict[str, object] | None) -> dict[str, object]:
    if evidence_quality is None:
        return {}
    return {
        "data_availability_status": _optional_str(evidence_quality.get("data_availability_status")),
        "availability_coverage": _optional_dict(evidence_quality.get("availability_coverage")),
        "row_contract": _optional_dict(evidence_quality.get("row_contract")),
        "causality_verified": bool(evidence_quality.get("causality_verified")),
        "emitted_replay_verified": bool(evidence_quality.get("emitted_replay_verified")),
        "strict_no_emission_verified": bool(evidence_quality.get("strict_no_emission_verified")),
        "evidence_quality_warnings": _string_tuple(evidence_quality.get("evidence_quality_warnings")),
    }


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_dict(value: object) -> dict[str, object] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value)
    return (str(value),)


def summary_payload(
    config: RunConfig,
    *,
    status: str,
    stage: str,
    failure_stage: str | None,
    message: str,
    engine: dict[str, object],
    assessment_status: str,
    evidence_quality: dict[str, object],
) -> dict[str, object]:
    semantics = runner_evidence_semantics(config.data.kind)
    engine_payload = dict(engine)
    return {
        "strategy_id": config.strategy_id,
        "mode": config.output.mode,
        "artifact_profile": config.output.artifact_profile,
        "artifact_trust_tier": artifact_trust_tier_for_profile(config.output.artifact_profile),
        "status": status,
        "stage": stage,
        "failure_stage": failure_stage,
        "message": message,
        "artifacts": [],
        "engine": engine_payload,
        "run_completed": True,
        "assessment_status": assessment_status,
        **semantics,
        **evidence_quality,
    }


def _trade_count(engine_run: EngineRun) -> int | None:
    if engine_run.screen_summary is not None:
        value = engine_run.screen_summary.get("trade_count")
        return int(value) if value is not None else None
    if engine_run.validate_summary is not None:
        screening_result = engine_run.validate_summary.get("screening_result")
        if isinstance(screening_result, dict):
            value = screening_result.get("trade_count")
            return int(value) if value is not None else None
    return None


def compact_engine_summary(engine_run: EngineRun) -> dict[str, object]:
    source = engine_run.screen_summary
    if source is None and engine_run.validate_summary is not None:
        screening_result = engine_run.validate_summary.get("screening_result")
        source = screening_result if isinstance(screening_result, dict) else None

    summary: dict[str, object] = {"passed": engine_run.passed, "trade_count": _trade_count(engine_run)}
    smoke_score = source.get("smoke_score") if isinstance(source, dict) else None
    if isinstance(smoke_score, dict):
        summary["smoke_score"] = {
            "sum_signed_trade_activity_gross": smoke_score.get("sum_signed_trade_activity_gross"),
            "sum_signed_trade_activity_funding": smoke_score.get("sum_signed_trade_activity_funding"),
            "sum_signed_trade_activity_cost": smoke_score.get("sum_signed_trade_activity_cost"),
            "sum_signed_trade_activity_net": smoke_score.get("sum_signed_trade_activity_net"),
        }
    else:
        summary["smoke_score"] = {
            "sum_signed_trade_activity_gross": None,
            "sum_signed_trade_activity_funding": None,
            "sum_signed_trade_activity_cost": None,
            "sum_signed_trade_activity_net": None,
        }
    if engine_run.validate_summary is not None:
        gates = engine_run.validate_summary.get("gates")
        if isinstance(gates, list):
            summary["gates"] = [
                {"name": gate.get("name"), "passed": gate.get("passed"), "detail": gate.get("detail")}
                for gate in gates
                if isinstance(gate, dict)
            ]
    return summary


def failure_notes(stage: str, message: str) -> str:
    return f"# Run Failed\n\nstage: {stage}\nmessage: {message}\n"


def result_status(engine_run: EngineRun) -> str:
    if engine_run.mode == "screen":
        return "screened"
    return "passed" if engine_run.passed else "failed"


def assessment_status(
    engine_run: EngineRun,
    *,
    evidence_quality: dict[str, object],
) -> str:
    if engine_run.mode == "screen":
        return "screened"
    if engine_run.passed and not evidence_quality.get("causality_verified"):
        return "smoke_unverified"
    return "smoke_passed" if engine_run.passed else "smoke_failed"


def completion_notes(config: RunConfig, engine_run: EngineRun) -> str:
    lines = [
        "# Run Complete",
        "",
        f"strategy_id: {config.strategy_id}",
        f"mode: {engine_run.mode}",
    ]
    if engine_run.mode == "screen":
        lines.append("status: screened")
        interpretation = (
            "runner screen evidence only; not validation pass, market robustness, "
            "or promotion evidence."
        )
    else:
        status = "passed" if engine_run.passed else "failed validation gates"
        lines.append(f"status: {status}")
        interpretation = "runner smoke evidence only; not market robustness or promotion evidence."
    if config.data.kind == "crypto_perp_funding":
        lines.append(
            "return_scope: price-and-funding; supplied funding events are included "
            "when they fall inside engine-held intervals."
        )
    lines.append(f"interpretation: {interpretation}")
    return "\n".join(lines) + "\n"
