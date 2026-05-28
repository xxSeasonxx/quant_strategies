from __future__ import annotations

import json
import re
import shutil
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from quant_strategies.datetime_utils import parse_aware_datetime
from quant_strategies.engine import EVIDENCE_SCHEMA_VERSION
from quant_strategies.evidence_semantics import artifact_trust_tier_for_profile, smoke_score_metric_semantics
from quant_strategies.provenance import (
    artifact_hashes,
    git_identity,
    package_versions,
    python_identity,
)
from quant_strategies.runner.config import RunConfig
from quant_strategies.runner.artifact_profiles import (
    canonical_row_line,
    json_safe_value,
)


_METADATA_COVERAGE_FIELDS = (
    "available_at",
    "bar_ingested_at",
    "quote_ingested_at",
    "funding_ingested_at",
    "joined_refreshed_at",
)


@dataclass(frozen=True)
class RowSummary:
    total: int
    ranges_by_symbol: dict[str, dict[str, Any]]
    normalized_rows_sha256: str
    data_availability_status: str
    availability_coverage: dict[str, Any]
    row_contract: dict[str, Any]
    metadata_field_coverage: dict[str, dict[str, int]]

    @classmethod
    def from_rows(
        cls,
        config: RunConfig,
        rows: list[dict[str, Any]],
        *,
        normalized_rows_hash: str | None = None,
    ) -> RowSummary:
        required_fields = _required_row_fields(config)
        missing_required_counts = {field: 0 for field in required_fields}
        funding_event_missing_counts = {"funding_timestamp": 0, "funding_rate": 0}
        metadata_present = {field: 0 for field in _METADATA_COVERAGE_FIELDS}
        metadata_seen: set[str] = set()
        ranges_by_symbol: dict[str, dict[str, Any]] = {}
        seen_keys: set[tuple[str, object]] = set()
        duplicate_key_count = 0
        aware_timestamps = 0
        invalid_timestamps = 0
        availability_present = 0
        availability_invalid = 0
        digest = hashlib.sha256() if normalized_rows_hash is None else None

        for row in rows:
            if digest is not None:
                line = canonical_row_line(row)
                digest.update(line.encode("utf-8"))
                digest.update(b"\n")

            symbol = str(row.get("symbol", ""))
            timestamp = row.get("timestamp")
            symbol_range = ranges_by_symbol.setdefault(
                symbol,
                {"count": 0, "min_timestamp": None, "max_timestamp": None},
            )
            symbol_range["count"] += 1
            if timestamp is not None:
                if symbol_range["min_timestamp"] is None or timestamp < symbol_range["min_timestamp"]:
                    symbol_range["min_timestamp"] = timestamp
                if symbol_range["max_timestamp"] is None or timestamp > symbol_range["max_timestamp"]:
                    symbol_range["max_timestamp"] = timestamp

            key = (symbol, timestamp)
            if key in seen_keys:
                duplicate_key_count += 1
            else:
                seen_keys.add(key)

            if _is_aware_timestamp(timestamp):
                aware_timestamps += 1
            else:
                invalid_timestamps += 1

            for field in required_fields:
                if row.get(field) is None:
                    missing_required_counts[field] += 1

            if config.data.kind == "crypto_perp_funding" and row.get("has_funding_event") is True:
                for field in funding_event_missing_counts:
                    if row.get(field) is None:
                        funding_event_missing_counts[field] += 1

            for field in _METADATA_COVERAGE_FIELDS:
                if field in row:
                    metadata_seen.add(field)
                    if row.get(field) is not None:
                        metadata_present[field] += 1

            available_at = row.get("available_at")
            if available_at is None:
                continue
            parsed_available_at, _ = parse_aware_datetime(available_at)
            if parsed_available_at is None:
                availability_invalid += 1
                continue
            availability_present += 1

        total = len(rows)
        availability_fraction = None if total == 0 else availability_present / total
        if total > 0 and availability_present == total:
            availability_status = "complete"
        elif availability_invalid > 0:
            availability_status = "invalid"
        elif availability_present > 0:
            availability_status = "partial"
        else:
            availability_status = "missing"
        availability_coverage: dict[str, Any] = {
            "field": "available_at",
            "present": availability_present,
            "total": total,
            "fraction": availability_fraction,
        }
        if availability_invalid:
            availability_coverage["invalid"] = availability_invalid

        if not rows:
            timestamp_status = "empty"
        elif aware_timestamps == total:
            timestamp_status = "aware"
        elif invalid_timestamps == total:
            timestamp_status = "invalid_or_naive"
        else:
            timestamp_status = "mixed"

        missing_required_fields = {
            field: count for field, count in missing_required_counts.items() if count > 0
        }
        funding_event_missing_fields = {
            field: count
            for field, count in funding_event_missing_counts.items()
            if count > 0 and config.data.kind == "crypto_perp_funding"
        }
        feedback = (
            ["row_contract_not_evaluated:no_rows"]
            if not rows
            else _row_contract_feedback(
                missing_required_fields=missing_required_fields,
                duplicate_key_count=duplicate_key_count,
                timestamp_status=timestamp_status,
                funding_event_missing_fields=funding_event_missing_fields,
            )
        )
        row_contract = {
            "data_kind": config.data.kind,
            "status": "not_evaluated" if not rows else "passed" if not feedback else "failed",
            "required_fields": list(required_fields),
            "missing_required_fields": missing_required_fields,
            "timestamp_status": timestamp_status,
            "duplicate_key_count": duplicate_key_count,
            "funding_event_missing_fields": funding_event_missing_fields,
            "freshness_status": "not_evaluated",
            "quant_data_feedback": feedback,
        }
        metadata_field_coverage = {
            field: {"present": metadata_present[field], "total": total}
            for field in _METADATA_COVERAGE_FIELDS
            if field in metadata_seen
        }
        json_ranges = {}
        for symbol, summary in ranges_by_symbol.items():
            json_ranges[symbol] = {
                "count": summary["count"],
                "min_timestamp": json_safe_value(summary["min_timestamp"]),
                "max_timestamp": json_safe_value(summary["max_timestamp"]),
            }
        return cls(
            total=total,
            ranges_by_symbol=dict(sorted(json_ranges.items())),
            normalized_rows_sha256=normalized_rows_hash or digest.hexdigest(),
            data_availability_status=availability_status,
            availability_coverage=availability_coverage,
            row_contract=row_contract,
            metadata_field_coverage=metadata_field_coverage,
        )

    def evidence_quality(self, *, causality_verified: bool) -> dict[str, Any]:
        payload = {
            "data_availability_status": self.data_availability_status,
            "availability_coverage": self.availability_coverage,
            "row_contract": self.row_contract,
        }
        payload.update(
            _causality_evidence(
                self.data_availability_status,
                causality_verified=causality_verified,
            )
        )
        return payload


