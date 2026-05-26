from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel

import quant_strategies.validation.artifacts as artifacts
from quant_strategies.validation.artifacts import (
    create_validation_result_dir,
    write_json_artifact,
    write_text_artifact,
)


class ArtifactPayload(BaseModel):
    created_at: datetime
    source_path: Path


def test_create_validation_result_dir_uses_strategy_id(tmp_path: Path):
    result_dir = create_validation_result_dir(tmp_path, "demo_strategy")

    assert result_dir.parent == tmp_path
    assert result_dir.name.endswith("-demo_strategy")
    assert result_dir.exists()


def test_create_validation_result_dir_adds_suffix_on_collision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=UTC):  # type: ignore[override]
            return cls(2026, 5, 25, 12, 30, 45, tzinfo=tz)

    monkeypatch.setattr(artifacts, "datetime", FixedDatetime)

    first = create_validation_result_dir(tmp_path, "demo_strategy")
    second = create_validation_result_dir(tmp_path, "demo_strategy")
    third = create_validation_result_dir(tmp_path, "demo_strategy")

    assert first.name == "2026-05-25T123045Z-demo_strategy"
    assert second.name == "2026-05-25T123045Z-demo_strategy-2"
    assert third.name == "2026-05-25T123045Z-demo_strategy-3"


def test_create_validation_result_dir_retries_atomic_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=UTC):  # type: ignore[override]
            return cls(2026, 5, 25, 12, 30, 45, tzinfo=tz)

    base_name = "2026-05-25T123045Z-demo_strategy"
    original_mkdir = Path.mkdir
    collided = False

    def mkdir_with_collision(path: Path, *args, **kwargs):
        nonlocal collided
        if path.name == base_name and not collided:
            collided = True
            original_mkdir(path, *args, **kwargs)
            raise FileExistsError(str(path))
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(artifacts, "datetime", FixedDatetime)
    monkeypatch.setattr(Path, "mkdir", mkdir_with_collision)

    result_dir = create_validation_result_dir(tmp_path, "demo_strategy")

    assert result_dir.name == "2026-05-25T123045Z-demo_strategy-2"
    assert (tmp_path / base_name).exists()


def test_write_json_artifact_is_stable(tmp_path: Path):
    path = write_json_artifact(tmp_path, "promotion_decision.json", {"b": 2, "a": 1})

    assert path == tmp_path / "promotion_decision.json"
    assert json.loads(path.read_text()) == {"a": 1, "b": 2}
    assert path.read_text() == '{\n  "a": 1,\n  "b": 2\n}\n'


def test_write_json_artifact_serializes_structured_payloads(tmp_path: Path):
    payload = {
        "model": ArtifactPayload(
            created_at=datetime(2026, 5, 25, 12, 30, 45, tzinfo=UTC),
            source_path=Path("configs/demo.toml"),
        ),
        "paths": (Path("results/summary.json"),),
        "dates": [date(2026, 5, 25)],
    }

    path = write_json_artifact(tmp_path, "nested/payload.json", payload)

    assert json.loads(path.read_text()) == {
        "dates": ["2026-05-25"],
        "model": {
            "created_at": "2026-05-25T12:30:45Z",
            "source_path": "configs/demo.toml",
        },
        "paths": ["results/summary.json"],
    }


@pytest.mark.parametrize("name", ["../escape.json", "/tmp/escape.json"])
def test_write_json_artifact_rejects_paths_outside_result_dir(tmp_path: Path, name: str):
    with pytest.raises(ValueError):
        write_json_artifact(tmp_path, name, {"ok": True})


def test_write_text_artifact_normalizes_newline_and_creates_parent_dir(tmp_path: Path):
    path = write_text_artifact(tmp_path, "notes/summary.md", "line")
    existing_newline = write_text_artifact(tmp_path, "notes/existing.md", "line\n")

    assert path == tmp_path / "notes" / "summary.md"
    assert path.read_text() == "line\n"
    assert existing_newline.read_text() == "line\n"
