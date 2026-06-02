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

_REQUIRED_TRACE_TABLE_METADATA = {
    "path",
    "artifact_kind",
    "format",
    "compression",
    "row_count",
    "row_group_count",
    "column_count",
    "columns",
    "arrow_schema",
    "schema_sha256",
    "file_sha256",
    "byte_size",
    "scenario_ids",
}

_TRACE_TABLE_METADATA_COMPARE_FIELDS = (
    "path",
    "artifact_kind",
    "format",
    "compression",
    "row_count",
    "row_group_count",
    "column_count",
    "columns",
    "arrow_schema",
    "schema_sha256",
    "byte_size",
    "scenario_ids",
)

_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")

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

_SCENARIO_IDS_METADATA_KEY = b"quant_strategies.scenario_ids"
_TRUSTED_FILE_SHA256_TOKEN = object()
_TRUSTED_FILE_SHA256_TOKEN_KEY = "_trusted_file_sha256_token"
_TRUSTED_FILE_SHA256_VALUE_KEY = "_trusted_file_sha256"


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
    scenario_id_tuple = tuple(scenario_ids)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    table = _materialize_known_trace_columns(pa, table, artifact_kind)
    table = _with_scenario_ids_metadata(table, scenario_id_tuple)
    pq.write_table(table, path, compression="zstd")
    metadata = table_metadata(
        result_dir,
        path,
        artifact_kind=artifact_kind,
        scenario_ids=scenario_id_tuple,
        logical_name=logical_name,
    )
    metadata[_TRUSTED_FILE_SHA256_TOKEN_KEY] = _TRUSTED_FILE_SHA256_TOKEN
    metadata[_TRUSTED_FILE_SHA256_VALUE_KEY] = metadata["file_sha256"]
    return metadata


