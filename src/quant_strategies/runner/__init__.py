from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

from quant_strategies.causality import (
    LookaheadCheckResult,
    check_hidden_lookahead,
    strict_replay_boundaries,
)
from quant_strategies.core import engine_runner as _engine_runner
from quant_strategies.core.errors import RunnerError
from quant_strategies.core.execution import (
    StrategyExecutionError,
    StrategyExecutionResult,
    execute_strategy_run,
)
from quant_strategies.data_contract import NormalizedRows
from quant_strategies.decisions import StrategyDecision
from quant_strategies.evidence_semantics import (
    replayable_from_artifacts_for_profile,
    runner_evidence_semantics,
)
from quant_strategies.observation_dependencies import (
    audit_observation_dependencies,
    observation_row_index,
)
from quant_strategies.runner import (
    artifacts,
    data_readiness,
    economic_metrics,
)
from quant_strategies.runner import (
    config as config_module,
)
from quant_strategies.runner.economic_metrics import RunEconomics, RunTrade
from quant_strategies.runner.events import RunnerEventSink, RunnerStageEmitter


@dataclass(frozen=True)
class RunCausalityEvidence:
    causality_check: str = "strict"
    verified: bool = False
    deterministic_replay_verified: bool = False
    emitted_replay_verified: bool = False
    strict_no_emission_verified: bool = False
    strict_replay_capped: bool = False
    strict_probe_count: int | None = None
    strict_probe_limit: int | None = None
    skipped_probe_count: int = 0
    skipped_probe_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunEvidence:
    replayable_from_artifacts: bool | None = None
    data_availability_status: str | None = None
    availability_coverage: dict[str, object] | None = None
    row_contract: dict[str, object] | None = None
    causality: RunCausalityEvidence = RunCausalityEvidence()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunOutcome:
    completed: bool = False
    failure_stage: str | None = None
    assessment_status: str = "runner_failed"
    promotion_eligible: bool = False
    # "validated" / "unvalidated_passthrough" on a completed run; "unknown" on a
    # run that failed before the param contract was conclusively determined.
    param_contract: str = "unknown"


@dataclass(frozen=True)
class RunResult:
    result_dir: Path | None
    notes_path: Path | None
    message: str
    outcome: RunOutcome = RunOutcome()
    evidence: RunEvidence = RunEvidence()
    economics: RunEconomics | None = None

    @property
    def succeeded(self) -> bool:
        return self.outcome.completed and self.outcome.failure_stage is None


