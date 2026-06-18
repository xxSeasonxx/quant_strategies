from __future__ import annotations

import math
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from numbers import Real
from pathlib import Path
from typing import Any

from quant_strategies.causality import (
    causality_completeness_violations,
    check_bounded_causality,
    check_hidden_lookahead,
)
from quant_strategies.core.accounting_model import SHARED_ACCOUNTING_MODEL
from quant_strategies.core.config import default_repo_root
from quant_strategies.core.data_audit import audit_decision_rows
from quant_strategies.core.decision_readiness import check_decision_readiness
from quant_strategies.core.evidence_quality import compact_evidence_quality
from quant_strategies.core.execution import (
    StrategyExecutionError,
    StrategyExecutionResult,
    execute_strategy_run,
)
from quant_strategies.evaluation.artifacts import (
    create_evaluation_result_dir,
    initialize_evaluation_artifacts,
    write_data_manifest,
    write_decision_records_artifact,
    write_evaluation_manifest,
    write_input_rows_artifact,
    write_json_artifact,
    write_parquet_artifact,
    write_text_artifact,
)
from quant_strategies.evaluation.backends import (
    EvaluationBackend,
    PreparedEvaluationBackend,
)
from quant_strategies.evaluation.benchmarks import benchmark_metrics_for_rows
from quant_strategies.evaluation.config import (
    load_evaluation_config,
    resolve_evaluation_config_path,
)
from quant_strategies.evaluation.dependencies import EvaluationDependencyError
from quant_strategies.evaluation.errors import EvaluationConfigError
from quant_strategies.evaluation.events import EvaluationEventSink, EvaluationStageEmitter
from quant_strategies.evaluation.fold_returns import (
    FoldReturnSeries,
    FoldScenarioMetrics,
    fold_metrics_from_scenario,
    fold_series_from_portfolio_path,
    split_portfolio_path_by_scenario,
    window_id_for_scenario,
)
from quant_strategies.evaluation.metrics import evaluation_metric_semantics
from quant_strategies.evaluation.results import EvaluationRunResult, PortfolioEvaluationResult
from quant_strategies.evaluation.scenarios import expand_evaluation_scenarios
from quant_strategies.evaluation.spine_backend import SpineEvaluationBackend
from quant_strategies.provenance import package_versions, python_identity


@dataclass(frozen=True)
class _EvaluationContext:
    repo_root: Path
    config: Any
    config_path: Path
    result_dir: Path
    selected_backend: EvaluationBackend
    event_emitter: EvaluationStageEmitter
    provenance: Mapping[str, str]


@dataclass
class _EvaluationState:
    backend_results: list[PortfolioEvaluationResult] = field(default_factory=list)
    trace_results: list[PortfolioEvaluationResult] = field(default_factory=list)
    data_windows: list[dict[str, Any]] = field(default_factory=list)
    expected_scenario_ids: list[str] = field(default_factory=list)
    required_scenario_ids: list[str] = field(default_factory=list)
    all_warnings: list[str] = field(default_factory=list)


_REQUIRED_COMPLETED_FLOAT_METRICS = (
    "total_return",
    "ending_value",
    "max_drawdown",
    "funding_cashflow_total",
)
_REQUIRED_COMPLETED_COUNT_METRICS = (
    "trade_count",
    "return_total_count_excluding_initial",
    "return_sample_count",
    "return_nonfinite_count",
    "funding_event_count",
)
# The single shared accounting/funding model identity. The book reports it for every
# data kind; the retired per-asset-class perp-ledger model name is gone (design D9).
_REQUIRED_COMPLETED_FUNDING_MODELS = {SHARED_ACCOUNTING_MODEL}
# Stages whose failure means the Tier-0 causal-replay / decision-contract
# integrity check did not pass (vs. a pre-causal failure, which leaves it unknown).
_CAUSAL_FAILURE_STAGES = frozenset({"data_audit", "preflight"})
_PROVENANCE_PACKAGE_NAMES = ("quant-strategies", "quant-data")
_SECONDS_PER_YEAR = 365.2425 * 24 * 60 * 60
_ANNUALIZATION_CADENCE_MISMATCH_FACTOR_THRESHOLD = 1.1
_ANNUALIZED_RISK_METRICS = ("annualized_return", "volatility", "sharpe", "sortino", "calmar")
_ANNUALIZED_CADENCE_NULL_WARNING = "annualized_metrics_null_due_to_cadence_mismatch"
_ANNUALIZED_CADENCE_INSUFFICIENT_NULL_WARNING = (
    "annualized_metrics_null_due_to_insufficient_cadence"
)


def run_evaluation(
    config_path: str | Path,
    *,
    repo_root: Path | None = None,
    event_sink: EvaluationEventSink | None = None,
) -> EvaluationRunResult:
    return _run_evaluation(
        config_path,
        repo_root=repo_root,
        event_sink=event_sink,
    )


