from __future__ import annotations

import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quant_strategies.causality import check_hidden_lookahead
from quant_strategies.core.config import default_repo_root
from quant_strategies.evaluation.artifacts import (
    create_evaluation_result_dir,
    initialize_evaluation_artifacts,
    table_metadata,
    write_data_manifest,
    write_evaluation_manifest,
    write_json_artifact,
    write_parquet_artifact,
    write_text_artifact,
)
from quant_strategies.evaluation.backend import PortfolioEvaluationResult, VectorBTProEvaluationBackend
from quant_strategies.evaluation.config import load_evaluation_config, resolve_evaluation_config_path
from quant_strategies.evaluation.dependencies import EvaluationDependencyError
from quant_strategies.evaluation.errors import EvaluationConfigError
from quant_strategies.evaluation.metrics import evaluation_metric_semantics
from quant_strategies.evaluation.scenarios import expand_evaluation_scenarios
from quant_strategies.runner.execution import StrategyExecutionError, execute_strategy_run


@dataclass(frozen=True)
class EvaluationRunResult:
    result_dir: Path | None
    message: str
    run_completed: bool = False
    failure_stage: str | None = None
    assessment_status: str = "evaluation_failed"
    evidence_quality_warnings: tuple[str, ...] = ()


def run_evaluation(
    config_path: str | Path,
    *,
    repo_root: Path | None = None,
    backend: Any | None = None,
) -> EvaluationRunResult:
    root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
    try:
        resolved_config_path = resolve_evaluation_config_path(config_path, repo_root=root)
        config = load_evaluation_config(resolved_config_path)
    except EvaluationConfigError as exc:
        return EvaluationRunResult(
            result_dir=None,
            message=str(exc),
            failure_stage="config_load",
            assessment_status="evaluation_failed",
        )

    try:
        result_dir = create_evaluation_result_dir(config.output.results_dir, config.strategy_id)
        initialize_evaluation_artifacts(resolved_config_path, config.strategy_path, result_dir)
    except OSError as exc:
        return EvaluationRunResult(
            result_dir=None,
            message=f"artifact initialization failed: {exc}",
            failure_stage="artifact_initialization",
            assessment_status="evaluation_failed",
        )

    selected_backend = backend or VectorBTProEvaluationBackend()
    backend_results: list[PortfolioEvaluationResult] = []
    trace_results: list[PortfolioEvaluationResult] = []
    data_windows: list[dict[str, Any]] = []
    expected_scenario_ids: list[str] = []
    all_warnings: list[str] = []

    try:
        for window in config.windows:
            execution_spec = config.to_execution_spec(window)
            execution = execute_strategy_run(
                execution_spec,
                repo_root=config.base_dir,
                row_contract_mode="validation",
            )
            row_contract = execution.normalized_rows.row_contract_summary()
            data_windows.append(
                {
                    "window_id": window.id,
                    "data": execution_spec.data.model_dump(mode="json"),
                    "row_count": len(execution.normalized_rows),
                    "ranges_by_symbol": execution.normalized_rows.ranges_by_symbol,
                    "availability_coverage": execution.normalized_rows.availability_coverage,
                    "normalized_rows_sha256": execution.normalized_rows_sha256,
                    "row_contract": row_contract,
                    "evidence_quality": execution.evidence_quality,
                    "decision_count": len(execution.decisions),
                }
            )
            if row_contract["status"] == "failed":
                return _failure_result(
                    result_dir,
                    "data_load",
                    "evaluation_failed",
                    "evaluation row contract failed",
                    warnings=tuple(all_warnings),
                )

            lookahead = check_hidden_lookahead(
                execution.generate_decisions,
                rows=execution.normalized_rows,
                params=execution.validated_params,
                baseline_decisions=execution.decisions,
                strategy_id=config.strategy_id,
                mode="strict",
            )
            if not lookahead.passed:
                return _failure_result(
                    result_dir,
                    "preflight",
                    "evaluation_preflight_failed",
                    "; ".join(lookahead.violations),
                    warnings=tuple(all_warnings),
                )
            all_warnings.extend(lookahead.skipped_probe_reasons)

            scenarios = expand_evaluation_scenarios(
                window=window,
                base_costs=config.cost_model,
                base_fill=config.fill_model,
            )
            expected_scenario_ids.extend(scenario.scenario_id for scenario in scenarios)
            projection_rows = execution.normalized_rows.projection_rows()
            try:
                prepared = (
                    selected_backend.prepare_inputs(decisions=execution.decisions, rows=projection_rows)
                    if hasattr(selected_backend, "prepare_inputs")
                    else None
                )
            except EvaluationDependencyError as exc:
                return _failure_result(
                    result_dir,
                    "portfolio_evaluation",
                    "portfolio_backend_unavailable",
                    str(exc),
                    warnings=tuple(all_warnings),
                )
            except ValueError as exc:
                return _failure_result(
                    result_dir,
                    "portfolio_evaluation",
                    "portfolio_evaluation_failed",
                    str(exc),
                    warnings=tuple(all_warnings),
                )
            except Exception as exc:
                return _failure_result(
                    result_dir,
                    "portfolio_evaluation",
                    "portfolio_evaluation_failed",
                    f"portfolio input preparation failed: {exc}",
                    warnings=tuple(all_warnings),
                )

            for scenario in scenarios:
                scenario_result = (
                    selected_backend.run_prepared(
                        prepared=prepared,
                        scenario=scenario,
                        metrics=config.metrics,
                    )
                    if prepared is not None and hasattr(selected_backend, "run_prepared")
                    else selected_backend.run(
                        decisions=execution.decisions,
                        rows=projection_rows,
                        scenario=scenario,
                        metrics=config.metrics,
                    )
                )
                backend_results.append(_strip_trace_tables(scenario_result))
                if scenario_result.status != "completed":
                    status = (
                        "portfolio_backend_unavailable"
                        if scenario_result.status == "unavailable"
                        else "portfolio_evaluation_failed"
                    )
                    return _failure_result(
                        result_dir,
                        "portfolio_evaluation",
                        status,
                        _backend_failure_message(scenario_result),
                        warnings=tuple(all_warnings),
                    )
                if scenario_result.tables is None:
                    return _failure_result(
                        result_dir,
                        "portfolio_evaluation",
                        "portfolio_evaluation_failed",
                        f"{scenario_result.scenario_id}: completed backend emitted no trace tables",
                        warnings=tuple(all_warnings),
                    )
                trace_results.append(scenario_result)
    except StrategyExecutionError as exc:
        return _failure_result(
            result_dir,
            exc.stage,
            "evaluation_failed",
            str(exc),
            warnings=tuple(all_warnings),
        )

    scenario_summary = _scenario_summary(backend_results, expected_scenario_ids)
    coverage = scenario_summary["scenario_coverage"]
    if coverage["missing_ids"] or coverage["unexpected_ids"]:
        return _failure_result(
            result_dir,
            "portfolio_evaluation",
            "portfolio_evaluation_failed",
            f"scenario coverage mismatch: missing={coverage['missing_ids']} unexpected={coverage['unexpected_ids']}",
            warnings=tuple(all_warnings),
        )

    metrics_payload = {
        "metric_semantics": evaluation_metric_semantics(),
        "scenarios": [
            {
                "scenario_id": item.scenario_id,
                "backend": item.backend,
                "status": item.status,
                "metrics": item.metrics,
                "warnings": list(item.warnings),
                "unsupported_semantics": list(item.unsupported_semantics),
            }
            for item in backend_results
        ],
    }
    try:
        write_data_manifest(result_dir, windows=data_windows)
        table_artifacts = _write_trace_tables(result_dir, trace_results)
        write_json_artifact(result_dir, "evaluation_metrics.json", metrics_payload)
        write_json_artifact(result_dir, "scenario_summary.json", scenario_summary)
        write_text_artifact(result_dir, "notes.md", _notes(config.strategy_id, backend_results))
        write_evaluation_manifest(
            result_dir,
            repo_root=root,
            path_base=config.base_dir,
            config=config,
            config_path=resolved_config_path,
            backend_name=getattr(selected_backend, "name", "unknown"),
            data_windows=data_windows,
            table_artifacts=table_artifacts,
            scenario_summary=scenario_summary,
        )
    except (OSError, ValueError) as exc:
        return _failure_result(
            result_dir,
            "artifact_write",
            "evaluation_failed",
            f"artifact write failed: {exc}",
            warnings=tuple(all_warnings),
        )

    return EvaluationRunResult(
        result_dir=result_dir,
        message=f"evaluation complete: {len(backend_results)} scenarios",
        run_completed=True,
        failure_stage=None,
        assessment_status="evaluation_complete",
        evidence_quality_warnings=tuple(all_warnings),
    )


