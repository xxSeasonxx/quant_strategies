from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

from quant_strategies.causality import (
    FOCUSED_CAUSALITY_PROFILE_VERSION,
    FocusedCausalityConfig,
    FocusedCausalityKey,
    FocusedCausalityResult,
    LookaheadCheckResult,
    check_focused_causality,
    check_hidden_lookahead,
    check_micro_causality,
    strict_replay_boundaries,
)
from quant_strategies.core import engine_runner as _engine_runner
from quant_strategies.core.errors import RunnerError
from quant_strategies.core.evidence_quality import CausalityVerification, EvidenceQuality
from quant_strategies.core.execution import (
    StrategyExecutionError,
    StrategyExecutionResult,
    execute_strategy_run,
)
from quant_strategies.core.portfolio_foundation import (
    FeasibilityError,
    FeasibilityVerdict,
    PortfolioFoundationConfig,
    PortfolioSizingReport,
    RunPortfolioFoundation,
    build_portfolio_foundation,
)
from quant_strategies.core.serialization import json_safe_value
from quant_strategies.data_contract import NormalizedRows
from quant_strategies.decisions import TargetDecision
from quant_strategies.evidence_semantics import (
    replayable_from_artifacts_for_profile,
    runner_evidence_semantics,
)
from quant_strategies.observation_dependencies import (
    audit_observation_dependencies,
    observation_row_index,
)
from quant_strategies.provenance import file_sha256
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

_OBSERVATION_AUDIT_SAMPLE_LIMIT = 10


@dataclass(frozen=True)
class RunCausalityEvidence:
    causality_check: str = "micro"
    verified: bool = False
    deterministic_replay_verified: bool = False
    emitted_replay_verified: bool = False
    strict_no_emission_verified: bool = False
    strict_replay_capped: bool = False
    strict_probe_count: int | None = None
    strict_probe_limit: int | None = None
    skipped_probe_count: int = 0
    skipped_probe_reasons: tuple[str, ...] = ()
    replay_scope: str | None = None
    candidate_probe_count: int | None = None
    selected_probe_count: int | None = None
    elapsed_seconds: float | None = None
    timeout_seconds: float | None = None
    timed_out: bool = False
    replay_warning: str | None = None


@dataclass(frozen=True)
class RunFocusedCausalityEvidence:
    status: str = "not_run"
    scoring_allowed: bool = False
    strategy_source_sha256: str | None = None
    strategy_id: str | None = None
    data_kind: str | None = None
    profile_version: str | None = None
    normalized_rows_sha256: str | None = None
    params_sha256: str | None = None
    max_probes: int | None = None
    timeout_seconds_key: float | None = None
    cache_hit: bool = False
    timeout_seconds: float | None = None
    candidate_probe_count: int | None = None
    selected_probe_count: int | None = None
    rejection_reason: str | None = None


@dataclass(frozen=True)
class RunEvidence:
    replayable_from_artifacts: bool | None = None
    data_availability_status: str | None = None
    availability_coverage: dict[str, object] | None = None
    row_contract: dict[str, object] | None = None
    causality: RunCausalityEvidence = RunCausalityEvidence()
    focused_causality: RunFocusedCausalityEvidence = RunFocusedCausalityEvidence()
    # Whether the run's causality mode admits scoring under policy (review No. 6):
    # any replay mode is admissible; ``off`` only when the operator-frozen
    # ``[causality_policy] allow_unverified_scoring`` is set (otherwise the run fails
    # closed at the causality stage). Mirrors the gate so the field is truthful.
    causality_admissible: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunOutcome:
    completed: bool = False
    failure_stage: str | None = None
    assessment_status: str = "runner_failed"
    # "validated" / "unvalidated_passthrough" on a completed run; "unknown" on a
    # run that failed before the param contract was conclusively determined.
    param_contract: str = "unknown"