def run_config(
    config_path: str | Path,
    *,
    repo_root: Path | None = None,
    event_sink: RunnerEventSink | None = None,
) -> RunResult:
    effective_repo_root = (
        Path(repo_root).resolve() if repo_root is not None else config_module.default_repo_root()
    )
    events = RunnerStageEmitter(event_sink)
    try:
        with events.stage(
            "config_load",
            config_path=str(config_path),
            repo_root=str(effective_repo_root),
        ):
            config_file = config_module.resolve_config_path(
                config_path, repo_root=effective_repo_root
            )
            config = config_module.load_config(config_file, repo_root=effective_repo_root)
    except RunnerError as exc:
        return RunResult(
            result_dir=None,
            notes_path=None,
            message=str(exc),
            outcome=RunOutcome(failure_stage="config_load"),
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
            outcome=RunOutcome(failure_stage="artifact_initialization"),
            evidence=RunEvidence(
                replayable_from_artifacts=replayable_from_artifacts_for_profile(
                    config.output.artifact_profile
                ),
                causality=RunCausalityEvidence(causality_check=config.output.causality_check),
            ),
        )

    try:
        with events.stage("strategy_execution", strategy_id=config.strategy_id):
            execution = execute_strategy_run(
                config.to_execution_spec(),
                repo_root=effective_repo_root,
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
        execution_normalized_rows=execution.execution_normalized_rows,
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
    decision_window_decisions = _decision_window_decisions(config, execution.decisions)
    if config.output.artifact_profile == "full":
        artifacts.write_decision_records(result_dir, decision_window_decisions)

    request, failure = _prepare_engine_request(
        config,
        result_dir,
        execution,
        decision_window_decisions,
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

    economics = economic_metrics.build_run_economics(engine_run)
    try:
        assessment_status, notes = _write_completion_artifacts(
            config,
            result_dir,
            execution,
            decision_window_decisions,
            engine_run,
            economics,
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
            outcome=RunOutcome(failure_stage="artifact_write"),
            evidence=_run_evidence(config, evidence_quality),
            economics=economics,
        )
    return RunResult(
        result_dir=result_dir,
        notes_path=result_dir / "notes.md",
        message=notes.strip(),
        outcome=RunOutcome(
            completed=True,
            failure_stage=None,
            assessment_status=assessment_status,
            promotion_eligible=False,
            param_contract=execution.param_contract,
        ),
        evidence=_run_evidence(config, evidence_quality),
        economics=economics,
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
            evidence_quality=_policy_evidence_quality(config, exc.evidence_quality),
            execution_normalized_rows=exc.execution_normalized_rows,
        )
    return _failure_result(
        config,
        result_dir,
        exc.stage,
        str(exc),
        repo_root=repo_root,
        evidence_quality=_policy_evidence_quality(config, exc.evidence_quality),
        event_emitter=event_emitter,
    )


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
        raise RunnerError("strategy_input_rows.jsonl hash does not match normalized_rows_sha256")


def _write_execution_data_manifest(
    result_dir: Path,
    config: config_module.RunConfig,
    *,
    rows: Sequence[Mapping[str, Any]],
    normalized_rows: NormalizedRows,
    evidence_quality: dict[str, object] | None,
    execution_normalized_rows: NormalizedRows | None = None,
) -> None:
    artifacts.write_data_manifest(
        result_dir,
        config,
        rows,
        normalized_rows=normalized_rows,
        execution_normalized_rows=execution_normalized_rows,
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
        causality_check=config.output.causality_check,
        deterministic_replay_verified=causality.deterministic_replay_verified,
        emitted_replay_verified=causality.emitted_replay_verified,
        strict_no_emission_verified=causality.strict_suppression_verified,
        strict_replay_capped=causality.strict_replay_capped,
        strict_probe_count=causality.strict_probe_count,
        strict_probe_limit=causality.strict_probe_limit,
        skipped_probe_count=causality.skipped_probe_count,
        skipped_probe_reasons=causality.skipped_probe_reasons,
    )
    return causality, evidence_quality


def _prepare_engine_request(
    config: config_module.RunConfig,
    result_dir: Path,
    execution: StrategyExecutionResult,
    decision_window_decisions: list[StrategyDecision],
    evidence_quality: dict[str, object],
    *,
    repo_root: Path,
    event_emitter: RunnerStageEmitter,
) -> tuple[_engine_runner.EvaluationRequest | None, RunResult | None]:
    try:
        with event_emitter.stage(
            "request_build",
            strategy_id=config.strategy_id,
            decision_count=len(decision_window_decisions),
        ):
            _assert_row_contract_allows_engine_request(evidence_quality)
            _assert_execution_row_contract_allows_engine_request(
                execution.execution_normalized_rows
            )
            _engine_runner.assert_supported_decisions(decision_window_decisions)
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
            decision_count=len(decision_window_decisions),
        ):
            data_readiness.assert_decision_rows_ready(
                execution.normalized_rows, decision_window_decisions
            )
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
            row_count=len(execution.execution_normalized_rows or execution.normalized_rows),
            decision_count=len(decision_window_decisions),
        ):
            request = _engine_runner.build_request(
                strategy_id=config.strategy_id,
                rows=execution.execution_normalized_rows or execution.normalized_rows,
                decisions=decision_window_decisions,
                fill_model=config.fill_model,
                cost_model=config.cost_model,
            )
            if config.output.artifact_profile == "full":
                artifacts.write_engine_request(result_dir, _engine_runner.request_json(request))
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


def _assert_execution_row_contract_allows_engine_request(
    normalized_rows: NormalizedRows | None,
) -> None:
    if normalized_rows is None:
        return
    row_contract = normalized_rows.row_contract_summary()
    if row_contract.get("status") == "failed":
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


def _decision_window_decisions(
    config: config_module.RunConfig,
    decisions: Sequence[StrategyDecision],
) -> list[StrategyDecision]:
    return [
        decision
        for decision in decisions
        if _date_in_window(decision.decision_time, config.data.start, config.data.end)
    ]


def _date_in_window(value: datetime | date, start: date, end: date) -> bool:
    item = value.date() if isinstance(value, datetime) else value
    return start <= item <= end


