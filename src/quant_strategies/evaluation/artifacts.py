from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
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
    "target_positions": "tables/target_positions.parquet",
    "target_exposure_summary": "tables/target_exposure_summary.parquet",
    "execution_events": "tables/execution_events.parquet",
    "funding_cashflows": "tables/funding_cashflows.parquet",
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

_REQUIRED_DECISION_RECORD_METADATA = {
    "path",
    "artifact_kind",
    "format",
    "row_count",
    "sha256",
    "byte_size",
}

_REQUIRED_INPUT_ROWS_METADATA = _REQUIRED_TRACE_TABLE_METADATA | {"normalized_rows_sha256"}

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
    "target_positions": {
        "scenario_id": "string",
        "timestamp": "timestamp_us_utc",
        "asset": "string",
        "target_weight": "float64",
        "event": "string",
        "decision_time": "timestamp_us_utc",
        "direction": "string",
    },
    "target_exposure_summary": {
        "scenario_id": "string",
        "asset": "string",
        "decision_count": "int64",
        "target_round_trip_turnover": "float64",
    },
    "funding_cashflows": {
        "scenario_id": "string",
        "timestamp": "timestamp_us_utc",
        "asset": "string",
        "funding_rate": "float64",
        "position_units": "float64",
        "mark_price": "float64",
        "funding_cashflow": "float64",
    },
    "execution_events": {
        "scenario_id": "string",
        "asset": "string",
        "timestamp": "timestamp_us_utc",
        "reason": "string",
        "side": "string",
        "fill_price": "float64",
        "delta_units": "float64",
        "normalized_notional": "float64",
        "real_notional": "float64",
        "base_cost": "float64",
        "impact_cost": "float64",
        "total_cost": "float64",
        "bar_notional_volume": "float64",
        "adv_notional_volume": "float64",
        "bar_participation": "float64",
        "adv_participation": "float64",
        "decision_time": "timestamp_us_utc",
        "decision_id": "string",
    },
}

_SCENARIO_IDS_METADATA_KEY = b"quant_strategies.scenario_ids"


class _TrustedTableMetadata(dict[str, Any]):
    __slots__ = ("_trusted_file_sha256",)

    def __init__(self, payload: Mapping[str, Any], *, trusted_file_sha256: str) -> None:
        super().__init__(payload)
        object.__setattr__(self, "_trusted_file_sha256", trusted_file_sha256)

    @property
    def trusted_file_sha256(self) -> str:
        return self._trusted_file_sha256

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(f"{type(self).__name__} attributes are immutable")


def create_evaluation_result_dir(
    results_root: Path, strategy_id: str, *, now: datetime | None = None
) -> Path:
    timestamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H%M%SZ")
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


def initialize_evaluation_artifacts(
    config_path: Path, strategy_path: Path, result_dir: Path
) -> None:
    shutil.copyfile(config_path, result_dir / "evaluation_config.toml")
    if strategy_path.is_file():
        shutil.copyfile(strategy_path, result_dir / "strategy_snapshot.py")