@dataclass(frozen=True)
class RunRetainability:
    retainable: bool = False
    reason: str | None = "run_not_completed"
    detail: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "retainable": self.retainable,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RunResult:
    result_dir: Path | None
    notes_path: Path | None
    message: str
    outcome: RunOutcome = RunOutcome()
    evidence: RunEvidence = RunEvidence()
    economics: RunEconomics | None = None
    foundation: RunPortfolioFoundation | None = None
    # Typed fail-closed feasibility verdict for the authoritative book. ``None`` only
    # when the run failed before the book was built; an infeasible book carries a
    # populated verdict (reason + observed exposure) and maps to a ``feasibility``
    # failure_stage so ``succeeded`` is false (design D5).
    feasibility: FeasibilityVerdict | None = None
    retainability: RunRetainability = RunRetainability()

    @property
    def succeeded(self) -> bool:
        return self.outcome.completed and self.outcome.failure_stage is None

    @property
    def retainable(self) -> bool:
        return self.retainability.retainable


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

    failure = _assert_engine_inputs_ready(
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

    foundation, verdict, failure = _build_portfolio_foundation(
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
    if foundation is None or not foundation.feasible:
        return _feasibility_failure_result(
            config,
            result_dir,
            verdict,
            repo_root=effective_repo_root,
            evidence_quality=evidence_quality,
            event_emitter=events,
        )

    economics = economic_metrics.build_run_economics(foundation)
    engine_run = _engine_runner.evaluate_foundation(
        economics,
        feasible=foundation.feasible,
        mode=_engine_mode(config),
        include_diagnostics=True,
    )
    retainability = _quick_run_retainability(
        config,
        evidence_quality,
        foundation.feasible_verdict(),
        foundation.sizing_report,
    )
    try:
        assessment_status, notes = _write_completion_artifacts(
            config,
            result_dir,
            execution,
            decision_window_decisions,
            engine_run,
            economics,
            foundation,
            retainability,
            evidence_quality,
            repo_root=effective_repo_root,
            event_emitter=events,
        )
    except OSError as exc:
        # The book was scored and feasible, but completion artifacts could not be
        # written. Return a structured artifact_write failure instead of raising.
        return RunResult(
            result_dir=result_dir,
            notes_path=None,
            message=f"artifact write failed: {exc}",
            outcome=RunOutcome(failure_stage="artifact_write"),
            evidence=_run_evidence(config, evidence_quality),
            economics=economics,
            foundation=None,
            feasibility=foundation.feasible_verdict(),
        )
    return RunResult(
        result_dir=result_dir,
        notes_path=result_dir / "notes.md",
        message=notes.strip(),
        outcome=RunOutcome(
            completed=True,
            failure_stage=None,
            assessment_status=assessment_status,
            param_contract=execution.param_contract,
        ),
        evidence=_run_evidence(config, evidence_quality),
        economics=economics,
        foundation=foundation,
        feasibility=foundation.feasible_verdict(),
        retainability=retainability,
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
    evidence_quality: EvidenceQuality | None,
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
) -> tuple[LookaheadCheckResult, EvidenceQuality]:
    if config.output.causality_check == "focused":
        return _prepare_focused_causality_evidence(config, execution, event_emitter)
    if config.output.causality_check == "micro":
        return _prepare_micro_causality_evidence(config, execution, event_emitter)

    with event_emitter.stage(
        "causality_check",
        strategy_id=config.strategy_id,
        decision_count=len(execution.decisions),
    ) as causality_event:
        causality = _check_causality(config, execution)
        if not causality.passed:
            causality_event.fail(_causality_message(causality))
    evidence_quality = execution.evidence_quality.with_causality(
        CausalityVerification.from_replay(
            execution.evidence_quality.data_availability_status,
            causality_check=config.output.causality_check,
            deterministic_replay_verified=causality.deterministic_replay_verified,
            emitted_replay_verified=causality.emitted_replay_verified,
            strict_no_emission_verified=causality.strict_suppression_verified,
            strict_replay_capped=causality.strict_replay_capped,
            strict_probe_count=causality.strict_probe_count,
            strict_probe_limit=causality.strict_probe_limit,
            skipped_probe_count=causality.skipped_probe_count,
            skipped_probe_reasons=causality.skipped_probe_reasons,
            replay_scope=causality.replay_scope,
            candidate_probe_count=causality.candidate_probe_count,
            selected_probe_count=causality.selected_probe_count,
            elapsed_seconds=causality.elapsed_seconds,
            timeout_seconds=causality.timeout_seconds,
            timed_out=causality.timed_out,
            replay_warning=causality.replay_warning,
        )
    )
    return causality, evidence_quality


def _prepare_micro_causality_evidence(
    config: config_module.RunConfig,
    execution: StrategyExecutionResult,
    event_emitter: RunnerStageEmitter,
) -> tuple[LookaheadCheckResult, EvidenceQuality]:
    with event_emitter.stage(
        "causality_check",
        strategy_id=config.strategy_id,
        decision_count=len(execution.decisions),
        mode="micro",
    ) as causality_event:
        micro = check_micro_causality(
            execution.generate_decisions,
            rows=execution.normalized_rows,
            params=execution.frozen_params,
            baseline_decisions=execution.decisions,
            strategy_id=config.strategy_id,
            max_probes=config.output.micro_probe_limit,
            timeout_seconds=config.output.micro_timeout_seconds,
        )
        micro_failed_closed = not micro.passed and not micro.timed_out
        if micro_failed_closed:
            causality_event.fail(_causality_message(micro))
    evidence_quality = execution.evidence_quality.with_causality(
        CausalityVerification.from_replay(
            execution.evidence_quality.data_availability_status,
            causality_check=config.output.causality_check,
            deterministic_replay_verified=micro.passed and micro.deterministic_replay_verified,
            emitted_replay_verified=False,
            strict_no_emission_verified=False,
            skipped_probe_count=micro.skipped_probe_count,
            skipped_probe_reasons=micro.skipped_probe_reasons,
            replay_scope="micro",
            candidate_probe_count=micro.candidate_probe_count,
            selected_probe_count=micro.selected_probe_count,
            timeout_seconds=micro.timeout_seconds,
            timed_out=micro.timed_out,
            replay_warning=micro.replay_warning,
        )
    )
    if micro_failed_closed:
        return micro, evidence_quality
    return (
        LookaheadCheckResult(
            passed=True,
            mode="emitted",
            replay_scope="micro",
        ),
        evidence_quality,
    )


def _prepare_focused_causality_evidence(
    config: config_module.RunConfig,
    execution: StrategyExecutionResult,
    event_emitter: RunnerStageEmitter,
) -> tuple[LookaheadCheckResult, EvidenceQuality]:
    focused_config = FocusedCausalityConfig(
        max_probes=config.output.focused_probe_limit,
        timeout_seconds=config.output.focused_timeout_seconds,
        profile_version=FOCUSED_CAUSALITY_PROFILE_VERSION,
    )
    key = _focused_causality_key(config, focused_config, execution)
    with event_emitter.stage(
        "causality_check",
        strategy_id=config.strategy_id,
        decision_count=len(execution.decisions),
        mode="focused",
    ) as causality_event:
        focused = _read_focused_causality_cache(config, key)
        if focused is None:
            focused = check_focused_causality(
                execution.generate_decisions,
                rows=execution.normalized_rows,
                params=execution.frozen_params,
                baseline_decisions=execution.decisions,
                strategy_id=config.strategy_id,
                key=key,
                config=focused_config,
            )
            _write_focused_causality_cache(config, focused)
        else:
            focused = replace(focused, cache_hit=True)
        if not focused.scoring_allowed:
            causality_event.fail(focused.rejection_reason or f"focused_causality_{focused.status}")

    causality = _focused_result_as_lookahead(focused)
    evidence_quality = execution.evidence_quality.with_causality(
        CausalityVerification.from_replay(
            execution.evidence_quality.data_availability_status,
            causality_check=config.output.causality_check,
            deterministic_replay_verified=False,
            emitted_replay_verified=False,
            strict_no_emission_verified=False,
            replay_scope="focused",
        )
    ).with_focused_causality(_focused_causality_payload(focused))
    return causality, evidence_quality


def _focused_causality_key(
    config: config_module.RunConfig,
    focused_config: FocusedCausalityConfig,
    execution: StrategyExecutionResult,
) -> FocusedCausalityKey:
    return FocusedCausalityKey(
        strategy_source_sha256=file_sha256(config.strategy_path),
        strategy_id=config.strategy_id,
        data_kind=config.data.kind,
        profile_version=focused_config.profile_version,
        normalized_rows_sha256=execution.normalized_rows_sha256,
        params_sha256=_params_sha256(execution.validated_params),
        max_probes=focused_config.max_probes,
        timeout_seconds=focused_config.timeout_seconds,
    )


def _focused_result_as_lookahead(focused: FocusedCausalityResult) -> LookaheadCheckResult:
    if focused.scoring_allowed:
        return LookaheadCheckResult(
            passed=True,
            mode="emitted",
            deterministic_replay_verified=False,
            emitted_replay_verified=False,
            strict_suppression_verified=False,
        )
    return LookaheadCheckResult(
        passed=False,
        mode="emitted",
        violations=(focused.rejection_reason or f"focused_causality_{focused.status}",),
    )


def _focused_causality_payload(focused: FocusedCausalityResult) -> dict[str, object]:
    return {
        "status": focused.status,
        "scoring_allowed": focused.scoring_allowed,
        "strategy_source_sha256": focused.key.strategy_source_sha256,
        "strategy_id": focused.key.strategy_id,
        "data_kind": focused.key.data_kind,
        "profile_version": focused.profile_version,
        "normalized_rows_sha256": focused.key.normalized_rows_sha256,
        "params_sha256": focused.key.params_sha256,
        "max_probes": focused.key.max_probes,
        "timeout_seconds_key": focused.key.timeout_seconds,
        "cache_hit": focused.cache_hit,
        "timeout_seconds": focused.timeout_seconds,
        "candidate_probe_count": focused.candidate_probe_count,
        "selected_probe_count": focused.selected_probe_count,
        "rejection_reason": focused.rejection_reason,
    }


def _focused_cache_path(config: config_module.RunConfig, key: FocusedCausalityKey) -> Path:
    digest_payload = {
        "strategy_source_sha256": key.strategy_source_sha256,
        "strategy_id": key.strategy_id,
        "data_kind": key.data_kind,
        "profile_version": key.profile_version,
        "normalized_rows_sha256": key.normalized_rows_sha256,
        "params_sha256": key.params_sha256,
        "max_probes": key.max_probes,
        "timeout_seconds": key.timeout_seconds,
    }
    digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return config.output.results_dir / ".focused_causality_cache" / f"{digest}.json"


def _params_sha256(params: Mapping[str, Any]) -> str:
    payload = json_safe_value(dict(params))
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _read_focused_causality_cache(
    config: config_module.RunConfig,
    key: FocusedCausalityKey,
) -> FocusedCausalityResult | None:
    path = _focused_cache_path(config, key)
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("profile_version") != key.profile_version:
        return None
    status = payload.get("status")
    if status not in {"passed", "failed", "timeout"}:
        return None
    return FocusedCausalityResult(
        status=status,
        scoring_allowed=bool(payload.get("scoring_allowed")),
        key=key,
        profile_version=str(payload.get("profile_version")),
        timeout_seconds=float(payload.get("timeout_seconds") or 0.0),
        candidate_probe_count=int(payload.get("candidate_probe_count") or 0),
        selected_probe_count=int(payload.get("selected_probe_count") or 0),
        rejection_reason=_optional_str(payload.get("rejection_reason")),
    )


def _write_focused_causality_cache(
    config: config_module.RunConfig,
    focused: FocusedCausalityResult,
) -> None:
    path = _focused_cache_path(config, focused.key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_focused_causality_payload(focused), indent=2, sort_keys=True) + "\n"
        )
    except OSError:
        return


def _assert_engine_inputs_ready(
    config: config_module.RunConfig,
    result_dir: Path,
    execution: StrategyExecutionResult,
    decision_window_decisions: list[TargetDecision],
    evidence_quality: EvidenceQuality,
    *,
    repo_root: Path,
    event_emitter: RunnerStageEmitter,
) -> RunResult | None:
    """Gate the row contract and decision-row readiness before scoring the book.

    The open-ticket translation layer (`assert_supported_decisions`) and the engine
    request build were retired with the per-trade scorer: the target book consumes the
    decisions directly and is the single PnL/NAV computation.
    """
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
    except RunnerError as exc:
        return _failure_result(
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
        return _failure_result(
            config,
            result_dir,
            "data_readiness",
            str(exc),
            repo_root=repo_root,
            evidence_quality=evidence_quality,
            event_emitter=event_emitter,
        )
    return None


def _assert_row_contract_allows_engine_request(evidence_quality: EvidenceQuality) -> None:
    row_contract = evidence_quality.row_contract
    if row_contract.get("status") != "failed":
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
    decisions: Sequence[TargetDecision],
) -> list[TargetDecision]:
    return [
        decision
        for decision in decisions
        if _date_in_window(decision.decision_time, config.data.start, config.data.end)
    ]


def _date_in_window(value: datetime | date, start: date, end: date) -> bool:
    item = value.date() if isinstance(value, datetime) else value
    return start <= item <= end


def _build_portfolio_foundation(
    config: config_module.RunConfig,
    result_dir: Path,
    execution: StrategyExecutionResult,
    decision_window_decisions: list[TargetDecision],
    evidence_quality: EvidenceQuality,
    *,
    repo_root: Path,
    event_emitter: RunnerStageEmitter,
) -> tuple[RunPortfolioFoundation | None, FeasibilityVerdict | None, RunResult | None]:
    """Build the authoritative scored book (fail-closed).

    A :class:`FeasibilityError` is the typed fail-closed verdict (leverage budget,
    unfinanced leverage) — surfaced as a populated verdict, never a swallowed
    ``None`` (design D5); the caller maps it to a ``feasibility`` failure_stage.
    A non-feasibility build error (missing/unfillable rows) is a structured
    ``portfolio_foundation`` stage failure, not a fail-open success.
    """
    rows = (execution.execution_normalized_rows or execution.normalized_rows).projection_rows()
    try:
        with event_emitter.stage(
            "portfolio_foundation",
            strategy_id=config.strategy_id,
            scenario_count=2,
            subwindows=config.output.foundation_subwindows,
        ):
            foundation = build_portfolio_foundation(
                rows=rows,
                decisions=decision_window_decisions,
                data=config.data,
                fill_model=config.fill_model,
                cost_model=config.cost_model,
                capacity_model=config.capacity_model,
                mark_rows=execution.mark_rows,
                mark_repair=execution.mark_repair,
                config=PortfolioFoundationConfig(
                    risk_budget=config.risk_budget,
                    subwindows=config.output.foundation_subwindows,
                    cost_stress_multiplier=config.output.foundation_cost_stress_multiplier,
                    fill_stress_fraction=config.output.foundation_fill_stress_fraction,
                    max_gross_exposure=config.leverage_budget.max_gross_exposure,
                    max_net_exposure=config.leverage_budget.max_net_exposure,
                    min_return_sample=config.output.foundation_min_return_sample,
                ),
            )
    except FeasibilityError as exc:
        return None, exc.verdict, None
    except (ValueError, RunnerError) as exc:
        return (
            None,
            None,
            _failure_result(
                config,
                result_dir,
                "portfolio_foundation",
                f"portfolio_foundation_failed: {type(exc).__name__}: {exc}",
                repo_root=repo_root,
                evidence_quality=evidence_quality,
                event_emitter=event_emitter,
            ),
        )
    return foundation, foundation.feasible_verdict(), None


def _feasibility_failure_result(
    config: config_module.RunConfig,
    result_dir: Path,
    verdict: FeasibilityVerdict | None,
    *,
    repo_root: Path,
    evidence_quality: EvidenceQuality,
    event_emitter: RunnerStageEmitter,
) -> RunResult:
    """Map an infeasible book to a typed ``feasibility`` failure with the verdict.

    The verdict reason (and observed exposure) is the actionable signal; the run is
    not scoreable and ``succeeded`` is false (design D5).
    """
    effective_verdict = verdict or FeasibilityVerdict(
        feasible=False, reason="infeasible", detail="portfolio book infeasible"
    )
    message = _feasibility_message(effective_verdict)
    retainability = RunRetainability(
        retainable=False,
        reason=effective_verdict.reason or "feasibility",
        detail=effective_verdict.detail,
    )
    failure = _failure_result(
        config,
        result_dir,
        "feasibility",
        message,
        repo_root=repo_root,
        evidence_quality=evidence_quality,
        retainability=retainability,
        event_emitter=event_emitter,
    )
    return replace(failure, feasibility=effective_verdict)


def _feasibility_message(verdict: FeasibilityVerdict) -> str:
    parts = [f"feasibility:{verdict.reason}" if verdict.reason else "feasibility:infeasible"]
    if verdict.observed_gross is not None:
        parts.append(f"observed_gross={verdict.observed_gross:.6g}")
    if verdict.observed_net is not None:
        parts.append(f"observed_net={verdict.observed_net:.6g}")
    if verdict.detail:
        parts.append(verdict.detail)
    return "; ".join(parts)


def _write_completion_artifacts(
    config: config_module.RunConfig,
    result_dir: Path,
    execution: StrategyExecutionResult,
    decision_window_decisions: list[TargetDecision],
    engine_run: _engine_runner.EngineRun,
    economics: RunEconomics,
    foundation: RunPortfolioFoundation | None,
    retainability: RunRetainability,
    evidence_quality: EvidenceQuality,
    *,
    repo_root: Path,
    event_emitter: RunnerStageEmitter,
) -> tuple[str, str]:
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
                    portfolio_foundation=(
                        None if foundation is None else foundation.matrix_payload()
                    ),
                ),
            )
        notes = artifacts.completion_notes(
            config,
            engine_run,
            assessment_status=assessment_status,
        )
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
                portfolio_foundation=(None if foundation is None else foundation.summary_payload()),
                retainability=retainability.payload(),
                generated_decision_count=len(execution.decisions),
                excluded_decision_count=len(execution.decisions) - len(decision_window_decisions),
            ),
        )
    return assessment_status, notes.strip()


