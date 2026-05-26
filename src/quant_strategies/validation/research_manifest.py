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
    researched_package = _researched_package_dir(
        config_path=config_path,
        strategy_path=strategy_path,
        repo_root=repo_root,
    )
    is_researched_package = researched_package is not None
    if not is_researched_package:
        return {
            "is_researched_package": False,
            "found": False,
            "passed": True,
            "violations": [],
        }

    layout_violations = _canonical_layout_violations(
        config_path=config_path,
        strategy_path=strategy_path,
        package_dir=researched_package,
    )
    if layout_violations:
        return {
            "is_researched_package": True,
            "found": False,
            "passed": False,
            "violations": layout_violations,
        }

    manifest_path = researched_package / "manifest.json"
    if not manifest_path.exists():
        return {
            "is_researched_package": True,
            "found": False,
            "passed": False,
            "violations": ["research_manifest_missing"],
        }

    try:
        payload = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "is_researched_package": True,
            "found": True,
            "manifest_path": _relative_path(manifest_path, repo_root),
            "passed": False,
            "violations": [f"research_manifest_unreadable: {exc}"],
        }

    variants = payload.get("variants")
    if not isinstance(variants, list):
        return {
            "is_researched_package": True,
            "found": True,
            "manifest_path": _relative_path(manifest_path, repo_root),
            "passed": False,
            "violations": ["research_manifest_variants_invalid"],
        }

    variant = _matching_variant(variants, manifest_path=manifest_path, config_path=config_path)
    if variant is None:
        return {
            "is_researched_package": True,
            "found": True,
            "manifest_path": _relative_path(manifest_path, repo_root),
            "passed": False,
            "violations": ["research_manifest_variant_missing"],
        }

    status = _variant_status(variant)
    violations: list[str] = []
    hashes = {
        "strategy_sha256": _safe_file_sha256(strategy_path),
        "validation_config_sha256": _safe_file_sha256(config_path),
    }
    if status not in _VALIDATION_READY_STATUSES:
        violations.append("research_manifest_status_not_validation_ready")
    expected_strategy_hash = variant.get("strategy_sha256")
    expected_config_hash = variant.get("validation_config_sha256")
    if expected_strategy_hash is None:
        violations.append("research_manifest_missing_strategy_hash")
    elif expected_strategy_hash != hashes["strategy_sha256"]:
        violations.append("research_manifest_strategy_hash_mismatch")
    if expected_config_hash is None:
        violations.append("research_manifest_missing_validation_config_hash")
    elif expected_config_hash != hashes["validation_config_sha256"]:
        violations.append("research_manifest_validation_config_hash_mismatch")

    return {
        "is_researched_package": True,
        "found": True,
        "manifest_path": _relative_path(manifest_path, repo_root),
        "variant_directory": str(variant.get("directory", "")),
        "lifecycle_status": status,
        "passed": not violations,
        "violations": violations,
        "hashes": hashes,
    }


def _researched_package_dir(
    *,
    config_path: Path,
    strategy_path: Path,
    repo_root: Path,
) -> Path | None:
    packages = {
        package
        for package in (
            _researched_package_dir_for_path(config_path, repo_root=repo_root),
            _researched_package_dir_for_path(strategy_path, repo_root=repo_root),
        )
        if package is not None
    }
    if not packages:
        return None
    if len(packages) == 1:
        return next(iter(packages))
    return repo_root.resolve() / "researched"


def _researched_package_dir_for_path(path: Path, *, repo_root: Path) -> Path | None:
    researched_root = (repo_root.resolve() / "researched").resolve()
    try:
        relative = path.resolve().relative_to(researched_root)
    except ValueError:
        return None
    if not relative.parts:
        return researched_root
    return researched_root / relative.parts[0]


def _canonical_layout_violations(
    *,
    config_path: Path,
    strategy_path: Path,
    package_dir: Path,
) -> list[str]:
    expected_config = package_dir / "validation.toml"
    expected_strategy = package_dir / "strategy.py"
    if config_path.resolve() == expected_config.resolve() and strategy_path.resolve() == expected_strategy.resolve():
        return []
    return ["research_manifest_invalid_layout"]


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
