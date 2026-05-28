from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quant_strategies.boundary import FrozenMapping, frozen_params, frozen_rows
from quant_strategies.decisions import validate_decision_output, validate_strategy_params
from quant_strategies.decisions.models import StrategyDecision
from quant_strategies.runner.artifact_profiles import normalized_rows_sha256 as rows_sha256
from quant_strategies.runner.artifacts import evidence_quality as assess_evidence_quality
from quant_strategies.runner.config import RunConfig
from quant_strategies.runner.data_loader import load_data
from quant_strategies.runner.errors import RunnerError
from quant_strategies.runner.strategy_loader import load_strategy


ExecutionStage = Literal[
    "strategy_import",
    "param_validation",
    "data_load",
    "decision_generation",
]

GenerateDecisions = Callable[
    [Sequence[Mapping[str, object]], Mapping[str, object]],
    list[StrategyDecision],
]


@dataclass(frozen=True)
class StrategyExecutionResult:
    generate_decisions: GenerateDecisions
    validated_params: dict[str, Any]
    loaded_rows: list[dict[str, Any]]
    frozen_rows: tuple[FrozenMapping, ...]
    frozen_params: FrozenMapping
    decisions: list[StrategyDecision]
    normalized_rows_sha256: str
    evidence_quality: dict[str, Any]


class StrategyExecutionError(RunnerError):
    def __init__(
        self,
        stage: ExecutionStage,
        message: str,
        *,
        loaded_rows: list[dict[str, Any]] | None = None,
        normalized_rows_sha256: str | None = None,
        evidence_quality: dict[str, Any] | None = None,
        violations: tuple[str, ...] = (),
        decision_count: int | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.loaded_rows = loaded_rows
        self.normalized_rows_sha256 = normalized_rows_sha256
        self.evidence_quality = evidence_quality
        self.violations = violations
        self.decision_count = decision_count


def execute_strategy_run(config: RunConfig, *, repo_root: Path) -> StrategyExecutionResult:
    try:
        generate_decisions = load_strategy(config.strategy_path, repo_root=repo_root)
    except RunnerError as exc:
        raise StrategyExecutionError("strategy_import", str(exc)) from exc

    try:
        validated_params = validate_strategy_params(generate_decisions, config.params)
    except Exception as exc:
        raise StrategyExecutionError(
            "param_validation",
            f"param validation failed: {exc}",
        ) from exc

    try:
        loaded = load_data(config)
    except RunnerError as exc:
        raise StrategyExecutionError("data_load", str(exc)) from exc

    rows = loaded.rows
    row_hash = rows_sha256(rows)
    evidence = assess_evidence_quality(config, rows)
    strategy_rows = frozen_rows(rows)
    strategy_params = frozen_params(validated_params)

    decision_count = 0
    try:
        output = generate_decisions(strategy_rows, strategy_params)
        decisions, violations = validate_decision_output(output, strategy_id=config.strategy_id)
        decision_count = len(decisions)
        if violations:
            raise StrategyExecutionError(
                "decision_generation",
                "; ".join(violations),
                loaded_rows=rows,
                normalized_rows_sha256=row_hash,
                evidence_quality=evidence,
                violations=tuple(violations),
                decision_count=decision_count,
            )
    except StrategyExecutionError:
        raise
    except Exception as exc:
        raise StrategyExecutionError(
            "decision_generation",
            f"strategy execution failed: {exc}",
            loaded_rows=rows,
            normalized_rows_sha256=row_hash,
            evidence_quality=evidence,
            decision_count=decision_count,
        ) from exc

    return StrategyExecutionResult(
        generate_decisions=generate_decisions,
        validated_params=validated_params,
        loaded_rows=rows,
        frozen_rows=strategy_rows,
        frozen_params=strategy_params,
        decisions=decisions,
        normalized_rows_sha256=row_hash,
        evidence_quality=evidence,
    )