def _run_evaluation(
    config_path: str | Path,
    *,
    repo_root: Path | None = None,
    backend: EvaluationBackend | None = None,
    event_sink: EvaluationEventSink | None = None,
) -> EvaluationRunResult:
    events = EvaluationStageEmitter(event_sink)
    try:
        with events.stage(
            "config_load",
            config_path=str(config_path),
            repo_root=str(repo_root) if repo_root is not None else None,
        ):
            root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
            resolved_config_path = resolve_evaluation_config_path(config_path, repo_root=repo_root)
            config = load_evaluation_config(resolved_config_path)
    except EvaluationConfigError as exc:
        return EvaluationRunResult(
            result_dir=None,
            message=str(exc),
            failure_stage="config_load",
            assessment_status="evaluation_failed",
        )

    try:
        with events.stage("artifact_initialization", strategy_id=config.strategy_id):
            result_dir = create_evaluation_result_dir(config.output.results_dir, config.strategy_id)
            initialize_evaluation_artifacts(resolved_config_path, config.strategy_path, result_dir)
    except OSError as exc:
        return EvaluationRunResult(
            result_dir=None,
            message=f"artifact initialization failed: {exc}",
            failure_stage="artifact_initialization",
            assessment_status="evaluation_failed",
        )

    selected_backend = backend or SpineEvaluationBackend()
    context = _EvaluationContext(
        repo_root=root,
        config=config,
        config_path=resolved_config_path,
        result_dir=result_dir,
        selected_backend=selected_backend,
        event_emitter=events,
        provenance=_run_provenance(backend_name=_backend_name(selected_backend)),
    )
    state = _EvaluationState()

    for window in config.windows:
        failure = _run_evaluation_window(context, state, window)
        if failure is not None:
            return failure

    scenario_summary = _scenario_summary(
        state.backend_results,
        state.expected_scenario_ids,
        required_ids=state.required_scenario_ids,
    )
    coverage_failure = _check_scenario_coverage(context, state, scenario_summary)
    if coverage_failure is not None:
        return coverage_failure

    annualization_cadence = _annualization_cadence_summary(
        state.trace_results,
        configured_periods_per_year=context.config.metrics.annualization_periods_per_year,
    )
    if annualization_cadence["warning"] is not None:
        state.all_warnings.append(str(annualization_cadence["warning"]))

    artifact_results = _completion_artifact_results(
        state.backend_results,
        annualization_cadence=annualization_cadence,
    )
    artifact_scenario_summary = _scenario_summary(
        artifact_results,
        state.expected_scenario_ids,
        required_ids=state.required_scenario_ids,
    )

    artifact_failure = _write_completion_artifacts(
        context,
        state,
        artifact_scenario_summary,
        annualization_cadence=annualization_cadence,
        backend_results=artifact_results,
    )
    if artifact_failure is not None:
        return artifact_failure

    run_provenance = _completion_provenance(context, state)
    fold_returns, scenario_metrics = _build_fold_outputs(
        trace_results=state.trace_results,
        metric_results=artifact_results,
        known_window_ids=tuple(window.id for window in context.config.windows),
        periods_per_year=float(context.config.metrics.annualization_periods_per_year),
        provenance=run_provenance,
    )

    return EvaluationRunResult(
        result_dir=result_dir,
        message=f"evaluation complete: {len(state.backend_results)} scenarios",
        run_completed=True,
        failure_stage=None,
        assessment_status="evaluation_complete",
        evidence_quality_warnings=tuple(state.all_warnings),
        fold_returns=fold_returns,
        scenario_metrics=scenario_metrics,
        causal_replay_passed=True,
        provenance=run_provenance,
    )


def _run_evaluation_window(
    context: _EvaluationContext,
    state: _EvaluationState,
    window: Any,
) -> EvaluationRunResult | None:
    execution_spec = context.config.to_execution_spec(window)
    try:
        with context.event_emitter.stage(
            "window_execution",
            strategy_id=context.config.strategy_id,
            window_id=window.id,
        ) as window_event:
            execution = execute_strategy_run(
                execution_spec,
                repo_root=context.config.base_dir,
                require_passed_row_contract=True,
            )
            row_contract = execution.normalized_rows.row_contract_summary()
            data_window = _data_window_payload(window, execution_spec, execution, row_contract)
            if row_contract["status"] != "passed":
                state.data_windows.append(data_window)
                message = f"evaluation row contract {row_contract['status']}"
                window_event.fail(message)
                return _failure_result(
                    context,
                    state,
                    "data_load",
                    "evaluation_failed",
                    message,
                )
            audit_artifacts, audit_failure = _write_window_audit_artifacts(
                context,
                window,
                execution,
            )
            data_window.update(audit_artifacts)
            state.data_windows.append(data_window)
            if audit_failure is not None:
                return _failure_result(
                    context,
                    state,
                    "artifact_write",
                    "evaluation_failed",
                    audit_failure,
                )
    except StrategyExecutionError as exc:
        return _failure_result(
            context,
            state,
            exc.stage,
            "evaluation_failed",
            str(exc),
        )

    audit_failure = _run_data_audit(context, state, window, execution, data_window)
    if audit_failure is not None:
        return audit_failure
    causality_failure = _run_causality_check(context, state, window, execution, data_window)
    if causality_failure is not None:
        return causality_failure
    return _run_window_portfolio_evaluation(context, state, window, execution)


def _data_window_payload(
    window: Any,
    execution_spec: Any,
    execution: StrategyExecutionResult,
    row_contract: dict[str, Any],
) -> dict[str, Any]:
    return {
        "window_id": window.id,
        "data": execution_spec.data.model_dump(mode="json"),
        "row_count": len(execution.normalized_rows),
        "ranges_by_symbol": execution.normalized_rows.ranges_by_symbol,
        "availability_coverage": execution.normalized_rows.availability_coverage,
        "normalized_rows_sha256": execution.normalized_rows_sha256,
        "row_contract": row_contract,
        "evidence_quality": compact_evidence_quality(execution.evidence_quality),
        "decision_count": len(execution.decisions),
    }


def _write_window_audit_artifacts(
    context: _EvaluationContext,
    window: Any,
    execution: StrategyExecutionResult,
) -> tuple[dict[str, Any], str | None]:
    artifacts: dict[str, Any] = {}
    try:
        with context.event_emitter.stage(
            "artifact_writes",
            strategy_id=context.config.strategy_id,
            window_id=window.id,
            artifact_kind="evaluation_audit",
        ):
            input_rows_artifact = write_input_rows_artifact(
                context.result_dir,
                window_id=window.id,
                rows=execution.normalized_rows.projection_rows(),
                normalized_rows_sha256=execution.normalized_rows_sha256,
            )
            artifacts["input_rows_artifact"] = input_rows_artifact
            decision_records_artifact = write_decision_records_artifact(
                context.result_dir,
                window_id=window.id,
                decisions=execution.decisions,
            )
            artifacts["decision_records_artifact"] = decision_records_artifact
    except Exception as exc:
        return artifacts, f"evaluation audit artifact write failed: {exc}"
    return artifacts, None


