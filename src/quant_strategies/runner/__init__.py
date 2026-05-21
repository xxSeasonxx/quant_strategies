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
    config_file = Path(config_path)
    effective_repo_root = Path(repo_root).resolve() if repo_root is not None else config_module.default_repo_root()
    try:
        config = config_module.load_config(config_file, repo_root=effective_repo_root)
    except RunnerError as exc:
        return RunResult(success=False, result_dir=None, notes_path=None, message=str(exc))

    result_dir = artifacts.create_result_dir(config)
    artifacts.initialize_run_artifacts(config_file, config, result_dir)

    try:
        loaded = data_loader.load_data(config)
        generate_signals = strategy_loader.load_strategy(config.strategy_path, repo_root=effective_repo_root)
        signals = generate_signals(loaded.rows, config.params)
        request = engine_runner.build_request(
            strategy_id=config.strategy_id,
            rows=loaded.rows,
            signals=signals,
            fill_model=config.fill_model,
            cost_model=config.cost_model,
        )
        engine_run = engine_runner.evaluate_request(request, mode=config.output.mode)
        notes = _success_notes(config.strategy_id, config.output.mode, engine_run.passed)
        artifacts.write_success_artifacts(
            result_dir,
            bars=engine_runner.bars_for_artifact(request),
            signals=engine_runner.signals_for_artifact(request),
            request_json=engine_runner.request_json(request),
            screen_summary=engine_run.screen_summary,
            validate_summary=engine_run.validate_summary,
            evidence_json=engine_run.evidence_json,
            notes=notes,
        )
        return RunResult(
            success=engine_run.passed,
            result_dir=result_dir,
            notes_path=result_dir / "notes.md",
            message=notes.strip(),
        )
    except RunnerError as exc:
        notes = f"# Run Failed\n\n{exc}\n"
    except Exception as exc:
        notes = f"# Run Failed\n\nstrategy execution failed: {exc}\n"

    artifacts.write_notes(result_dir, notes)
    return RunResult(success=False, result_dir=result_dir, notes_path=result_dir / "notes.md", message=notes.strip())


def _success_notes(strategy_id: str, mode: str, passed: bool) -> str:
    status = "passed" if passed else "failed validation gates"
    return f"# Run Complete\n\nstrategy_id: {strategy_id}\nmode: {mode}\nstatus: {status}\n"


__all__ = ["RunResult", "run_config"]
