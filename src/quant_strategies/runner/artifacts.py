from __future__ import annotations

import json
import re
import shutil
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_strategies.core.engine_runner import EngineRun
from quant_strategies.core.evidence_quality import compact_evidence_quality, compact_row_contract
from quant_strategies.core.serialization import json_safe_value
from quant_strategies.data_contract import NormalizedRows
from quant_strategies.engine import EVIDENCE_SCHEMA_VERSION
from quant_strategies.evidence_semantics import (
    causality_evidence_fields,
    replayable_from_artifacts_for_profile,
    runner_evidence_semantics,
    trade_result_metric_semantics,
)
from quant_strategies.provenance import (
    artifact_hashes,
    environment_identity,
    source_identity,
)
from quant_strategies.runner.config import RunConfig

RUNNER_EVIDENCE_SCHEMA_VERSION = "quant_strategies.runner.evidence/v1"


def create_result_dir(config: RunConfig, *, now: datetime | None = None) -> Path:
    timestamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H%M%SZ")
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


def write_evidence(result_dir: Path, evidence_json: str, *, quick_checks: bool) -> None:
    (result_dir / "evidence.json").write_text(
        runner_evidence_json(evidence_json, quick_checks=quick_checks)
    )


def runner_evidence_json(evidence_json: str, *, quick_checks: bool) -> str:
    payload = json.loads(evidence_json)
    payload["schema_version"] = RUNNER_EVIDENCE_SCHEMA_VERSION
    payload["quick_checks"] = quick_checks
    _remove_engine_mode_fields(payload)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"


def _remove_engine_mode_fields(payload: dict[str, Any]) -> None:
    payload.pop("mode", None)
    screening_result = payload.get("screening_result")
    if isinstance(screening_result, dict):
        screening_result.pop("mode", None)
    validation_report = payload.get("validation_report")
    if isinstance(validation_report, dict):
        validation_report.pop("mode", None)
        nested_screening_result = validation_report.get("screening_result")
        if isinstance(nested_screening_result, dict):
            nested_screening_result.pop("mode", None)


def evidence_quality(
    config: RunConfig,
    rows: Sequence[Mapping[str, Any]] | NormalizedRows,
    *,
    deterministic_replay_verified: bool | None = None,
    emitted_replay_verified: bool = False,
    strict_no_emission_verified: bool = False,
    strict_replay_capped: bool = False,
    strict_probe_count: int | None = None,
    strict_probe_limit: int | None = None,
    skipped_probe_count: int = 0,
    skipped_probe_reasons: tuple[str, ...] = (),
    replay_scope: str | None = None,
    candidate_probe_count: int | None = None,
    selected_probe_count: int | None = None,
    elapsed_seconds: float | None = None,
    timeout_seconds: float | None = None,
    timed_out: bool = False,
    replay_warning: str | None = None,
) -> dict[str, Any]:
    return compact_evidence_quality(
        _normalized_rows(config, rows).evidence_quality(
            deterministic_replay_verified=deterministic_replay_verified,
            emitted_replay_verified=emitted_replay_verified,
            strict_no_emission_verified=strict_no_emission_verified,
            causality_check=config.output.causality_check,
            strict_replay_capped=strict_replay_capped,
            strict_probe_count=strict_probe_count,
            strict_probe_limit=strict_probe_limit,
            skipped_probe_count=skipped_probe_count,
            skipped_probe_reasons=skipped_probe_reasons,
            replay_scope=replay_scope,
            candidate_probe_count=candidate_probe_count,
            selected_probe_count=selected_probe_count,
            elapsed_seconds=elapsed_seconds,
            timeout_seconds=timeout_seconds,
            timed_out=timed_out,
            replay_warning=replay_warning,
        )
    )


