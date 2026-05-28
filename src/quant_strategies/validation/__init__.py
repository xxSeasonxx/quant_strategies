from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field as _field
from pathlib import Path
from typing import TYPE_CHECKING as _TYPE_CHECKING, Any

from quant_strategies.boundary import frozen_params, frozen_rows
from quant_strategies.decisions import (
    StrategyDecision,
    validate_decision_output,
    validate_strategy_params,
)
from quant_strategies.provenance import file_sha256
from quant_strategies.runner.config import default_repo_root
from quant_strategies.runner.execution import (
    StrategyExecutionError,
    execute_strategy_run,
)
from quant_strategies.validation.artifacts import (
    canonical_jsonl_lines,
    create_validation_result_dir,
    write_json_artifact,
    write_text_artifact,
)
from quant_strategies.validation.backends import (
    BackendRunResult,
    DecisionGenerationStatus,
    ScenarioBackendRunResult,
    ValidationBackend,
    backend_metric_semantics,
    get_backend,
)
from quant_strategies.validation.capabilities import backend_capability_matrix
from quant_strategies.validation.config import ScenarioRunConfig
from quant_strategies.validation.config import load_validation_config
from quant_strategies.validation.config import resolve_validation_config_path
from quant_strategies.validation.data_audit import audit_decision_rows
from quant_strategies.validation.lookahead import check_hidden_lookahead
from quant_strategies.validation.manifest import rows_sha256, write_validation_manifest
from quant_strategies.validation.matrix import MatrixScenario, expand_validation_matrix
from quant_strategies.validation.policy import (
    ValidationPolicyDecision,
    classify_validation,
    overfit_controls_from_search_pressure,
)
from quant_strategies.validation.readiness import check_validation_readiness

if _TYPE_CHECKING:
    from quant_strategies.runner.execution import StrategyExecutionResult as _StrategyExecutionResult


@dataclass(frozen=True)
class ValidationRunResult:
    success: bool
    result_dir: Path | None
    decision: ValidationPolicyDecision
    message: str


@dataclass(frozen=True)
class _ScenarioDecisionOutcome:
    decisions: list[StrategyDecision]
    decision_generation_status: DecisionGenerationStatus
    decisions_regenerated: bool
    failure: BackendRunResult | None = None


@dataclass(frozen=True)
class _ValidationContext:
    repo_root: Path
    path_base: Path
    config: Any
    config_path: Path
    result_dir: Path
    backend_name: str
    selected_backend: ValidationBackend


@dataclass
class _ValidationState:
    all_decisions: list[StrategyDecision] = _field(default_factory=list)
    backend_results: list[ScenarioBackendRunResult] = _field(default_factory=list)
    data_audits: list[dict[str, Any]] = _field(default_factory=list)
    data_provenance: list[dict[str, Any]] = _field(default_factory=list)
    failure_reasons: list[str] = _field(default_factory=list)
    required_scenario_ids: list[str] = _field(default_factory=list)


_MIN_VALIDATION_TRADES = 10


def run_validation(
    config_path: str | Path,
    *,
    repo_root: Path | None = None,
    backend: ValidationBackend | None = None,
) -> ValidationRunResult:
    root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
    resolved_config_path = resolve_validation_config_path(config_path, repo_root=repo_root)
    config = load_validation_config(resolved_config_path)
    path_base = config.base_dir
    result_dir = create_validation_result_dir(config.output.results_dir, config.strategy_id)
    _write_static_validation_artifacts(
        result_dir=result_dir,
        config=config,
        config_path=resolved_config_path,
    )

    state = _ValidationState()
    backend_name = config.backend

    try:
        selected_backend = backend or get_backend(config.backend)
        backend_name = _backend_name(selected_backend, config.backend)
    except Exception as exc:
        return _failure_result(
            result_dir=result_dir,
            repo_root=root,
            path_base=path_base,
            config=config,
            config_path=resolved_config_path,
            backend_name=backend_name,
            decisions=state.all_decisions,
            data_audits=state.data_audits,
            data_provenance=state.data_provenance,
            backend_results=state.backend_results,
            reason="backend_selection_failed",
            failure_details=[_failure_detail("backend_selection", exc)],
        )

    context = _ValidationContext(
        repo_root=root,
        path_base=path_base,
        config=config,
        config_path=resolved_config_path,
        result_dir=result_dir,
        backend_name=backend_name,
        selected_backend=selected_backend,
    )
    for window in config.windows:
        terminal_result = _run_validation_window(context, state, window)
        if terminal_result is not None:
            return terminal_result

    decision = _classify_validation_state(context, state)
    _write_validation_artifacts(
        result_dir=result_dir,
        repo_root=root,
        path_base=path_base,
        config=config,
        config_path=resolved_config_path,
        backend_name=backend_name,
        decisions=state.all_decisions,
        data_audits=state.data_audits,
        data_provenance=state.data_provenance,
        backend_results=state.backend_results,
        decision=decision,
        failure_details=[],
    )
    return _validation_result(result_dir, decision)


