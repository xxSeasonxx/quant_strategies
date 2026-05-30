from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field as _field
from pathlib import Path
from typing import TYPE_CHECKING as _TYPE_CHECKING, Any

from quant_strategies.causality import check_hidden_lookahead
from quant_strategies.data_contract import NormalizedRows, RowContractMode
from quant_strategies.decisions import StrategyDecision
from quant_strategies.provenance import file_sha256, text_sha256
from quant_strategies.runner.artifact_profiles import (
    canonical_rows_jsonl,
    normalized_rows_sha256,
)
from quant_strategies.core.config import default_repo_root
from quant_strategies.runner.execution import (
    StrategyExecutionError,
    execute_strategy_run,
)
from quant_strategies.validation.artifacts import (
    backend_runs_payload,
    canonical_jsonl_lines,
    create_validation_result_dir,
    robustness_matrix_payload,
    write_json_artifact,
    write_text_artifact,
)
from quant_strategies.validation.backends import (
    BackendRunResult,
    DecisionGenerationStatus,
    ScenarioBackendRunResult,
    ValidationBackend,
    get_backend,
)
from quant_strategies.validation.config import ScenarioRunConfig
from quant_strategies.validation.config import load_validation_config
from quant_strategies.validation.config import resolve_validation_config_path
from quant_strategies.validation.data_audit import audit_decision_rows
from quant_strategies.validation.events import ValidationEventSink, ValidationStageEmitter
from quant_strategies.validation.manifest import write_validation_manifest
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
    result_dir: Path | None
    decision: ValidationPolicyDecision
    message: str
    run_completed: bool = True
    failure_stage: str | None = None


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
    row_contract_mode: RowContractMode
    event_emitter: ValidationStageEmitter


@dataclass
class _ValidationState:
    all_decisions: list[StrategyDecision] = _field(default_factory=list)
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
    backend: ValidationBackend | None = None,
    event_sink: ValidationEventSink | None = None,
) -> ValidationRunResult:
    events = ValidationStageEmitter(event_sink)
    with events.stage(
        "config_load",
        config_path=str(config_path),
        repo_root=str(repo_root) if repo_root is not None else None,
    ):
        root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
        resolved_config_path = resolve_validation_config_path(config_path, repo_root=repo_root)
        config = load_validation_config(resolved_config_path)
        path_base = config.base_dir

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
            decision=_hard_no_decision("artifact_initialization_failed"),
            message=f"artifact initialization failed: {exc}",
            run_completed=False,
            failure_stage="artifact_initialization",
        )

    state = _ValidationState()
    backend_name = config.verdict_source

    try:
        with events.stage("backend_selection", backend=config.verdict_source):
            selected_backend = backend or get_backend(config.verdict_source)
            backend_name = _backend_name(selected_backend, config.verdict_source)
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
            failure_stage="backend_selection",
            failure_details=[_failure_detail("backend_selection", exc)],
            event_emitter=events,
        )

    # Validation always uses the validation row contract; strict replay is always
    # on (Phase 1) and paper_readiness governs only the readiness gates.
    row_contract_mode = RowContractMode.VALIDATION
    context = _ValidationContext(
        repo_root=root,
        path_base=path_base,
        config=config,
        config_path=resolved_config_path,
        result_dir=result_dir,
        backend_name=backend_name,
        selected_backend=selected_backend,
        row_contract_mode=row_contract_mode,
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
            row_contract_mode=context.row_contract_mode.value,
        ):
            execution = execute_strategy_run(
                execution_spec,
                repo_root=context.path_base,
                row_contract_mode=context.row_contract_mode,
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
    audit_payload = _audit_window_execution(context, state, window, execution)
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
    execution: _StrategyExecutionResult,
) -> dict[str, Any]:
    strategy_rows = execution.normalized_rows
    decisions = execution.decisions
    try:
        with context.event_emitter.stage(
            "data_audit",
            strategy_id=context.config.strategy_id,
            window_id=window.id,
            row_contract_mode=context.row_contract_mode.value,
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
            mode="strict",
            decision_count=len(decisions),
        ) as causality_event:
            # Strict suppression-replay is always on: boundaries auto-derive from the
            # row grid so a peek-to-suppress strategy is caught on the default path,
            # not only when paper_readiness is enabled.
            lookahead = check_hidden_lookahead(
                execution.generate_decisions,
                rows=execution.normalized_rows,
                params=execution.frozen_params,
                baseline_decisions=decisions,
                strategy_id=context.config.strategy_id,
            )
            causality_violations = _validation_causality_violations(lookahead)
            if causality_violations:
                causality_event.fail(
                    _event_failure_message(causality_violations, "hidden_lookahead_check_failed")
                )
        audit_payload.update(_lookahead_audit_payload(lookahead))
        if causality_violations:
            reason = _causality_failure_reason(causality_violations)
            state.failure_reasons.append(reason)
            if state.failure_stage is None:
                state.failure_stage = "data_audit"
            audit_payload["passed"] = False
            audit_payload["violations"] = list(audit.violations) + list(causality_violations)

    if audit_payload["passed"]:
        readiness_violations = check_validation_readiness(decisions, context.config.readiness)
        if readiness_violations:
            state.failure_reasons.append("validation_readiness_failed")
            if state.failure_stage is None:
                state.failure_stage = "validation_readiness"
            audit_payload["passed"] = False
            audit_payload["violations"] = list(audit.violations) + list(readiness_violations)
    return audit_payload