def _quick_run_retainability(
    config: config_module.RunConfig,
    evidence_quality: EvidenceQuality,
    verdict: FeasibilityVerdict,
    sizing_report: PortfolioSizingReport | None,
) -> RunRetainability:
    if not verdict.feasible:
        return RunRetainability(
            retainable=False,
            reason=verdict.reason or "feasibility",
            detail=verdict.detail,
        )

    causality_reason = _causality_retainability_reason(config, evidence_quality)
    if causality_reason is not None:
        reason, detail = causality_reason
        return RunRetainability(retainable=False, reason=reason, detail=detail)

    envelope_reason = _envelope_retainability_reason(config)
    if envelope_reason is not None:
        reason, detail = envelope_reason
        return RunRetainability(retainable=False, reason=reason, detail=detail)

    sizing_reason = _sizing_retainability_reason(sizing_report)
    if sizing_reason is not None:
        reason, detail = sizing_reason
        return RunRetainability(retainable=False, reason=reason, detail=detail)

    return RunRetainability(retainable=True, reason=None, detail=None)


def _causality_retainability_reason(
    config: config_module.RunConfig,
    evidence_quality: EvidenceQuality,
) -> tuple[str, str | None] | None:
    causality = evidence_quality.causality
    check = causality.causality_check or config.output.causality_check
    if causality.timed_out:
        return ("causality_timeout", causality.replay_warning)
    warning = causality.replay_warning
    if warning is not None:
        return ("causality_replay_warning", warning)
    if check != "strict":
        return (
            "causality_not_retention_verified",
            f"{check} replay is not complete retention proof",
        )
    if not causality.verified:
        return ("causality_not_retention_verified", "strict replay was not fully verified")
    if causality.strict_replay_capped:
        return ("causality_not_retention_verified", "strict replay was capped")
    return None


