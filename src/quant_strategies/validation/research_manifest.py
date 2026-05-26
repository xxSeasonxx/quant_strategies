from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quant_strategies.provenance import file_sha256


_VALIDATION_READY_STATUSES = {"validation_ready", "validated_for_testing"}


def check_research_manifest(
    *,
    config_path: Path,
    strategy_path: Path,
    repo_root: Path,
) -> dict[str, Any]:
    manifest_path = _find_parent_manifest(config_path=config_path, repo_root=repo_root)
    if manifest_path is None:
        return {"found": False, "passed": True, "violations": []}

    try:
        payload = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "found": True,
            "manifest_path": _relative_path(manifest_path, repo_root),
            "passed": False,
            "violations": [f"research_manifest_unreadable: {exc}"],
        }

    variants = payload.get("variants")
    if not isinstance(variants, list):
        return {
            "found": True,
            "manifest_path": _relative_path(manifest_path, repo_root),
            "passed": False,
            "violations": ["research_manifest_variants_invalid"],
        }

    variant = _matching_variant(variants, manifest_path=manifest_path, config_path=config_path)
    if variant is None:
        return {
            "found": True,
            "manifest_path": _relative_path(manifest_path, repo_root),
            "passed": True,
            "warnings": ["research_manifest_variant_missing"],
            "violations": [],
        }

    status = _variant_status(variant)
    violations: list[str] = []
    hashes = {
        "strategy_sha256": _safe_file_sha256(strategy_path),
        "validation_config_sha256": _safe_file_sha256(config_path),
    }
    if status in _VALIDATION_READY_STATUSES:
        expected_strategy_hash = variant.get("strategy_sha256") or variant.get("code_sha256")
        expected_config_hash = variant.get("validation_config_sha256") or variant.get(
            "config_sha256"
        )
        if expected_strategy_hash is None:
            violations.append("research_manifest_missing_strategy_hash")
        elif expected_strategy_hash != hashes["strategy_sha256"]:
            violations.append("research_manifest_strategy_hash_mismatch")
        if expected_config_hash is None:
            violations.append("research_manifest_missing_validation_config_hash")
        elif expected_config_hash != hashes["validation_config_sha256"]:
            violations.append("research_manifest_validation_config_hash_mismatch")

    return {
        "found": True,
        "manifest_path": _relative_path(manifest_path, repo_root),
        "variant_directory": str(variant.get("directory", "")),
        "lifecycle_status": status,
        "passed": not violations,
        "violations": violations,
        "hashes": hashes,
    }


def _find_parent_manifest(*, config_path: Path, repo_root: Path) -> Path | None:
    current = config_path.resolve().parent
    root = repo_root.resolve()
    while True:
        candidate = current / "manifest.json"
        if candidate.exists():
            return candidate
        if current == root or current.parent == current:
            return None
        current = current.parent


def _matching_variant(
    variants: list[Any],
    *,
    manifest_path: Path,
    config_path: Path,
) -> dict[str, Any] | None:
    config_dir = config_path.resolve().parent
    manifest_dir = manifest_path.resolve().parent
    for item in variants:
        if not isinstance(item, dict):
            continue
        directory = item.get("directory")
        if not isinstance(directory, str):
            continue
        if (manifest_dir / directory).resolve() == config_dir:
            return item
    return None


def _variant_status(variant: dict[str, Any]) -> str | None:
    value = (
        variant.get("lifecycle_status")
        or variant.get("validation_status")
        or variant.get("status")
    )
    return str(value) if value is not None else None


def _safe_file_sha256(path: Path) -> str | None:
    try:
        return file_sha256(path)
    except OSError:
        return None


def _relative_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path)