def _run_data_audit(
    context: _EvaluationContext,
    state: _EvaluationState,
    window: Any,
    execution: StrategyExecutionResult,
    data_window: dict[str, Any],
) -> EvaluationRunResult | None:
    try:
        with context.event_emitter.stage(
            "data_audit",
            strategy_id=context.config.strategy_id,
            window_id=window.id,
            decision_count=len(execution.decisions),
        ) as audit_event:
            audit = audit_decision_rows(execution.normalized_rows, execution.decisions)
            data_window["data_audit"] = {"window_id": window.id, **audit.model_dump(mode="json")}
            if audit.passed:
                readiness_violations = check_decision_readiness(
                    execution.decisions,
                    context.config.readiness,
                    data_kind=context.config.data.kind,
                    include_inferred_data_kind_fields=False,
                )
                if readiness_violations:
                    data_window["data_audit"]["passed"] = False
                    data_window["data_audit"]["violations"] = list(readiness_violations)
                    message = "; ".join(readiness_violations)
                    audit_event.fail(message)
                    return _failure_result(
                        context,
                        state,
                        "data_audit",
                        "evaluation_preflight_failed",
                        message,
                    )
                return None
            message = "; ".join(audit.violations) if audit.violations else "data_audit_failed"
            audit_event.fail(message)
            return _failure_result(
                context,
                state,
                "data_audit",
                "evaluation_preflight_failed",
                message,
            )
    except Exception as exc:
        data_window["data_audit"] = {
            "window_id": window.id,
            "row_count": len(execution.normalized_rows),
            "decision_count": len(execution.decisions),
            "passed": False,
            "violations": [f"data_audit_failed: {exc}"],
        }
        return _failure_result(
            context,
            state,
            "data_audit",
            "evaluation_preflight_failed",
            f"data_audit_failed: {exc}",
        )


def _run_causality_check(
    context: _EvaluationContext,
    state: _EvaluationState,
    window: Any,
    execution: StrategyExecutionResult,
    data_window: dict[str, Any],
) -> EvaluationRunResult | None:
    with context.event_emitter.stage(
        "causality_check",
        strategy_id=context.config.strategy_id,
        window_id=window.id,
        mode=context.config.causality_replay.scope,
        decision_count=len(execution.decisions),
    ) as causality_event:
        lookahead = _run_configured_causality_replay(context, execution)
        data_window["causality_replay"] = _lookahead_replay_payload(
            lookahead,
            replay_scope=context.config.causality_replay.scope,
        )
        state.all_warnings.extend(lookahead.skipped_probe_reasons)
        causality_violations = _configured_causality_violations(
            context.config.causality_replay.scope,
            lookahead,
        )
        if causality_violations:
            message = "; ".join(causality_violations)
            causality_event.fail(message)
            return _failure_result(
                context,
                state,
                "preflight",
                "evaluation_preflight_failed",
                message,
            )
    return None


def _run_configured_causality_replay(
    context: _EvaluationContext,
    execution: StrategyExecutionResult,
) -> Any:
    if context.config.causality_replay.scope == "bounded":
        return check_bounded_causality(
            execution.generate_decisions,
            rows=execution.normalized_rows,
            params=execution.validated_params,
            baseline_decisions=execution.decisions,
            strategy_id=context.config.strategy_id,
            max_probes=context.config.causality_replay.probe_limit,
            timeout_seconds=context.config.causality_replay.timeout_seconds,
        )
    return check_hidden_lookahead(
        execution.generate_decisions,
        rows=execution.normalized_rows,
        params=execution.validated_params,
        baseline_decisions=execution.decisions,
        strategy_id=context.config.strategy_id,
        mode="strict",
    )


def _configured_causality_violations(scope: str, lookahead: Any) -> tuple[str, ...]:
    if scope == "bounded":
        violations = list(lookahead.violations)
        if lookahead.skipped_probe_reasons:
            violations.append(f"bounded_probe_skipped: {lookahead.skipped_probe_reasons[0]}")
        return tuple(dict.fromkeys(violations))
    return causality_completeness_violations(lookahead)


def _lookahead_replay_payload(lookahead: Any, *, replay_scope: str) -> dict[str, Any]:
    return {
        "replay_scope": replay_scope,
        "replay_mode": lookahead.mode,
        "deterministic_replay_verified": lookahead.deterministic_replay_verified,
        "emitted_replay_verified": lookahead.emitted_replay_verified,
        "strict_suppression_verified": lookahead.strict_suppression_verified,
        "skipped_probe_count": lookahead.skipped_probe_count,
        "skipped_probe_reasons": list(lookahead.skipped_probe_reasons),
        "candidate_probe_count": lookahead.candidate_probe_count,
        "selected_probe_count": lookahead.selected_probe_count,
        "elapsed_seconds": lookahead.elapsed_seconds,
        "timeout_seconds": lookahead.timeout_seconds,
        "timed_out": lookahead.timed_out,
        "replay_warning": lookahead.replay_warning,
    }


def _run_window_portfolio_evaluation(
    context: _EvaluationContext,
    state: _EvaluationState,
    window: Any,
    execution: StrategyExecutionResult,
) -> EvaluationRunResult | None:
    scenarios = expand_evaluation_scenarios(
        window=window,
        base_costs=context.config.cost_model,
        base_fill=context.config.fill_model,
        configured_scenarios=context.config.scenarios,
    )
    state.expected_scenario_ids.extend(scenario.scenario_id for scenario in scenarios)
    state.required_scenario_ids.extend(
        scenario.scenario_id for scenario in scenarios if scenario.required
    )
    projection_rows = execution.normalized_rows.projection_rows()
    benchmark_metrics, benchmark_failure = _window_benchmark_metrics(
        context, state, window, projection_rows
    )
    if benchmark_failure is not None:
        return benchmark_failure
    prepared, preparation_failure = _prepare_portfolio_inputs(
        context,
        state,
        window,
        execution,
        projection_rows,
        scenario_count=len(scenarios),
    )
    if preparation_failure is not None:
        return preparation_failure

    for scenario in scenarios:
        scenario_failure = _run_portfolio_scenario(
            context,
            state,
            window,
            execution,
            projection_rows,
            scenario,
            prepared=prepared,
            benchmark_metrics=benchmark_metrics,
        )
        if scenario_failure is not None:
            return scenario_failure
    return None


