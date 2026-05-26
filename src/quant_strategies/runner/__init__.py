from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quant_strategies.boundary import frozen_params, frozen_rows
from quant_strategies.decisions import (
    StrategyDecision,
    validate_decision_output,
    validate_strategy_params,
)
from quant_strategies.evidence_semantics import runner_evidence_semantics
from quant_strategies.runner import (
    artifacts,
    config as config_module,
    data_loader,
    data_readiness,
    engine_runner,
    strategy_loader,
)
from quant_strategies.runner.artifact_profiles import normalized_rows_sha256, write_summary_profile_artifact
from quant_strategies.runner.decision_adapter import decisions_to_signal_rows
from quant_strategies.runner.errors import RunnerError


@dataclass(frozen=True)
class RunResult:
    success: bool
    result_dir: Path | None
    notes_path: Path | None
    message: str
    run_completed: bool = False
    assessment_status: str = "runner_failed"
    promotion_eligible: bool = False


def run_config(config_path: str | Path, *, repo_root: Path | None = None) -> RunResult:
    effective_repo_root = Path(repo_root).resolve() if repo_root is not None else config_module.default_repo_root()
    try:
        config_file = config_module.resolve_config_path(config_path, repo_root=effective_repo_root)
        config = config_module.load_config(config_file, repo_root=effective_repo_root)
    except RunnerError as exc:
        return RunResult(success=False, result_dir=None, notes_path=None, message=str(exc))

    result_dir = artifacts.create_result_dir(config)
    artifacts.initialize_run_artifacts(config_file, config, result_dir)

    try:
        generate_decisions = strategy_loader.load_strategy(config.strategy_path, repo_root=effective_repo_root)
    except RunnerError as exc:
        return _failure_result(config, result_dir, "strategy_import", str(exc), repo_root=effective_repo_root)

    try:
        validated_params = validate_strategy_params(generate_decisions, config.params)
    except Exception as exc:
        return _failure_result(
            config,
            result_dir,
            "param_validation",
            f"param validation failed: {exc}",
            repo_root=effective_repo_root,
        )

    try:
        loaded = data_loader.load_data(config)
        normalized_rows_hash = normalized_rows_sha256(loaded.rows)
        strategy_input_rows_jsonl_sha256 = None
        if config.output.artifact_profile == "full":
            strategy_input_rows_jsonl_sha256 = artifacts.write_strategy_input_rows(result_dir, loaded.rows)
        artifacts.write_data_manifest(
            result_dir,
            config,
            loaded.rows,
            strategy_input_rows_jsonl_sha256=strategy_input_rows_jsonl_sha256,
            normalized_rows_hash=normalized_rows_hash,
        )
    except RunnerError as exc:
        return _failure_result(config, result_dir, "data_load", str(exc), repo_root=effective_repo_root)

    try:
        decision_output = generate_decisions(frozen_rows(loaded.rows), frozen_params(validated_params))
        decisions = _validated_decisions(decision_output, strategy_id=config.strategy_id)
        signals = decisions_to_signal_rows(decisions)
        if config.output.artifact_profile == "full":
            artifacts.write_decision_records(result_dir, decisions)
            artifacts.write_signals(result_dir, signals)
    except Exception as exc:
        return _failure_result(
            config,
            result_dir,
            "decision_generation",
            f"strategy execution failed: {exc}",
            repo_root=effective_repo_root,
        )

    try:
        data_readiness.assert_decision_rows_ready(loaded.rows, signals)
    except RunnerError as exc:
        return _failure_result(config, result_dir, "data_readiness", str(exc), repo_root=effective_repo_root)

    try:
        request = engine_runner.build_request(
            strategy_id=config.strategy_id,
            rows=loaded.rows,
            signals=signals,
            fill_model=config.fill_model,
            cost_model=config.cost_model,
        )
        if config.output.artifact_profile == "full":
            artifacts.write_engine_request(result_dir, engine_runner.request_json(request))
    except RunnerError as exc:
        return _failure_result(config, result_dir, "request_build", str(exc), repo_root=effective_repo_root)

    try:
        engine_run = engine_runner.evaluate_request(
            request,
            mode=config.output.mode,
            include_evidence=config.output.artifact_profile == "full",
        )
    except RunnerError as exc:
        return _failure_result(config, result_dir, "engine_evaluation", str(exc), repo_root=effective_repo_root)

    engine_summary = _compact_engine_summary(engine_run)
    if config.output.artifact_profile == "full" and engine_run.evidence_json:
        artifacts.write_evidence(result_dir, engine_run.evidence_json)
    if config.output.artifact_profile == "summary":
        write_summary_profile_artifact(
            result_dir,
            config=config,
            rows=loaded.rows,
            decisions=decisions,
            signals=signals,
            engine=engine_summary,
            normalized_rows_hash=normalized_rows_hash,
        )
    notes = _completion_notes(config, engine_run)
    artifacts.write_notes(result_dir, notes)
    artifacts.write_run_manifest(
        result_dir,
        repo_root=effective_repo_root,
        evidence=runner_evidence_semantics(config.data.kind),
        artifact_profile=config.output.artifact_profile,
    )
    success = _result_success(engine_run)
    assessment_status = _assessment_status(engine_run)
    artifacts.write_summary(
        result_dir,
        _summary_payload(
            config,
            success=success,
            status=_result_status(engine_run),
            stage="completed",
            message=notes.strip(),
            engine=engine_summary,
            assessment_status=assessment_status,
        ),
    )
    return RunResult(
        success=success,
        result_dir=result_dir,
        notes_path=result_dir / "notes.md",
        message=notes.strip(),
        run_completed=True,
        assessment_status=assessment_status,
        promotion_eligible=False,
    )


