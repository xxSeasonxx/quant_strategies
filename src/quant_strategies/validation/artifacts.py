from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def create_validation_result_dir(results_root: Path, strategy_id: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    safe_strategy_id = strategy_id.replace("/", "_").replace(" ", "_")
    result_dir = results_root / f"{timestamp}-{safe_strategy_id}"
    result_dir.mkdir(parents=True, exist_ok=False)
    return result_dir


def write_json_artifact(result_dir: Path, name: str, payload: Any) -> Path:
    path = result_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    return path


def write_text_artifact(result_dir: Path, name: str, payload: str) -> Path:
    path = result_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if payload.endswith("\n") else payload + "\n")
    return path
