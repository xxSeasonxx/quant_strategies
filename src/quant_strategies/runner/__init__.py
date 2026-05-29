from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quant_strategies.causality import LookaheadCheckResult, check_hidden_lookahead
from quant_strategies.data_contract import NormalizedRows, RowContractMode
from quant_strategies.decisions import StrategyDecision
from quant_strategies.evidence_semantics import artifact_trust_tier_for_profile, runner_evidence_semantics
from quant_strategies.observation_dependencies import (
    audit_observation_dependencies,
    observation_row_index,
)
from quant_strategies.runner import (
    artifacts,
    config as config_module,
    data_readiness,
    engine_runner,
)
from quant_strategies.runner.artifact_profiles import write_summary_profile_artifact
from quant_strategies.runner.errors import RunnerError
from quant_strategies.runner.events import RunnerEventSink, RunnerStageEmitter
from quant_strategies.runner.execution import (
    StrategyExecutionError,
    StrategyExecutionResult,
    execute_strategy_run,
)


@dataclass(frozen=True)
class RunResult:
    result_dir: Path | None
    notes_path: Path | None
    message: str
    run_completed: bool = False
    failure_stage: str | None = None
    assessment_status: str = "runner_failed"
    promotion_eligible: bool = False
    param_contract: str = "validated"
    artifact_trust_tier: str | None = None
    data_availability_status: str | None = None
    availability_coverage: dict[str, object] | None = None
    row_contract: dict[str, object] | None = None
    causality_verified: bool = False
    emitted_replay_verified: bool = False
    strict_no_emission_verified: bool = False
    evidence_quality_warnings: tuple[str, ...] = ()


def run_config(
    config_path: str | Path,
    *,
    repo_root: Path | None = None,
    event_sink: RunnerEventSink | None = None,
) -> RunResult:
    effective_repo_root = Path(repo_root).resolve() if repo_root is not None else config_module.default_repo_root()
    events = RunnerStageEmitter(event_sink)
    try:
        with events.stage(
            "config_load",
            config_path=str(config_path),
            repo_root=str(effective_repo_root),
        ):
            config_file = config_module.resolve_config_path(config_path, repo_root=effective_repo_root)
            config = config_module.load_config(config_file, repo_root=effective_repo_root)
    except RunnerError as exc:
        return RunResult(
            result_dir=None,
            notes_path=None,
            message=str(exc),
            failure_stage="config_load",
        )

    try:
        with events.stage("artifact_initialization", strategy_id=config.strategy_id):
            result_dir = artifacts.create_result_dir(config)
            artifacts.initialize_run_artifacts(config_file, config, result_dir)
    except OSError as exc:
        return RunResult(
            result_dir=None,
            notes_path=None,
            message=f"artifact initialization failed: {exc}",
            failure_stage="artifact_initialization",
        )

    try:
        with events.stage("strategy_execution", strategy_id=config.strategy_id):
            execution = execute_strategy_run(
                config.to_execution_spec(),
                repo_root=effective_repo_root,
                row_contract_mode=_runner_row_contract_mode(config),
            )
    except StrategyExecutionError as exc:
        return _execution_failure_result(
            config,
            result_dir,
            exc,
            repo_root=effective_repo_root,
            event_emitter=events,
        )

    _write_strategy_input_rows_if_full(
        result_dir,
        config,
        execution.normalized_rows,
    )
    observation_failure = _audit_observation_dependencies(
        config,
        result_dir,
        execution,
        repo_root=effective_repo_root,
        event_emitter=events,
    )
    if observation_failure is not None:
        return observation_failure

    causality, evidence_quality = _prepare_causality_evidence(config, execution, events)
    _write_execution_data_manifest(
        result_dir,
        config,
        rows=execution.loaded_rows,
        normalized_rows=execution.normalized_rows,
        evidence_quality=evidence_quality,
    )
    if not causality.passed:
        return _failure_result(
            config,
            result_dir,
            "causality",
            _causality_message(causality),
            repo_root=effective_repo_root,
            evidence_quality=evidence_quality,
            event_emitter=events,
        )
    if config.output.artifact_profile == "full":
        artifacts.write_decision_records(result_dir, execution.decisions)

    request, failure = _prepare_engine_request(
        config,
        result_dir,
        execution,
        evidence_quality,
        repo_root=effective_repo_root,
        event_emitter=events,
    )
    if failure is not None:
        return failure

    engine_run, failure = _evaluate_engine_request(
        config,
        result_dir,
        request,
        evidence_quality,
        repo_root=effective_repo_root,
        event_emitter=events,
    )
    if failure is not None:
        return failure

    try:
        assessment_status, notes = _write_completion_artifacts(
            config,
            result_dir,
            execution,
            engine_run,
            evidence_quality,
            repo_root=effective_repo_root,
            event_emitter=events,
        )
    except OSError as exc:
        # Engine ran and the verdict is known, but completion artifacts could not be
        # written. Return a structured artifact_write failure instead of raising.
        return RunResult(
            result_dir=result_dir,
            notes_path=None,
            message=f"artifact write failed: {exc}",
            failure_stage="artifact_write",
        )
    return RunResult(
        result_dir=result_dir,
        notes_path=result_dir / "notes.md",
        message=notes.strip(),
        run_completed=True,
        failure_stage=None,
        assessment_status=assessment_status,
        promotion_eligible=False,
        param_contract=execution.param_contract,
        artifact_trust_tier=artifact_trust_tier_for_profile(config.output.artifact_profile),
        **artifacts.run_result_evidence_fields(evidence_quality),
    )


