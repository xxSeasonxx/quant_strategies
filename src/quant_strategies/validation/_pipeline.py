from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from dataclasses import field as _field
from pathlib import Path
from typing import TYPE_CHECKING as _TYPE_CHECKING
from typing import Any

from quant_strategies.causality import (
    causality_completeness_violations,
    check_bounded_causality,
    check_hidden_lookahead,
)
from quant_strategies.core.config import default_repo_root
from quant_strategies.core.data_audit import audit_decision_rows
from quant_strategies.core.execution import (
    StrategyExecutionError,
    execute_strategy_run,
)
from quant_strategies.core.portfolio_foundation import RoundTrip
from quant_strategies.core.serialization import canonical_rows_jsonl, normalized_rows_sha256
from quant_strategies.data_contract import NormalizedRows
from quant_strategies.decisions import TargetDecision
from quant_strategies.provenance import file_sha256, text_sha256
from quant_strategies.validation.artifact_names import safe_scenario_artifact_path
from quant_strategies.validation.artifacts import (
    backend_runs_payload,
    canonical_jsonl_lines,
    cost_fill_sensitivity_payload,
    create_validation_result_dir,
    write_json_artifact,
    write_text_artifact,
)
from quant_strategies.validation.backends import (
    BackendRunResult,
    ScenarioBackendRunResult,
    ValidationBackend,
)
from quant_strategies.validation.config import (
    ScenarioRunConfig,
    load_validation_config,
    resolve_validation_config_path,
)
from quant_strategies.validation.engine_backend import SpineBackend
from quant_strategies.validation.errors import ValidationConfigError
from quant_strategies.validation.events import ValidationEventSink, ValidationStageEmitter
from quant_strategies.validation.manifest import write_validation_manifest
from quant_strategies.validation.matrix import MatrixScenario, expand_validation_matrix
from quant_strategies.validation.policy import (
    ValidationPolicyDecision,
    classify_validation,
    overfit_controls_from_search_pressure,
)
from quant_strategies.validation.readiness import check_validation_readiness
from quant_strategies.validation.results import ValidationRunResult

if _TYPE_CHECKING:
    from quant_strategies.core.execution import StrategyExecutionResult as _StrategyExecutionResult


@dataclass(frozen=True)
class _ValidationContext:
    repo_root: Path
    path_base: Path
    config: Any
    config_path: Path
    result_dir: Path
    backend_name: str
    selected_backend: ValidationBackend
    event_emitter: ValidationStageEmitter


@dataclass
class _ValidationState:
    all_decisions: list[TargetDecision] = _field(default_factory=list)
    backend_results: list[ScenarioBackendRunResult] = _field(default_factory=list)
    data_audits: list[dict[str, Any]] = _field(default_factory=list)
    data_provenance: list[dict[str, Any]] = _field(default_factory=list)
    failure_reasons: list[str] = _field(default_factory=list)
    required_scenario_ids: list[str] = _field(default_factory=list)
    failure_stage: str | None = None


_MIN_VALIDATION_TRADES = 10


def run_validation(
    config_path: str | Path,
    *,
    repo_root: Path | None = None,
    event_sink: ValidationEventSink | None = None,
) -> ValidationRunResult:
    return _run_validation(
        config_path,
        repo_root=repo_root,
        event_sink=event_sink,
    )


