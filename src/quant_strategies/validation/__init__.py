from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from quant_strategies.boundary import frozen_params, frozen_rows
from quant_strategies.decisions import (
    StrategyDecision,
    validate_decision_output,
    validate_strategy_params,
)
from quant_strategies.provenance import file_sha256
from quant_strategies.runner import data_loader
from quant_strategies.runner.config import default_repo_root
from quant_strategies.validation.artifacts import (
    create_validation_result_dir,
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
from quant_strategies.validation.capabilities import backend_capability_matrix
from quant_strategies.validation.config import load_validation_config
from quant_strategies.validation.config import resolve_validation_config_path
from quant_strategies.validation.data_audit import audit_decision_rows
from quant_strategies.validation.manifest import rows_sha256, write_validation_manifest
from quant_strategies.validation.matrix import MatrixScenario, expand_validation_matrix
from quant_strategies.validation.policy import ValidationPolicyDecision, classify_validation
from quant_strategies.validation.readiness import check_validation_readiness
from quant_strategies.validation.research_manifest import check_research_manifest
from quant_strategies.validation.strategy_loader import load_decision_strategy


@dataclass(frozen=True)
class ValidationRunResult:
    success: bool
    result_dir: Path | None
    decision: ValidationPolicyDecision
    message: str


@dataclass(frozen=True)
class _ScenarioDecisionOutcome:
    decisions: list[StrategyDecision]
    decision_generation_status: DecisionGenerationStatus
    decisions_regenerated: bool
    failure: BackendRunResult | None = None


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
    data_provenance: list[dict[str, Any]] = []
    min_trades = 10
    failure_reasons: list[str] = []
    required_scenario_ids: list[str] = []
    backend_name = config.backend
    research_manifest = check_research_manifest(
        config_path=config_path,
        strategy_path=config.strategy_path,
        repo_root=root,
    )
    if not research_manifest["passed"]:
        return _failure_result(
            result_dir=result_dir,
            repo_root=root,
            config=config,
            config_path=config_path,
            backend_name=backend_name,
            decisions=all_decisions,
            data_audits=data_audits,
            data_provenance=data_provenance,
            backend_results=backend_results,
            research_manifest=research_manifest,
            reason="research_manifest_integrity_failed",
        )

    if research_manifest.get("is_researched_package") and config.readiness is None:
        data_audits.append(
            _failed_data_audit(
                "config",
                row_count=0,
                decision_count=0,
                violations=("validation_readiness_metadata_missing",),
            )
        )
        return _failure_result(
            result_dir=result_dir,
            repo_root=root,
            config=config,
            config_path=config_path,
            backend_name=backend_name,
            decisions=all_decisions,
            data_audits=data_audits,
            data_provenance=data_provenance,
            backend_results=backend_results,
            research_manifest=research_manifest,
            reason="validation_readiness_failed",
        )

    try:
        selected_backend = backend or get_backend(config.backend)
        backend_name = _backend_name(selected_backend, config.backend)
    except Exception as exc:
        return _failure_result(
            result_dir=result_dir,
            repo_root=root,
            config=config,
            config_path=config_path,
            backend_name=backend_name,
            decisions=all_decisions,
            data_audits=data_audits,
            data_provenance=data_provenance,
            backend_results=backend_results,
            research_manifest=research_manifest,
            reason="backend_selection_failed",
        )

    try:
        generate_decisions = load_decision_strategy(config.strategy_path, repo_root=root)
    except Exception as exc:
        return _failure_result(
            result_dir=result_dir,
            repo_root=root,
            config=config,
            config_path=config_path,
            backend_name=backend_name,
            decisions=all_decisions,
            data_audits=data_audits,
            data_provenance=data_provenance,
            backend_results=backend_results,
            research_manifest=research_manifest,
            reason="strategy_import_failed",
        )

    try:
        base_params = validate_strategy_params(generate_decisions, config.params)
    except Exception as exc:
        data_audits.append(
            _failed_data_audit(
                "config",
                row_count=0,
                decision_count=0,
                violations=(f"param_validation_failed: {exc}",),
            )
        )
        return _failure_result(
            result_dir=result_dir,
            repo_root=root,
            config=config,
            config_path=config_path,
            backend_name=backend_name,
            decisions=all_decisions,
            data_audits=data_audits,
            data_provenance=data_provenance,
            backend_results=backend_results,
            research_manifest=research_manifest,
            reason="param_validation_failed",
        )

    for window in config.windows:
        run_config = config.to_run_config(window, results_dir=result_dir / "runner_smoke" / window.id)
        try:
            loaded = data_loader.load_data(run_config)
        except Exception as exc:
            data_provenance.append(
                _data_provenance(
                    window.id,
                    run_config,
                    status="failed",
                    rows=None,
                    message=str(exc),
                )
            )
            data_audits.append(
                _failed_data_audit(
                    window.id,
                    row_count=0,
                    decision_count=0,
                    violations=(f"data_load_failed: {exc}",),
                )
            )
            continue
        data_provenance.append(
            _data_provenance(window.id, run_config, status="loaded", rows=loaded.rows)
        )
        strategy_rows = frozen_rows(loaded.rows)

        try:
            decision_output = generate_decisions(strategy_rows, frozen_params(base_params))
        except Exception as exc:
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

        decisions, violations = validate_decision_output(decision_output, strategy_id=config.strategy_id)
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
            audit = audit_decision_rows(strategy_rows, decisions)
        except Exception as exc:
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

        audit_payload = {"window_id": window.id, **audit.model_dump(mode="json")}
        if audit.passed and config.readiness is not None:
            readiness_violations = check_validation_readiness(decisions, config.readiness)
            if readiness_violations:
                failure_reasons.append("validation_readiness_failed")
                audit_payload["passed"] = False
                audit_payload["violations"] = list(audit.violations) + list(readiness_violations)

        data_audits.append(audit_payload)
        if audit_payload["passed"]:
            scenarios = expand_validation_matrix(
                window_id=window.id,
                base_params=_plain_mapping(base_params),
                base_costs=_plain_mapping(config.cost_model),
                base_fill=_plain_mapping(config.fill_model),
            )
            required_scenario_ids.extend(scenario.id for scenario in scenarios if scenario.required)
            for scenario in scenarios:
                scenario_config = _scenario_config(
                    config=config,
                    scenario=scenario,
                    base_params=base_params,
                )
                decision_outcome = _scenario_decision_outcome(
                    scenario=scenario,
                    generate_decisions=generate_decisions,
                    base_decisions=decisions,
                    rows=loaded.rows,
                    strategy_id=config.strategy_id,
                    scenario_config=scenario_config,
                    readiness=config.readiness,
                    backend_name=backend_name,
                )
                backend_result = decision_outcome.failure
                decision_records_path = None
                decision_records_sha256 = None
                if backend_result is None:
                    decision_records_path, decision_records_sha256 = _write_scenario_decision_records(
                        result_dir=result_dir,
                        scenario_id=scenario.id,
                        decisions=decision_outcome.decisions,
                    )
                    try:
                        raw_backend_result = selected_backend.run(
                            decisions=list(decision_outcome.decisions),
                            rows=frozen_rows(loaded.rows),
                            config=scenario_config,
                        )
                    except Exception as exc:
                        backend_result = _failed_backend_result(
                            backend_name,
                            f"backend_exception: {exc}",
                        )
                    else:
                        try:
                            backend_result = BackendRunResult.model_validate(raw_backend_result)
                        except Exception as exc:
                            backend_result = _failed_backend_result(
                                backend_name,
                                f"invalid_backend_result: {exc}",
                            )
                backend_results.append(
                    ScenarioBackendRunResult(
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
                    )
                )

    data_passed = all(audit["passed"] for audit in data_audits)
    if failure_reasons:
        decision = _hard_no_decision(failure_reasons)
    else:
        decision = classify_validation(
            data_passed=data_passed,
            backend_results=backend_results,
            min_trades=min_trades,
            required_scenario_ids=tuple(required_scenario_ids),
            paper_readiness=config.paper_readiness,
        )
    _write_validation_artifacts(
        result_dir=result_dir,
        repo_root=root,
        config=config,
        config_path=config_path,
        backend_name=backend_name,
        decisions=all_decisions,
        data_audits=data_audits,
        data_provenance=data_provenance,
        backend_results=backend_results,
        decision=decision,
        research_manifest=research_manifest,
    )
    return _validation_result(result_dir, decision)


def _validation_result(result_dir: Path, decision: ValidationPolicyDecision) -> ValidationRunResult:
    return ValidationRunResult(
        success=decision.decision in {"mechanical_pass", "watchlist", "paper_candidate"},
        result_dir=result_dir,
        decision=decision,
        message=f"validation decision: {decision.decision}",
    )


def _hard_no_decision(reasons: str | Sequence[str]) -> ValidationPolicyDecision:
    reason_tuple = (reasons,) if isinstance(reasons, str) else tuple(dict.fromkeys(reasons))
    return ValidationPolicyDecision(
        decision="hard_no",
        reasons=reason_tuple,
        failed_gates=reason_tuple,
        gate_details={reason: "failed" for reason in reason_tuple},
    )


def _failure_result(
    *,
    result_dir: Path,
    repo_root: Path,
    config: Any,
    config_path: Path,
    backend_name: str,
    decisions: list[StrategyDecision],
    data_audits: list[dict[str, Any]],
    data_provenance: list[dict[str, Any]],
    backend_results: list[ScenarioBackendRunResult],
    research_manifest: dict[str, Any],
    reason: str,
) -> ValidationRunResult:
    decision = _hard_no_decision(reason)
    _write_validation_artifacts(
        result_dir=result_dir,
        repo_root=repo_root,
        config=config,
        config_path=config_path,
        backend_name=backend_name,
        decisions=decisions,
        data_audits=data_audits,
        data_provenance=data_provenance,
        backend_results=backend_results,
        decision=decision,
        research_manifest=research_manifest,
    )
    return _validation_result(result_dir, decision)


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
    run_config: Any,
    *,
    status: str,
    rows: Sequence[Mapping[str, Any]] | None,
    message: str | None = None,
) -> dict[str, Any]:
    payload = {
        "window_id": window_id,
        "status": status,
        "data": {
            "kind": run_config.data.kind,
            "dataset": run_config.data.dataset,
            "symbols": list(run_config.data.symbols),
            "start": run_config.data.start.isoformat(),
            "end": run_config.data.end.isoformat(),
            "strict": run_config.data.strict,
        },
        "row_count": 0 if rows is None else len(rows),
        "rows_sha256": None if rows is None else rows_sha256(rows),
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
) -> SimpleNamespace:
    return SimpleNamespace(
        scenario_id=scenario.id,
        params={**_plain_mapping(base_params), **scenario.params},
        cost_model=SimpleNamespace(
            **{**_plain_mapping(config.cost_model), **scenario.cost_model}
        ),
        fill_model=SimpleNamespace(
            **{**_plain_mapping(config.fill_model), **scenario.fill_model}
        ),
        data=SimpleNamespace(**_plain_mapping(config.data)),
    )