def _envelope_retainability_reason(
    config: config_module.RunConfig,
) -> tuple[str, str | None] | None:
    if not config.envelope.operator_frozen:
        return ("envelope_not_operator_frozen", "set [envelope] operator_frozen = true")
    if config.cost_model.fee_bps_per_side + config.cost_model.slippage_bps_per_side <= 0.0:
        return ("envelope_zero_cost", "fee_bps_per_side + slippage_bps_per_side must be positive")
    capacity = config.capacity_model
    if capacity.mode == "adv_impact":
        if (capacity.impact_coefficient_bps or 0.0) <= 0.0:
            return (
                "capacity_impact_unpriced",
                "adv_impact requires positive impact_coefficient_bps",
            )
        if (capacity.max_bar_participation or 0.0) > 1.0 or (
            capacity.max_adv_participation or 0.0
        ) > 1.0:
            return (
                "capacity_participation_unbounded",
                "max bar/ADV participation must be <= 1.0",
            )
    return None


def _sizing_retainability_reason(
    sizing_report: PortfolioSizingReport | None,
) -> tuple[str, str | None] | None:
    if sizing_report is None:
        return ("risk_budget_sizing_missing", "portfolio sizing report is required")
    if not math.isfinite(sizing_report.book_scale) or sizing_report.book_scale <= 0.0:
        return (
            "risk_budget_sizing_missing",
            "portfolio sizing report must record a positive book_scale",
        )
    return None