def _window_benchmark_metrics(
    context: _EvaluationContext,
    state: _EvaluationState,
    window: Any,
    projection_rows: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], EvaluationRunResult | None]:
    if context.config.benchmark is None:
        return {}, None
    try:
        with context.event_emitter.stage(
            "benchmark_metrics",
            strategy_id=context.config.strategy_id,
            window_id=window.id,
            benchmark_symbol=context.config.benchmark.symbol,
        ):
            metrics = benchmark_metrics_for_rows(
                projection_rows,
                symbol=context.config.benchmark.symbol,
            )
    except ValueError as exc:
        message = f"{window.id}: {exc}"
        return {}, _failure_result(
            context,
            state,
            "benchmark_metrics",
            "portfolio_evaluation_failed",
            message,
        )
    return metrics, None


def _prepare_portfolio_inputs(
    context: _EvaluationContext,
    state: _EvaluationState,
    window: Any,
    execution: StrategyExecutionResult,
    projection_rows: Sequence[dict[str, Any]],
    *,
    scenario_count: int,
) -> tuple[Any | None, EvaluationRunResult | None]:
    try:
        with context.event_emitter.stage(
            "portfolio_input_preparation",
            strategy_id=context.config.strategy_id,
            window_id=window.id,
            backend=_backend_name(context.selected_backend),
            decision_count=len(execution.decisions),
            row_count=len(projection_rows),
            scenario_count=scenario_count,
        ):
            prepared = (
                context.selected_backend.prepare_inputs(
                    decisions=execution.decisions,
                    rows=projection_rows,
                    data_kind=context.config.data.kind,
                    capacity_model=context.config.capacity_model,
                    risk_budget=context.config.risk_budget,
                    leverage_budget=context.config.leverage_budget,
                )
                if isinstance(context.selected_backend, PreparedEvaluationBackend)
                else None
            )
    except EvaluationDependencyError as exc:
        return None, _failure_result(
            context,
            state,
            "portfolio_evaluation",
            "portfolio_backend_unavailable",
            str(exc),
        )
    except ValueError as exc:
        return None, _failure_result(
            context,
            state,
            "portfolio_evaluation",
            "portfolio_evaluation_failed",
            str(exc),
        )
    except Exception as exc:
        return None, _failure_result(
            context,
            state,
            "portfolio_evaluation",
            "portfolio_evaluation_failed",
            f"portfolio input preparation failed: {exc}",
        )
    return prepared, None


def _run_portfolio_scenario(
    context: _EvaluationContext,
    state: _EvaluationState,
    window: Any,
    execution: StrategyExecutionResult,
    projection_rows: Sequence[dict[str, Any]],
    scenario: Any,
    *,
    prepared: Any | None,
    benchmark_metrics: Mapping[str, Any],
) -> EvaluationRunResult | None:
    with context.event_emitter.stage(
        "portfolio_evaluation",
        strategy_id=context.config.strategy_id,
        window_id=window.id,
        scenario_id=scenario.scenario_id,
        backend=_backend_name(context.selected_backend),
    ) as scenario_event:
        scenario_result = (
            context.selected_backend.run_prepared(
                prepared=prepared,
                scenario=scenario,
                metrics=context.config.metrics,
            )
            if prepared is not None
            and isinstance(context.selected_backend, PreparedEvaluationBackend)
            else context.selected_backend.run(
                decisions=execution.decisions,
                rows=projection_rows,
                scenario=scenario,
                metrics=context.config.metrics,
                data_kind=context.config.data.kind,
                capacity_model=context.config.capacity_model,
                risk_budget=context.config.risk_budget,
                leverage_budget=context.config.leverage_budget,
            )
        )
        scenario_result = _with_scenario_metadata(scenario_result, scenario)
        if scenario_result.status == "completed":
            scenario_result = _with_benchmark_metrics(scenario_result, benchmark_metrics)
        id_mismatch_failure = _scenario_id_mismatch_failure(scenario, scenario_result)
        if id_mismatch_failure is not None:
            state.backend_results.append(_strip_trace_tables(scenario_result))
            scenario_event.fail(id_mismatch_failure, backend_status=scenario_result.status)
            return _failure_result(
                context,
                state,
                "portfolio_evaluation",
                "portfolio_evaluation_failed",
                id_mismatch_failure,
            )
        if scenario_result.status != "completed":
            state.backend_results.append(_strip_trace_tables(scenario_result))
            status = (
                "portfolio_backend_unavailable"
                if scenario_result.status == "unavailable"
                else "portfolio_evaluation_failed"
            )
            message = _backend_failure_message(scenario_result)
            if not scenario.required:
                _record_optional_scenario_failure(state, scenario, message)
                return None
            scenario_event.fail(message, backend_status=scenario_result.status)
            return _failure_result(
                context,
                state,
                "portfolio_evaluation",
                status,
                message,
            )
        scoreability_failure = _completed_scoreability_failure(scenario_result)
        if scoreability_failure is not None:
            failed_result = _failed_scenario_result(scenario_result, scoreability_failure)
            if not scenario.required:
                state.backend_results.append(_strip_trace_tables(failed_result))
                _record_optional_scenario_failure(state, scenario, scoreability_failure)
                return None
            state.backend_results.append(_strip_trace_tables(failed_result))
            scenario_event.fail(scoreability_failure, backend_status=scenario_result.status)
            return _failure_result(
                context,
                state,
                "portfolio_evaluation",
                "portfolio_evaluation_failed",
                scoreability_failure,
            )
        metric_failure = _completed_metric_failure(scenario_result)
        if metric_failure is not None:
            if not scenario.required:
                state.backend_results.append(
                    _strip_trace_tables(_failed_scenario_result(scenario_result, metric_failure))
                )
                _record_optional_scenario_failure(state, scenario, metric_failure)
                return None
            scenario_event.fail(metric_failure, backend_status=scenario_result.status)
            return _failure_result(
                context,
                state,
                "portfolio_evaluation",
                "portfolio_evaluation_failed",
                metric_failure,
            )
        if scenario_result.tables is None:
            message = f"{scenario_result.scenario_id}: completed backend emitted no trace tables"
            if not scenario.required:
                state.backend_results.append(
                    _strip_trace_tables(_failed_scenario_result(scenario_result, message))
                )
                _record_optional_scenario_failure(state, scenario, message)
                return None
            scenario_event.fail(message, backend_status=scenario_result.status)
            return _failure_result(
                context,
                state,
                "portfolio_evaluation",
                "portfolio_evaluation_failed",
                message,
            )
        missing_trace_table = _missing_trace_table(scenario_result)
        if missing_trace_table is not None:
            message = f"{scenario_result.scenario_id}: missing trace table: {missing_trace_table}"
            if not scenario.required:
                state.backend_results.append(
                    _strip_trace_tables(_failed_scenario_result(scenario_result, message))
                )
                _record_optional_scenario_failure(state, scenario, message)
                return None
            scenario_event.fail(message, backend_status=scenario_result.status)
            return _failure_result(
                context,
                state,
                "portfolio_evaluation",
                "portfolio_evaluation_failed",
                message,
            )
        state.backend_results.append(_strip_trace_tables(scenario_result))
        state.trace_results.append(scenario_result)
    return None


