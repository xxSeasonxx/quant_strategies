from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_strategies.core.serialization import json_safe_value
from quant_strategies.evaluation.metrics import evaluation_metric_semantics
from quant_strategies.provenance import (
    artifact_hashes,
    environment_identity,
    file_sha256,
    source_identity,
    text_sha256,
)

_REQUIRED_TRACE_TABLES = {
    "portfolio_path": "tables/portfolio_path.parquet",
    "trades": "tables/trades.parquet",
    "positions": "tables/positions.parquet",
    "per_asset_metrics": "tables/per_asset_metrics.parquet",
}

_TRACE_COLUMN_TYPES = {
    "portfolio_path": {
        "scenario_id": "string",
        "timestamp": "timestamp_us_utc",
        "portfolio_value": "float64",
        "period_return": "float64",
        "drawdown": "float64",
    },
    "trades": {
        "scenario_id": "string",
    },
    "positions": {
        "scenario_id": "string",
        "asset": "string",
        "weight": "float64",
    },
    "per_asset_metrics": {
        "scenario_id": "string",
        "asset": "string",
        "trade_count": "int64",
        "turnover": "float64",
    },
}


def create_evaluation_result_dir(results_root: Path, strategy_id: str, *, now: datetime | None = None) -> Path:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    base_name = f"{timestamp}-{_safe_name(strategy_id)}"
    results_root.mkdir(parents=True, exist_ok=True)

    suffix = 1
    while True:
        name = base_name if suffix == 1 else f"{base_name}-{suffix}"
        result_dir = results_root / name
        try:
            result_dir.mkdir()
        except FileExistsError:
            suffix += 1
            continue
        return result_dir


def initialize_evaluation_artifacts(config_path: Path, strategy_path: Path, result_dir: Path) -> None:
    shutil.copyfile(config_path, result_dir / "evaluation_config.toml")
    if strategy_path.is_file():
        shutil.copyfile(strategy_path, result_dir / "strategy_snapshot.py")


def write_json_artifact(result_dir: Path, name: str, payload: Any) -> Path:
    path = _artifact_path(result_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe_value(payload), indent=2, sort_keys=True, allow_nan=False) + "\n")
    return path


def write_text_artifact(result_dir: Path, name: str, payload: str) -> Path:
    path = _artifact_path(result_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload)
    return path


def write_data_manifest(result_dir: Path, *, windows: list[dict[str, Any]]) -> Path:
    return write_json_artifact(
        result_dir,
        "data_manifest.json",
        {
            "schema_version": "quant_strategies.evaluation.data_manifest/v1",
            "windows": windows,
        },
    )