def _engine_mode(config: config_module.RunConfig) -> _engine_runner.EngineMode:
    return "gate" if config.output.quick_checks else "screen"


def _check_causality(
    config: config_module.RunConfig,
    execution: StrategyExecutionResult,
) -> LookaheadCheckResult:
    if config.output.causality_check == "off":
        if config.causality_policy.allow_unverified_scoring:
            return LookaheadCheckResult(passed=True, mode="emitted", replay_scope="off")
        return LookaheadCheckResult(
            passed=False,
            mode="emitted",
            replay_scope="off",
            violations=(
                'causality_check_off_non_scoreable: causality_check="off" runs no '
                "look-ahead replay, so its NAV path is not scoreable; choose a replay mode "
                "(micro/emitted/focused/strict) or set "
                "[causality_policy] allow_unverified_scoring=true to override",
            ),
        )

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
    decisions: list[TargetDecision],
) -> None:
    row_index, timestamp_violations = observation_row_index(rows)
    violations = (
        *timestamp_violations,
        *audit_observation_dependencies(row_index, decisions),
    )
    if violations:
        raise data_readiness.DataReadinessError(_format_observation_audit_violations(violations))


def _format_observation_audit_violations(violations: Sequence[str]) -> str:
    if not violations:
        return "observation audit failed"

    counts = Counter(_observation_audit_category(violation) for violation in violations)
    category_summary = ", ".join(
        f"{category}={count}" for category, count in sorted(counts.items())
    )
    unique_samples = tuple(dict.fromkeys(violations))
    sample_limit = _OBSERVATION_AUDIT_SAMPLE_LIMIT
    samples = "; ".join(unique_samples[:sample_limit])
    omitted = len(unique_samples) - sample_limit

    message = f"observation audit failed: {len(violations)} violations"
    if category_summary:
        message = f"{message} ({category_summary})"
    message = f"{message}; sample violations: {samples}"
    if omitted > 0:
        message = f"{message}; {omitted} unique violations omitted"
    return message


