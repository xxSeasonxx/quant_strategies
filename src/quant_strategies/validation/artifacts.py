from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from quant_strategies.validation.backends import ScenarioBackendRunResult, backend_metric_semantics
from quant_strategies.validation.policy import ValidationPolicyDecision


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
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if hasattr(value, "item") and callable(value.item):
        try:
            return _json_value(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return str(value)
    return value


def scenario_classification_reasons(item: ScenarioBackendRunResult) -> tuple[str, ...]:
    result = item.result
    if result.status == "failed":
        return (f"{result.backend}_failed",)
    if result.status == "unavailable":
        return ("backend_unavailable",)
    if result.status == "unsupported" or result.unsupported_semantics:
        return ("unsupported_semantics",)
    if result.status == "completed" and not result.feasibility.feasible:
        return ("non_scoreable",)
    return ()


def backend_runs_payload(backend_results: list[ScenarioBackendRunResult]) -> dict[str, Any]:
    return {
        "metric_semantics": backend_metric_semantics(),
        "results": [
            {
                "window_id": item.window_id,
                "scenario_id": item.scenario_id,
                "scenario_kind": item.scenario_kind,
                "required": item.required,
                "scoreability_bearing": item.scoreability_bearing,
                "diagnostic_only": item.diagnostic_only,
                "decision_count": item.decision_count,
                "decision_records_path": item.decision_records_path,
                "decision_records_sha256": item.decision_records_sha256,
                "trade_ledger_path": item.trade_ledger_path,
                "trade_ledger_sha256": item.trade_ledger_sha256,
                "result": item.result.model_dump(mode="json"),
            }
            for item in backend_results
        ],
    }


def cost_fill_sensitivity_payload(
    *,
    decision: ValidationPolicyDecision,
    backend_results: list[ScenarioBackendRunResult],
    failure_details: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "decision": decision.model_dump(mode="json"),
        "scenarios": [
            {
                "window_id": item.window_id,
                "scenario_id": item.scenario_id,
                "scenario_kind": item.scenario_kind,
                "required": item.required,
                "scoreability_bearing": item.scoreability_bearing,
                "diagnostic_only": item.diagnostic_only,
                "decision_count": item.decision_count,
                "decision_records_path": item.decision_records_path,
                "decision_records_sha256": item.decision_records_sha256,
                "trade_ledger_path": item.trade_ledger_path,
                "trade_ledger_sha256": item.trade_ledger_sha256,
                "backend": item.result.backend,
                "status": item.result.status,
                "metrics": item.result.metrics,
                "warnings": item.result.warnings,
                "unsupported_semantics": item.result.unsupported_semantics,
                "feasibility": item.result.feasibility.payload(),
                "classification_reasons": scenario_classification_reasons(item),
            }
            for item in backend_results
        ],
        "failure_details": failure_details,
    }