def create_result_dir(config: RunConfig, *, now: datetime | None = None) -> Path:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    base_name = f"{timestamp}-{_safe_name(config.strategy_id)}"
    config.output.results_dir.mkdir(parents=True, exist_ok=True)
    result_dir = config.output.results_dir / base_name
    suffix = 2
    while True:
        try:
            result_dir.mkdir()
        except FileExistsError:
            result_dir = config.output.results_dir / f"{base_name}-{suffix}"
            suffix += 1
            continue
        return result_dir


def initialize_run_artifacts(config_path: Path, config: RunConfig, result_dir: Path) -> None:
    shutil.copyfile(config_path, result_dir / "config.toml")
    if config.strategy_path.is_file():
        shutil.copyfile(config.strategy_path, result_dir / "strategy_snapshot.py")


def write_strategy_input_rows(result_dir: Path, rows: list[dict[str, Any]]) -> str:
    jsonl_path = result_dir / "strategy_input_rows.jsonl"
    return write_jsonl(jsonl_path, rows)


def write_decision_records(result_dir: Path, decisions: list[Any]) -> None:
    lines = [_canonical_json_line(decision) for decision in decisions]
    (result_dir / "decision_records.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""))


def write_engine_request(result_dir: Path, request_json: str) -> None:
    (result_dir / "engine_request.json").write_text(request_json)


def write_evidence(result_dir: Path, evidence_json: str) -> None:
    (result_dir / "evidence.json").write_text(evidence_json)


def evidence_quality(
    config: RunConfig,
    rows: list[dict[str, Any]],
    *,
    causality_verified: bool = False,
) -> dict[str, Any]:
    return RowSummary.from_rows(config, rows).evidence_quality(causality_verified=causality_verified)


def with_causality_verification(
    evidence_quality_payload: Mapping[str, Any],
    *,
    causality_verified: bool,
) -> dict[str, Any]:
    payload = dict(evidence_quality_payload)
    payload.update(
        _causality_evidence(
            payload.get("data_availability_status"),
            causality_verified=causality_verified,
        )
    )
    return payload


def _causality_evidence(
    data_availability_status: object,
    *,
    causality_verified: bool,
) -> dict[str, Any]:
    if data_availability_status == "complete":
        verified = causality_verified
        warnings = [] if verified else ["runner_causality_not_verified"]
    elif data_availability_status == "invalid":
        verified = False
        warnings = ["available_at_invalid", "runner_causality_not_verified"]
    elif data_availability_status == "partial":
        verified = False
        warnings = ["available_at_partial", "runner_causality_not_verified"]
    else:
        verified = False
        warnings = ["available_at_missing", "runner_causality_not_verified"]
    return {
        "causality_verified": verified,
        "evidence_quality_warnings": warnings,
    }


def row_contract_status(config: RunConfig, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return RowSummary.from_rows(config, rows).row_contract


def write_data_manifest(
    result_dir: Path,
    config: RunConfig,
    rows: list[dict[str, Any]],
    *,
    normalized_rows_hash: str,
    row_summary: RowSummary | None = None,
    evidence_quality_payload: dict[str, Any] | None = None,
) -> None:
    row_summary = row_summary or RowSummary.from_rows(config, rows, normalized_rows_hash=normalized_rows_hash)
    quality = evidence_quality_payload or row_summary.evidence_quality(causality_verified=False)
    payload = {
        "artifact_profile": config.output.artifact_profile,
        "artifact_trust_tier": artifact_trust_tier_for_profile(config.output.artifact_profile),
        "data": {
            "kind": config.data.kind,
            "dataset": config.data.dataset,
            "symbols": list(config.data.symbols),
            "start": config.data.start.isoformat(),
            "end": config.data.end.isoformat(),
            "strict": config.data.strict,
        },
        "rows": {
            "total": row_summary.total,
            "by_symbol": row_summary.ranges_by_symbol,
        },
        "normalized_rows_sha256": row_summary.normalized_rows_sha256,
        "metric_semantics": smoke_score_metric_semantics(config.data.kind),
        "metadata_field_coverage": row_summary.metadata_field_coverage,
        **quality,
    }
    _write_json(result_dir / "data_manifest.json", payload)


def write_run_manifest(
    result_dir: Path,
    *,
    repo_root: Path,
    evidence: dict[str, object],
    artifact_profile: str,
) -> None:
    payload = {
        "repository": _git_identity(repo_root, result_dir),
        "python": python_identity(),
        "packages": _package_versions(["quant-strategies", "quant-data", "pydantic"]),
        "engine": {"evidence_schema": EVIDENCE_SCHEMA_VERSION},
        "artifact_profile": artifact_profile,
        "artifact_trust_tier": artifact_trust_tier_for_profile(artifact_profile),
        "evidence": evidence,
        "artifacts": _artifact_hashes(result_dir),
    }
    _write_json(result_dir / "run_manifest.json", payload)


def write_summary(result_dir: Path, summary: dict[str, Any]) -> None:
    payload = dict(summary)
    payload["artifacts"] = _artifact_names(result_dir, include_summary=True)
    _write_json(result_dir / "summary.json", payload)


def write_notes(result_dir: Path, notes: str) -> None:
    (result_dir / "notes.md").write_text(notes.rstrip() + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("w") as handle:
        for row in rows:
            line = canonical_row_line(row)
            handle.write(line + "\n")
            digest.update(line.encode("utf-8"))
            digest.update(b"\n")
    return digest.hexdigest()


def _canonical_json_line(value: Any) -> str:
    if hasattr(value, "model_dump"):
        payload = value.model_dump(mode="json")
    else:
        payload = json_safe_value(value)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _required_row_fields(config: RunConfig) -> tuple[str, ...]:
    fields = ["symbol", "timestamp", "open", "high", "low", "close"]
    if config.data.kind == "crypto_perp_funding":
        fields.append("has_funding_event")
    if config.data.kind == "forex_with_quotes" and config.fill_model.price == "quote":
        fields.extend(["bid", "ask", "mid"])
    return tuple(fields)


def _is_aware_timestamp(value: object) -> bool:
    if isinstance(value, datetime):
        return value.tzinfo is not None and value.utcoffset() is not None
    if isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return False
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    return False


def _row_contract_feedback(
    *,
    missing_required_fields: dict[str, int],
    duplicate_key_count: int,
    timestamp_status: str,
    funding_event_missing_fields: dict[str, int],
) -> list[str]:
    feedback = [
        f"missing_required_field:{field}:{count}"
        for field, count in sorted(missing_required_fields.items())
    ]
    feedback.extend(
        f"missing_funding_event_field:{field}:{count}"
        for field, count in sorted(funding_event_missing_fields.items())
    )
    if duplicate_key_count:
        feedback.append(f"duplicate_symbol_timestamp_keys:{duplicate_key_count}")
    if timestamp_status not in {"aware", "empty"}:
        feedback.append(f"timestamp_status:{timestamp_status}")
    return feedback


def _artifact_hashes(result_dir: Path) -> dict[str, dict[str, str]]:
    return artifact_hashes(
        result_dir,
        exclude_names={"run_manifest.json", "summary.json"},
        recursive=False,
    )


def _package_versions(package_names: list[str]) -> dict[str, str | None]:
    return package_versions(package_names)


def _git_identity(repo_root: Path, result_dir: Path) -> dict[str, Any]:
    return git_identity(repo_root, exclude_paths=(result_dir,))


def _artifact_names(result_dir: Path, *, include_summary: bool) -> list[str]:
    names = {path.name for path in result_dir.iterdir() if path.is_file()}
    if include_summary:
        names.add("summary.json")
    return sorted(names)


def _safe_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return name or "strategy"