def _run_validation(
    config_path: str | Path,
    *,
    repo_root: Path | None = None,
    backend: ValidationBackend | None = None,
    event_sink: ValidationEventSink | None = None,
) -> ValidationRunResult:
    events = ValidationStageEmitter(event_sink)
    try:
        with events.stage(
            "config_load",
            config_path=str(config_path),
            repo_root=str(repo_root) if repo_root is not None else None,
        ):
            root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
            resolved_config_path = resolve_validation_config_path(config_path, repo_root=repo_root)
            config = load_validation_config(resolved_config_path)
            path_base = config.base_dir
    except ValidationConfigError as exc:
        return ValidationRunResult(
            result_dir=None,
            decision=_mechanical_fail_decision("validation_config_failed"),
            message=str(exc),
            run_completed=False,
            failure_stage="config_load",
        )

    try:
        with events.stage("artifact_initialization", strategy_id=config.strategy_id):
            result_dir = create_validation_result_dir(config.output.results_dir, config.strategy_id)
            _write_static_validation_artifacts(
                result_dir=result_dir,
                config=config,
                config_path=resolved_config_path,
            )
    except OSError as exc:
        # The result dir/static artifacts could not be written; there is no dir to
        # write a failure manifest into, so return a structured result directly
        # instead of letting a raw filesystem error escape to the caller/CLI.
        return ValidationRunResult(
            result_dir=None,
            decision=_mechanical_fail_decision("artifact_initialization_failed"),
            message=f"artifact initialization failed: {exc}",
            run_completed=False,
            failure_stage="artifact_initialization",
        )

    state = _ValidationState()
    with events.stage("backend_selection", backend=config.verdict_source):
        selected_backend = backend if backend is not None else SpineBackend()
        backend_name = str(selected_backend.name)

    # Strict replay is always on (Phase 1); mechanical_thresholds governs only the
    # mechanical gates.
    context = _ValidationContext(
        repo_root=root,
        path_base=path_base,
        config=config,
        config_path=resolved_config_path,
        result_dir=result_dir,
        backend_name=backend_name,
        selected_backend=selected_backend,
        event_emitter=events,
    )
    for window in config.windows:
        terminal_result = _run_validation_window(context, state, window)
        if terminal_result is not None:
            return terminal_result

    with events.stage("policy_classification", strategy_id=config.strategy_id):
        decision = _classify_validation_state(context, state)
    try:
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
            event_emitter=events,
        )
    except OSError as exc:
        # Verdict was computed but its artifacts could not be persisted. Surface the
        # computed decision with an artifact_write failure rather than re-routing
        # through _failure_result (which would attempt the same write again).
        return ValidationRunResult(
            result_dir=result_dir,
            decision=decision,
            message=f"validation decision: {decision.decision}; artifact write failed: {exc}",
            run_completed=False,
            failure_stage="artifact_write",
        )
    return _validation_result(result_dir, decision, failure_stage=state.failure_stage)


def _run_validation_window(
    context: _ValidationContext,
    state: _ValidationState,
    window: Any,
) -> ValidationRunResult | None:
    execution_spec = context.config.to_execution_spec(window)
    try:
        with context.event_emitter.stage(
            "window_execution",
            strategy_id=context.config.strategy_id,
            window_id=window.id,
        ):
            execution = execute_strategy_run(
                execution_spec,
                repo_root=context.path_base,
            )
    except StrategyExecutionError as exc:
        return _handle_window_execution_error(context, state, window, execution_spec, exc)

    rows_path, rows_hash = _write_window_rows(
        result_dir=context.result_dir,
        window_id=window.id,
        rows=execution.loaded_rows,
    )
    state.data_provenance.append(
        _data_provenance(
            window.id,
            execution_spec,
            status="loaded",
            rows=execution.loaded_rows,
            rows_path=rows_path,
            rows_hash=rows_hash,
            normalized_rows=execution.normalized_rows,
        )
    )
    state.all_decisions.extend(execution.decisions)
    audit_payload = _audit_window_execution(context, state, window, execution_spec, execution)
    state.data_audits.append(audit_payload)
    if audit_payload["passed"]:
        _run_window_scenarios(context, state, window, execution_spec, execution)
    return None