def write_json_artifact(result_dir: Path, name: str, payload: Any) -> Path:
    path = _artifact_path(result_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_safe_value(payload), indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
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


def write_input_rows_artifact(
    result_dir: Path,
    *,
    window_id: str,
    rows: Sequence[Mapping[str, Any]],
    normalized_rows_sha256: str,
) -> dict[str, Any]:
    import pandas as pd

    artifact_name = f"audit/input_rows/{_audit_artifact_stem(window_id)}.parquet"
    frame = pd.DataFrame([dict(row) for row in rows])
    metadata = dict(
        write_parquet_artifact(
            result_dir,
            artifact_name,
            frame,
            artifact_kind="normalized_input_rows",
            scenario_ids=(),
        )
    )
    metadata["normalized_rows_sha256"] = normalized_rows_sha256
    return metadata


def write_decision_records_artifact(
    result_dir: Path,
    *,
    window_id: str,
    decisions: Sequence[Any],
) -> dict[str, Any]:
    artifact_name = f"audit/decision_records/{_audit_artifact_stem(window_id)}.jsonl"
    payload = _canonical_jsonl_lines(decisions)
    path = write_text_artifact(result_dir, artifact_name, payload)
    return {
        "path": path.relative_to(result_dir).as_posix(),
        "artifact_kind": "decision_records",
        "format": "jsonl",
        "row_count": len(decisions),
        "sha256": file_sha256(path),
        "byte_size": path.stat().st_size,
    }


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
    return _TrustedTableMetadata(metadata, trusted_file_sha256=metadata["file_sha256"])


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
    logical_schema = schema.remove_metadata()
    footer_scenario_ids = _scenario_ids_from_footer(schema, artifact_kind=artifact_kind)
    if scenario_ids and list(scenario_ids) != footer_scenario_ids:
        raise ValueError(
            "supplied scenario_ids do not match Parquet metadata: "
            f"supplied={list(scenario_ids)!r}; file={footer_scenario_ids!r}"
        )
    arrow_schema = str(logical_schema)
    manifest_path = _artifact_path(result_dir, logical_name) if logical_name is not None else path
    relative_path = manifest_path.resolve().relative_to(result_dir.resolve()).as_posix()
    metadata = {
        "path": relative_path,
        "artifact_kind": artifact_kind,
        "format": "parquet",
        "compression": _compression_from_footer(parquet_metadata),
        "row_count": int(parquet_metadata.num_rows),
        "row_group_count": int(parquet_metadata.num_row_groups),
        "column_count": len(logical_schema.names),
        "columns": [
            {
                "name": field.name,
                "logical_type": str(field.type),
                "nullable": bool(field.nullable),
            }
            for field in logical_schema
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
    annualization_cadence: Mapping[str, Any] | None = None,
    evidence_quality_warnings: Sequence[str] = (),
) -> Path:
    _validate_trace_table_artifacts(
        table_artifacts, result_dir=result_dir, scenario_summary=scenario_summary
    )
    manifest_table_artifacts = [dict(item) for item in table_artifacts]
    audit_artifacts = _validated_audit_artifacts_from_windows(data_windows, result_dir=result_dir)
    input_rows_embedded = bool(data_windows)
    decision_records_embedded = bool(data_windows)
    write_json_artifact(
        result_dir,
        "environment.json",
        environment_identity(
            repo_root,
            package_names=(
                "quant-strategies",
                "quant-data",
                "pydantic",
                "pandas",
                "pyarrow",
            ),
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
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "config_path": _relative_path(config_path, path_base),
            "config_sha256": file_sha256(config_path),
            "assessment_status": "evaluation_complete",
            "evidence_class": "research_evaluation",
            "evidence_quality_warnings": list(evidence_quality_warnings),
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
        "annualization_cadence": json_safe_value(annualization_cadence or {}),
        "scenario_summary": json_safe_value(scenario_summary),
        "scenario_coverage": scenario_summary["scenario_coverage"],
        "audit_artifacts": audit_artifacts,
        "tables": manifest_table_artifacts,
        "replayability": {
            "basis": (
                "candidate config, strategy snapshot, normalized input row snapshots, "
                "decision records, scenario assumptions, and Parquet trace tables"
            ),
            "replayable_from_artifacts": input_rows_embedded and decision_records_embedded,
            "input_rows_embedded": input_rows_embedded,
            "decision_records_embedded": decision_records_embedded,
            "limitation": "upstream data provenance is recorded, but vendor truth still belongs to quant_data",
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
                "target_positions.parquet",
                "target_exposure_summary.parquet",
                "execution_events.parquet",
                "funding_cashflows.parquet",
                *(Path(item["path"]).name for item in audit_artifacts["input_rows"]),
            },
            recursive=True,
        ),
    }
    return write_json_artifact(result_dir, "evaluation_manifest.json", payload)


def _validated_audit_artifacts_from_windows(
    data_windows: list[dict[str, Any]],
    *,
    result_dir: Path,
) -> dict[str, list[dict[str, Any]]]:
    input_rows: list[dict[str, Any]] = []
    decision_records: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for window in data_windows:
        window_id = _data_window_string(window, "window_id")
        expected_input_path = f"audit/input_rows/{_audit_artifact_stem(window_id)}.parquet"
        expected_decision_path = f"audit/decision_records/{_audit_artifact_stem(window_id)}.jsonl"
        row_count = _data_window_non_negative_int(window, "row_count")
        decision_count = _data_window_non_negative_int(window, "decision_count")
        normalized_rows_hash = _data_window_sha256(window, "normalized_rows_sha256")
        input_rows_artifact = window.get("input_rows_artifact")
        decision_records_artifact = window.get("decision_records_artifact")
        if not isinstance(input_rows_artifact, Mapping):
            raise ValueError(
                f"data window {window_id!r} is missing input_rows audit artifact metadata"
            )
        if not isinstance(decision_records_artifact, Mapping):
            raise ValueError(
                f"data window {window_id!r} is missing decision_records audit artifact metadata"
            )

        _validate_input_rows_audit_artifact(
            input_rows_artifact,
            result_dir=result_dir,
            expected_path=expected_input_path,
            expected_row_count=row_count,
            expected_normalized_rows_sha256=normalized_rows_hash,
        )
        _record_unique_audit_path(input_rows_artifact["path"], seen_paths)
        _validate_decision_records_audit_artifact(
            decision_records_artifact,
            result_dir=result_dir,
            expected_path=expected_decision_path,
            expected_row_count=decision_count,
        )
        _record_unique_audit_path(decision_records_artifact["path"], seen_paths)
        input_rows.append(dict(input_rows_artifact))
        decision_records.append(dict(decision_records_artifact))
    return {
        "input_rows": input_rows,
        "decision_records": decision_records,
    }


def _validate_input_rows_audit_artifact(
    item: Mapping[str, Any],
    *,
    result_dir: Path,
    expected_path: str,
    expected_row_count: int,
    expected_normalized_rows_sha256: str,
) -> None:
    missing_keys = _REQUIRED_INPUT_ROWS_METADATA - set(item)
    none_keys = {key for key in _REQUIRED_INPUT_ROWS_METADATA if key in item and item[key] is None}
    if missing_keys:
        missing = ", ".join(sorted(missing_keys))
        raise ValueError(f"input_rows audit artifact is missing required metadata: {missing}")
    if none_keys:
        missing = ", ".join(sorted(none_keys))
        raise ValueError(f"input_rows audit artifact is missing required metadata: {missing}")

    if item["artifact_kind"] != "normalized_input_rows":
        raise ValueError("input_rows audit artifact artifact_kind must be normalized_input_rows")
    if item["format"] != "parquet":
        raise ValueError("input_rows audit artifact format must be parquet")
    if item["scenario_ids"] != []:
        raise ValueError("input_rows audit artifact scenario_ids must be empty")
    if item["path"] != expected_path:
        raise ValueError("input_rows audit artifact path does not match data window")
    artifact_path = _validated_audit_path(
        result_dir, item["path"], suffix=".parquet", label="input_rows"
    )
    for hash_key in ("file_sha256", "schema_sha256"):
        if not isinstance(item[hash_key], str) or not _SHA256_PATTERN.fullmatch(item[hash_key]):
            raise ValueError(f"input_rows audit artifact {hash_key} must be 64 hex characters")
    if file_sha256(artifact_path) != item["file_sha256"]:
        raise ValueError("input_rows audit artifact file_sha256 does not match file")
    if item["normalized_rows_sha256"] != expected_normalized_rows_sha256:
        raise ValueError(
            "input_rows audit artifact normalized_rows_sha256 does not match data window"
        )

    _validate_non_negative_int(item, "row_count", kind="input_rows audit artifact")
    if item["row_count"] != expected_row_count:
        raise ValueError("input_rows audit artifact row_count does not match data window row_count")
    _validate_non_negative_int(item, "row_group_count", kind="input_rows audit artifact")
    _validate_positive_int(item, "column_count", kind="input_rows audit artifact")
    _validate_positive_int(item, "byte_size", kind="input_rows audit artifact")
    actual_metadata = table_metadata(
        result_dir,
        artifact_path,
        artifact_kind="normalized_input_rows",
        logical_name=item["path"],
        include_file_hash=False,
    )
    for key in _TRACE_TABLE_METADATA_COMPARE_FIELDS:
        if item[key] != actual_metadata[key]:
            raise ValueError(
                f"input_rows audit artifact metadata does not match Parquet file for {key}"
            )


def _validate_decision_records_audit_artifact(
    item: Mapping[str, Any],
    *,
    result_dir: Path,
    expected_path: str,
    expected_row_count: int,
) -> None:
    missing_keys = _REQUIRED_DECISION_RECORD_METADATA - set(item)
    none_keys = {
        key for key in _REQUIRED_DECISION_RECORD_METADATA if key in item and item[key] is None
    }
    if missing_keys:
        missing = ", ".join(sorted(missing_keys))
        raise ValueError(f"decision_records audit artifact is missing required metadata: {missing}")
    if none_keys:
        missing = ", ".join(sorted(none_keys))
        raise ValueError(f"decision_records audit artifact is missing required metadata: {missing}")
    if item["artifact_kind"] != "decision_records":
        raise ValueError("decision_records audit artifact artifact_kind must be decision_records")
    if item["format"] != "jsonl":
        raise ValueError("decision_records audit artifact format must be jsonl")
    if item["path"] != expected_path:
        raise ValueError("decision_records audit artifact path does not match data window")
    artifact_path = _validated_audit_path(
        result_dir, item["path"], suffix=".jsonl", label="decision_records"
    )
    if not isinstance(item["sha256"], str) or not _SHA256_PATTERN.fullmatch(item["sha256"]):
        raise ValueError("decision_records audit artifact sha256 must be 64 hex characters")
    if file_sha256(artifact_path) != item["sha256"]:
        raise ValueError("decision_records audit artifact sha256 does not match file")
    _validate_non_negative_int(item, "row_count", kind="decision_records audit artifact")
    if item["row_count"] != expected_row_count:
        raise ValueError(
            "decision_records audit artifact row_count does not match data window decision_count"
        )
    _validate_non_negative_int(item, "byte_size", kind="decision_records audit artifact")
    if item["byte_size"] != artifact_path.stat().st_size:
        raise ValueError("decision_records audit artifact byte_size does not match file")
    lines = artifact_path.read_text().splitlines()
    if len(lines) != item["row_count"]:
        raise ValueError("decision_records audit artifact row_count does not match file")
    for line in lines:
        json.loads(line)


def _data_window_string(window: Mapping[str, Any], key: str) -> str:
    value = window.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"data window {key} must be a non-empty string")
    return value


def _data_window_non_negative_int(window: Mapping[str, Any], key: str) -> int:
    value = window.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"data window {key} must be a non-negative integer")
    return value


