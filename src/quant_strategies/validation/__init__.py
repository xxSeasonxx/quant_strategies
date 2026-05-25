from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quant_strategies.decisions import StrategyDecision
from quant_strategies.runner import data_loader
from quant_strategies.runner.config import default_repo_root
from quant_strategies.validation.artifacts import (
    create_validation_result_dir,
    write_json_artifact,
    write_text_artifact,
)
from quant_strategies.validation.backends import ValidationBackend, get_backend
from quant_strategies.validation.config import load_validation_config
from quant_strategies.validation.data_audit import audit_decision_rows
from quant_strategies.validation.policy import PromotionDecision, classify_validation
from quant_strategies.validation.strategy_loader import load_decision_strategy


@dataclass(frozen=True)
class ValidationRunResult:
    success: bool
    result_dir: Path | None
    decision: PromotionDecision
    message: str


def run_validation(
    package_or_config_path: str | Path,
    *,
    repo_root: Path | None = None,
    backend: ValidationBackend | None = None,
) -> ValidationRunResult:
    root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
    config = load_validation_config(package_or_config_path, repo_root=root)
    selected_backend = backend or get_backend(config.backend)
    result_dir = create_validation_result_dir(config.output.results_dir, config.strategy_id)
    generate_decisions = load_decision_strategy(config.strategy_path, repo_root=root)

    all_decisions: list[StrategyDecision] = []
    backend_results = []
    data_audits = []
    min_trades = 10

    for window in config.windows:
        run_config = config.to_run_config(window, results_dir=result_dir / "runner_smoke" / window.id)
        loaded = data_loader.load_data(run_config)
        if not loaded.rows:
            data_audits.append(
                {
                    "window_id": window.id,
                    "row_count": 0,
                    "decision_count": 0,
                    "passed": False,
                    "violations": ("no_rows_loaded",),
                }
            )
            continue
        decisions = generate_decisions(loaded.rows, config.params)
        all_decisions.extend(decisions)
        audit = audit_decision_rows(loaded.rows, decisions)
        data_audits.append({"window_id": window.id, **audit.model_dump(mode="json")})
        if audit.passed:
            backend_results.append(
                selected_backend.run(decisions=decisions, rows=loaded.rows, config=config)
            )

    data_passed = all(audit["passed"] for audit in data_audits)
    decision = classify_validation(
        data_passed=data_passed,
        backend_results=backend_results,
        min_trades=min_trades,
    )
    _write_validation_artifacts(
        result_dir=result_dir,
        decisions=all_decisions,
        data_audits=data_audits,
        backend_results=backend_results,
        decision=decision,
    )
    return ValidationRunResult(
        success=decision.decision == "clear_yes",
        result_dir=result_dir,
        decision=decision,
        message=f"validation decision: {decision.decision}",
    )


def _write_validation_artifacts(
    *,
    result_dir: Path,
    decisions: list[StrategyDecision],
    data_audits: list[dict[str, Any]],
    backend_results: list[Any],
    decision: PromotionDecision,
) -> None:
    decision_lines = [item.model_dump_json() for item in decisions]
    write_text_artifact(result_dir, "decision_records.jsonl", "\n".join(decision_lines))
    write_json_artifact(result_dir, "data_audit.json", {"windows": data_audits})
    write_json_artifact(
        result_dir,
        "backend_runs/summary.json",
        {"results": [result.model_dump(mode="json") for result in backend_results]},
    )
    write_json_artifact(
        result_dir,
        "promotion_decision.json",
        decision.model_dump(mode="json"),
    )
    write_text_artifact(
        result_dir,
        "validation_report.md",
        f"# Validation Report\n\nDecision: `{decision.decision}`\n\n"
        f"Reasons: {', '.join(decision.reasons) or 'none'}\n",
    )