def _observation_audit_category(violation: str) -> str:
    if violation.startswith("invalid timestamp"):
        return "invalid_observation_timestamp"
    if violation.startswith("missing observation row"):
        return "missing_observation_row"
    if violation.startswith("missing observation field"):
        return "missing_observation_field"
    if "references future row" in violation:
        return "future_observation_row"
    if violation.startswith("missing available_at"):
        return "missing_observation_available_at"
    if violation.startswith("invalid available_at"):
        return "invalid_observation_available_at"
    if violation.startswith("observation row") and "was available after decision_time" in violation:
        return "late_observation_available_at"
    return "observation_audit"


def _causality_message(result: LookaheadCheckResult) -> str:
    return "; ".join(result.violations) if result.violations else "hidden_lookahead_check_failed"


def _policy_evidence_quality(
    config: config_module.RunConfig,
    evidence_quality: EvidenceQuality | None,
) -> EvidenceQuality | None:
    if evidence_quality is None:
        return None
    return evidence_quality.with_causality(
        CausalityVerification.from_replay(
            evidence_quality.data_availability_status,
            causality_check=config.output.causality_check,
            deterministic_replay_verified=False,
            emitted_replay_verified=False,
            strict_no_emission_verified=False,
            replay_scope=config.output.causality_check,
        )
    )