def _scenario_decision_outcome(
    *,
    scenario: MatrixScenario,
    generate_decisions: Any,
    base_decisions: list[StrategyDecision],
    rows: Sequence[Mapping[str, Any]],
    strategy_id: str,
    scenario_config: Any,
    readiness: Any,
    backend_name: str,
) -> _ScenarioDecisionOutcome:
    if scenario.kind != "parameter":
        return _ScenarioDecisionOutcome(
            decisions=list(base_decisions),
            decision_generation_status="base_reused",
            decisions_regenerated=False,
        )
    try:
        scenario_params = validate_strategy_params(generate_decisions, scenario_config.params)
        decision_output = generate_decisions(frozen_rows(rows), frozen_params(scenario_params))
    except Exception as exc:
        return _ScenarioDecisionOutcome(
            decisions=[],
            decision_generation_status="failed",
            decisions_regenerated=False,
            failure=_failed_backend_result(
                backend_name,
                f"parameter_decision_generation_failed: {exc}",
            ),
        )

    scenario_decisions, violations = validate_decision_output(
        decision_output,
        strategy_id=strategy_id,
    )
    if violations:
        return _ScenarioDecisionOutcome(
            decisions=[],
            decision_generation_status="failed",
            decisions_regenerated=False,
            failure=_failed_backend_result(
                backend_name,
                f"parameter_decision_generation_failed: {'; '.join(violations)}",
            ),
        )
    audit = audit_decision_rows(frozen_rows(rows), scenario_decisions)
    if not audit.passed:
        return _ScenarioDecisionOutcome(
            decisions=[],
            decision_generation_status="failed",
            decisions_regenerated=False,
            failure=_failed_backend_result(
                backend_name,
                f"parameter_decision_audit_failed: {'; '.join(audit.violations)}",
            ),
        )
    if readiness is not None:
        readiness_violations = check_validation_readiness(scenario_decisions, readiness)
        if readiness_violations:
            return _ScenarioDecisionOutcome(
                decisions=[],
                decision_generation_status="failed",
                decisions_regenerated=False,
                failure=_failed_backend_result(
                    backend_name,
                    f"parameter_decision_readiness_failed: {'; '.join(readiness_violations)}",
                ),
            )
    return _ScenarioDecisionOutcome(
        decisions=scenario_decisions,
        decision_generation_status="regenerated",
        decisions_regenerated=True,
    )


