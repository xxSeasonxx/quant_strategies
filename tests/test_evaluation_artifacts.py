from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from quant_strategies.evaluation.artifacts import (
    create_evaluation_result_dir,
    write_json_artifact,
    write_parquet_artifact,
    write_text_artifact,
)


def test_write_parquet_artifact_records_schema_hash_and_row_count(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    frame = pd.DataFrame(
        {
            "scenario_id": ["w/base", "w/base"],
            "timestamp": [
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 2, tzinfo=timezone.utc),
            ],
            "portfolio_value": [100.0, 101.0],
        }
    )

    metadata = write_parquet_artifact(
        result_dir,
        "tables/portfolio_path.parquet",
        frame,
        artifact_kind="portfolio_path",
        scenario_ids=("w/base",),
    )

    path = result_dir / "tables" / "portfolio_path.parquet"
    assert path.exists()
    assert metadata["path"] == "tables/portfolio_path.parquet"
    assert metadata["artifact_kind"] == "portfolio_path"
    assert metadata["format"] == "parquet"
    assert metadata["row_count"] == 2
    assert [column["name"] for column in metadata["columns"]] == ["scenario_id", "timestamp", "portfolio_value"]
    assert metadata["scenario_ids"] == ["w/base"]
    assert len(metadata["file_sha256"]) == 64
    assert len(metadata["schema_sha256"]) == 64
    assert metadata["byte_size"] > 0
    assert metadata["row_group_count"] >= 1


def test_table_metadata_is_stable_for_empty_table(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    frame = pd.DataFrame({"scenario_id": [], "asset": [], "turnover": []})

    metadata = write_parquet_artifact(
        result_dir,
        "tables/per_asset_metrics.parquet",
        frame,
        artifact_kind="per_asset_metrics",
        scenario_ids=(),
    )

    assert metadata["row_count"] == 0
    assert [column["name"] for column in metadata["columns"]] == ["scenario_id", "asset", "turnover"]
    assert "scenario_id" in metadata["arrow_schema"]


def test_write_json_artifact_rejects_path_escape(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()

    try:
        write_json_artifact(result_dir, "../escape.json", {"x": 1})
    except ValueError as exc:
        assert "Artifact name must stay inside result_dir" in str(exc)
    else:
        raise AssertionError("path escape should fail")


def test_write_text_artifact_writes_plain_markdown(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()

    path = write_text_artifact(result_dir, "notes.md", "# Notes\n")

    assert path == result_dir / "notes.md"
    assert path.read_text() == "# Notes\n"


def test_create_evaluation_result_dir_uses_strategy_id_and_suffix(tmp_path: Path):
    root = tmp_path / "evaluation_results"
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    first = create_evaluation_result_dir(root, "demo strategy", now=now)
    second = create_evaluation_result_dir(root, "demo strategy", now=now)

    assert first.name == "2026-01-01T120000Z-demo_strategy"
    assert second.name == "2026-01-01T120000Z-demo_strategy-2"