def _failure_result(
    config: config_module.RunConfig,
    result_dir: Path,
    stage: str,
    message: str,
    *,
    repo_root: Path,
    evidence_quality: EvidenceQuality | None = None,
    retainability: RunRetainability | None = None,
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
                    retainability=(None if retainability is None else retainability.payload()),
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
        ),
        evidence=_run_evidence(config, quality),
        retainability=retainability or RunRetainability(),
    )


def _run_evidence(
    config: config_module.RunConfig,
    evidence_quality: EvidenceQuality | None,
) -> RunEvidence:
    quality = evidence_quality or artifacts.evidence_quality(config, [])
    causality = quality.causality
    return RunEvidence(
        replayable_from_artifacts=replayable_from_artifacts_for_profile(
            config.output.artifact_profile
        ),
        data_availability_status=quality.data_availability_status,
        availability_coverage=dict(quality.availability_coverage),
        row_contract=dict(quality.row_contract),
        causality=RunCausalityEvidence(
            causality_check=causality.causality_check,
            verified=causality.verified,
            deterministic_replay_verified=causality.deterministic_replay_verified,
            emitted_replay_verified=causality.emitted_replay_verified,
            strict_no_emission_verified=causality.strict_no_emission_verified,
            strict_replay_capped=causality.strict_replay_capped,
            strict_probe_count=causality.strict_probe_count,
            strict_probe_limit=causality.strict_probe_limit,
            skipped_probe_count=causality.skipped_probe_count,
            skipped_probe_reasons=causality.skipped_probe_reasons,
            replay_scope=causality.replay_scope,
            candidate_probe_count=causality.candidate_probe_count,
            selected_probe_count=causality.selected_probe_count,
            elapsed_seconds=causality.elapsed_seconds,
            timeout_seconds=causality.timeout_seconds,
            timed_out=causality.timed_out,
            replay_warning=causality.replay_warning,
        ),
        focused_causality=_run_focused_causality_evidence(quality.focused_causality),
        causality_admissible=_causality_admissible(config, quality),
        warnings=causality.warnings,
    )