def _run_validation_window(
    context: _ValidationContext,
    state: _ValidationState,
    window: Any,
) -> ValidationRunResult | None:
    run_config = context.config.to_run_config(
        window,
        results_dir=context.result_dir / "runner_smoke" / window.id,
    )
    try:
        execution = execute_strategy_run(run_config, repo_root=context.path_base)
    except StrategyExecutionError as exc:
        return _handle_window_execution_error(context, state, window, run_config, exc)

    state.data_provenance.append(
        _data_provenance(window.id, run_config, status="loaded", rows=execution.loaded_rows)
    )
    state.all_decisions.extend(execution.decisions)
    audit_payload = _audit_window_execution(context, state, window, execution)
    state.data_audits.append(audit_payload)
    if audit_payload["passed"]:
        _run_window_scenarios(context, state, window, run_config, execution)
    return None


def _handle_window_execution_error(
    context: _ValidationContext,
    state: _ValidationState,
    window: Any,
    run_config: Any,
    exc: StrategyExecutionError,
) -> ValidationRunResult | None:
    if exc.stage == "strategy_import":
        return _failure_result_from_state(
            context,
            state,
            reason="strategy_import_failed",
            failure_details=[_execution_failure_detail("strategy_import", exc)],
        )
    if exc.stage == "param_validation":
        state.data_audits.append(
            _failed_data_audit(
                "config",
                row_count=0,
                decision_count=0,
                violations=(f"param_validation_failed: {_execution_failure_message(exc)}",),
            )
        )
        return _failure_result_from_state(
            context,
            state,
            reason="param_validation_failed",
            failure_details=[_execution_failure_detail("param_validation", exc)],
        )
    if exc.stage == "data_load":
        state.data_provenance.append(
            _data_provenance(
                window.id,
                run_config,
                status="failed",
                rows=None,
                message=str(exc),
            )
        )
        state.data_audits.append(
            _failed_data_audit(
                window.id,
                row_count=0,
                decision_count=0,
                violations=(f"data_load_failed: {exc}",),
            )
        )
        return None
    if exc.stage == "decision_generation":
        if exc.loaded_rows is not None:
            state.data_provenance.append(
                _data_provenance(
                    window.id,
                    run_config,
                    status="loaded",
                    rows=exc.loaded_rows,
                )
            )
        if exc.violations:
            state.data_audits.append(
                _failed_data_audit(
                    window.id,
                    row_count=0 if exc.loaded_rows is None else len(exc.loaded_rows),
                    decision_count=exc.decision_count or 0,
                    violations=exc.violations,
                )
            )
            return None
        state.failure_reasons.append("strategy_generation_failed")
        state.data_audits.append(
            _failed_data_audit(
                window.id,
                row_count=0 if exc.loaded_rows is None else len(exc.loaded_rows),
                decision_count=exc.decision_count or 0,
                violations=(f"strategy_generation_failed: {_execution_failure_message(exc)}",),
            )
        )
        return None
    raise exc