def table_metadata(
    result_dir: Path,
    path: Path,
    *,
    artifact_kind: str,
    scenario_ids: tuple[str, ...] = (),
    logical_name: str | None = None,
    include_file_hash: bool = True,
) -> dict[str, Any]:
    import pyarrow.parquet as pq

    parquet_file = pq.ParquetFile(path)
    parquet_metadata = parquet_file.metadata
    schema = parquet_file.schema_arrow
    footer_scenario_ids = _scenario_ids_from_footer(schema, artifact_kind=artifact_kind)
    if scenario_ids and list(scenario_ids) != footer_scenario_ids:
        raise ValueError(
            "supplied scenario_ids do not match Parquet metadata: "
            f"supplied={list(scenario_ids)!r}; file={footer_scenario_ids!r}"
        )
    arrow_schema = str(schema)
    manifest_path = _artifact_path(result_dir, logical_name) if logical_name is not None else path
    relative_path = manifest_path.resolve().relative_to(result_dir.resolve()).as_posix()
    metadata = {
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
        "byte_size": path.stat().st_size,
        "scenario_ids": footer_scenario_ids,
    }
    if include_file_hash:
        metadata["file_sha256"] = file_sha256(path)
    return metadata


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
    _validate_trace_table_artifacts(table_artifacts, result_dir=result_dir, scenario_summary=scenario_summary)
    manifest_table_artifacts = [_manifest_table_artifact(item) for item in table_artifacts]
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
        "tables": manifest_table_artifacts,
        "replayability": {
            "basis": "candidate config, strategy snapshot, normalized row hash, scenario assumptions, and Parquet trace tables",
            "input_rows_embedded": False,
            "limitation": "input rows are identified by normalized hash and upstream data config; raw rows are not embedded in evaluation artifacts",
        },
        "trace_artifacts": {
            "format": "parquet",
            "table_count": len(manifest_table_artifacts),
            "total_byte_size": sum(int(item["byte_size"]) for item in manifest_table_artifacts),
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


def _manifest_table_artifact(item: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if not str(key).startswith("_trusted_")}


def _materialize_known_trace_columns(pa: Any, table: Any, artifact_kind: str) -> Any:
    column_types = _TRACE_COLUMN_TYPES.get(artifact_kind)
    if column_types is None:
        return table

    fields = []
    columns = []
    for column_name, logical_type in column_types.items():
        arrow_type = _arrow_type(pa, logical_type)
        if column_name in table.schema.names:
            field = table.schema.field(column_name)
            fields.append(pa.field(column_name, arrow_type, nullable=field.nullable))
            columns.append(table[column_name].cast(arrow_type))
        else:
            fields.append(pa.field(column_name, arrow_type, nullable=True))
            columns.append(pa.nulls(table.num_rows, type=arrow_type))

    for field in table.schema:
        if field.name in column_types:
            continue
        fields.append(field)
        columns.append(table[field.name])
    return pa.Table.from_arrays(columns, schema=pa.schema(fields))


def _with_scenario_ids_metadata(table: Any, scenario_ids: tuple[str, ...]) -> Any:
    metadata = dict(table.schema.metadata or {})
    metadata[_SCENARIO_IDS_METADATA_KEY] = json.dumps(list(scenario_ids), allow_nan=False).encode("utf-8")
    return table.replace_schema_metadata(metadata)


def _scenario_ids_from_footer(schema: Any, *, artifact_kind: str) -> list[str]:
    metadata = schema.metadata or {}
    raw_value = metadata.get(_SCENARIO_IDS_METADATA_KEY)
    if raw_value is None:
        if artifact_kind in _TRACE_COLUMN_TYPES:
            raise ValueError(f"{artifact_kind} trace table is missing scenario_ids Parquet metadata")
        return []

    try:
        value = json.loads(raw_value.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{artifact_kind} trace table has invalid scenario_ids Parquet metadata") from exc

    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{artifact_kind} trace table scenario_ids Parquet metadata must be a list of strings")
    return value


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


def _validate_trace_table_artifacts(
    table_artifacts: list[dict[str, Any]],
    *,
    result_dir: Path,
    scenario_summary: Mapping[str, Any],
) -> None:
    kinds = []
    for index, item in enumerate(table_artifacts):
        if not isinstance(item, Mapping):
            raise ValueError(f"trace table metadata at index {index} must be a mapping")
        missing_keys = _REQUIRED_TRACE_TABLE_METADATA - set(item)
        none_keys = {key for key in _REQUIRED_TRACE_TABLE_METADATA if key in item and item[key] is None}
        if missing_keys:
            missing = ", ".join(sorted(missing_keys))
            raise ValueError(f"trace table metadata at index {index} is missing required metadata: {missing}")
        if none_keys:
            missing = ", ".join(sorted(none_keys))
            raise ValueError(f"trace table metadata at index {index} is missing required metadata: {missing}")

        artifact_kind = item["artifact_kind"]
        if not isinstance(artifact_kind, str) or not artifact_kind:
            raise ValueError(f"trace table metadata at index {index} has invalid artifact_kind")
        kinds.append(artifact_kind)

    required_kinds = set(_REQUIRED_TRACE_TABLES)
    actual_kinds = set(kinds)
    if len(table_artifacts) != len(_REQUIRED_TRACE_TABLES) or actual_kinds != required_kinds or len(kinds) != len(actual_kinds):
        missing = ", ".join(sorted(required_kinds - actual_kinds)) or "none"
        extra = ", ".join(sorted(str(kind) for kind in actual_kinds - required_kinds)) or "none"
        raise ValueError(
            "trace table metadata must contain exactly the required trace tables: "
            f"{', '.join(_REQUIRED_TRACE_TABLES)}; missing={missing}; extra={extra}"
        )

    by_kind = {item["artifact_kind"]: item for item in table_artifacts}
    expected_scenario_ids: set[Any] | None = None
    for kind, required_path in _REQUIRED_TRACE_TABLES.items():
        item = by_kind[kind]
        _validate_trace_table_metadata_item(item, kind=kind, required_path=required_path, result_dir=result_dir)

        scenario_ids = _trace_table_scenario_ids(item, kind=kind)
        if expected_scenario_ids is None:
            expected_scenario_ids = scenario_ids
        elif scenario_ids != expected_scenario_ids:
            raise ValueError("trace table scenario_ids must be consistent across required trace tables")

    coverage_scenario_ids = _scenario_coverage_ids(scenario_summary)
    if expected_scenario_ids is not None and expected_scenario_ids != coverage_scenario_ids:
        raise ValueError(
            "trace table scenario_ids must match scenario_summary scenario_coverage; "
            f"table={sorted(expected_scenario_ids)!r}; coverage={sorted(coverage_scenario_ids)!r}"
        )


def _validate_trace_table_metadata_item(
    item: Mapping[str, Any],
    *,
    kind: str,
    required_path: str,
    result_dir: Path,
) -> None:
    if not isinstance(item["path"], str):
        raise ValueError(f"{kind} trace table metadata path must be a string")
    try:
        artifact_path = _artifact_path(result_dir, item["path"])
    except ValueError as exc:
        raise ValueError(f"{kind} trace table metadata path must stay inside result_dir") from exc
    if artifact_path.suffix != ".parquet":
        raise ValueError(f"{kind} trace table metadata path must have .parquet suffix")
    if not artifact_path.is_file():
        raise ValueError(f"{kind} trace table metadata path does not exist under result_dir")
    if item["path"] != required_path:
        raise ValueError(f"{kind} trace table metadata path must be {required_path}")

    if item["format"] != "parquet":
        raise ValueError(f"{kind} trace table metadata format must be parquet")

    for hash_key in ("file_sha256", "schema_sha256"):
        if not isinstance(item[hash_key], str) or not _SHA256_PATTERN.fullmatch(item[hash_key]):
            raise ValueError(f"{kind} trace table metadata {hash_key} must be 64 hex characters")
    trusted_file_hash = item.get(_TRUSTED_FILE_SHA256_VALUE_KEY)
    if item.get(_TRUSTED_FILE_SHA256_TOKEN_KEY) is _TRUSTED_FILE_SHA256_TOKEN:
        if trusted_file_hash != item["file_sha256"]:
            raise ValueError(f"{kind} trace table metadata file_sha256 does not match trusted writer hash")
    elif file_sha256(artifact_path) != item["file_sha256"]:
        raise ValueError(f"{kind} trace table metadata file_sha256 does not match Parquet file")

    _validate_non_negative_int(item, "row_count", kind=kind)
    _validate_non_negative_int(item, "row_group_count", kind=kind)
    _validate_positive_int(item, "column_count", kind=kind)
    _validate_positive_int(item, "byte_size", kind=kind)

    columns = item["columns"]
    if not isinstance(columns, list) or not any(
        isinstance(column, Mapping) and column.get("name") == "scenario_id" for column in columns
    ):
        raise ValueError(f"{kind} trace table metadata columns must include scenario_id")

    scenario_ids = item["scenario_ids"]
    if not isinstance(scenario_ids, (list, tuple)):
        raise ValueError(f"{kind} trace table scenario_ids must be a list or tuple")

    try:
        actual_metadata = table_metadata(
            result_dir,
            artifact_path,
            artifact_kind=kind,
            logical_name=item["path"],
            include_file_hash=False,
        )
    except Exception as exc:
        raise ValueError(f"{kind} trace table metadata could not be verified from Parquet file") from exc

    for key in _TRACE_TABLE_METADATA_COMPARE_FIELDS:
        expected_value = actual_metadata[key]
        supplied_value = list(scenario_ids) if key == "scenario_ids" else item[key]
        if supplied_value != expected_value:
            raise ValueError(
                f"{kind} trace table metadata does not match Parquet file for {key}: "
                f"supplied={supplied_value!r}; actual={expected_value!r}"
            )


def _validate_non_negative_int(item: Mapping[str, Any], key: str, *, kind: str) -> None:
    value = item[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{kind} trace table metadata {key} must be >= 0")


def _validate_positive_int(item: Mapping[str, Any], key: str, *, kind: str) -> None:
    value = item[key]
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{kind} trace table metadata {key} must be > 0")


def _trace_table_scenario_ids(item: Mapping[str, Any], *, kind: str) -> set[Any]:
    scenario_ids = item["scenario_ids"]
    if not isinstance(scenario_ids, (list, tuple)):
        raise ValueError(f"{kind} trace table scenario_ids must be a list or tuple")
    return set(scenario_ids)


def _scenario_coverage_ids(scenario_summary: Mapping[str, Any]) -> set[Any]:
    scenario_coverage = scenario_summary.get("scenario_coverage")
    if not isinstance(scenario_coverage, Mapping):
        raise ValueError("scenario_ids validation requires scenario_summary scenario_coverage")

    has_expected_ids = "expected_ids" in scenario_coverage
    has_completed_ids = "completed_ids" in scenario_coverage
    expected_ids = _coverage_id_set(scenario_coverage["expected_ids"]) if has_expected_ids else None
    completed_ids = _coverage_id_set(scenario_coverage["completed_ids"]) if has_completed_ids else None
    if has_expected_ids and has_completed_ids and expected_ids != completed_ids:
        raise ValueError(
            "scenario_coverage expected_ids and completed_ids must match for a completed evaluation manifest; "
            f"expected={sorted(expected_ids)!r}; completed={sorted(completed_ids)!r}"
        )
    if has_expected_ids:
        return expected_ids
    if has_completed_ids:
        return completed_ids
    return set(scenario_coverage)


def _coverage_id_set(value: Any) -> set[Any]:
    if value is None:
        raise ValueError("scenario_ids coverage expected_ids/completed_ids must be arrays")
    if not isinstance(value, (list, tuple, set)):
        raise ValueError("scenario_ids coverage expected_ids/completed_ids must be arrays")
    return set(value)


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