def _execution_failure_result(
    config: config_module.RunConfig,
    result_dir: Path,
    exc: StrategyExecutionError,
    *,
    repo_root: Path,
    event_emitter: RunnerStageEmitter,
) -> RunResult:
    if (
        exc.stage == "decision_generation"
        and exc.loaded_rows is not None
        and exc.normalized_rows is not None
    ):
        _write_strategy_input_rows_if_full(
            result_dir,
            config,
            exc.normalized_rows,
        )
        _write_execution_data_manifest(
            result_dir,
            config,
            rows=exc.loaded_rows,
            normalized_rows=exc.normalized_rows,
            evidence_quality=exc.evidence_quality,
        )
    return _failure_result(
        config,
        result_dir,
        exc.stage,
        str(exc),
        repo_root=repo_root,
        evidence_quality=exc.evidence_quality,
        event_emitter=event_emitter,
    )


def _runner_row_contract_mode(config: config_module.RunConfig) -> RowContractMode:
    # Strictness comes from the explicit `row_contract` policy, NOT from the
    # `artifact_profile` verbosity knob (a verbosity change must never flip pass/fail).
    return RowContractMode(config.row_contract)


def _write_strategy_input_rows_if_full(
    result_dir: Path,
    config: config_module.RunConfig,
    normalized_rows: NormalizedRows,
) -> None:
    if config.output.artifact_profile != "full":
        return
    written_hash = artifacts.write_strategy_input_rows(
        result_dir,
        normalized_rows.projection_rows(),
    )
    if written_hash != normalized_rows.normalized_rows_sha256:
        raise RunnerError(
            "strategy_input_rows.jsonl hash does not match normalized_rows_sha256"
        )


def _write_execution_data_manifest(
    result_dir: Path,
    config: config_module.RunConfig,
    *,
    rows: Sequence[Mapping[str, Any]],
    normalized_rows: NormalizedRows,
    evidence_quality: dict[str, object] | None,
) -> None:
    artifacts.write_data_manifest(
        result_dir,
        config,
        rows,
        normalized_rows=normalized_rows,
        evidence_quality_payload=evidence_quality,
    )


def _prepare_causality_evidence(
    config: config_module.RunConfig,
    execution: StrategyExecutionResult,
    event_emitter: RunnerStageEmitter,
) -> tuple[LookaheadCheckResult, dict[str, object]]:
    with event_emitter.stage(
        "causality_check",
        strategy_id=config.strategy_id,
        decision_count=len(execution.decisions),
    ) as causality_event:
        causality = _check_causality(config, execution)
        if not causality.passed:
            causality_event.fail(_causality_message(causality))
    evidence_quality = artifacts.with_causality_verification(
        execution.evidence_quality,
        emitted_replay_verified=causality.emitted_replay_verified,
        strict_no_emission_verified=causality.strict_suppression_verified,
    )
    return causality, evidence_quality