def _write_trace_tables(result_dir: Path, results: list[PortfolioEvaluationResult]) -> list[dict[str, Any]]:
    scenario_ids = tuple(result.scenario_id for result in results)
    frames = {
        "portfolio_path": _combine_trace_frames(results, "portfolio_path"),
        "trades": _combine_trace_frames(results, "trades"),
        "positions": _combine_trace_frames(results, "positions"),
        "per_asset_metrics": _combine_trace_frames(results, "per_asset_metrics"),
    }
    final_dir = result_dir / "tables"
    staging_dir = result_dir / "tables_staging"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    if final_dir.exists():
        raise OSError(f"trace table directory already exists: {final_dir}")

    try:
        for artifact_kind, frame in frames.items():
            write_parquet_artifact(
                result_dir,
                f"tables_staging/{artifact_kind}.parquet",
                frame,
                artifact_kind=artifact_kind,
                scenario_ids=scenario_ids,
                logical_name=f"tables/{artifact_kind}.parquet",
            )
        staging_dir.rename(final_dir)
    except Exception:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        raise

    return [
        table_metadata(
            result_dir,
            final_dir / f"{artifact_kind}.parquet",
            artifact_kind=artifact_kind,
            scenario_ids=scenario_ids,
            logical_name=f"tables/{artifact_kind}.parquet",
        )
        for artifact_kind in ("portfolio_path", "trades", "positions", "per_asset_metrics")
    ]