def _scenario_id_mismatch_failure(scenario: Any, result: PortfolioEvaluationResult) -> str | None:
    if result.scenario_id == scenario.scenario_id:
        return None
    return (
        f"backend scenario id mismatch: expected={scenario.scenario_id} actual={result.scenario_id}"
    )


def _with_scenario_metadata(
    result: PortfolioEvaluationResult,
    scenario: Any,
) -> PortfolioEvaluationResult:
    return result.model_copy(
        update={
            "required": bool(scenario.required),
            "scoreability_bearing": bool(scenario.scoreability_bearing),
        }
    )


def _failed_scenario_result(
    result: PortfolioEvaluationResult, message: str
) -> PortfolioEvaluationResult:
    return result.model_copy(
        update={
            "status": "failed",
            "warnings": (*result.warnings, message),
            "tables": None,
        }
    )


def _record_optional_scenario_failure(state: _EvaluationState, scenario: Any, message: str) -> None:
    state.all_warnings.append(f"optional_scenario_failed:{scenario.scenario_id}:{message}")


def _with_benchmark_metrics(
    result: PortfolioEvaluationResult,
    benchmark_metrics: Mapping[str, Any],
) -> PortfolioEvaluationResult:
    if not benchmark_metrics:
        return result
    benchmark_return = _finite_float_metric(benchmark_metrics.get("benchmark_total_return"))
    total_return = _finite_float_metric(result.metrics.get("total_return"))
    if benchmark_return is None or total_return is None:
        return result
    metrics = dict(result.metrics)
    metrics.update(benchmark_metrics)
    metrics["excess_total_return"] = total_return - benchmark_return
    return result.model_copy(update={"metrics": metrics})


def _check_scenario_coverage(
    context: _EvaluationContext,
    state: _EvaluationState,
    scenario_summary: dict[str, Any],
) -> EvaluationRunResult | None:
    coverage = scenario_summary["scenario_coverage"]
    if not coverage["missing_ids"] and not coverage["unexpected_ids"]:
        return None
    message = (
        "scenario coverage mismatch: "
        f"missing={coverage['missing_ids']} unexpected={coverage['unexpected_ids']}"
    )
    with context.event_emitter.stage(
        "portfolio_evaluation",
        strategy_id=context.config.strategy_id,
        scenario_id="scenario_coverage",
        backend=_backend_name(context.selected_backend),
    ) as coverage_event:
        coverage_event.fail(message)
    return _failure_result(
        context,
        state,
        "portfolio_evaluation",
        "portfolio_evaluation_failed",
        message,
    )


def _write_completion_artifacts(
    context: _EvaluationContext,
    state: _EvaluationState,
    scenario_summary: dict[str, Any],
    *,
    annualization_cadence: Mapping[str, Any],
    backend_results: Sequence[PortfolioEvaluationResult],
) -> EvaluationRunResult | None:
    metrics_payload = {
        "metric_semantics": evaluation_metric_semantics(),
        "annualization_cadence": annualization_cadence,
        "evidence_quality_warnings": list(state.all_warnings),
        "scenarios": [
            {
                "scenario_id": item.scenario_id,
                "backend": item.backend,
                "status": item.status,
                "required": item.required,
                "scoreability_bearing": item.scoreability_bearing,
                "feasibility": item.feasibility.payload(),
                "sizing_report": (
                    None if item.sizing_report is None else item.sizing_report.payload()
                ),
                "metrics": item.metrics,
                "warnings": list(item.warnings),
                "unsupported_semantics": list(item.unsupported_semantics),
            }
            for item in backend_results
        ],
    }
    try:
        with context.event_emitter.stage(
            "artifact_writes",
            strategy_id=context.config.strategy_id,
            scenario_count=len(state.backend_results),
        ):
            write_data_manifest(context.result_dir, windows=state.data_windows)
            table_artifacts = _write_trace_tables(context.result_dir, state.trace_results)
            write_json_artifact(context.result_dir, "evaluation_metrics.json", metrics_payload)
            write_json_artifact(context.result_dir, "scenario_summary.json", scenario_summary)
            write_text_artifact(
                context.result_dir,
                "notes.md",
                _notes(context.config.strategy_id, list(backend_results)),
            )
            write_evaluation_manifest(
                context.result_dir,
                repo_root=context.repo_root,
                path_base=context.config.base_dir,
                config=context.config,
                config_path=context.config_path,
                backend_name=_backend_name(context.selected_backend),
                data_windows=state.data_windows,
                table_artifacts=table_artifacts,
                scenario_summary=scenario_summary,
                annualization_cadence=annualization_cadence,
                evidence_quality_warnings=tuple(state.all_warnings),
            )
    except Exception as exc:
        _cleanup_trace_table_dirs(context.result_dir)
        return _failure_result(
            context,
            state,
            "artifact_write",
            "evaluation_failed",
            f"artifact write failed: {exc}",
        )
    return None


def _run_provenance(*, backend_name: str) -> dict[str, str]:
    """Run-level provenance: package + python versions + backend name.

    Deterministic and side-effect-light (no git shell-out; the manifest already
    records git identity). Only string-valued entries are kept so the mapping
    satisfies the typed `Mapping[str, str]` contract.
    """
    provenance: dict[str, str] = {"backend": backend_name}
    provenance["python"] = python_identity()["version"]
    for name, version in package_versions(_PROVENANCE_PACKAGE_NAMES).items():
        if version is not None:
            provenance[f"{name}_version"] = version
    return provenance