def _audit_window_execution(
    context: _ValidationContext,
    state: _ValidationState,
    window: Any,
    execution: _StrategyExecutionResult,
) -> dict[str, Any]:
    strategy_rows = frozen_rows(execution.loaded_rows)
    decisions = execution.decisions
    try:
        audit = audit_decision_rows(strategy_rows, decisions)
    except Exception as exc:
        state.failure_reasons.append("data_audit_failed")
        return _failed_data_audit(
            window.id,
            row_count=len(execution.loaded_rows),
            decision_count=len(decisions),
            violations=(f"data_audit_failed: {exc}",),
        )

    audit_payload = {"window_id": window.id, **audit.model_dump(mode="json")}
    if audit.passed:
        lookahead = check_hidden_lookahead(
            execution.generate_decisions,
            rows=execution.loaded_rows,
            params=execution.validated_params,
            baseline_decisions=decisions,
            strategy_id=context.config.strategy_id,
        )
        if not lookahead.passed:
            reason = (
                "hidden_lookahead_check_failed"
                if any(
                    item.startswith("hidden_lookahead_check_failed")
                    for item in lookahead.violations
                )
                else "hidden_lookahead_detected"
            )
            state.failure_reasons.append(reason)
            audit_payload["passed"] = False
            audit_payload["violations"] = list(audit.violations) + list(lookahead.violations)

    if audit_payload["passed"]:
        readiness_violations = check_validation_readiness(decisions, context.config.readiness)
        if readiness_violations:
            state.failure_reasons.append("validation_readiness_failed")
            audit_payload["passed"] = False
            audit_payload["violations"] = list(audit.violations) + list(readiness_violations)
    return audit_payload


def _run_window_scenarios(
    context: _ValidationContext,
    state: _ValidationState,
    window: Any,
    run_config: Any,
    execution: _StrategyExecutionResult,
) -> None:
    scenarios = expand_validation_matrix(
        window_id=window.id,
        base_params=_plain_mapping(execution.validated_params),
        base_costs=_plain_mapping(context.config.cost_model),
        base_fill=_plain_mapping(context.config.fill_model),
    )
    state.required_scenario_ids.extend(scenario.id for scenario in scenarios if scenario.required)
    for scenario in scenarios:
        state.backend_results.append(
            _run_scenario_backend(context, window, run_config, execution, scenario)
        )


def _run_scenario_backend(
    context: _ValidationContext,
    window: Any,
    run_config: Any,
    execution: _StrategyExecutionResult,
    scenario: MatrixScenario,
) -> ScenarioBackendRunResult:
    scenario_config = _scenario_config(
        config=context.config,
        scenario=scenario,
        base_params=execution.validated_params,
        data=run_config.data,
    )
    decision_outcome = _scenario_decision_outcome(
        scenario=scenario,
        generate_decisions=execution.generate_decisions,
        base_decisions=execution.decisions,
        rows=execution.loaded_rows,
        strategy_id=context.config.strategy_id,
        scenario_config=scenario_config,
        readiness=context.config.readiness,
        backend_name=context.backend_name,
    )
    backend_result = decision_outcome.failure
    decision_records_path = None
    decision_records_sha256 = None
    if backend_result is None:
        decision_records_path, decision_records_sha256 = _write_scenario_decision_records(
            result_dir=context.result_dir,
            scenario_id=scenario.id,
            decisions=decision_outcome.decisions,
        )
        try:
            raw_backend_result = context.selected_backend.run(
                decisions=list(decision_outcome.decisions),
                rows=frozen_rows(execution.loaded_rows),
                config=scenario_config,
            )
        except Exception as exc:
            backend_result = _failed_backend_result(
                context.backend_name,
                f"backend_exception: {exc}",
            )
        else:
            try:
                backend_result = BackendRunResult.model_validate(raw_backend_result)
            except Exception as exc:
                backend_result = _failed_backend_result(
                    context.backend_name,
                    f"invalid_backend_result: {exc}",
                )
    return ScenarioBackendRunResult(
        window_id=window.id,
        scenario_id=scenario.id,
        required=scenario.required,
        result=backend_result,
        scenario_kind=scenario.kind,
        decisions_regenerated=decision_outcome.decisions_regenerated,
        diagnostic_only=not scenario.required,
        decision_generation_status=decision_outcome.decision_generation_status,
        decision_count=len(decision_outcome.decisions),
        decision_records_path=decision_records_path,
        decision_records_sha256=decision_records_sha256,
    )


def _classify_validation_state(
    context: _ValidationContext,
    state: _ValidationState,
) -> ValidationPolicyDecision:
    data_passed = all(audit["passed"] for audit in state.data_audits)
    if state.failure_reasons:
        return _hard_no_decision(
            state.failure_reasons,
            search_pressure=context.config.search_pressure,
        )
    return classify_validation(
        data_passed=data_passed,
        backend_results=state.backend_results,
        min_trades=_MIN_VALIDATION_TRADES,
        required_scenario_ids=tuple(state.required_scenario_ids),
        paper_readiness=context.config.paper_readiness,
        search_pressure=context.config.search_pressure,
    )