def _combine_trace_frames(results: list[PortfolioEvaluationResult], table_name: str) -> Any:
    import pandas as pd

    frames = []
    for result in results:
        assert result.tables is not None
        frames.append(getattr(result.tables, table_name))
    if not frames:
        return pd.DataFrame({"scenario_id": []})
    return pd.concat(frames, ignore_index=True)


def _strip_trace_tables(result: PortfolioEvaluationResult) -> PortfolioEvaluationResult:
    return result.model_copy(update={"tables": None})


def _backend_failure_message(result: PortfolioEvaluationResult) -> str:
    parts = [result.scenario_id, result.status]
    parts.extend(result.unsupported_semantics)
    parts.extend(result.warnings)
    return ": ".join(parts)


def _failure_result(
    result_dir: Path | None,
    failure_stage: str,
    assessment_status: str,
    message: str,
    *,
    warnings: Sequence[str],
) -> EvaluationRunResult:
    return EvaluationRunResult(
        result_dir=result_dir,
        message=message,
        run_completed=False,
        failure_stage=failure_stage,
        assessment_status=assessment_status,
        evidence_quality_warnings=tuple(warnings),
    )


def _scenario_summary(results: list[PortfolioEvaluationResult], expected_ids: list[str]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for result in results:
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
    completed_ids = [result.scenario_id for result in results if result.status == "completed"]
    unexpected_ids = sorted(set(completed_ids) - set(expected_ids))
    missing_ids = sorted(set(expected_ids) - set(completed_ids))
    return {
        "scenario_count": len(results),
        "status_counts": dict(sorted(status_counts.items())),
        "scenario_coverage": {
            "expected_count": len(expected_ids),
            "completed_count": len(completed_ids),
            "expected_ids": expected_ids,
            "completed_ids": completed_ids,
            "missing_ids": missing_ids,
            "unexpected_ids": unexpected_ids,
        },
        "scenarios": [
            {
                "scenario_id": result.scenario_id,
                "backend": result.backend,
                "status": result.status,
                "metric_count": len(result.metrics),
                "warnings": list(result.warnings),
                "unsupported_semantics": list(result.unsupported_semantics),
            }
            for result in results
        ],
    }


def _notes(strategy_id: str, results: list[PortfolioEvaluationResult]) -> str:
    return (
        "# Evaluation Notes\n\n"
        f"- Strategy: `{strategy_id}`\n"
        f"- Scenarios: {len(results)}\n"
        "- Evidence class: research evaluation\n"
        "- Authority: evidence only; not validation, promotion, paper trading, or live trading authority.\n"
    )