def _evaluate_engine_request(
    config: config_module.RunConfig,
    result_dir: Path,
    request: _engine_runner.EvaluationRequest | None,
    evidence_quality: dict[str, object],
    *,
    repo_root: Path,
    event_emitter: RunnerStageEmitter,
) -> tuple[_engine_runner.EngineRun | None, RunResult | None]:
    if request is None:
        raise ValueError("request is required when no failure was returned")
    try:
        with event_emitter.stage(
            "engine_evaluation",
            strategy_id=config.strategy_id,
            quick_checks=config.output.quick_checks,
        ):
            return (
                _engine_runner.evaluate_request(
                    request,
                    mode=_engine_mode(config),
                    include_evidence=config.output.artifact_profile == "full",
                    include_diagnostics=True,
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
    decision_window_decisions: list[StrategyDecision],
    engine_run: _engine_runner.EngineRun | None,
    economics: RunEconomics,
    evidence_quality: dict[str, object],
    *,
    repo_root: Path,
    event_emitter: RunnerStageEmitter,
) -> tuple[str, str]:
    if engine_run is None:
        raise ValueError("engine_run is required when no failure was returned")
    with event_emitter.stage(
        "artifact_writes", strategy_id=config.strategy_id, status_stage="completed"
    ):
        engine_summary_with_trades = artifacts.compact_engine_summary(
            engine_run,
            include_diagnostic_trades=True,
        )
        engine_summary = dict(engine_summary_with_trades)
        engine_summary.pop("diagnostic_trades", None)
        assessment_status = artifacts.assessment_status(
            engine_run,
            quick_checks=config.output.quick_checks,
            evidence_quality=evidence_quality,
        )
        if config.output.artifact_profile == "full" and engine_run.evidence_json:
            artifacts.write_evidence(
                result_dir,
                engine_run.evidence_json,
                quick_checks=config.output.quick_checks,
            )
        if config.output.artifact_profile == "summary":
            from quant_strategies.runner.artifact_profiles import write_summary_profile_artifact

            has_explicit_load_window = (
                config.data.load_start is not None or config.data.load_end is not None
            )
            write_summary_profile_artifact(
                result_dir,
                config=config,
                rows=execution.loaded_rows,
                decisions=decision_window_decisions,
                engine=engine_summary,
                normalized_rows_hash=execution.normalized_rows_sha256,
                row_ranges=execution.normalized_rows.ranges_by_symbol,
                execution_normalized_rows_hash=(
                    execution.execution_normalized_rows_sha256 if has_explicit_load_window else None
                ),
                execution_row_ranges=(
                    None
                    if not has_explicit_load_window or execution.execution_normalized_rows is None
                    else execution.execution_normalized_rows.ranges_by_symbol
                ),
            )
        if config.output.artifact_profile == "diagnostic":
            from quant_strategies.runner import diagnostics

            diagnostics.write_diagnostics(
                result_dir,
                diagnostics.diagnostic_payload(
                    config=config,
                    engine=engine_summary_with_trades,
                    assessment_status=assessment_status,
                    evidence_quality=evidence_quality,
                    economic_slices=economics.slices_payload(),
                ),
            )
        notes = artifacts.completion_notes(config, engine_run)
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
                status=artifacts.result_status(engine_run),
                stage="completed",
                failure_stage=None,
                message=notes.strip(),
                engine=engine_summary,
                assessment_status=assessment_status,
                evidence_quality=evidence_quality,
                param_contract=execution.param_contract,
                economic_metrics=economics.summary_payload(),
                generated_decision_count=len(execution.decisions),
                excluded_decision_count=len(execution.decisions) - len(decision_window_decisions),
            ),
        )
    return assessment_status, notes.strip()


def _engine_mode(config: config_module.RunConfig) -> _engine_runner.EngineMode:
    return "gate" if config.output.quick_checks else "screen"


