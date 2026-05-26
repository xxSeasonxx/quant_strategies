from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from quant_strategies.decisions import StrategyDecision
from quant_strategies.runner import data_loader
from quant_strategies.runner.config import default_repo_root
from quant_strategies.validation.artifacts import (
    create_validation_result_dir,
    write_json_artifact,
    write_text_artifact,
)
from quant_strategies.validation.backends import (
    BackendRunResult,
    ScenarioBackendRunResult,
    ValidationBackend,
    get_backend,
)
from quant_strategies.validation.config import load_validation_config
from quant_strategies.validation.config import resolve_validation_config_path
from quant_strategies.validation.data_audit import audit_decision_rows
from quant_strategies.validation.matrix import MatrixScenario, expand_validation_matrix
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
    config_path = resolve_validation_config_path(package_or_config_path, repo_root=root)
    config = load_validation_config(config_path, repo_root=root)
    result_dir = create_validation_result_dir(config.output.results_dir, config.strategy_id)
    _write_static_validation_artifacts(result_dir=result_dir, config=config, config_path=config_path)

    all_decisions: list[StrategyDecision] = []
    backend_results: list[ScenarioBackendRunResult] = []
    data_audits: list[dict[str, Any]] = []
    min_trades = 10
    failure_reasons: list[str] = []
    required_scenario_ids: list[str] = []

    try:
        selected_backend = backend or get_backend(config.backend)
    except BaseException as exc:
        _raise_interrupt(exc)
        decision = PromotionDecision(decision="hard_no", reasons=("backend_selection_failed",))
        _write_validation_artifacts(
            result_dir=result_dir,
            decisions=all_decisions,
            data_audits=data_audits,
            backend_results=backend_results,
            decision=decision,
        )
        return _validation_result(result_dir, decision)

    try:
        generate_decisions = load_decision_strategy(config.strategy_path, repo_root=root)
    except BaseException as exc:
        _raise_interrupt(exc)
        decision = PromotionDecision(decision="hard_no", reasons=("strategy_import_failed",))
        _write_validation_artifacts(
            result_dir=result_dir,
            decisions=all_decisions,
            data_audits=data_audits,
            backend_results=backend_results,
            decision=decision,
        )
        return _validation_result(result_dir, decision)

    for window in config.windows:
        run_config = config.to_run_config(window, results_dir=result_dir / "runner_smoke" / window.id)
        try:
            loaded = data_loader.load_data(run_config)
        except BaseException as exc:
            _raise_interrupt(exc)
            data_audits.append(
                _failed_data_audit(
                    window.id,
                    row_count=0,
                    decision_count=0,
                    violations=(f"data_load_failed: {exc}",),
                )
            )
            continue

        try:
            decision_output = generate_decisions(loaded.rows, config.params)
        except BaseException as exc:
            _raise_interrupt(exc)
            failure_reasons.append("strategy_generation_failed")
            data_audits.append(
                _failed_data_audit(
                    window.id,
                    row_count=len(loaded.rows),
                    decision_count=0,
                    violations=(f"strategy_generation_failed: {exc}",),
                )
            )
            continue

        decisions, violations = _validate_decisions(decision_output, strategy_id=config.strategy_id)
        if violations:
            data_audits.append(
                _failed_data_audit(
                    window.id,
                    row_count=len(loaded.rows),
                    decision_count=len(decisions),
                    violations=violations,
                )
            )
            continue

        all_decisions.extend(decisions)
        try:
            audit = audit_decision_rows(loaded.rows, decisions)
        except BaseException as exc:
            _raise_interrupt(exc)
            failure_reasons.append("data_audit_failed")
            data_audits.append(
                _failed_data_audit(
                    window.id,
                    row_count=len(loaded.rows),
                    decision_count=len(decisions),
                    violations=(f"data_audit_failed: {exc}",),
                )
            )
            continue

        data_audits.append({"window_id": window.id, **audit.model_dump(mode="json")})
        if audit.passed:
            scenarios = expand_validation_matrix(
                window_id=window.id,
                base_params=_plain_mapping(config.params),
                base_costs=_plain_mapping(config.cost_model),
                base_fill=_plain_mapping(config.fill_model),
            )
            required_scenario_ids.extend(scenario.id for scenario in scenarios if scenario.required)
            for scenario in scenarios:
                scenario_config = _scenario_config(config=config, scenario=scenario)
                try:
                    raw_backend_result = selected_backend.run(
                        decisions=decisions,
                        rows=loaded.rows,
                        config=scenario_config,
                    )
                except BaseException as exc:
                    _raise_interrupt(exc)
                    backend_result = _failed_backend_result(
                        _backend_name(selected_backend, config.backend),
                        f"backend_exception: {exc}",
                    )
                else:
                    try:
                        backend_result = BackendRunResult.model_validate(raw_backend_result)
                    except BaseException as exc:
                        _raise_interrupt(exc)
                        backend_result = _failed_backend_result(
                            _backend_name(selected_backend, config.backend),
                            f"invalid_backend_result: {exc}",
                        )
                backend_results.append(
                    ScenarioBackendRunResult(
                        window_id=window.id,
                        scenario_id=scenario.id,
                        required=scenario.required,
                        result=backend_result,
                    )
                )

    data_passed = all(audit["passed"] for audit in data_audits)
    if failure_reasons:
        decision = PromotionDecision(
            decision="hard_no",
            reasons=tuple(dict.fromkeys(failure_reasons)),
        )
    else:
        decision = classify_validation(
            data_passed=data_passed,
            backend_results=backend_results,
            min_trades=min_trades,
            required_scenario_ids=tuple(required_scenario_ids),
        )
    _write_validation_artifacts(
        result_dir=result_dir,
        decisions=all_decisions,
        data_audits=data_audits,
        backend_results=backend_results,
        decision=decision,
    )
    return _validation_result(result_dir, decision)