def _causality_admissible(
    config: config_module.RunConfig,
    quality: EvidenceQuality,
) -> bool:
    """Does the causality dimension admit scoring under policy (review No. 6)?

    A mode that ran some replay (``micro``/``emitted``/``focused``/``strict``) is
    admissible; ``off`` ran no replay and is admissible only when the operator-frozen
    ``[causality_policy] allow_unverified_scoring`` is set (otherwise the run already
    fails closed at the causality stage). This mirrors the gate so the surfaced field is
    truthful on both the scored and the failed path.
    """
    causality = quality.causality
    check = causality.causality_check or config.output.causality_check
    if check == "off":
        return config.causality_policy.allow_unverified_scoring
    if check == "micro":
        return quality.data_availability_status == "complete"
    if causality.verified or causality.emitted_replay_verified:
        return True
    focused = quality.focused_causality
    if isinstance(focused, Mapping) and bool(focused.get("scoring_allowed")):
        return True
    return False


def _run_focused_causality_evidence(value: object) -> RunFocusedCausalityEvidence:
    if not isinstance(value, Mapping):
        return RunFocusedCausalityEvidence()
    return RunFocusedCausalityEvidence(
        status=str(value.get("status") or "not_run"),
        scoring_allowed=bool(value.get("scoring_allowed")),
        strategy_source_sha256=_optional_str(value.get("strategy_source_sha256")),
        strategy_id=_optional_str(value.get("strategy_id")),
        data_kind=_optional_str(value.get("data_kind")),
        profile_version=_optional_str(value.get("profile_version")),
        normalized_rows_sha256=_optional_str(value.get("normalized_rows_sha256")),
        params_sha256=_optional_str(value.get("params_sha256")),
        max_probes=_optional_int(value.get("max_probes")),
        timeout_seconds_key=_optional_float(value.get("timeout_seconds_key")),
        cache_hit=bool(value.get("cache_hit")),
        timeout_seconds=_optional_float(value.get("timeout_seconds")),
        candidate_probe_count=_optional_int(value.get("candidate_probe_count")),
        selected_probe_count=_optional_int(value.get("selected_probe_count")),
        rejection_reason=_optional_str(value.get("rejection_reason")),
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


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
    "RunPortfolioFoundation",
    "RunResult",
    "RunTrade",
    "run_config",
]
