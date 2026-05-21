from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quant_strategies.runner import artifacts, config as config_module, data_loader, engine_runner, strategy_loader
from quant_strategies.runner.errors import RunnerError


@dataclass(frozen=True)
class RunResult:
    success: bool
    result_dir: Path | None
    notes_path: Path | None
    message: str


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
        generate_signals = strategy_loader.load_strategy(config.strategy_path, repo_root=effective_repo_root)
    except RunnerError as exc:
        return _failure_result(config, result_dir, "strategy_import", str(exc))

    try:
        loaded = data_loader.load_data(config)
        artifacts.write_strategy_input_rows(result_dir, loaded.rows)
    except RunnerError as exc:
        return _failure_result(config, result_dir, "data_load", str(exc))

    try:
        signals = generate_signals(loaded.rows, config.params)
        artifacts.write_signals(result_dir, signals)
    except Exception as exc:
        return _failure_result(config, result_dir, "signal_generation", f"strategy execution failed: {exc}")

    try:
        request = engine_runner.build_request(
            strategy_id=config.strategy_id,
            rows=loaded.rows,
            signals=signals,
            fill_model=config.fill_model,
            cost_model=config.cost_model,
        )
        artifacts.write_engine_request(result_dir, engine_runner.request_json(request))
    except RunnerError as exc:
        return _failure_result(config, result_dir, "request_build", str(exc))

    try:
        engine_run = engine_runner.evaluate_request(request, mode=config.output.mode)
    except RunnerError as exc:
        return _failure_result(config, result_dir, "engine_evaluation", str(exc))

    if engine_run.evidence_json:
        artifacts.write_evidence(result_dir, engine_run.evidence_json)
    notes = _success_notes(config.strategy_id, config.output.mode, engine_run.passed)
    artifacts.write_notes(result_dir, notes)
    artifacts.write_summary(
        result_dir,
        _summary_payload(
            config,
            success=engine_run.passed,
            status="passed" if engine_run.passed else "failed",
            stage="completed",
            message=notes.strip(),
            engine={"passed": engine_run.passed, "trade_count": _trade_count(engine_run)},
        ),
    )
    return RunResult(
        success=engine_run.passed,
        result_dir=result_dir,
        notes_path=result_dir / "notes.md",
        message=notes.strip(),
    )


def _failure_result(config: config_module.RunConfig, result_dir: Path, stage: str, message: str) -> RunResult:
    notes = _failure_notes(stage, message)
    artifacts.write_notes(result_dir, notes)
    artifacts.write_summary(
        result_dir,
        _summary_payload(
            config,
            success=False,
            status="failed",
            stage=stage,
            message=message,
            engine={"passed": None, "trade_count": None},
        ),
    )
    return RunResult(success=False, result_dir=result_dir, notes_path=result_dir / "notes.md", message=notes.strip())


def _summary_payload(
    config: config_module.RunConfig,
    *,
    success: bool,
    status: str,
    stage: str,
    message: str,
    engine: dict[str, object],
) -> dict[str, object]:
    return {
        "strategy_id": config.strategy_id,
        "mode": config.output.mode,
        "success": success,
        "status": status,
        "stage": stage,
        "message": message,
        "artifacts": [],
        "engine": engine,
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


def _failure_notes(stage: str, message: str) -> str:
    return f"# Run Failed\n\nstage: {stage}\nmessage: {message}\n"


def _success_notes(strategy_id: str, mode: str, passed: bool) -> str:
    status = "passed" if passed else "failed validation gates"
    return (
        "# Run Complete\n\n"
        f"strategy_id: {strategy_id}\n"
        f"mode: {mode}\n"
        f"status: {status}\n"
        "interpretation: runner smoke evidence only; not market robustness or promotion evidence.\n"
    )


__all__ = ["RunResult", "run_config"]
