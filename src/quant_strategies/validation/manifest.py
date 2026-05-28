from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from quant_strategies.provenance import (
    artifact_hashes,
    file_sha256,
    git_identity,
    package_versions,
    python_identity,
    text_sha256,
)
from quant_strategies.validation.artifacts import canonical_jsonl_lines, write_json_artifact
from quant_strategies.validation.backends import ScenarioBackendRunResult


def rows_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    return text_sha256(canonical_jsonl_lines(list(rows)))


def write_validation_manifest(
    result_dir: Path,
    *,
    repo_root: Path,
    path_base: Path,
    config: Any,
    config_path: Path,
    backend_name: str,
    data_provenance: list[dict[str, Any]],
    backend_results: list[ScenarioBackendRunResult],
    capability_matrix: dict[str, Any],
) -> Path:
    payload = {
        "repository": git_identity(repo_root, exclude_paths=(result_dir,)),
        "python": python_identity(),
        "packages": package_versions(
            ["quant-strategies", "quant-data", "pydantic", "pandas", "vectorbtpro"]
        ),
        "validation": {
            "strategy_id": config.strategy_id,
            "backend": backend_name,
            "config_path": _relative_path(config_path, path_base),
            "config_sha256": _optional_hash(config_path),
        },
        "strategy": {
            "path": _relative_path(Path(config.strategy_path), path_base),
            "snapshot_sha256": _optional_hash(result_dir / "strategy_snapshot.py"),
        },
        "data": {"windows": data_provenance},
        "backend": _backend_summary(
            backend_name=backend_name,
            backend_results=backend_results,
            capability_matrix=capability_matrix,
        ),
        "core_hashes": _core_hashes(result_dir),
        "artifacts": artifact_hashes(
            result_dir,
            exclude_names={"validation_manifest.json"},
            recursive=True,
        ),
    }
    return write_json_artifact(result_dir, "validation_manifest.json", payload)


def _backend_summary(
    *,
    backend_name: str,
    backend_results: list[ScenarioBackendRunResult],
    capability_matrix: dict[str, Any],
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    unsupported: set[str] = set()
    scenarios: list[dict[str, Any]] = []
    for item in backend_results:
        status = item.result.status
        status_counts[status] = status_counts.get(status, 0) + 1
        unsupported.update(item.result.unsupported_semantics)
        scenarios.append(
            {
                "window_id": item.window_id,
                "scenario_id": item.scenario_id,
                "scenario_kind": item.scenario_kind,
                "required": item.required,
                "diagnostic_only": item.diagnostic_only,
                "decisions_regenerated": item.decisions_regenerated,
                "decision_generation_status": item.decision_generation_status,
                "decision_count": item.decision_count,
                "decision_records_path": item.decision_records_path,
                "decision_records_sha256": item.decision_records_sha256,
                "backend": item.result.backend,
                "status": status,
                "unsupported_semantics": list(item.result.unsupported_semantics),
            }
        )
    return {
        "selected": backend_name,
        "status_counts": dict(sorted(status_counts.items())),
        "unsupported_semantics": sorted(unsupported),
        "capability_matrix": capability_matrix,
        "scenarios": scenarios,
    }


def _core_hashes(result_dir: Path) -> dict[str, str | None]:
    names = (
        "validation_config.toml",
        "strategy_snapshot.py",
        "decision_records.jsonl",
        "data_audit.json",
        "backend_runs/summary.json",
        "backend_capability_matrix.json",
        "robustness_matrix.json",
        "validation_decision.json",
        "validation_report.md",
    )
    hashes = {name: _optional_hash(result_dir / name) for name in names}
    row_dir = result_dir / "data_rows"
    if row_dir.exists():
        for path in sorted(row_dir.rglob("*")):
            if path.is_file():
                name = path.relative_to(result_dir).as_posix()
                hashes[name] = _optional_hash(path)
    return hashes


def _optional_hash(path: Path) -> str | None:
    try:
        return file_sha256(path)
    except OSError:
        return None


def _relative_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path)