def _completion_provenance(context: _EvaluationContext, state: _EvaluationState) -> dict[str, str]:
    """Augment run provenance with the data-snapshot identity (FR-I1)."""
    provenance = dict(context.provenance)
    snapshot_hashes = [
        str(window["normalized_rows_sha256"])
        for window in state.data_windows
        if window.get("normalized_rows_sha256")
    ]
    if snapshot_hashes:
        provenance["normalized_rows_sha256"] = ",".join(snapshot_hashes)
    provenance["causality_replay_scope"] = context.config.causality_replay.scope
    return provenance


def _build_fold_outputs(
    *,
    trace_results: Sequence[PortfolioEvaluationResult],
    metric_results: Sequence[PortfolioEvaluationResult],
    known_window_ids: Sequence[str],
    periods_per_year: float,
    provenance: Mapping[str, str],
) -> tuple[tuple[FoldReturnSeries, ...], tuple[FoldScenarioMetrics, ...]]:
    """Build typed per-fold return series + summary metrics from trace tables.

    Return series come from the in-process `portfolio_path` frames (`trace_results`);
    the cadence-corrected scalars come from `metric_results` (tables stripped). Both
    are keyed by `(window_id, scenario_id)`; the window id is resolved from the
    scenario id against the known window ids.
    """
    result_by_scenario = {result.scenario_id: result for result in metric_results}
    fold_returns: list[FoldReturnSeries] = []
    scenario_metrics: list[FoldScenarioMetrics] = []
    for result in trace_results:
        if result.tables is None:
            continue
        per_scenario = split_portfolio_path_by_scenario(result.tables.portfolio_path)
        if not per_scenario:
            per_scenario = {result.scenario_id: result.tables.portfolio_path}
        for scenario_id, frame in per_scenario.items():
            window_id = window_id_for_scenario(scenario_id, known_window_ids)
            fold_returns.append(
                fold_series_from_portfolio_path(
                    window_id,
                    scenario_id,
                    frame,
                    periods_per_year=periods_per_year,
                )
            )
            metric_result = result_by_scenario.get(scenario_id)
            scenario_metrics.append(
                fold_metrics_from_scenario(
                    window_id,
                    scenario_id,
                    {} if metric_result is None else metric_result.metrics,
                    provenance=provenance,
                    causal_ok=True,
                    scoreability_bearing=(
                        True if metric_result is None else metric_result.scoreability_bearing
                    ),
                    feasibility=None if metric_result is None else metric_result.feasibility,
                    sizing_report=None if metric_result is None else metric_result.sizing_report,
                )
            )
    return tuple(fold_returns), tuple(scenario_metrics)


def _completion_artifact_results(
    results: Sequence[PortfolioEvaluationResult],
    *,
    annualization_cadence: Mapping[str, Any],
) -> list[PortfolioEvaluationResult]:
    if annualization_cadence.get("status") == "ok":
        return list(results)
    return [
        _null_annualized_risk_metrics_due_to_cadence(
            result,
            cadence_status=str(annualization_cadence.get("status") or "unknown"),
        )
        for result in results
    ]


def _null_annualized_risk_metrics_due_to_cadence(
    result: PortfolioEvaluationResult,
    *,
    cadence_status: str,
) -> PortfolioEvaluationResult:
    if result.status != "completed":
        return result
    metrics = dict(result.metrics)
    for name in _ANNUALIZED_RISK_METRICS:
        if name in metrics:
            metrics[name] = None
    warnings = result.warnings
    null_warning = (
        _ANNUALIZED_CADENCE_INSUFFICIENT_NULL_WARNING
        if cadence_status == "insufficient"
        else _ANNUALIZED_CADENCE_NULL_WARNING
    )
    if null_warning not in warnings:
        warnings = (*warnings, null_warning)
    return result.model_copy(update={"metrics": metrics, "warnings": warnings})


def _annualization_cadence_summary(
    results: list[PortfolioEvaluationResult],
    *,
    configured_periods_per_year: int,
) -> dict[str, Any]:
    groups = _portfolio_path_cadence_groups(
        results,
        configured_periods_per_year=configured_periods_per_year,
    )
    spacing_count = sum(int(group["spacing_observation_count"]) for group in groups)
    measured_scenario_ids = {str(group["scenario_id"]) for group in groups}
    insufficient_scenario_ids = sorted(
        set(_completed_portfolio_path_scenario_ids(results)) - measured_scenario_ids
    )
    summary: dict[str, Any] = {
        "configured_periods_per_year": configured_periods_per_year,
        "observed_median_spacing_seconds": None,
        "implied_periods_per_year": None,
        "mismatch_factor": None,
        "spacing_observation_count": spacing_count,
        "observed_group_count": len(groups),
        "offending_scenario_ids": [],
        "insufficient_scenario_ids": insufficient_scenario_ids,
        "status": "insufficient",
        "warning": None,
    }
    if not groups:
        summary["warning"] = _annualization_cadence_insufficient_warning(
            spacing_count,
            insufficient_scenario_ids,
        )
        return summary

    offending_groups = [
        group
        for group in groups
        if group["mismatch_factor"] > _ANNUALIZATION_CADENCE_MISMATCH_FACTOR_THRESHOLD
    ]
    offending_ids = sorted(str(group["scenario_id"]) for group in offending_groups)
    representative = max(
        offending_groups or groups,
        key=lambda group: group["mismatch_factor"],
    )
    summary.update(
        {
            "observed_median_spacing_seconds": representative["observed_median_spacing_seconds"],
            "implied_periods_per_year": representative["implied_periods_per_year"],
            "mismatch_factor": representative["mismatch_factor"],
            "offending_scenario_ids": offending_ids,
            "status": "ok",
        }
    )
    if insufficient_scenario_ids:
        summary["status"] = "insufficient"
        summary["warning"] = _annualization_cadence_insufficient_warning(
            spacing_count,
            insufficient_scenario_ids,
        )
        return summary
    if offending_groups:
        warning = (
            "annualization_cadence_mismatch:"
            f"configured_periods_per_year={configured_periods_per_year}:"
            f"offending_scenario_ids={','.join(offending_ids)}:"
            f"observed_median_spacing_seconds={representative['observed_median_spacing_seconds']:g}:"
            f"implied_periods_per_year={representative['implied_periods_per_year']:.6g}:"
            f"mismatch_factor={representative['mismatch_factor']:.6g}"
        )
        summary["status"] = "warning"
        summary["offending_scenario_ids"] = offending_ids
        summary["warning"] = warning
    return summary