def _check_causality(
    config: config_module.RunConfig,
    execution: StrategyExecutionResult,
) -> LookaheadCheckResult:
    if config.output.causality_check == "off":
        return LookaheadCheckResult(passed=True, mode="emitted")

    try:
        if (
            config.output.causality_check == "strict"
            and config.output.strict_probe_limit is not None
        ):
            boundaries = strict_replay_boundaries(execution.normalized_rows, execution.decisions)
            limit = config.output.strict_probe_limit
            emitted_boundaries = tuple(
                boundary for boundary in boundaries if boundary.expected_decision_ids
            )
            strict_probe_boundaries = tuple(
                boundary for boundary in boundaries if not boundary.expected_decision_ids
            )
            capped = len(strict_probe_boundaries) > limit
            selected_boundaries = (
                *emitted_boundaries,
                *(strict_probe_boundaries[:limit] if capped else strict_probe_boundaries),
            )
            causality = check_hidden_lookahead(
                execution.generate_decisions,
                rows=execution.normalized_rows,
                params=execution.frozen_params,
                baseline_decisions=execution.decisions,
                strategy_id=config.strategy_id,
                mode="strict",
                boundaries=selected_boundaries,
            )
            if capped:
                return replace(
                    causality,
                    strict_suppression_verified=False,
                    strict_replay_capped=True,
                    strict_probe_count=limit,
                    strict_probe_limit=limit,
                )
            return replace(
                causality,
                strict_probe_count=len(strict_probe_boundaries),
                strict_probe_limit=limit,
            )

        return check_hidden_lookahead(
            execution.generate_decisions,
            rows=execution.normalized_rows,
            params=execution.frozen_params,
            baseline_decisions=execution.decisions,
            strategy_id=config.strategy_id,
            mode=config.output.causality_check,
        )
    except Exception as exc:
        return LookaheadCheckResult(
            passed=False,
            mode=config.output.causality_check,
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
            evidence_quality=_policy_evidence_quality(config, execution.evidence_quality),
            execution_normalized_rows=execution.execution_normalized_rows,
        )
        return _failure_result(
            config,
            result_dir,
            "observation_audit",
            str(exc),
            repo_root=repo_root,
            evidence_quality=_policy_evidence_quality(config, execution.evidence_quality),
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


def _policy_evidence_quality(
    config: config_module.RunConfig,
    evidence_quality: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if evidence_quality is None:
        return None
    return artifacts.with_causality_verification(
        evidence_quality,
        causality_check=config.output.causality_check,
        deterministic_replay_verified=False,
        emitted_replay_verified=False,
        strict_no_emission_verified=False,
    )


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
    notes_path: Path | None = result_dir / "notes.md"
    try:
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
    except OSError:
        # Artifacts could not be persisted; return the structured failure (original
        # stage) rather than letting a raw filesystem error escape to the caller.
        notes_path = None
    return RunResult(
        result_dir=result_dir,
        notes_path=notes_path,
        message=notes.strip(),
        outcome=RunOutcome(
            completed=False,
            failure_stage=stage,
            assessment_status="runner_failed",
            promotion_eligible=False,
        ),
        evidence=_run_evidence(config, quality),
    )


def _run_evidence(
    config: config_module.RunConfig,
    evidence_quality: dict[str, object] | None,
) -> RunEvidence:
    quality = evidence_quality or {}
    return RunEvidence(
        replayable_from_artifacts=replayable_from_artifacts_for_profile(
            config.output.artifact_profile
        ),
        data_availability_status=_optional_str(quality.get("data_availability_status")),
        availability_coverage=_optional_dict(quality.get("availability_coverage")),
        row_contract=_optional_dict(quality.get("row_contract")),
        causality=RunCausalityEvidence(
            causality_check=str(quality.get("causality_check", config.output.causality_check)),
            verified=bool(quality.get("causality_verified")),
            deterministic_replay_verified=bool(quality.get("deterministic_replay_verified")),
            emitted_replay_verified=bool(quality.get("emitted_replay_verified")),
            strict_no_emission_verified=bool(quality.get("strict_no_emission_verified")),
            strict_replay_capped=bool(quality.get("strict_replay_capped")),
            strict_probe_count=_optional_int(quality.get("strict_probe_count")),
            strict_probe_limit=_optional_int(quality.get("strict_probe_limit")),
            skipped_probe_count=int(quality.get("skipped_probe_count") or 0),
            skipped_probe_reasons=_string_tuple(quality.get("skipped_probe_reasons")),
        ),
        warnings=_string_tuple(quality.get("evidence_quality_warnings")),
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_dict(value: object) -> dict[str, object] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _optional_int(value: object) -> int | None:
    return int(value) if isinstance(value, int) else None


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value)
    return (str(value),)


__all__ = [
    "RunCausalityEvidence",
    "RunEconomics",
    "RunEvidence",
    "RunOutcome",
    "RunResult",
    "RunTrade",
    "run_config",
]