def write_parquet_artifact(
    result_dir: Path,
    name: str,
    frame: Any,
    *,
    artifact_kind: str,
    scenario_ids: Iterable[str],
    logical_name: str | None = None,
) -> dict[str, Any]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = _artifact_path(result_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    table = _cast_known_trace_columns(pa, table, artifact_kind)
    pq.write_table(table, path, compression="zstd")
    return table_metadata(
        result_dir,
        path,
        artifact_kind=artifact_kind,
        scenario_ids=tuple(scenario_ids),
        logical_name=logical_name,
    )


def table_metadata(
    result_dir: Path,
    path: Path,
    *,
    artifact_kind: str,
    scenario_ids: tuple[str, ...],
    logical_name: str | None = None,
) -> dict[str, Any]:
    import pyarrow.parquet as pq

    parquet_file = pq.ParquetFile(path)
    parquet_metadata = parquet_file.metadata
    schema = parquet_file.schema_arrow
    arrow_schema = str(schema)
    manifest_path = _artifact_path(result_dir, logical_name) if logical_name is not None else path
    relative_path = manifest_path.resolve().relative_to(result_dir.resolve()).as_posix()
    return {
        "path": relative_path,
        "artifact_kind": artifact_kind,
        "format": "parquet",
        "compression": _compression_from_footer(parquet_metadata),
        "row_count": int(parquet_metadata.num_rows),
        "row_group_count": int(parquet_metadata.num_row_groups),
        "column_count": len(schema.names),
        "columns": [
            {
                "name": field.name,
                "logical_type": str(field.type),
                "nullable": bool(field.nullable),
            }
            for field in schema
        ],
        "arrow_schema": arrow_schema,
        "schema_sha256": text_sha256(arrow_schema),
        "file_sha256": file_sha256(path),
        "byte_size": path.stat().st_size,
        "scenario_ids": list(scenario_ids),
    }


def write_evaluation_manifest(
    result_dir: Path,
    *,
    repo_root: Path,
    path_base: Path,
    config: Any,
    config_path: Path,
    backend_name: str,
    data_windows: list[dict[str, Any]],
    table_artifacts: list[dict[str, Any]],
    scenario_summary: Mapping[str, Any],
) -> Path:
    _validate_trace_table_artifacts(table_artifacts)
    write_json_artifact(
        result_dir,
        "environment.json",
        environment_identity(
            repo_root,
            package_names=("quant-strategies", "quant-data", "pydantic", "pandas", "pyarrow", "vectorbtpro"),
            exclude_paths=(result_dir,),
        ),
    )
    payload = {
        "manifest_schema_version": "quant_strategies.evaluation.manifest/v1",
        "artifact_profile": "evaluation_parquet_trace_v1",
        "repository": source_identity(repo_root),
        "evaluation": {
            "strategy_id": config.strategy_id,
            "backend": {
                "name": backend_name,
                "version": None,
            },
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "config_path": _relative_path(config_path, path_base),
            "config_sha256": file_sha256(config_path),
            "assessment_status": "evaluation_complete",
            "evidence_class": "research_evaluation",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
        },
        "strategy": {
            "path": _relative_path(Path(config.strategy_path), path_base),
            "snapshot_sha256": _optional_hash(result_dir / "strategy_snapshot.py"),
        },
        "data": {
            "manifest_path": "data_manifest.json",
            "windows": data_windows,
        },
        "metric_semantics": evaluation_metric_semantics(),
        "scenario_summary": json_safe_value(scenario_summary),
        "scenario_coverage": scenario_summary["scenario_coverage"],
        "tables": table_artifacts,
        "replayability": {
            "basis": "candidate config, strategy snapshot, normalized row hash, scenario assumptions, and Parquet trace tables",
            "input_rows_embedded": False,
            "limitation": "input rows are identified by normalized hash and upstream data config; raw rows are not embedded in evaluation artifacts",
        },
        "trace_artifacts": {
            "format": "parquet",
            "table_count": len(table_artifacts),
            "total_byte_size": sum(int(item["byte_size"]) for item in table_artifacts),
        },
        "artifacts": artifact_hashes(
            result_dir,
            exclude_names={
                "environment.json",
                "evaluation_manifest.json",
                "portfolio_path.parquet",
                "trades.parquet",
                "positions.parquet",
                "per_asset_metrics.parquet",
            },
            recursive=True,
        ),
    }
    return write_json_artifact(result_dir, "evaluation_manifest.json", payload)


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


def _cast_known_trace_columns(pa: Any, table: Any, artifact_kind: str) -> Any:
    column_types = _TRACE_COLUMN_TYPES.get(artifact_kind)
    if column_types is None:
        return table

    fields = []
    columns = []
    for field in table.schema:
        arrow_type = _arrow_type(pa, column_types.get(field.name))
        if arrow_type is None:
            fields.append(field)
            columns.append(table[field.name])
            continue
        fields.append(pa.field(field.name, arrow_type, nullable=field.nullable))
        columns.append(table[field.name].cast(arrow_type))
    return pa.Table.from_arrays(columns, schema=pa.schema(fields))


def _arrow_type(pa: Any, logical_type: str | None) -> Any:
    if logical_type == "string":
        return pa.string()
    if logical_type == "float64":
        return pa.float64()
    if logical_type == "int64":
        return pa.int64()
    if logical_type == "timestamp_us_utc":
        return pa.timestamp("us", tz="UTC")
    return None


def _validate_trace_table_artifacts(table_artifacts: list[dict[str, Any]]) -> None:
    kinds = []
    for index, item in enumerate(table_artifacts):
        if not isinstance(item, Mapping):
            raise ValueError(f"trace table artifact at index {index} must be a mapping")
        missing_keys = {"artifact_kind", "path", "format", "byte_size", "scenario_ids"} - set(item)
        if missing_keys:
            missing = ", ".join(sorted(missing_keys))
            raise ValueError(f"trace table artifact at index {index} is missing required metadata: {missing}")
        kinds.append(item["artifact_kind"])

    required_kinds = set(_REQUIRED_TRACE_TABLES)
    actual_kinds = set(kinds)
    if len(table_artifacts) != len(_REQUIRED_TRACE_TABLES) or actual_kinds != required_kinds or len(kinds) != len(actual_kinds):
        missing = ", ".join(sorted(required_kinds - actual_kinds)) or "none"
        extra = ", ".join(sorted(str(kind) for kind in actual_kinds - required_kinds)) or "none"
        raise ValueError(
            "table_artifacts must contain exactly the required trace tables: "
            f"{', '.join(_REQUIRED_TRACE_TABLES)}; missing={missing}; extra={extra}"
        )

    by_kind = {item["artifact_kind"]: item for item in table_artifacts}
    expected_scenario_ids: tuple[Any, ...] | None = None
    for kind, required_path in _REQUIRED_TRACE_TABLES.items():
        item = by_kind[kind]
        if item["path"] != required_path:
            raise ValueError(f"{kind} trace table path must be {required_path}")
        if item["format"] != "parquet":
            raise ValueError(f"{kind} trace table format must be parquet")

        scenario_ids = item["scenario_ids"]
        if not isinstance(scenario_ids, (list, tuple)):
            raise ValueError(f"{kind} trace table scenario_ids must be a list or tuple")
        scenario_ids_tuple = tuple(scenario_ids)
        if expected_scenario_ids is None:
            expected_scenario_ids = scenario_ids_tuple
        elif scenario_ids_tuple != expected_scenario_ids:
            raise ValueError("trace table scenario_ids must be consistent across required trace tables")


def _compression_from_footer(metadata: Any) -> str | dict[str, str]:
    compression_by_column: dict[str, str] = {}
    for row_group_index in range(metadata.num_row_groups):
        row_group = metadata.row_group(row_group_index)
        for column_index in range(row_group.num_columns):
            column = row_group.column(column_index)
            compression_by_column[column.path_in_schema] = str(column.compression).lower()
    compressions = set(compression_by_column.values())
    if len(compressions) == 1:
        return compressions.pop()
    return compression_by_column or "zstd"


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("_") or "evaluation"


def _optional_hash(path: Path) -> str | None:
    try:
        return file_sha256(path)
    except OSError:
        return None


def _relative_path(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return str(path)