def _validation_result(result_dir: Path, decision: PromotionDecision) -> ValidationRunResult:
    return ValidationRunResult(
        success=decision.decision == "clear_yes",
        result_dir=result_dir,
        decision=decision,
        message=f"validation decision: {decision.decision}",
    )


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


def _validate_decisions(
    output: object,
    *,
    strategy_id: str,
) -> tuple[list[StrategyDecision], tuple[str, ...]]:
    if (
        isinstance(output, str | bytes | bytearray)
        or isinstance(output, Mapping)
        or not isinstance(output, Sequence)
    ):
        return [], ("invalid_decision_output",)

    decisions: list[StrategyDecision] = []
    violations: list[str] = []
    for index, item in enumerate(output):
        if not isinstance(item, StrategyDecision):
            violations.append(f"invalid_decision_output[{index}]")
            continue
        if item.strategy_id != strategy_id:
            violations.append(
                f"decision_strategy_id_mismatch[{index}]: expected {strategy_id}, got {item.strategy_id}"
            )
            continue
        decisions.append(item)

    return decisions, tuple(violations)


def _plain_mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return dict(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return dict(value)
    return dict(vars(value))


def _scenario_config(*, config: Any, scenario: MatrixScenario) -> SimpleNamespace:
    return SimpleNamespace(
        scenario_id=scenario.id,
        params={**_plain_mapping(config.params), **scenario.params},
        cost_model=SimpleNamespace(
            **{**_plain_mapping(config.cost_model), **scenario.cost_model}
        ),
        fill_model=SimpleNamespace(
            **{**_plain_mapping(config.fill_model), **scenario.fill_model}
        ),
        data=SimpleNamespace(**_plain_mapping(config.data)),
    )


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
    decisions: list[StrategyDecision],
    data_audits: list[dict[str, Any]],
    backend_results: list[ScenarioBackendRunResult],
    decision: PromotionDecision,
) -> None:
    decision_lines = [item.model_dump_json() for item in decisions]
    write_text_artifact(result_dir, "decision_records.jsonl", "\n".join(decision_lines))
    write_json_artifact(result_dir, "data_audit.json", {"windows": data_audits})
    write_json_artifact(
        result_dir,
        "backend_runs/summary.json",
        {
            "results": [
                {
                    "window_id": item.window_id,
                    "scenario_id": item.scenario_id,
                    "required": item.required,
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
                    "required": item.required,
                    "backend": item.result.backend,
                    "status": item.result.status,
                    "metrics": item.result.metrics,
                    "warnings": item.result.warnings,
                    "unsupported_semantics": item.result.unsupported_semantics,
                    "classification_reasons": _scenario_classification_reasons(item),
                }
                for item in backend_results
            ],
        },
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


def _scenario_classification_reasons(item: ScenarioBackendRunResult) -> tuple[str, ...]:
    result = item.result
    if result.status == "failed":
        return (f"{result.backend}_failed",)
    if result.status == "unavailable":
        return ("backend_unavailable",)
    if result.status == "unsupported" or result.unsupported_semantics:
        return ("unsupported_semantics",)
    return ()


def _raise_interrupt(exc: BaseException) -> None:
    if isinstance(exc, KeyboardInterrupt):
        raise exc