def _failure_result_from_state(
    context: _ValidationContext,
    state: _ValidationState,
    *,
    reason: str,
    failure_details: list[dict[str, str]],
) -> ValidationRunResult:
    return _failure_result(
        result_dir=context.result_dir,
        repo_root=context.repo_root,
        path_base=context.path_base,
        config=context.config,
        config_path=context.config_path,
        backend_name=context.backend_name,
        decisions=state.all_decisions,
        data_audits=state.data_audits,
        data_provenance=state.data_provenance,
        backend_results=state.backend_results,
        reason=reason,
        failure_details=failure_details,
    )


def _validation_result(result_dir: Path, decision: ValidationPolicyDecision) -> ValidationRunResult:
    return ValidationRunResult(
        success=decision.decision in {"mechanical_pass", "watchlist", "mechanical_review_candidate"},
        result_dir=result_dir,
        decision=decision,
        message=f"validation decision: {decision.decision}",
    )


def _hard_no_decision(
    reasons: str | Sequence[str],
    *,
    search_pressure: object | None = None,
) -> ValidationPolicyDecision:
    reason_tuple = (reasons,) if isinstance(reasons, str) else tuple(dict.fromkeys(reasons))
    return ValidationPolicyDecision(
        decision="hard_no",
        reasons=reason_tuple,
        failed_gates=reason_tuple,
        gate_details={reason: "failed" for reason in reason_tuple},
        overfit_controls=overfit_controls_from_search_pressure(search_pressure),
    )


def _failure_detail(stage: str, exc: Exception) -> dict[str, str]:
    return {
        "stage": stage,
        "type": type(exc).__name__,
        "message": str(exc),
    }


def _execution_failure_detail(stage: str, exc: StrategyExecutionError) -> dict[str, str]:
    cause = exc.__cause__ if exc.__cause__ is not None else exc
    return _failure_detail(stage, cause)


def _execution_failure_message(exc: StrategyExecutionError) -> str:
    cause = exc.__cause__ if exc.__cause__ is not None else exc
    return str(cause)


def _failure_result(
    *,
    result_dir: Path,
    repo_root: Path,
    path_base: Path,
    config: Any,
    config_path: Path,
    backend_name: str,
    decisions: list[StrategyDecision],
    data_audits: list[dict[str, Any]],
    data_provenance: list[dict[str, Any]],
    backend_results: list[ScenarioBackendRunResult],
    reason: str,
    failure_details: list[dict[str, str]] | None = None,
) -> ValidationRunResult:
    decision = _hard_no_decision(
        reason,
        search_pressure=getattr(config, "search_pressure", None),
    )
    _write_validation_artifacts(
        result_dir=result_dir,
        repo_root=repo_root,
        path_base=path_base,
        config=config,
        config_path=config_path,
        backend_name=backend_name,
        decisions=decisions,
        data_audits=data_audits,
        data_provenance=data_provenance,
        backend_results=backend_results,
        decision=decision,
        failure_details=failure_details or [],
    )
    return _validation_result(result_dir, decision)


def _failed_data_audit(
    window_id: str,
    *,
    row_count: int,
    decision_count: int,
    violations: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "window_id": window_id,
        "row_count": row_count,
        "decision_count": decision_count,
        "passed": False,
        "violations": violations,
    }


def _data_provenance(
    window_id: str,
    run_config: Any,
    *,
    status: str,
    rows: Sequence[Mapping[str, Any]] | None,
    message: str | None = None,
) -> dict[str, Any]:
    payload = {
        "window_id": window_id,
        "status": status,
        "data": {
            "kind": run_config.data.kind,
            "dataset": run_config.data.dataset,
            "symbols": list(run_config.data.symbols),
            "start": run_config.data.start.isoformat(),
            "end": run_config.data.end.isoformat(),
            "strict": run_config.data.strict,
        },
        "row_count": 0 if rows is None else len(rows),
        "rows_sha256": None if rows is None else rows_sha256(rows),
    }
    if message is not None:
        payload["message"] = message
    return payload


