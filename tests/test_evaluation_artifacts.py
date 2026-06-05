from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from quant_strategies.evaluation.artifacts import (
    create_evaluation_result_dir,
    table_metadata,
    write_evaluation_manifest,
    write_json_artifact,
    write_parquet_artifact,
    write_text_artifact,
)
from quant_strategies.provenance import file_sha256


def test_write_parquet_artifact_records_schema_hash_and_row_count(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    frame = pd.DataFrame(
        {
            "scenario_id": ["w/base", "w/base"],
            "timestamp": [
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 2, tzinfo=UTC),
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
    assert metadata["compression"] == "zstd"
    assert metadata["row_count"] == 2
    assert [column["name"] for column in metadata["columns"]] == [
        "scenario_id",
        "timestamp",
        "portfolio_value",
        "period_return",
        "drawdown",
    ]
    assert metadata["scenario_ids"] == ["w/base"]
    assert len(metadata["file_sha256"]) == 64
    assert len(metadata["schema_sha256"]) == 64
    assert metadata["byte_size"] > 0
    assert metadata["row_group_count"] >= 1


def test_write_parquet_artifact_can_report_logical_path_for_staged_file(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    frame = pd.DataFrame({"scenario_id": ["base"], "portfolio_value": [100.0]})

    metadata = write_parquet_artifact(
        result_dir,
        "tables_staging/portfolio_path.parquet",
        frame,
        artifact_kind="portfolio_path",
        scenario_ids=("base",),
        logical_name="tables/portfolio_path.parquet",
    )

    physical_path = result_dir / "tables_staging" / "portfolio_path.parquet"
    assert physical_path.exists()
    assert metadata["path"] == "tables/portfolio_path.parquet"
    assert metadata["file_sha256"] == file_sha256(physical_path)


def test_table_metadata_is_stable_for_empty_table(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    frame = pd.DataFrame({"scenario_id": [], "asset": [], "target_round_trip_turnover": []})

    metadata = write_parquet_artifact(
        result_dir,
        "tables/target_exposure_summary.parquet",
        frame,
        artifact_kind="target_exposure_summary",
        scenario_ids=(),
    )

    assert metadata["row_count"] == 0
    assert [column["name"] for column in metadata["columns"]] == [
        "scenario_id",
        "asset",
        "decision_count",
        "target_round_trip_turnover",
    ]
    logical_types = {column["name"]: column["logical_type"] for column in metadata["columns"]}
    assert logical_types["scenario_id"] == "string"
    assert logical_types["asset"] == "string"
    assert logical_types["target_round_trip_turnover"] == "double"
    assert logical_types["decision_count"] == "int64"


def test_table_metadata_reads_scenario_ids_from_parquet_footer(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    write_parquet_artifact(
        result_dir,
        "tables/trades.parquet",
        pd.DataFrame({"scenario_id": ["base"]}),
        artifact_kind="trades",
        scenario_ids=("base",),
    )

    metadata = table_metadata(
        result_dir,
        result_dir / "tables" / "trades.parquet",
        artifact_kind="trades",
    )

    assert metadata["scenario_ids"] == ["base"]


@pytest.mark.parametrize(
    ("artifact_kind", "frame", "expected_types"),
    [
        (
            "portfolio_path",
            pd.DataFrame({"scenario_id": []}),
            {
                "scenario_id": "string",
                "timestamp": "timestamp[us, tz=UTC]",
                "portfolio_value": "double",
                "period_return": "double",
                "drawdown": "double",
            },
        ),
        (
            "target_positions",
            pd.DataFrame({"scenario_id": []}),
            {
                "scenario_id": "string",
                "timestamp": "timestamp[us, tz=UTC]",
                "asset": "string",
                "target_weight": "double",
                "event": "string",
                "decision_time": "timestamp[us, tz=UTC]",
                "direction": "string",
            },
        ),
        (
            "target_exposure_summary",
            pd.DataFrame(),
            {
                "scenario_id": "string",
                "asset": "string",
                "decision_count": "int64",
                "target_round_trip_turnover": "double",
            },
        ),
        (
            "funding_cashflows",
            pd.DataFrame({"scenario_id": []}),
            {
                "scenario_id": "string",
                "timestamp": "timestamp[us, tz=UTC]",
                "asset": "string",
                "funding_rate": "double",
                "position_units": "double",
                "mark_price": "double",
                "funding_cashflow": "double",
            },
        ),
    ],
)
def test_write_parquet_artifact_materializes_empty_trace_table_schema(
    tmp_path: Path,
    artifact_kind: str,
    frame: pd.DataFrame,
    expected_types: dict[str, str],
):
    result_dir = tmp_path / "results"
    result_dir.mkdir()

    metadata = write_parquet_artifact(
        result_dir,
        f"tables/{artifact_kind}.parquet",
        frame,
        artifact_kind=artifact_kind,
        scenario_ids=(),
    )

    assert metadata["row_count"] == 0
    assert [column["name"] for column in metadata["columns"]] == list(expected_types)
    logical_types = {column["name"]: column["logical_type"] for column in metadata["columns"]}
    assert logical_types == expected_types


def test_write_evaluation_manifest_rejects_partial_trace_table_artifacts(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    config_path = tmp_path / "evaluation_config.toml"
    config_path.write_text("strategy_id = 'demo'\n")
    strategy_path = tmp_path / "demo_strategy.py"
    strategy_path.write_text('"""Demo strategy."""\n')
    table_metadata = write_parquet_artifact(
        result_dir,
        "tables/portfolio_path.parquet",
        pd.DataFrame({"scenario_id": ["base"], "portfolio_value": [100.0]}),
        artifact_kind="portfolio_path",
        scenario_ids=("base",),
    )

    try:
        write_evaluation_manifest(
            result_dir,
            repo_root=tmp_path,
            path_base=tmp_path,
            config=SimpleNamespace(strategy_id="demo", strategy_path=strategy_path),
            config_path=config_path,
            backend_name="unit-test",
            data_windows=[],
            table_artifacts=[table_metadata],
            scenario_summary=_scenario_summary("base"),
        )
    except ValueError as exc:
        assert "required trace tables" in str(exc)
    else:
        raise AssertionError("partial trace table artifacts should fail")


def test_write_evaluation_manifest_rejects_inconsistent_trace_scenario_ids(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    config_path = tmp_path / "evaluation_config.toml"
    config_path.write_text("strategy_id = 'demo'\n")
    strategy_path = tmp_path / "demo_strategy.py"
    strategy_path.write_text('"""Demo strategy."""\n')
    table_artifacts = _write_required_trace_tables(result_dir, scenario_ids=("base",))
    table_artifacts[-1] = {**table_artifacts[-1], "scenario_ids": ["stress"]}

    try:
        write_evaluation_manifest(
            result_dir,
            repo_root=tmp_path,
            path_base=tmp_path,
            config=SimpleNamespace(strategy_id="demo", strategy_path=strategy_path),
            config_path=config_path,
            backend_name="unit-test",
            data_windows=[],
            table_artifacts=table_artifacts,
            scenario_summary=_scenario_summary("base"),
        )
    except ValueError as exc:
        assert "scenario_ids" in str(exc)
    else:
        raise AssertionError("inconsistent trace table scenario_ids should fail")


def test_write_evaluation_manifest_rejects_forged_trace_table_metadata(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    config_path = tmp_path / "evaluation_config.toml"
    config_path.write_text("strategy_id = 'demo'\n")
    strategy_path = tmp_path / "demo_strategy.py"
    strategy_path.write_text('"""Demo strategy."""\n')
    table_artifacts = _write_required_trace_tables(result_dir, scenario_ids=("base",))
    table_artifacts[0] = {**table_artifacts[0], "row_count": table_artifacts[0]["row_count"] + 1}

    with pytest.raises(ValueError, match="trace table metadata"):
        write_evaluation_manifest(
            result_dir,
            repo_root=tmp_path,
            path_base=tmp_path,
            config=SimpleNamespace(strategy_id="demo", strategy_path=strategy_path),
            config_path=config_path,
            backend_name="unit-test",
            data_windows=[],
            table_artifacts=table_artifacts,
            scenario_summary=_scenario_summary("base"),
        )


def test_write_evaluation_manifest_rejects_tampered_trace_table_file_hash(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    config_path = tmp_path / "evaluation_config.toml"
    config_path.write_text("strategy_id = 'demo'\n")
    strategy_path = tmp_path / "demo_strategy.py"
    strategy_path.write_text('"""Demo strategy."""\n')
    table_artifacts = _write_required_trace_tables(result_dir, scenario_ids=("base",))
    table_artifacts[0] = {**table_artifacts[0], "file_sha256": "0" * 64}

    with pytest.raises(ValueError, match="file_sha256"):
        write_evaluation_manifest(
            result_dir,
            repo_root=tmp_path,
            path_base=tmp_path,
            config=SimpleNamespace(strategy_id="demo", strategy_path=strategy_path),
            config_path=config_path,
            backend_name="unit-test",
            data_windows=[],
            table_artifacts=table_artifacts,
            scenario_summary=_scenario_summary("base"),
        )


def test_write_evaluation_manifest_rejects_tampered_live_trace_table_file_hash(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    config_path = tmp_path / "evaluation_config.toml"
    config_path.write_text("strategy_id = 'demo'\n")
    strategy_path = tmp_path / "demo_strategy.py"
    strategy_path.write_text('"""Demo strategy."""\n')
    table_artifacts = _write_required_trace_tables(result_dir, scenario_ids=("base",))
    table_artifacts[0]["file_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="file_sha256"):
        write_evaluation_manifest(
            result_dir,
            repo_root=tmp_path,
            path_base=tmp_path,
            config=SimpleNamespace(strategy_id="demo", strategy_path=strategy_path),
            config_path=config_path,
            backend_name="unit-test",
            data_windows=[],
            table_artifacts=table_artifacts,
            scenario_summary=_scenario_summary("base"),
        )


def test_write_evaluation_manifest_rejects_forged_trace_table_scenario_ids(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    config_path = tmp_path / "evaluation_config.toml"
    config_path.write_text("strategy_id = 'demo'\n")
    strategy_path = tmp_path / "demo_strategy.py"
    strategy_path.write_text('"""Demo strategy."""\n')
    table_artifacts = [
        {**metadata, "scenario_ids": ["base", "stress"]}
        for metadata in _write_required_trace_tables(result_dir, scenario_ids=("base",))
    ]

    with pytest.raises(ValueError, match="scenario_ids"):
        write_evaluation_manifest(
            result_dir,
            repo_root=tmp_path,
            path_base=tmp_path,
            config=SimpleNamespace(strategy_id="demo", strategy_path=strategy_path),
            config_path=config_path,
            backend_name="unit-test",
            data_windows=[],
            table_artifacts=table_artifacts,
            scenario_summary=_scenario_summary("base", "stress"),
        )


def test_write_evaluation_manifest_rejects_mismatched_expected_completed_coverage(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    config_path = tmp_path / "evaluation_config.toml"
    config_path.write_text("strategy_id = 'demo'\n")
    strategy_path = tmp_path / "demo_strategy.py"
    strategy_path.write_text('"""Demo strategy."""\n')
    table_artifacts = _write_required_trace_tables(result_dir, scenario_ids=("base",))
    scenario_summary = {
        "scenario_coverage": {
            "expected_ids": ["base", "stress"],
            "completed_ids": ["base"],
        }
    }

    with pytest.raises(ValueError, match="scenario_coverage"):
        write_evaluation_manifest(
            result_dir,
            repo_root=tmp_path,
            path_base=tmp_path,
            config=SimpleNamespace(strategy_id="demo", strategy_path=strategy_path),
            config_path=config_path,
            backend_name="unit-test",
            data_windows=[],
            table_artifacts=table_artifacts,
            scenario_summary=scenario_summary,
        )


def test_write_evaluation_manifest_treats_empty_expected_coverage_as_declared(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    config_path = tmp_path / "evaluation_config.toml"
    config_path.write_text("strategy_id = 'demo'\n")
    strategy_path = tmp_path / "demo_strategy.py"
    strategy_path.write_text('"""Demo strategy."""\n')
    table_artifacts = _write_required_trace_tables(result_dir, scenario_ids=("base",))
    scenario_summary = {
        "scenario_coverage": {
            "expected_ids": [],
            "completed_ids": ["base"],
        }
    }

    with pytest.raises(ValueError, match="scenario_coverage"):
        write_evaluation_manifest(
            result_dir,
            repo_root=tmp_path,
            path_base=tmp_path,
            config=SimpleNamespace(strategy_id="demo", strategy_path=strategy_path),
            config_path=config_path,
            backend_name="unit-test",
            data_windows=[],
            table_artifacts=table_artifacts,
            scenario_summary=scenario_summary,
        )


@pytest.mark.parametrize("artifact_index", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("missing_value", [True, False])
def test_write_evaluation_manifest_rejects_missing_required_trace_table_metadata(
    tmp_path: Path,
    artifact_index: int,
    missing_value: bool,
):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    config_path = tmp_path / "evaluation_config.toml"
    config_path.write_text("strategy_id = 'demo'\n")
    strategy_path = tmp_path / "demo_strategy.py"
    strategy_path.write_text('"""Demo strategy."""\n')
    table_artifacts = _write_required_trace_tables(result_dir, scenario_ids=("base",))
    table_artifacts[artifact_index] = dict(table_artifacts[artifact_index])
    if missing_value:
        del table_artifacts[artifact_index]["file_sha256"]
    else:
        table_artifacts[artifact_index]["file_sha256"] = None

    with pytest.raises(ValueError, match="trace table metadata"):
        write_evaluation_manifest(
            result_dir,
            repo_root=tmp_path,
            path_base=tmp_path,
            config=SimpleNamespace(strategy_id="demo", strategy_path=strategy_path),
            config_path=config_path,
            backend_name="unit-test",
            data_windows=[],
            table_artifacts=table_artifacts,
            scenario_summary=_scenario_summary("base"),
        )


def test_write_evaluation_manifest_rejects_trace_table_scenario_ids_missing_expected_coverage(
    tmp_path: Path,
):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    config_path = tmp_path / "evaluation_config.toml"
    config_path.write_text("strategy_id = 'demo'\n")
    strategy_path = tmp_path / "demo_strategy.py"
    strategy_path.write_text('"""Demo strategy."""\n')
    table_artifacts = _write_required_trace_tables(result_dir, scenario_ids=("base",))

    with pytest.raises(ValueError, match="scenario_ids"):
        write_evaluation_manifest(
            result_dir,
            repo_root=tmp_path,
            path_base=tmp_path,
            config=SimpleNamespace(strategy_id="demo", strategy_path=strategy_path),
            config_path=config_path,
            backend_name="unit-test",
            data_windows=[],
            table_artifacts=table_artifacts,
            scenario_summary=_scenario_summary("base", "stress"),
        )


def test_write_evaluation_manifest_keeps_trace_tables_out_of_artifact_hashes(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    config_path = tmp_path / "evaluation_config.toml"
    config_path.write_text("strategy_id = 'demo'\n")
    strategy_path = tmp_path / "demo_strategy.py"
    strategy_path.write_text('"""Demo strategy."""\n')
    table_artifacts = _write_required_trace_tables(result_dir, scenario_ids=("base",))

    write_evaluation_manifest(
        result_dir,
        repo_root=tmp_path,
        path_base=tmp_path,
        config=SimpleNamespace(strategy_id="demo", strategy_path=strategy_path),
        config_path=config_path,
        backend_name="unit-test",
        data_windows=[],
        table_artifacts=table_artifacts,
        scenario_summary=_scenario_summary("base"),
    )

    manifest = json.loads((result_dir / "evaluation_manifest.json").read_text())
    artifact_paths = set(manifest["artifacts"])
    assert not any(path.endswith(".parquet") for path in artifact_paths)
    assert manifest["tables"][0]["path"] == "tables/portfolio_path.parquet"
    assert manifest["tables"][0]["file_sha256"]
    assert manifest["trace_artifacts"]["table_count"] == 5


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
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    first = create_evaluation_result_dir(root, "demo strategy", now=now)
    second = create_evaluation_result_dir(root, "demo strategy", now=now)

    assert first.name == "2026-01-01T120000Z-demo_strategy"
    assert second.name == "2026-01-01T120000Z-demo_strategy-2"


def _write_required_trace_tables(
    result_dir: Path, *, scenario_ids: tuple[str, ...]
) -> list[dict[str, object]]:
    return [
        write_parquet_artifact(
            result_dir,
            "tables/portfolio_path.parquet",
            pd.DataFrame(
                {
                    "scenario_id": list(scenario_ids),
                    "timestamp": [datetime(2026, 1, 1, tzinfo=UTC) for _ in scenario_ids],
                    "portfolio_value": [100.0 for _ in scenario_ids],
                    "period_return": [0.0 for _ in scenario_ids],
                    "drawdown": [0.0 for _ in scenario_ids],
                }
            ),
            artifact_kind="portfolio_path",
            scenario_ids=scenario_ids,
        ),
        write_parquet_artifact(
            result_dir,
            "tables/trades.parquet",
            pd.DataFrame({"scenario_id": list(scenario_ids)}),
            artifact_kind="trades",
            scenario_ids=scenario_ids,
        ),
        write_parquet_artifact(
            result_dir,
            "tables/target_positions.parquet",
            pd.DataFrame(
                {
                    "scenario_id": list(scenario_ids),
                    "timestamp": [datetime(2026, 1, 1, tzinfo=UTC) for _ in scenario_ids],
                    "asset": ["SPY" for _ in scenario_ids],
                    "target_weight": [1.0 for _ in scenario_ids],
                    "event": ["entry" for _ in scenario_ids],
                    "decision_time": [datetime(2026, 1, 1, tzinfo=UTC) for _ in scenario_ids],
                    "direction": ["long" for _ in scenario_ids],
                }
            ),
            artifact_kind="target_positions",
            scenario_ids=scenario_ids,
        ),
        write_parquet_artifact(
            result_dir,
            "tables/target_exposure_summary.parquet",
            pd.DataFrame(
                {
                    "scenario_id": list(scenario_ids),
                    "asset": ["SPY" for _ in scenario_ids],
                    "target_round_trip_turnover": [0.1 for _ in scenario_ids],
                }
            ),
            artifact_kind="target_exposure_summary",
            scenario_ids=scenario_ids,
        ),
        write_parquet_artifact(
            result_dir,
            "tables/funding_cashflows.parquet",
            pd.DataFrame(
                {
                    "scenario_id": [],
                    "timestamp": [],
                    "asset": [],
                    "funding_rate": [],
                    "position_units": [],
                    "mark_price": [],
                    "funding_cashflow": [],
                }
            ),
            artifact_kind="funding_cashflows",
            scenario_ids=scenario_ids,
        ),
    ]


def _scenario_summary(*scenario_ids: str) -> dict[str, object]:
    ids = list(scenario_ids)
    return {
        "scenario_coverage": {
            "expected_ids": ids,
            "completed_ids": ids,
        }
    }