def _prepare_engine_request(
    config: config_module.RunConfig,
    result_dir: Path,
    execution: StrategyExecutionResult,
    evidence_quality: dict[str, object],
    *,
    repo_root: Path,
    event_emitter: RunnerStageEmitter,
) -> tuple[engine_runner.EvaluationRequest | None, RunResult | None]:
    try:
        with event_emitter.stage(
            "request_build",
            strategy_id=config.strategy_id,
            decision_count=len(execution.decisions),
        ):
            _assert_row_contract_allows_engine_request(evidence_quality)
            engine_runner.assert_supported_decisions(execution.decisions)
    except RunnerError as exc:
        return None, _failure_result(
            config,
            result_dir,
            "request_build",
            str(exc),
            repo_root=repo_root,
            evidence_quality=evidence_quality,
            event_emitter=event_emitter,
        )

    try:
        with event_emitter.stage(
            "data_readiness",
            strategy_id=config.strategy_id,
            decision_count=len(execution.decisions),
        ):
            data_readiness.assert_decision_rows_ready(execution.normalized_rows, execution.decisions)
    except RunnerError as exc:
        return None, _failure_result(
            config,
            result_dir,
            "data_readiness",
            str(exc),
            repo_root=repo_root,
            evidence_quality=evidence_quality,
            event_emitter=event_emitter,
        )

    try:
        with event_emitter.stage(
            "request_build",
            strategy_id=config.strategy_id,
            row_count=len(execution.loaded_rows),
            decision_count=len(execution.decisions),
        ):
            request = engine_runner.build_request(
                strategy_id=config.strategy_id,
                rows=execution.normalized_rows,
                decisions=execution.decisions,
                fill_model=config.fill_model,
                cost_model=config.cost_model,
            )
            if config.output.artifact_profile == "full":
                artifacts.write_engine_request(result_dir, engine_runner.request_json(request))
    except RunnerError as exc:
        return None, _failure_result(
            config,
            result_dir,
            "request_build",
            str(exc),
            repo_root=repo_root,
            evidence_quality=evidence_quality,
            event_emitter=event_emitter,
        )
    return request, None


def _assert_row_contract_allows_engine_request(evidence_quality: dict[str, object]) -> None:
    row_contract = evidence_quality.get("row_contract")
    if not isinstance(row_contract, Mapping) or row_contract.get("status") != "failed":
        return
    raise RunnerError(_row_contract_failure_message(row_contract))


def _row_contract_failure_message(row_contract: Mapping[str, object]) -> str:
    feedback = row_contract.get("quant_data_feedback")
    if isinstance(feedback, Sequence) and not isinstance(feedback, str):
        reasons = [str(item) for item in feedback if item]
        if reasons:
            return f"row_contract_failed: {'; '.join(reasons)}"

    issue_reasons = row_contract.get("issue_reasons")
    if isinstance(issue_reasons, Mapping):
        reasons = [
            f"{reason}:{count}"
            for reason, count in sorted(issue_reasons.items(), key=lambda item: str(item[0]))
        ]
        if reasons:
            return f"row_contract_failed: {'; '.join(reasons)}"

    return "row_contract_failed"


def _evaluate_engine_request(
    config: config_module.RunConfig,
    result_dir: Path,
    request: engine_runner.EvaluationRequest | None,
    evidence_quality: dict[str, object],
    *,
    repo_root: Path,
    event_emitter: RunnerStageEmitter,
) -> tuple[engine_runner.EngineRun | None, RunResult | None]:
    if request is None:
        raise ValueError("request is required when no failure was returned")
    try:
        with event_emitter.stage(
            "engine_evaluation",
            strategy_id=config.strategy_id,
            mode=config.output.mode,
        ):
            return (
                engine_runner.evaluate_request(
                    request,
                    mode=config.output.mode,
                    include_evidence=config.output.artifact_profile == "full",
                ),
                None,
            )
    except RunnerError as exc:
        return None, _failure_result(
            config,
            result_dir,
            "engine_evaluation",
            str(exc),
            repo_root=repo_root,
            evidence_quality=evidence_quality,
            event_emitter=event_emitter,
        )