def _annualization_cadence_insufficient_warning(
    spacing_count: int,
    scenario_ids: Sequence[str],
) -> str:
    warning = f"annualization_cadence_insufficient:spacing_observation_count={spacing_count}"
    if scenario_ids:
        warning += f":insufficient_scenario_ids={','.join(scenario_ids)}"
    return warning


def _completed_portfolio_path_scenario_ids(
    results: Sequence[PortfolioEvaluationResult],
) -> tuple[str, ...]:
    scenario_ids: list[str] = []
    for result in results:
        if result.status != "completed" or result.tables is None:
            continue
        frame = result.tables.portfolio_path
        columns = getattr(frame, "columns", ())
        if frame is None or "timestamp" not in columns:
            scenario_ids.append(result.scenario_id)
            continue
        if "scenario_id" in columns and hasattr(frame, "groupby"):
            group_ids = [str(scenario_id) for scenario_id, _group in frame.groupby("scenario_id")]
            scenario_ids.extend(group_ids or [result.scenario_id])
            continue
        scenario_ids.append(result.scenario_id)
    return tuple(dict.fromkeys(scenario_ids))


def _portfolio_path_cadence_groups(
    results: list[PortfolioEvaluationResult],
    *,
    configured_periods_per_year: int,
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for result in results:
        if result.status != "completed" or result.tables is None:
            continue
        frame = result.tables.portfolio_path
        if frame is None or "timestamp" not in getattr(frame, "columns", ()):
            continue
        frame_groups = (
            ((str(scenario_id), group) for scenario_id, group in frame.groupby("scenario_id"))
            if "scenario_id" in frame.columns and hasattr(frame, "groupby")
            else ((result.scenario_id, frame),)
        )
        for scenario_id, group in frame_groups:
            spacings = _timestamp_spacing_seconds(group["timestamp"])
            if not spacings:
                continue
            median_spacing = _median(spacings)
            if median_spacing <= 0.0 or not math.isfinite(median_spacing):
                continue
            implied_periods_per_year = _SECONDS_PER_YEAR / median_spacing
            mismatch_factor = max(
                configured_periods_per_year / implied_periods_per_year,
                implied_periods_per_year / configured_periods_per_year,
            )
            groups.append(
                {
                    "scenario_id": scenario_id,
                    "observed_median_spacing_seconds": median_spacing,
                    "implied_periods_per_year": implied_periods_per_year,
                    "mismatch_factor": mismatch_factor,
                    "spacing_observation_count": len(spacings),
                }
            )
    return groups


def _timestamp_spacing_seconds(values: Any) -> list[float]:
    import pandas as pd

    timestamps = pd.to_datetime(values, utc=True, errors="coerce").dropna()
    if len(timestamps) < 2:
        return []
    unique_timestamps = sorted(dict.fromkeys(timestamps))
    return [
        float((current - previous).total_seconds())
        for previous, current in zip(unique_timestamps, unique_timestamps[1:])
        if current > previous
    ]


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[midpoint])
    return (float(ordered[midpoint - 1]) + float(ordered[midpoint])) / 2.0


def _backend_name(backend: Any) -> str:
    return getattr(backend, "name", "unknown")


def _write_trace_tables(
    result_dir: Path, results: list[PortfolioEvaluationResult]
) -> list[dict[str, Any]]:
    scenario_ids = tuple(result.scenario_id for result in results)
    artifact_kinds = (
        "portfolio_path",
        "trades",
        "target_positions",
        "target_exposure_summary",
        "execution_events",
        "funding_cashflows",
    )
    frames = {
        artifact_kind: _combine_trace_frames(results, artifact_kind)
        for artifact_kind in artifact_kinds
    }
    final_dir = result_dir / "tables"
    staging_dir = result_dir / "tables_staging"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    if final_dir.exists():
        raise OSError(f"trace table directory already exists: {final_dir}")

    table_artifacts: list[dict[str, Any]] = []
    try:
        for artifact_kind in artifact_kinds:
            table_artifacts.append(
                write_parquet_artifact(
                    result_dir,
                    f"tables_staging/{artifact_kind}.parquet",
                    frames[artifact_kind],
                    artifact_kind=artifact_kind,
                    scenario_ids=scenario_ids,
                    logical_name=f"tables/{artifact_kind}.parquet",
                )
            )
        staging_dir.rename(final_dir)
    except Exception:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        raise

    return table_artifacts


def _missing_trace_table(result: PortfolioEvaluationResult) -> str | None:
    if result.tables is None:
        return "tables"
    for artifact_kind in (
        "portfolio_path",
        "trades",
        "target_positions",
        "target_exposure_summary",
        "execution_events",
        "funding_cashflows",
    ):
        if getattr(result.tables, artifact_kind) is None:
            return artifact_kind
    return None


def _cleanup_trace_table_dirs(result_dir: Path) -> None:
    for dirname in ("tables", "tables_staging"):
        path = result_dir / dirname
        try:
            if path.exists():
                shutil.rmtree(path)
        except OSError:
            pass


def _combine_trace_frames(results: list[PortfolioEvaluationResult], table_name: str) -> Any:
    import pandas as pd

    frames = []
    for result in results:
        assert result.tables is not None
        frame = getattr(result.tables, table_name)
        frames.append(frame)
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


def _completed_scoreability_failure(result: PortfolioEvaluationResult) -> str | None:
    if (
        result.status != "completed"
        or not result.scoreability_bearing
        or result.feasibility.feasible
    ):
        return None
    reason = result.feasibility.reason or "infeasible"
    parts = [f"{result.scenario_id}: non_scoreable:{reason}"]
    if result.feasibility.detail:
        parts.append(str(result.feasibility.detail))
    return ": ".join(parts)