def _data_window_sha256(window: Mapping[str, Any], key: str) -> str:
    value = window.get(key)
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"data window {key} must be 64 hex characters")
    return value


def _validated_audit_path(result_dir: Path, path: Any, *, suffix: str, label: str) -> Path:
    if not isinstance(path, str):
        raise ValueError(f"{label} audit artifact path must be a string")
    try:
        artifact_path = _artifact_path(result_dir, path)
    except ValueError as exc:
        raise ValueError(f"{label} audit artifact path must stay inside result_dir") from exc
    if artifact_path.suffix != suffix:
        raise ValueError(f"{label} audit artifact path must have {suffix} suffix")
    if not artifact_path.is_file():
        raise ValueError(f"{label} audit artifact path does not exist under result_dir")
    return artifact_path


def _record_unique_audit_path(path: str, seen_paths: set[str]) -> None:
    if path in seen_paths:
        raise ValueError(f"audit artifact paths must be unique: {path}")
    seen_paths.add(path)


def _canonical_jsonl_lines(items: Sequence[Any]) -> str:
    lines = [
        json.dumps(
            _canonical_record_value(item), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        for item in items
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def _canonical_record_value(value: Any) -> Any:
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return value.model_dump(mode="json")
    return json_safe_value(value)


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
            if table.num_rows == 0 and not field.type.equals(arrow_type):
                columns.append(pa.nulls(0, type=arrow_type))
            else:
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
    metadata[_SCENARIO_IDS_METADATA_KEY] = json.dumps(list(scenario_ids), allow_nan=False).encode(
        "utf-8"
    )
    return table.replace_schema_metadata(metadata)


def _scenario_ids_from_footer(schema: Any, *, artifact_kind: str) -> list[str]:
    metadata = schema.metadata or {}
    raw_value = metadata.get(_SCENARIO_IDS_METADATA_KEY)
    if raw_value is None:
        if artifact_kind in _TRACE_COLUMN_TYPES:
            raise ValueError(
                f"{artifact_kind} trace table is missing scenario_ids Parquet metadata"
            )
        return []

    try:
        value = json.loads(raw_value.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"{artifact_kind} trace table has invalid scenario_ids Parquet metadata"
        ) from exc

    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(
            f"{artifact_kind} trace table scenario_ids Parquet metadata must be a list of strings"
        )
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
        none_keys = {
            key for key in _REQUIRED_TRACE_TABLE_METADATA if key in item and item[key] is None
        }
        if missing_keys:
            missing = ", ".join(sorted(missing_keys))
            raise ValueError(
                f"trace table metadata at index {index} is missing required metadata: {missing}"
            )
        if none_keys:
            missing = ", ".join(sorted(none_keys))
            raise ValueError(
                f"trace table metadata at index {index} is missing required metadata: {missing}"
            )

        artifact_kind = item["artifact_kind"]
        if not isinstance(artifact_kind, str) or not artifact_kind:
            raise ValueError(f"trace table metadata at index {index} has invalid artifact_kind")
        kinds.append(artifact_kind)

    required_kinds = set(_REQUIRED_TRACE_TABLES)
    actual_kinds = set(kinds)
    if (
        len(table_artifacts) != len(_REQUIRED_TRACE_TABLES)
        or actual_kinds != required_kinds
        or len(kinds) != len(actual_kinds)
    ):
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
        _validate_trace_table_metadata_item(
            item, kind=kind, required_path=required_path, result_dir=result_dir
        )

        scenario_ids = set(item["scenario_ids"])
        if expected_scenario_ids is None:
            expected_scenario_ids = scenario_ids
        elif scenario_ids != expected_scenario_ids:
            raise ValueError(
                "trace table scenario_ids must be consistent across required trace tables"
            )

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
    trusted_file_hash = (
        item.trusted_file_sha256 if isinstance(item, _TrustedTableMetadata) else None
    )
    if trusted_file_hash is not None:
        if trusted_file_hash != item["file_sha256"]:
            raise ValueError(
                f"{kind} trace table metadata file_sha256 does not match trusted writer hash"
            )
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
        raise ValueError(
            f"{kind} trace table metadata could not be verified from Parquet file"
        ) from exc

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


def _scenario_coverage_ids(scenario_summary: Mapping[str, Any]) -> set[Any]:
    scenario_coverage = scenario_summary.get("scenario_coverage")
    if not isinstance(scenario_coverage, Mapping):
        raise ValueError("scenario_ids validation requires scenario_summary scenario_coverage")

    has_expected_ids = "expected_ids" in scenario_coverage
    has_completed_ids = "completed_ids" in scenario_coverage
    expected_ids = _coverage_id_set(scenario_coverage["expected_ids"]) if has_expected_ids else None
    completed_ids = (
        _coverage_id_set(scenario_coverage["completed_ids"]) if has_completed_ids else None
    )
    if has_expected_ids and has_completed_ids and expected_ids != completed_ids:
        optional_ids = _coverage_id_set(scenario_coverage.get("optional_ids", ()))
        missing_optional_ids = _coverage_id_set(scenario_coverage.get("missing_optional_ids", ()))
        missing_required_ids = _coverage_id_set(scenario_coverage.get("missing_required_ids", ()))
        if (
            missing_required_ids
            or not completed_ids <= expected_ids
            or expected_ids - completed_ids != missing_optional_ids
            or not missing_optional_ids <= optional_ids
        ):
            raise ValueError(
                "scenario_coverage expected_ids and completed_ids must match for a completed evaluation manifest "
                "unless only optional scenarios are missing; "
                f"expected={sorted(expected_ids)!r}; completed={sorted(completed_ids)!r}"
            )
        return completed_ids
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


def _audit_artifact_stem(window_id: str) -> str:
    digest = hashlib.sha256(window_id.encode("utf-8")).hexdigest()[:12]
    return f"{_safe_name(window_id)}-{digest}"


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