def with_causality_verification(
    evidence_quality_payload: Mapping[str, Any],
    *,
    causality_check: str,
    deterministic_replay_verified: bool,
    emitted_replay_verified: bool,
    strict_no_emission_verified: bool,
    strict_replay_capped: bool = False,
    strict_probe_count: int | None = None,
    strict_probe_limit: int | None = None,
    skipped_probe_count: int = 0,
    skipped_probe_reasons: tuple[str, ...] = (),
    replay_scope: str | None = None,
    candidate_probe_count: int | None = None,
    selected_probe_count: int | None = None,
    elapsed_seconds: float | None = None,
    timeout_seconds: float | None = None,
    timed_out: bool = False,
    replay_warning: str | None = None,
) -> dict[str, Any]:
    payload = compact_evidence_quality(evidence_quality_payload)
    payload.update(
        causality_evidence_fields(
            payload.get("data_availability_status"),
            causality_check=causality_check,
            deterministic_replay_verified=deterministic_replay_verified,
            emitted_replay_verified=emitted_replay_verified,
            strict_no_emission_verified=strict_no_emission_verified,
            strict_replay_capped=strict_replay_capped,
            strict_probe_count=strict_probe_count,
            strict_probe_limit=strict_probe_limit,
            skipped_probe_count=skipped_probe_count,
            skipped_probe_reasons=skipped_probe_reasons,
            replay_scope=replay_scope,
            candidate_probe_count=candidate_probe_count,
            selected_probe_count=selected_probe_count,
            elapsed_seconds=elapsed_seconds,
            timeout_seconds=timeout_seconds,
            timed_out=timed_out,
            replay_warning=replay_warning,
        )
    )
    return payload


def row_contract_status(
    config: RunConfig,
    rows: Sequence[Mapping[str, Any]] | NormalizedRows,
) -> dict[str, Any]:
    return compact_row_contract(_normalized_rows(config, rows).row_contract_summary())


def write_data_manifest(
    result_dir: Path,
    config: RunConfig,
    rows: Sequence[Mapping[str, Any]] | NormalizedRows,
    *,
    normalized_rows: NormalizedRows | None = None,
    execution_normalized_rows: NormalizedRows | None = None,
    evidence_quality_payload: dict[str, Any] | None = None,
) -> None:
    normalized = _normalized_rows(config, rows, normalized_rows=normalized_rows)
    quality = compact_evidence_quality(evidence_quality_payload or normalized.evidence_quality())
    execution_rows = execution_normalized_rows or normalized
    data_payload = {
        "kind": config.data.kind,
        "dataset": config.data.dataset,
        "symbols": list(config.data.symbols),
        "start": config.data.start.isoformat(),
        "end": config.data.end.isoformat(),
    }
    has_explicit_load_window = (
        config.data.load_start is not None or config.data.load_end is not None
    )
    if has_explicit_load_window:
        data_payload["load_start"] = config.data.effective_load_start.isoformat()
        data_payload["load_end"] = config.data.effective_load_end.isoformat()

    payload = {
        "artifact_profile": config.output.artifact_profile,
        "replayable_from_artifacts": replayable_from_artifacts_for_profile(
            config.output.artifact_profile
        ),
        "data": data_payload,
        "rows": {
            "total": len(normalized),
            "by_symbol": normalized.ranges_by_symbol,
        },
        "normalized_rows_sha256": normalized.normalized_rows_sha256,
        "metric_semantics": trade_result_metric_semantics(config.data.kind),
        **quality,
    }
    if has_explicit_load_window:
        payload["execution_rows"] = {
            "total": len(execution_rows),
            "by_symbol": execution_rows.ranges_by_symbol,
            "normalized_rows_sha256": execution_rows.normalized_rows_sha256,
            "row_contract": execution_rows.row_contract_summary(),
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
        "replayable_from_artifacts": replayable_from_artifacts_for_profile(artifact_profile),
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
            line = _canonical_json_line(row)
            payload = f"{line}\n".encode()
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
    return NormalizedRows.from_rows(config, rows)


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


# --- summary/notes shaping (relocated out of the runner orchestrator) ---


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
    param_contract: str = "unknown",
    economic_metrics: Mapping[str, object] | None = None,
    generated_decision_count: int | None = None,
    excluded_decision_count: int | None = None,
) -> dict[str, object]:
    semantics = runner_evidence_semantics(config.data.kind)
    engine_payload = dict(engine)
    payload = {
        "strategy_id": config.strategy_id,
        "quick_checks": config.output.quick_checks,
        "artifact_profile": config.output.artifact_profile,
        "replayable_from_artifacts": replayable_from_artifacts_for_profile(
            config.output.artifact_profile
        ),
        "status": status,
        "stage": stage,
        "failure_stage": failure_stage,
        "message": message,
        "artifacts": [],
        "engine": engine_payload,
        "run_completed": failure_stage is None,
        "assessment_status": assessment_status,
        # "unvalidated_passthrough" when the strategy defines no validate_params:
        # the quick-run still ran but its params were not schema-checked.
        "param_contract": param_contract,
        **semantics,
        **evidence_quality,
    }
    if economic_metrics is not None:
        payload["economic_metrics"] = json_safe_value(dict(economic_metrics))
    if generated_decision_count is not None:
        payload["generated_decision_count"] = generated_decision_count
    if excluded_decision_count is not None:
        payload["excluded_decision_count"] = excluded_decision_count
    return payload


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