def _plain_mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return dict(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return dict(value)
    return dict(vars(value))


def _scenario_config(
    *,
    config: Any,
    scenario: MatrixScenario,
    base_params: Mapping[str, Any],
    data: Any,
) -> ScenarioRunConfig:
    return ScenarioRunConfig.model_validate(
        {
            "scenario_id": scenario.id,
            "params": {**_plain_mapping(base_params), **scenario.params},
            "cost_model": {**_plain_mapping(config.cost_model), **scenario.cost_model},
            "fill_model": {**_plain_mapping(config.fill_model), **scenario.fill_model},
            "data": _plain_mapping(data),
        }
    )


def _scenario_decision_outcome(
    *,
    scenario: MatrixScenario,
    generate_decisions: Any,
    base_decisions: list[StrategyDecision],
    rows: Sequence[Mapping[str, Any]],
    strategy_id: str,
    scenario_config: Any,
    readiness: Any,
    backend_name: str,
) -> _ScenarioDecisionOutcome:
    if scenario.kind != "parameter":
        return _ScenarioDecisionOutcome(
            decisions=list(base_decisions),
            decision_generation_status="base_reused",
            decisions_regenerated=False,
        )
    try:
        scenario_params = validate_strategy_params(generate_decisions, scenario_config.params)
        decision_output = generate_decisions(frozen_rows(rows), frozen_params(scenario_params))
    except Exception as exc:
        return _ScenarioDecisionOutcome(
            decisions=[],
            decision_generation_status="failed",
            decisions_regenerated=False,
            failure=_failed_backend_result(
                backend_name,
                f"parameter_decision_generation_failed: {exc}",
            ),
        )

    scenario_decisions, violations = validate_decision_output(
        decision_output,
        strategy_id=strategy_id,
    )
    if violations:
        return _ScenarioDecisionOutcome(
            decisions=[],
            decision_generation_status="failed",
            decisions_regenerated=False,
            failure=_failed_backend_result(
                backend_name,
                f"parameter_decision_generation_failed: {'; '.join(violations)}",
            ),
        )
    audit = audit_decision_rows(frozen_rows(rows), scenario_decisions)
    if not audit.passed:
        return _ScenarioDecisionOutcome(
            decisions=[],
            decision_generation_status="failed",
            decisions_regenerated=False,
            failure=_failed_backend_result(
                backend_name,
                f"parameter_decision_audit_failed: {'; '.join(audit.violations)}",
            ),
        )
    readiness_violations = check_validation_readiness(scenario_decisions, readiness)
    if readiness_violations:
        return _ScenarioDecisionOutcome(
            decisions=[],
            decision_generation_status="failed",
            decisions_regenerated=False,
            failure=_failed_backend_result(
                backend_name,
                f"parameter_decision_readiness_failed: {'; '.join(readiness_violations)}",
            ),
        )
    return _ScenarioDecisionOutcome(
        decisions=scenario_decisions,
        decision_generation_status="regenerated",
        decisions_regenerated=True,
    )


def _write_scenario_decision_records(
    *,
    result_dir: Path,
    scenario_id: str,
    decisions: list[StrategyDecision],
) -> tuple[str, str]:
    artifact_name = f"backend_runs/decision_records/{_safe_scenario_artifact_path(scenario_id)}.jsonl"
    path = write_text_artifact(result_dir, artifact_name, canonical_jsonl_lines(decisions))
    return path.relative_to(result_dir).as_posix(), file_sha256(path)


def _safe_scenario_artifact_path(scenario_id: str) -> str:
    safe_parts = [
        "".join(char if char.isalnum() or char in "_.-" else "-" for char in part).strip(".")
        for part in scenario_id.split("/")
    ]
    safe_parts = [part or "scenario" for part in safe_parts]
    return "/".join(safe_parts)


def _backend_name(backend: ValidationBackend, fallback: str) -> str:
    name = getattr(backend, "name", fallback)
    return str(name) if name else fallback


def _failed_backend_result(backend_name: str, warning: str) -> BackendRunResult:
    return BackendRunResult(
        backend=backend_name,
        status="failed",
        metrics={},
        warnings=(warning,),
        unsupported_semantics=(),
    )


def _write_static_validation_artifacts(*, result_dir: Path, config: Any, config_path: Path) -> None:
    try:
        validation_config = config_path.read_text()
    except OSError as exc:
        validation_config = f"# validation config snapshot unavailable: {exc}\n"
    write_text_artifact(result_dir, "validation_config.toml", validation_config)

    try:
        strategy_snapshot = Path(config.strategy_path).read_text()
    except OSError as exc:
        strategy_snapshot = f"# strategy snapshot unavailable: {exc}\n"
    write_text_artifact(result_dir, "strategy_snapshot.py", strategy_snapshot)
    write_json_artifact(result_dir, "decision_schema.json", StrategyDecision.model_json_schema())


def _write_validation_artifacts(
    *,
    result_dir: Path,
    repo_root: Path,
    path_base: Path,
    config: Any,
    config_path: Path,
    backend_name: str,
    decisions: list[StrategyDecision],
    data_audits: list[dict[str, Any]],
    data_provenance: list[dict[str, Any]],
    backend_results: list[ScenarioBackendRunResult],
    decision: ValidationPolicyDecision,
    failure_details: list[dict[str, str]] | None = None,
) -> None:
    failure_details = failure_details or []
    capability_matrix = backend_capability_matrix(backend_name, backend_results)
    write_text_artifact(result_dir, "decision_records.jsonl", canonical_jsonl_lines(decisions))
    write_json_artifact(result_dir, "data_audit.json", {"windows": data_audits})
    write_json_artifact(
        result_dir,
        "backend_runs/summary.json",
        {
            "metric_semantics": backend_metric_semantics(),
            "results": [
                {
                    "window_id": item.window_id,
                    "scenario_id": item.scenario_id,
                    "scenario_kind": item.scenario_kind,
                    "required": item.required,
                    "diagnostic_only": item.diagnostic_only,
                    "decisions_regenerated": item.decisions_regenerated,
                    "decision_generation_status": item.decision_generation_status,
                    "decision_count": item.decision_count,
                    "decision_records_path": item.decision_records_path,
                    "decision_records_sha256": item.decision_records_sha256,
                    "result": item.result.model_dump(mode="json"),
                }
                for item in backend_results
            ]
        },
    )
    write_json_artifact(
        result_dir,
        "robustness_matrix.json",
        {
            "decision": decision.model_dump(mode="json"),
            "scenarios": [
                {
                    "window_id": item.window_id,
                    "scenario_id": item.scenario_id,
                    "scenario_kind": item.scenario_kind,
                    "required": item.required,
                    "diagnostic_only": item.diagnostic_only,
                    "decisions_regenerated": item.decisions_regenerated,
                    "decision_generation_status": item.decision_generation_status,
                    "decision_count": item.decision_count,
                    "decision_records_path": item.decision_records_path,
                    "decision_records_sha256": item.decision_records_sha256,
                    "backend": item.result.backend,
                    "status": item.result.status,
                    "metrics": item.result.metrics,
                    "warnings": item.result.warnings,
                    "unsupported_semantics": item.result.unsupported_semantics,
                    "classification_reasons": _scenario_classification_reasons(item),
                }
                for item in backend_results
            ],
            "failure_details": failure_details,
        },
    )
    write_json_artifact(result_dir, "backend_capability_matrix.json", capability_matrix)
    decision_payload = decision.model_dump(mode="json")
    decision_payload["failure_details"] = failure_details
    write_json_artifact(result_dir, "validation_decision.json", decision_payload)
    failed_gates = ", ".join(decision.failed_gates) or "none"
    passed_gates = ", ".join(decision.passed_gates) or "none"
    reasons = ", ".join(decision.reasons) or "none"
    gate_details = "\n".join(
        f"- {name}: {detail}" for name, detail in sorted(decision.gate_details.items())
    )
    if not gate_details:
        gate_details = "- none"
    write_text_artifact(
        result_dir,
        "validation_report.md",
        (
            "# Validation Report\n\n"
            f"Decision: `{decision.decision}`\n\n"
            f"Reasons: {reasons}\n\n"
            f"Passed gates: {passed_gates}\n\n"
            f"Failed gates: {failed_gates}\n\n"
            f"Gate details:\n{gate_details}\n"
        ),
    )
    write_validation_manifest(
        result_dir,
        repo_root=repo_root,
        path_base=path_base,
        config=config,
        config_path=config_path,
        backend_name=backend_name,
        data_provenance=data_provenance,
        backend_results=backend_results,
        capability_matrix=capability_matrix,
    )


def _scenario_classification_reasons(item: ScenarioBackendRunResult) -> tuple[str, ...]:
    result = item.result
    if result.status == "failed":
        return (f"{result.backend}_failed",)
    if result.status == "unavailable":
        return ("backend_unavailable",)
    if result.status == "unsupported" or result.unsupported_semantics:
        return ("unsupported_semantics",)
    return ()