def _failure_result(
    config: config_module.RunConfig,
    result_dir: Path,
    stage: str,
    message: str,
    *,
    repo_root: Path,
) -> RunResult:
    notes = _failure_notes(stage, message)
    artifacts.write_notes(result_dir, notes)
    artifacts.write_run_manifest(
        result_dir,
        repo_root=repo_root,
        evidence=runner_evidence_semantics(config.data.kind),
        artifact_profile=config.output.artifact_profile,
    )
    artifacts.write_summary(
        result_dir,
        _summary_payload(
            config,
            success=False,
            status="failed",
            stage=stage,
            message=message,
            engine={"passed": None, "trade_count": None},
            assessment_status="runner_failed",
        ),
    )
    return RunResult(
        success=False,
        result_dir=result_dir,
        notes_path=result_dir / "notes.md",
        message=notes.strip(),
        run_completed=True,
        assessment_status="runner_failed",
        promotion_eligible=False,
    )


def _validated_decisions(output: object, *, strategy_id: str) -> list[StrategyDecision]:
    decisions, violations = validate_decision_output(output, strategy_id=strategy_id)
    if violations:
        raise ValueError("; ".join(violations))
    return decisions


def _summary_payload(
    config: config_module.RunConfig,
    *,
    success: bool,
    status: str,
    stage: str,
    message: str,
    engine: dict[str, object],
    assessment_status: str,
) -> dict[str, object]:
    semantics = runner_evidence_semantics(config.data.kind)
    engine_payload = dict(engine)
    engine_payload.setdefault(
        "smoke_score",
        {
            "sum_weighted_trade_gross_return": None,
            "sum_weighted_trade_funding_return": None,
            "sum_weighted_trade_cost_return": None,
            "sum_weighted_trade_net_return": None,
        },
    )
    return {
        "strategy_id": config.strategy_id,
        "mode": config.output.mode,
        "artifact_profile": config.output.artifact_profile,
        "success": success,
        "status": status,
        "stage": stage,
        "message": message,
        "artifacts": [],
        "engine": engine_payload,
        "run_completed": True,
        "assessment_status": assessment_status,
        **semantics,
    }


def _trade_count(engine_run: engine_runner.EngineRun) -> int | None:
    if engine_run.screen_summary is not None:
        value = engine_run.screen_summary.get("trade_count")
        return int(value) if value is not None else None
    if engine_run.validate_summary is not None:
        screening_result = engine_run.validate_summary.get("screening_result")
        if isinstance(screening_result, dict):
            value = screening_result.get("trade_count")
            return int(value) if value is not None else None
    return None


def _compact_engine_summary(engine_run: engine_runner.EngineRun) -> dict[str, object]:
    source = engine_run.screen_summary
    if source is None and engine_run.validate_summary is not None:
        screening_result = engine_run.validate_summary.get("screening_result")
        source = screening_result if isinstance(screening_result, dict) else None

    summary: dict[str, object] = {"passed": engine_run.passed, "trade_count": _trade_count(engine_run)}
    smoke_score = source.get("smoke_score") if isinstance(source, dict) else None
    if isinstance(smoke_score, dict):
        summary["smoke_score"] = {
            "sum_weighted_trade_gross_return": smoke_score.get("sum_weighted_trade_gross_return"),
            "sum_weighted_trade_funding_return": smoke_score.get("sum_weighted_trade_funding_return"),
            "sum_weighted_trade_cost_return": smoke_score.get("sum_weighted_trade_cost_return"),
            "sum_weighted_trade_net_return": smoke_score.get("sum_weighted_trade_net_return"),
        }
    else:
        summary["smoke_score"] = {
            "sum_weighted_trade_gross_return": None,
            "sum_weighted_trade_funding_return": None,
            "sum_weighted_trade_cost_return": None,
            "sum_weighted_trade_net_return": None,
        }
    if engine_run.validate_summary is not None:
        gates = engine_run.validate_summary.get("gates")
        if isinstance(gates, list):
            summary["gates"] = [
                {"name": gate.get("name"), "passed": gate.get("passed"), "detail": gate.get("detail")}
                for gate in gates
                if isinstance(gate, dict)
            ]
    return summary


def _failure_notes(stage: str, message: str) -> str:
    return f"# Run Failed\n\nstage: {stage}\nmessage: {message}\n"


def _result_success(engine_run: engine_runner.EngineRun) -> bool:
    if engine_run.mode == "screen":
        return True
    return bool(engine_run.passed)


def _result_status(engine_run: engine_runner.EngineRun) -> str:
    if engine_run.mode == "screen":
        return "screened"
    return "passed" if engine_run.passed else "failed"


def _assessment_status(engine_run: engine_runner.EngineRun) -> str:
    if engine_run.mode == "screen":
        return "screened"
    return "smoke_passed" if engine_run.passed else "smoke_failed"


def _completion_notes(config: config_module.RunConfig, engine_run: engine_runner.EngineRun) -> str:
    lines = [
        "# Run Complete",
        "",
        f"strategy_id: {config.strategy_id}",
        f"mode: {engine_run.mode}",
    ]
    if engine_run.mode == "screen":
        lines.append("status: screened")
        interpretation = (
            "runner screen evidence only; not validation pass, market robustness, "
            "or promotion evidence."
        )
    else:
        status = "passed" if engine_run.passed else "failed validation gates"
        lines.append(f"status: {status}")
        interpretation = "runner smoke evidence only; not market robustness or promotion evidence."
    if config.data.kind == "crypto_perp_funding":
        lines.append(
            "return_scope: price-and-funding; supplied funding events are included "
            "when they fall inside engine-held intervals."
        )
    lines.append(f"interpretation: {interpretation}")
    return "\n".join(lines) + "\n"


__all__ = ["RunResult", "run_config"]
