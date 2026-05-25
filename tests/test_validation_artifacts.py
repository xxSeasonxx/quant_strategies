from __future__ import annotations

import json
from pathlib import Path

from quant_strategies.validation.artifacts import create_validation_result_dir, write_json_artifact


def test_create_validation_result_dir_uses_strategy_id(tmp_path: Path):
    result_dir = create_validation_result_dir(tmp_path, "demo_strategy")

    assert result_dir.parent == tmp_path
    assert result_dir.name.endswith("-demo_strategy")
    assert result_dir.exists()


def test_write_json_artifact_is_stable(tmp_path: Path):
    path = write_json_artifact(tmp_path, "promotion_decision.json", {"b": 2, "a": 1})

    assert path == tmp_path / "promotion_decision.json"
    assert json.loads(path.read_text()) == {"a": 1, "b": 2}
    assert path.read_text().endswith("\n")