def _write_completion_artifacts(
    config: config_module.RunConfig,
    result_dir: Path,
    execution: StrategyExecutionResult,
    engine_run: engine_runner.EngineRun | None,
    evidence_quality: dict[str, object],
    *,
    repo_root: Path,
    event_emitter: RunnerStageEmitter,
) -> tuple[str, str]:
    if engine_run is None:
        raise ValueError("engine_run is required when no failure was returned")
    with event_emitter.stage("artifact_writes", strategy_id=config.strategy_id, status_stage="completed"):
        engine_summary = artifacts.compact_engine_summary(engine_run)
        if config.output.artifact_profile == "full" and engine_run.evidence_json:
            artifacts.write_evidence(result_dir, engine_run.evidence_json)
        if config.output.artifact_profile == "summary":
            write_summary_profile_artifact(
                result_dir,
                config=config,
                rows=execution.loaded_rows,
                decisions=execution.decisions,
                engine=engine_summary,
                normalized_rows_hash=execution.normalized_rows_sha256,
                row_ranges=execution.normalized_rows.ranges_by_symbol,
            )
        notes = artifacts.completion_notes(config, engine_run)
        artifacts.write_notes(result_dir, notes)
        artifacts.write_run_manifest(
            result_dir,
            repo_root=repo_root,
            evidence=runner_evidence_semantics(config.data.kind),
            artifact_profile=config.output.artifact_profile,
        )
        assessment_status = artifacts.assessment_status(engine_run, evidence_quality=evidence_quality)
        artifacts.write_summary(
            result_dir,
            artifacts.summary_payload(
                config,
                status=artifacts.result_status(engine_run),
                stage="completed",
                failure_stage=None,
                message=notes.strip(),
                engine=engine_summary,
                assessment_status=assessment_status,
                evidence_quality=evidence_quality,
                param_contract=execution.param_contract,
            ),
        )
    return assessment_status, notes.strip()


def _check_causality(
    config: config_module.RunConfig,
    execution: StrategyExecutionResult,
) -> LookaheadCheckResult:
    try:
        return check_hidden_lookahead(
            execution.generate_decisions,
            rows=execution.normalized_rows,
            params=execution.frozen_params,
            baseline_decisions=execution.decisions,
            strategy_id=config.strategy_id,
        )
    except Exception as exc:
        return LookaheadCheckResult(
            passed=False,
            violations=(f"hidden_lookahead_check_failed: {type(exc).__name__}: {exc}",),
        )


def _audit_observation_dependencies(
    config: config_module.RunConfig,
    result_dir: Path,
    execution: StrategyExecutionResult,
    *,
    repo_root: Path,
    event_emitter: RunnerStageEmitter,
) -> RunResult | None:
    try:
        with event_emitter.stage(
            "observation_audit",
            strategy_id=config.strategy_id,
            decision_count=len(execution.decisions),
        ):
            _assert_declared_observations_causal(execution.normalized_rows, execution.decisions)
    except RunnerError as exc:
        _write_execution_data_manifest(
            result_dir,
            config,
            rows=execution.loaded_rows,
            normalized_rows=execution.normalized_rows,
            evidence_quality=execution.evidence_quality,
        )
        return _failure_result(
            config,
            result_dir,
            "observation_audit",
            str(exc),
            repo_root=repo_root,
            evidence_quality=execution.evidence_quality,
            event_emitter=event_emitter,
        )
    return None


def _assert_declared_observations_causal(
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
    decisions: list[StrategyDecision],
) -> None:
    row_index, timestamp_violations = observation_row_index(rows)
    violations = (
        *timestamp_violations,
        *audit_observation_dependencies(row_index, decisions),
    )
    if violations:
        raise data_readiness.DataReadinessError("; ".join(violations))


def _causality_message(result: LookaheadCheckResult) -> str:
    return "; ".join(result.violations) if result.violations else "hidden_lookahead_check_failed"


def _failure_result(
    config: config_module.RunConfig,
    result_dir: Path,
    stage: str,
    message: str,
    *,
    repo_root: Path,
    evidence_quality: dict[str, object] | None = None,
    event_emitter: RunnerStageEmitter | None = None,
) -> RunResult:
    notes = artifacts.failure_notes(stage, message)
    quality = evidence_quality or artifacts.evidence_quality(config, [])
    emitter = event_emitter or RunnerStageEmitter()
    with emitter.stage("artifact_writes", strategy_id=config.strategy_id, status_stage=stage):
        artifacts.write_notes(result_dir, notes)
        artifacts.write_run_manifest(
            result_dir,
            repo_root=repo_root,
            evidence=runner_evidence_semantics(config.data.kind),
            artifact_profile=config.output.artifact_profile,
        )
        artifacts.write_summary(
            result_dir,
            artifacts.summary_payload(
                config,
                status="failed",
                stage=stage,
                failure_stage=stage,
                message=message,
                engine={"passed": None, "trade_count": None},
                assessment_status="runner_failed",
                evidence_quality=quality,
            ),
        )
    return RunResult(
        result_dir=result_dir,
        notes_path=result_dir / "notes.md",
        message=notes.strip(),
        run_completed=True,
        failure_stage=stage,
        assessment_status="runner_failed",
        promotion_eligible=False,
        artifact_trust_tier=artifact_trust_tier_for_profile(config.output.artifact_profile),
        **artifacts.run_result_evidence_fields(quality),
    )


__all__ = ["RunResult", "run_config"]