def _write_scenario_decision_records(
    *,
    result_dir: Path,
    scenario_id: str,
    decisions: list[StrategyDecision],
) -> tuple[str, str]:
    artifact_name = f"backend_runs/decision_records/{_safe_scenario_artifact_path(scenario_id)}.jsonl"
    lines = [item.model_dump_json() for item in decisions]
    path = write_text_artifact(result_dir, artifact_name, "\n".join(lines))
    return path.relative_to(result_dir).as_posix(), file_sha256(path)


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
    config: Any,
    config_path: Path,
    backend_name: str,
    decisions: list[StrategyDecision],
    data_audits: list[dict[str, Any]],
    data_provenance: list[dict[str, Any]],
    backend_results: list[ScenarioBackendRunResult],
    decision: ValidationPolicyDecision,
    research_manifest: dict[str, Any],
) -> None:
    capability_matrix = backend_capability_matrix(backend_name, backend_results)
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
                    "scenario_kind": item.scenario_kind,
                    "required": item.required,
                    "diagnostic_only": item.diagnostic_only,
                    "decisions_regenerated": item.decisions_regenerated,
                    "decision_generation_status": item.decision_generation_status,
                    "decision_count": item.decision_count,
                    "decision_records_path": item.decision_records_path,
                    "decision_records_sha256": item.decision_records_sha256,
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
                    "scenario_kind": item.scenario_kind,
                    "required": item.required,
                    "diagnostic_only": item.diagnostic_only,
                    "decisions_regenerated": item.decisions_regenerated,
                    "decision_generation_status": item.decision_generation_status,
                    "decision_count": item.decision_count,
                    "decision_records_path": item.decision_records_path,
                    "decision_records_sha256": item.decision_records_sha256,
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
    write_json_artifact(result_dir, "backend_capability_matrix.json", capability_matrix)
    write_json_artifact(
        result_dir,
        "validation_decision.json",
        decision.model_dump(mode="json"),
    )
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
        config=config,
        config_path=config_path,
        backend_name=backend_name,
        data_provenance=data_provenance,
        backend_results=backend_results,
        capability_matrix=capability_matrix,
        research_manifest=research_manifest,
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