def _validation_causality_violations(lookahead: Any) -> tuple[str, ...]:
    violations = list(lookahead.violations)
    if lookahead.passed and not lookahead.deterministic_replay_verified:
        violations.append("determinism_replay_not_verified")
    if lookahead.passed and not lookahead.emitted_replay_verified:
        violations.append("emitted_replay_not_verified")
    if lookahead.passed and not lookahead.strict_suppression_verified:
        violations.append("strict_suppression_replay_not_verified")
    return tuple(dict.fromkeys(violations))


def _lookahead_audit_payload(lookahead: Any) -> dict[str, Any]:
    return {
        "deterministic_replay_verified": lookahead.deterministic_replay_verified,
        "emitted_replay_verified": lookahead.emitted_replay_verified,
        "strict_suppression_verified": lookahead.strict_suppression_verified,
        "skipped_probe_count": lookahead.skipped_probe_count,
        "skipped_probe_reasons": list(lookahead.skipped_probe_reasons),
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
        base_params=_plain_mapping(execution.validated_params),
        base_costs=_plain_mapping(context.config.cost_model),
        base_fill=_plain_mapping(context.config.fill_model),
    )
    state.required_scenario_ids.extend(scenario.id for scenario in scenarios if scenario.required)
    for scenario in scenarios:
        scenario_result = _run_scenario_backend(context, window, execution_spec, execution, scenario)
        state.backend_results.append(scenario_result)
        _record_agreement_failure(state, scenario_result)