def compact_engine_summary(
    engine_run: EngineRun,
    *,
    include_diagnostic_trades: bool = False,
) -> dict[str, object]:
    source = engine_run.screen_summary
    if source is None and engine_run.validate_summary is not None:
        screening_result = engine_run.validate_summary.get("screening_result")
        source = screening_result if isinstance(screening_result, dict) else None

    summary: dict[str, object] = {
        "passed": engine_run.passed,
        "trade_count": _trade_count(engine_run),
    }
    trade_result = source.get("trade_result") if isinstance(source, dict) else None
    if isinstance(trade_result, dict):
        summary["trade_result"] = {
            "sum_signed_trade_activity_gross": trade_result.get("sum_signed_trade_activity_gross"),
            "sum_signed_trade_activity_funding": trade_result.get(
                "sum_signed_trade_activity_funding"
            ),
            "sum_signed_trade_activity_cost": trade_result.get("sum_signed_trade_activity_cost"),
            "sum_signed_trade_activity_net": trade_result.get("sum_signed_trade_activity_net"),
        }
    else:
        summary["trade_result"] = {
            "sum_signed_trade_activity_gross": None,
            "sum_signed_trade_activity_funding": None,
            "sum_signed_trade_activity_cost": None,
            "sum_signed_trade_activity_net": None,
        }
    trades = source.get("trades") if isinstance(source, dict) else None
    if include_diagnostic_trades and isinstance(trades, list):
        summary["diagnostic_trades"] = trades
    if engine_run.validate_summary is not None:
        gates = engine_run.validate_summary.get("gates")
        if isinstance(gates, list):
            summary["gates"] = [
                {
                    "name": gate.get("name"),
                    "passed": gate.get("passed"),
                    "detail": gate.get("detail"),
                }
                for gate in gates
                if isinstance(gate, dict)
            ]
    return summary


def failure_notes(stage: str, message: str) -> str:
    return f"# Run Failed\n\nstage: {stage}\nmessage: {message}\n"


def result_status(engine_run: EngineRun) -> str:
    _ = engine_run
    return "completed"


def assessment_status(
    engine_run: EngineRun,
    *,
    quick_checks: bool,
    evidence_quality: dict[str, object],
) -> str:
    if not quick_checks:
        return "diagnostics_complete"
    if engine_run.passed and not evidence_quality.get("causality_verified"):
        return "quick_check_unverified"
    return "quick_check_passed" if engine_run.passed else "quick_check_failed"


def completion_notes(config: RunConfig, engine_run: EngineRun) -> str:
    lines = [
        "# Run Complete",
        "",
        f"strategy_id: {config.strategy_id}",
        f"quick_checks: {str(config.output.quick_checks).lower()}",
        "status: completed",
    ]
    if not config.output.quick_checks:
        interpretation = (
            "runner diagnostic evidence only; quick checks were not enabled; not validation, "
            "market robustness, or promotion evidence."
        )
    else:
        quick_check_status = "passed" if engine_run.passed else "failed"
        lines.append(f"quick_check_result: {quick_check_status}")
        interpretation = "runner quick checks only; not market robustness or promotion evidence."
    if config.data.kind == "crypto_perp_funding":
        lines.append(
            "return_scope: price-and-funding; supplied funding events are included "
            "when they fall inside engine-held intervals."
        )
    lines.append(f"interpretation: {interpretation}")
    return "\n".join(lines) + "\n"
