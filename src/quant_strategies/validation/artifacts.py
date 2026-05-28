from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def create_validation_result_dir(results_root: Path, strategy_id: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    safe_strategy_id = strategy_id.replace("/", "_").replace(" ", "_")
    base_name = f"{timestamp}-{safe_strategy_id}"
    result_dir = results_root / base_name
    suffix = 2
    results_root.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            result_dir.mkdir()
        except FileExistsError:
            result_dir = results_root / f"{base_name}-{suffix}"
            suffix += 1
            continue
        return result_dir


def write_json_artifact(result_dir: Path, name: str, payload: Any) -> Path:
    path = _artifact_path(result_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_value(payload), indent=2, sort_keys=True) + "\n")
    return path


def write_text_artifact(result_dir: Path, name: str, payload: str) -> Path:
    path = _artifact_path(result_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if payload.endswith("\n") else payload + "\n")
    return path


def canonical_jsonl_lines(items: list[Any]) -> str:
    lines = [
        json.dumps(_json_value(item), sort_keys=True, separators=(",", ":"), allow_nan=False)
        for item in items
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def _artifact_path(result_dir: Path, name: str) -> Path:
    artifact_name = Path(name)
    if artifact_name.is_absolute() or ".." in artifact_name.parts:
        raise ValueError("Artifact name must stay inside result_dir")

    root = result_dir.resolve()
    path = result_dir / artifact_name
    try:
        path.resolve().relative_to(root)
    except ValueError as exc:
        raise ValueError("Artifact name must stay inside result_dir") from exc
    return path


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _json_value(value.model_dump(mode="json"))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    return value