def _record_agreement_failure(
    state: _ValidationState,
    scenario_result: ScenarioBackendRunResult,
) -> None:
    agreement = scenario_result.agreement
    if agreement is None or agreement.status != "fail":
        return
    state.failure_reasons.append(
        "backend_agreement_failed:"
        f"scenario={scenario_result.scenario_id}:"
        f"engine_return={agreement.engine_return}:"
        f"vbt_return={agreement.vbt_return}:"
        f"abs_dev={agreement.abs_deviation}:"
        f"tol_abs={agreement.tolerance_abs}:tol_rel={agreement.tolerance_rel}"
    )
    if state.failure_stage is None:
        state.failure_stage = "agreement_oracle"


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
        base_params=execution.validated_params,
        data=execution_spec.data,
    )
    decision_outcome = _scenario_decision_outcome(
        base_decisions=execution.decisions,
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
            with context.event_emitter.stage(
                "scenario_backend",
                strategy_id=context.config.strategy_id,
                window_id=window.id,
                scenario_id=scenario.id,
                backend=context.backend_name,
            ):
                raw_backend_result = context.selected_backend.run(
                    decisions=list(decision_outcome.decisions),
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
    if backend_result is not None and backend_result.trades:
        trade_ledger_path, trade_ledger_sha256 = _write_scenario_trade_ledger(
            result_dir=context.result_dir,
            scenario_id=scenario.id,
            trades=backend_result.trades,
        )
    agreement = _run_agreement_oracle(
        context, scenario_config, decision_outcome, execution, backend_result
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
        trade_ledger_path=trade_ledger_path,
        trade_ledger_sha256=trade_ledger_sha256,
        agreement=agreement,
    )


def _run_agreement_oracle(
    context: _ValidationContext,
    scenario_config: ScenarioRunConfig,
    decision_outcome: _ScenarioDecisionOutcome,
    execution: _StrategyExecutionResult,
    backend_result: BackendRunResult,
):
    """Opt-in cross-check of the engine verdict against VectorBT Pro.

    Off by default. Runs only when the backend completed, reusing the verdict's
    already-computed metrics (no re-screen). A divergence becomes a hard_no via
    state.failure_reasons (see _record_agreement_failure). Any oracle error is
    recorded as inconclusive and never crashes the run.
    """
    oracle = context.config.agreement_oracle
    if not oracle.enabled or backend_result.status != "completed":
        return None

    from quant_strategies.validation.agreement import AgreementResult, evaluate_agreement

    try:
        return evaluate_agreement(
            engine_metrics=backend_result.metrics,
            decisions=list(decision_outcome.decisions),
            rows=execution.normalized_rows.projection_rows(),
            config=scenario_config,
            tolerance_abs=oracle.tolerance_abs,
            tolerance_rel=oracle.tolerance_rel,
        )
    except Exception as exc:  # never let the cross-check crash the verdict
        return AgreementResult(status="inconclusive", note=f"agreement_oracle_error:{exc}")


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
    if not data_passed and state.failure_stage is None:
        state.failure_stage = "data_audit"
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
    failure_stage: str,
    failure_details: list[dict[str, str]] | None = None,
    event_emitter: ValidationStageEmitter | None = None,
) -> ValidationRunResult:
    decision = _hard_no_decision(
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
        # its original failure_stage rather than raising to the caller (every hard_no
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
            "strict": execution_spec.data.strict,
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
            None
            if normalized_rows is None
            else normalized_rows.row_contract_summary()
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
    base_decisions: list[StrategyDecision],
) -> _ScenarioDecisionOutcome:
    return _ScenarioDecisionOutcome(
        decisions=list(base_decisions),
        decision_generation_status="base_reused",
        decisions_regenerated=False,
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
    artifact_name = f"backend_runs/{subdir}/{_safe_scenario_artifact_path(scenario_id)}.jsonl"
    path = write_text_artifact(result_dir, artifact_name, canonical_jsonl_lines(list(records)))
    return path.relative_to(result_dir).as_posix(), file_sha256(path)


def _write_scenario_decision_records(
    *,
    result_dir: Path,
    scenario_id: str,
    decisions: list[StrategyDecision],
) -> tuple[str, str]:
    return _write_scenario_jsonl(
        result_dir=result_dir, subdir="decision_records", scenario_id=scenario_id, records=decisions
    )


def _write_scenario_trade_ledger(
    *,
    result_dir: Path,
    scenario_id: str,
    trades: Sequence[Any],
) -> tuple[str, str]:
    # Per-scenario engine trade ledger: net_return is recomputable as sum(trade.net_return).
    return _write_scenario_jsonl(
        result_dir=result_dir, subdir="trade_ledgers", scenario_id=scenario_id, records=trades
    )


def _write_window_rows(
    *,
    result_dir: Path,
    window_id: str,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[str, str]:
    artifact_name = f"data_rows/{_safe_scenario_artifact_path(window_id)}.jsonl"
    payload = canonical_rows_jsonl(rows)
    path = write_text_artifact(result_dir, artifact_name, payload)
    written_payload = payload if payload.endswith("\n") else f"{payload}\n"
    return path.relative_to(result_dir).as_posix(), text_sha256(written_payload)


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
            "robustness_matrix.json",
            robustness_matrix_payload(
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