def _completed_metric_failure(result: PortfolioEvaluationResult) -> str | None:
    for name in _REQUIRED_COMPLETED_FLOAT_METRICS:
        if _finite_float_metric(result.metrics.get(name)) is None:
            return f"{result.scenario_id}: invalid completed metrics: {name}"
    for name in _REQUIRED_COMPLETED_COUNT_METRICS:
        if _non_negative_int_metric(result.metrics.get(name)) is None:
            return f"{result.scenario_id}: invalid completed metrics: {name}"
    if result.metrics.get("funding_model") not in _REQUIRED_COMPLETED_FUNDING_MODELS:
        return f"{result.scenario_id}: invalid completed metrics: funding_model"
    return None


def _finite_float_metric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    metric = float(value)
    return metric if math.isfinite(metric) else None


def _non_negative_int_metric(value: Any) -> int | None:
    metric = _finite_float_metric(value)
    if metric is None or not metric.is_integer() or metric < 0.0:
        return None
    return int(metric)


def _failure_result(
    context: _EvaluationContext,
    state: _EvaluationState,
    failure_stage: str,
    assessment_status: str,
    message: str,
    *,
    unsupported_semantics: Sequence[str] = (),
) -> EvaluationRunResult:
    warnings = tuple(state.all_warnings)
    unsupported = tuple(dict.fromkeys([*unsupported_semantics, *_unsupported_semantics(state)]))
    artifact_warning = _write_failure_artifacts(
        context,
        state,
        failure_stage=failure_stage,
        assessment_status=assessment_status,
        message=message,
        warnings=warnings,
        unsupported_semantics=unsupported,
    )
    if artifact_warning is not None:
        warnings = (*warnings, artifact_warning)
    return EvaluationRunResult(
        result_dir=context.result_dir,
        message=message,
        run_completed=False,
        failure_stage=failure_stage,
        assessment_status=assessment_status,
        evidence_quality_warnings=warnings,
        causal_replay_passed=(False if failure_stage in _CAUSAL_FAILURE_STAGES else None),
        provenance={
            **dict(context.provenance),
            "causality_replay_scope": context.config.causality_replay.scope,
        },
    )


def _write_failure_artifacts(
    context: _EvaluationContext,
    state: _EvaluationState,
    *,
    failure_stage: str,
    assessment_status: str,
    message: str,
    warnings: Sequence[str],
    unsupported_semantics: Sequence[str],
) -> str | None:
    scenario_summary = _scenario_summary(
        state.backend_results,
        state.expected_scenario_ids,
        required_ids=state.required_scenario_ids,
    )
    payload = {
        "schema_version": "quant_strategies.evaluation.failure/v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "strategy_id": context.config.strategy_id,
        "backend": _backend_name(context.selected_backend),
        "failure_stage": failure_stage,
        "assessment_status": assessment_status,
        "message": message,
        "evidence_quality_warnings": list(warnings),
        "unsupported_semantics": list(unsupported_semantics),
        "data_windows": state.data_windows,
        "scenario_summary": scenario_summary,
        "not_authority": "not validation, promotion, paper trading, or live trading authority",
    }
    try:
        with context.event_emitter.stage(
            "failure_artifact_writes",
            strategy_id=context.config.strategy_id,
            failure_stage=failure_stage,
        ):
            write_json_artifact(context.result_dir, "evaluation_failure.json", payload)
            write_text_artifact(
                context.result_dir,
                "notes.md",
                _failure_notes(
                    context.config.strategy_id,
                    failure_stage=failure_stage,
                    assessment_status=assessment_status,
                    message=message,
                    scenario_count=len(state.backend_results),
                ),
            )
    except Exception as exc:
        return f"evaluation_failure_artifact_write_failed: {type(exc).__name__}: {exc}"
    return None


def _unsupported_semantics(state: _EvaluationState) -> tuple[str, ...]:
    values: list[str] = []
    for result in state.backend_results:
        values.extend(result.unsupported_semantics)
    return tuple(dict.fromkeys(values))


def _scenario_summary(
    results: list[PortfolioEvaluationResult],
    expected_ids: list[str],
    *,
    required_ids: list[str],
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for result in results:
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
    completed_ids = [result.scenario_id for result in results if result.status == "completed"]
    expected_id_set = set(expected_ids)
    required_id_set = set(required_ids)
    optional_ids = [
        scenario_id for scenario_id in expected_ids if scenario_id not in required_id_set
    ]
    unexpected_ids = sorted(set(completed_ids) - expected_id_set)
    missing_required_ids = sorted(required_id_set - set(completed_ids))
    missing_optional_ids = sorted(set(optional_ids) - set(completed_ids))
    return {
        "scenario_count": len(results),
        "status_counts": dict(sorted(status_counts.items())),
        "scenario_coverage": {
            "expected_count": len(expected_ids),
            "required_count": len(required_ids),
            "optional_count": len(optional_ids),
            "completed_count": len(completed_ids),
            "expected_ids": expected_ids,
            "required_ids": required_ids,
            "optional_ids": optional_ids,
            "completed_ids": completed_ids,
            "missing_ids": missing_required_ids,
            "missing_required_ids": missing_required_ids,
            "missing_optional_ids": missing_optional_ids,
            "unexpected_ids": unexpected_ids,
        },
        "scenarios": [
            {
                "scenario_id": result.scenario_id,
                "backend": result.backend,
                "status": result.status,
                "required": result.required,
                "scoreability_bearing": result.scoreability_bearing,
                "feasibility": result.feasibility.payload(),
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


def _failure_notes(
    strategy_id: str,
    *,
    failure_stage: str,
    assessment_status: str,
    message: str,
    scenario_count: int,
) -> str:
    return (
        "# Evaluation Notes\n\n"
        f"- Strategy: `{strategy_id}`\n"
        f"- Status: `{assessment_status}`\n"
        f"- Failure stage: `{failure_stage}`\n"
        f"- Message: {message}\n"
        f"- Scenarios reached: {scenario_count}\n"
        "- Evidence class: failed research evaluation\n"
        "- Authority: evidence only; not validation, promotion, paper trading, or live trading authority.\n"
    )
