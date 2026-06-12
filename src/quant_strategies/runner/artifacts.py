from __future__ import annotations

import json
import re
import shutil
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_strategies.core.engine_runner import EngineRun
from quant_strategies.core.evidence_quality import (
    CausalityVerification,
    EvidenceQuality,
    EvidenceQualityPayload,
    compact_evidence_quality,
    compact_row_contract,
)
from quant_strategies.core.serialization import json_safe_value
from quant_strategies.data_contract import NormalizedRows
from quant_strategies.engine import EVIDENCE_SCHEMA_VERSION
from quant_strategies.evidence_semantics import (
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


def evidence_quality(
    config: RunConfig,
    rows: Sequence[Mapping[str, Any]] | NormalizedRows,
) -> EvidenceQuality:
    normalized = _normalized_rows(config, rows)
    return normalized.evidence_quality(
        causality=CausalityVerification.from_replay(
            normalized.data_availability_status,
            causality_check=config.output.causality_check,
        ),
    )


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
    evidence_quality_payload: EvidenceQualityPayload | None = None,
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
    evidence_quality: EvidenceQualityPayload,
    param_contract: str = "unknown",
    economic_metrics: Mapping[str, object] | None = None,
    portfolio_foundation: Mapping[str, object] | None = None,
    retainability: Mapping[str, object] | None = None,
    generated_decision_count: int | None = None,
    excluded_decision_count: int | None = None,
) -> dict[str, object]:
    semantics = runner_evidence_semantics(config.data.kind)
    engine_payload = dict(engine)
    quality = compact_evidence_quality(evidence_quality)
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
        **quality,
    }
    retainability_payload = (
        {"retainable": False, "reason": "run_not_completed", "detail": None}
        if retainability is None
        else dict(retainability)
    )
    payload["retainability"] = json_safe_value(retainability_payload)
    payload["retainable"] = bool(retainability_payload.get("retainable"))
    if economic_metrics is not None:
        payload["economic_metrics"] = json_safe_value(dict(economic_metrics))
    if portfolio_foundation is not None:
        payload["portfolio_foundation"] = json_safe_value(dict(portfolio_foundation))
    if generated_decision_count is not None:
        payload["generated_decision_count"] = generated_decision_count
    if excluded_decision_count is not None:
        payload["excluded_decision_count"] = excluded_decision_count
    return payload


def compact_engine_summary(
    engine_run: EngineRun,
    *,
    include_diagnostic_trades: bool = False,
) -> dict[str, object]:
    """Compact the book-derived run summary for the ``summary.json`` engine block.

    ``nav_attribution`` is the realized NAV attribution of the single book walk
    (gross/funding/cost/net as fractions of NAV); it is the same model of money as
    the per-trade ledger, not an independent per-trade sum.
    """
    summary: dict[str, object] = {
        "feasible": engine_run.feasible,
        "trade_count": engine_run.trade_count,
        "nav_attribution": dict(engine_run.nav_attribution),
    }
    if include_diagnostic_trades:
        summary["diagnostic_trades"] = [dict(trade) for trade in engine_run.diagnostic_trades]
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
    evidence_quality: EvidenceQualityPayload,
) -> str:
    quality = compact_evidence_quality(evidence_quality)
    if not quick_checks:
        return "diagnostics_complete"
    if engine_run.feasible and not quality.get("causality_verified"):
        return "quick_check_unverified"
    return "quick_check_passed" if engine_run.feasible else "quick_check_failed"


def completion_notes(config: RunConfig, engine_run: EngineRun, *, assessment_status: str) -> str:
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
        quick_check_status = {
            "quick_check_passed": "passed",
            "quick_check_failed": "failed",
            "quick_check_unverified": "unverified",
        }[assessment_status]
        lines.append(f"quick_check_result: {quick_check_status}")
        interpretation = "runner quick checks only; not market robustness or promotion evidence."
    if config.data.kind == "crypto_perp_funding":
        lines.append(
            "return_scope: price-and-funding; supplied funding events are included "
            "when they fall inside engine-held intervals."
        )
    lines.append(f"interpretation: {interpretation}")
    return "\n".join(lines) + "\n"