def _handle_window_execution_error(
    context: _ValidationContext,
    state: _ValidationState,
    window: Any,
    execution_spec: Any,
    exc: StrategyExecutionError,
) -> ValidationRunResult | None:
    if exc.stage == "strategy_import":
        return _failure_result_from_state(
            context,
            state,
            reason="strategy_import_failed",
            failure_stage="strategy_import",
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
            failure_stage="param_validation",
            failure_details=[_execution_failure_detail("param_validation", exc)],
        )
    if exc.stage == "data_load":
        if state.failure_stage is None:
            state.failure_stage = "data_load"
        state.data_provenance.append(
            _data_provenance(
                window.id,
                execution_spec,
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
        if state.failure_stage is None:
            state.failure_stage = "decision_generation"
        if exc.loaded_rows is not None:
            rows_path, rows_hash = _write_window_rows(
                result_dir=context.result_dir,
                window_id=window.id,
                rows=exc.loaded_rows,
            )
            state.data_provenance.append(
                _data_provenance(
                    window.id,
                    execution_spec,
                    status="loaded",
                    rows=exc.loaded_rows,
                    rows_path=rows_path,
                    rows_hash=rows_hash,
                    normalized_rows=exc.normalized_rows,
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
    execution_spec: Any,
    execution: _StrategyExecutionResult,
) -> dict[str, Any]:
    strategy_rows = execution.normalized_rows
    decisions = execution.decisions
    try:
        with context.event_emitter.stage(
            "data_audit",
            strategy_id=context.config.strategy_id,
            window_id=window.id,
            decision_count=len(decisions),
        ) as audit_event:
            audit = audit_decision_rows(strategy_rows, decisions)
            if not audit.passed:
                audit_event.fail(_event_failure_message(audit.violations, "data_audit_failed"))
    except Exception as exc:
        state.failure_reasons.append("data_audit_failed")
        if state.failure_stage is None:
            state.failure_stage = "data_audit"
        return _failed_data_audit(
            window.id,
            row_count=len(execution.loaded_rows),
            decision_count=len(decisions),
            violations=(f"data_audit_failed: {exc}",),
        )

    audit_payload = {"window_id": window.id, **audit.model_dump(mode="json")}
    if audit.passed:
        with context.event_emitter.stage(
            "causality_check",
            strategy_id=context.config.strategy_id,
            window_id=window.id,
            mode=context.config.causality_replay.scope,
            decision_count=len(decisions),
        ) as causality_event:
            # Strict suppression-replay is always on: boundaries auto-derive from the
            # row grid so a peek-to-suppress strategy is caught on the default path,
            # not only when mechanical_thresholds is enabled.
            lookahead = _run_configured_causality_replay(
                context,
                execution,
                decisions,
            )
            causality_violations = _configured_causality_violations(
                context.config.causality_replay.scope,
                lookahead,
            )
            if causality_violations:
                causality_event.fail(
                    _event_failure_message(causality_violations, "hidden_lookahead_check_failed")
                )
            audit_payload.update(
                _lookahead_audit_payload(
                    lookahead,
                    replay_scope=context.config.causality_replay.scope,
                )
            )
        if causality_violations:
            reason = _causality_failure_reason(causality_violations)
            state.failure_reasons.append(reason)
            if state.failure_stage is None:
                state.failure_stage = "data_audit"
            audit_payload["passed"] = False
            audit_payload["violations"] = list(audit.violations) + list(causality_violations)

    if audit_payload["passed"]:
        readiness_violations = check_validation_readiness(
            decisions,
            context.config.readiness,
            data_kind=context.config.data.kind,
        )
        if readiness_violations:
            state.failure_reasons.append("validation_readiness_failed")
            if state.failure_stage is None:
                state.failure_stage = "validation_readiness"
            audit_payload["passed"] = False
            audit_payload["violations"] = list(audit.violations) + list(readiness_violations)
    return audit_payload


def _run_configured_causality_replay(
    context: _ValidationContext,
    execution: _StrategyExecutionResult,
    decisions: list[Any],
) -> Any:
    if context.config.causality_replay.scope == "bounded":
        return check_bounded_causality(
            execution.generate_decisions,
            rows=execution.normalized_rows,
            params=execution.frozen_params,
            baseline_decisions=decisions,
            strategy_id=context.config.strategy_id,
            max_probes=context.config.causality_replay.probe_limit,
            timeout_seconds=context.config.causality_replay.timeout_seconds,
        )
    return check_hidden_lookahead(
        execution.generate_decisions,
        rows=execution.normalized_rows,
        params=execution.frozen_params,
        baseline_decisions=decisions,
        strategy_id=context.config.strategy_id,
    )


def _configured_causality_violations(scope: str, lookahead: Any) -> tuple[str, ...]:
    if scope == "bounded":
        violations = list(lookahead.violations)
        if lookahead.skipped_probe_reasons:
            violations.append(f"bounded_probe_skipped: {lookahead.skipped_probe_reasons[0]}")
        return tuple(dict.fromkeys(violations))
    return causality_completeness_violations(lookahead)


def _lookahead_audit_payload(lookahead: Any, *, replay_scope: str) -> dict[str, Any]:
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


def _causality_failure_reason(violations: Sequence[str]) -> str:
    ordered_reasons = (
        "strategy_generation_not_deterministic",
        "strict_suppression_replay_not_verified",
        "hidden_lookahead_suppression_detected",
        "hidden_lookahead_detected",
    )
    for reason in ordered_reasons:
        if reason in violations:
            return reason
    if any(item.startswith("determinism_check_failed") for item in violations):
        return "determinism_check_failed"
    if any(item.startswith("hidden_lookahead_check_failed") for item in violations):
        return "hidden_lookahead_check_failed"
    return violations[0] if violations else "causality_check_failed"


def _run_window_scenarios(
    context: _ValidationContext,
    state: _ValidationState,
    window: Any,
    execution_spec: Any,
    execution: _StrategyExecutionResult,
) -> None:
    scenarios = expand_validation_matrix(
        window_id=window.id,
        base_costs=_plain_mapping(context.config.cost_model),
        base_fill=_plain_mapping(context.config.fill_model),
    )
    state.required_scenario_ids.extend(scenario.id for scenario in scenarios if scenario.required)
    for scenario in scenarios:
        scenario_result = _run_scenario_backend(
            context, window, execution_spec, execution, scenario
        )
        state.backend_results.append(scenario_result)


def _run_scenario_backend(
    context: _ValidationContext,
    window: Any,
    execution_spec: Any,
    execution: _StrategyExecutionResult,
    scenario: MatrixScenario,
) -> ScenarioBackendRunResult:
    scenario_config = _scenario_config(
        config=context.config,
        scenario=scenario,
        data=execution_spec.data,
    )
    scenario_decisions = list(execution.decisions)
    decision_records_path, decision_records_sha256 = _write_scenario_decision_records(
        result_dir=context.result_dir,
        scenario_id=scenario.id,
        decisions=scenario_decisions,
    )
    try:
        with context.event_emitter.stage(
            "scenario_backend",
            strategy_id=context.config.strategy_id,
            window_id=window.id,
            scenario_id=scenario.id,
            backend=context.backend_name,
        ):
            raw_backend_result = context.selected_backend.run(
                decisions=list(scenario_decisions),
                rows=execution.normalized_rows.projection_rows(),
                config=scenario_config,
            )
    except Exception as exc:
        backend_result = _failed_backend_result(
            context.backend_name,
            f"backend_exception: {exc}",
        )
    else:
        if isinstance(raw_backend_result, BackendRunResult):
            backend_result = raw_backend_result
        else:
            backend_result = _failed_backend_result(
                context.backend_name,
                "invalid_backend_result: expected BackendRunResult, "
                f"got {type(raw_backend_result).__name__}",
            )
    trade_ledger_path = None
    trade_ledger_sha256 = None
    if backend_result.round_trips:
        trade_ledger_path, trade_ledger_sha256 = _write_scenario_trade_ledger(
            result_dir=context.result_dir,
            scenario_id=scenario.id,
            round_trips=backend_result.round_trips,
        )
    return ScenarioBackendRunResult(
        window_id=window.id,
        scenario_id=scenario.id,
        required=scenario.required,
        result=backend_result,
        scenario_kind=scenario.kind,
        scoreability_bearing=scenario.scoreability_bearing,
        diagnostic_only=not scenario.scoreability_bearing,
        decision_count=len(scenario_decisions),
        decision_records_path=decision_records_path,
        decision_records_sha256=decision_records_sha256,
        trade_ledger_path=trade_ledger_path,
        trade_ledger_sha256=trade_ledger_sha256,
    )


def _classify_validation_state(
    context: _ValidationContext,
    state: _ValidationState,
) -> ValidationPolicyDecision:
    data_passed = all(audit["passed"] for audit in state.data_audits)
    if state.failure_reasons:
        return _mechanical_fail_decision(
            state.failure_reasons,
            search_pressure=context.config.search_pressure,
        )
    if not data_passed and state.failure_stage is None:
        state.failure_stage = "data_audit"
    return classify_validation(
        data_passed=data_passed,
        backend_results=state.backend_results,
        min_trades=_MIN_VALIDATION_TRADES,
        required_scenario_ids=tuple(state.required_scenario_ids),
        mechanical_thresholds=context.config.mechanical_thresholds,
        search_pressure=context.config.search_pressure,
    )


def _failure_result_from_state(
    context: _ValidationContext,
    state: _ValidationState,
    *,
    reason: str,
    failure_stage: str,
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
        failure_stage=failure_stage,
        failure_details=failure_details,
        event_emitter=context.event_emitter,
    )


def _validation_result(
    result_dir: Path,
    decision: ValidationPolicyDecision,
    *,
    failure_stage: str | None,
) -> ValidationRunResult:
    return ValidationRunResult(
        result_dir=result_dir,
        decision=decision,
        message=f"validation decision: {decision.decision}",
        run_completed=True,
        failure_stage=failure_stage,
    )


def _mechanical_fail_decision(
    reasons: str | Sequence[str],
    *,
    search_pressure: object | None = None,
) -> ValidationPolicyDecision:
    reason_tuple = (reasons,) if isinstance(reasons, str) else tuple(dict.fromkeys(reasons))
    return ValidationPolicyDecision(
        decision="mechanical_fail",
        reasons=reason_tuple,
        failed_gates=reason_tuple,
        gate_details=dict.fromkeys(reason_tuple, "failed"),
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
    decisions: list[TargetDecision],
    data_audits: list[dict[str, Any]],
    data_provenance: list[dict[str, Any]],
    backend_results: list[ScenarioBackendRunResult],
    reason: str,
    failure_stage: str,
    failure_details: list[dict[str, str]] | None = None,
    event_emitter: ValidationStageEmitter | None = None,
) -> ValidationRunResult:
    decision = _mechanical_fail_decision(
        reason,
        search_pressure=getattr(config, "search_pressure", None),
    )
    try:
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
            event_emitter=event_emitter,
        )
    except OSError:
        # Artifacts could not be persisted; still return the structured verdict with
        # its original failure_stage rather than raising to the caller (every mechanical_fail
        # path routes through here, including API consumers with no CLI backstop).
        pass
    return _validation_result(result_dir, decision, failure_stage=failure_stage)


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
    execution_spec: Any,
    *,
    status: str,
    rows: Sequence[Mapping[str, Any]] | None,
    rows_path: str | None = None,
    rows_hash: str | None = None,
    normalized_rows: NormalizedRows | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    row_count = 0 if rows is None else len(rows)
    payload = {
        "window_id": window_id,
        "status": status,
        "data": {
            "kind": execution_spec.data.kind,
            "dataset": execution_spec.data.dataset,
            "symbols": list(execution_spec.data.symbols),
            "start": execution_spec.data.start.isoformat(),
            "end": execution_spec.data.end.isoformat(),
        },
        "row_count": row_count,
        "rows_path": None if rows is None else rows_path,
        "rows_sha256": (
            None
            if rows is None
            else rows_hash
            or (
                normalized_rows.normalized_rows_sha256
                if normalized_rows is not None
                else normalized_rows_sha256(rows)
            )
        ),
        "row_contract": (
            None if normalized_rows is None else normalized_rows.row_contract_summary()
        ),
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
    data: Any,
) -> ScenarioRunConfig:
    return ScenarioRunConfig.model_validate(
        {
            "scenario_id": scenario.id,
            "cost_model": {**_plain_mapping(config.cost_model), **scenario.cost_model},
            "fill_model": {**_plain_mapping(config.fill_model), **scenario.fill_model},
            "data": _plain_mapping(data),
            "capacity_model": _plain_mapping(config.capacity_model),
            "risk_budget": _plain_mapping(config.risk_budget),
            "leverage_budget": _plain_mapping(config.leverage_budget),
        }
    )


def _event_failure_message(violations: Sequence[str], fallback: str) -> str:
    return "; ".join(violations) if violations else fallback


def _write_scenario_jsonl(
    *,
    result_dir: Path,
    subdir: str,
    scenario_id: str,
    records: Sequence[Any],
) -> tuple[str, str]:
    # Single home for the per-scenario JSONL artifact path + hash contract.
    artifact_name = f"backend_runs/{subdir}/{safe_scenario_artifact_path(scenario_id)}.jsonl"
    path = write_text_artifact(result_dir, artifact_name, canonical_jsonl_lines(list(records)))
    return path.relative_to(result_dir).as_posix(), file_sha256(path)


def _write_scenario_decision_records(
    *,
    result_dir: Path,
    scenario_id: str,
    decisions: list[TargetDecision],
) -> tuple[str, str]:
    return _write_scenario_jsonl(
        result_dir=result_dir, subdir="decision_records", scenario_id=scenario_id, records=decisions
    )


def _write_scenario_trade_ledger(
    *,
    result_dir: Path,
    scenario_id: str,
    round_trips: Sequence[RoundTrip],
) -> tuple[str, str]:
    # Per-scenario netted-book round-trip ledger: the gated net_return is recomputable
    # as sum(round_trip.realized_pnl) / initial equity (design D4 reconciliation).
    records = [asdict(trip) for trip in round_trips]
    return _write_scenario_jsonl(
        result_dir=result_dir, subdir="trade_ledgers", scenario_id=scenario_id, records=records
    )


def _write_window_rows(
    *,
    result_dir: Path,
    window_id: str,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[str, str]:
    artifact_name = f"data_rows/{safe_scenario_artifact_path(window_id)}.jsonl"
    payload = canonical_rows_jsonl(rows)
    path = write_text_artifact(result_dir, artifact_name, payload)
    written_payload = payload if payload.endswith("\n") else f"{payload}\n"
    return path.relative_to(result_dir).as_posix(), text_sha256(written_payload)


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
    write_json_artifact(result_dir, "decision_schema.json", TargetDecision.model_json_schema())


def _write_validation_artifacts(
    *,
    result_dir: Path,
    repo_root: Path,
    path_base: Path,
    config: Any,
    config_path: Path,
    backend_name: str,
    decisions: list[TargetDecision],
    data_audits: list[dict[str, Any]],
    data_provenance: list[dict[str, Any]],
    backend_results: list[ScenarioBackendRunResult],
    decision: ValidationPolicyDecision,
    failure_details: list[dict[str, str]] | None = None,
    event_emitter: ValidationStageEmitter | None = None,
) -> None:
    emitter = event_emitter or ValidationStageEmitter()
    with emitter.stage("artifact_writes", strategy_id=config.strategy_id):
        failure_details = failure_details or []
        write_text_artifact(result_dir, "decision_records.jsonl", canonical_jsonl_lines(decisions))
        write_json_artifact(result_dir, "data_audit.json", {"windows": data_audits})
        write_json_artifact(
            result_dir,
            "backend_runs/summary.json",
            backend_runs_payload(backend_results),
        )
        write_json_artifact(
            result_dir,
            "cost_fill_sensitivity.json",
            cost_fill_sensitivity_payload(
                decision=decision,
                backend_results=backend_results,
                failure_details=failure_details,
            ),
        )
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
        )
