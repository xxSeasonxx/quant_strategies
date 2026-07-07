from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from quant_strategies.boundary import FrozenMapping, frozen_params
from quant_strategies.core.config import StrategyExecutionSpec
from quant_strategies.core.data_loader import load_data
from quant_strategies.core.errors import RunnerError, StrategyLoadError
from quant_strategies.core.evidence_quality import EvidenceQuality
from quant_strategies.data_contract import NormalizedRows
from quant_strategies.decisions import (
    DecisionStrategyLoadError,
    load_decision_strategy,
    validate_decision_output,
    validate_strategy_params,
)
from quant_strategies.decisions.models import TargetDecision

ExecutionStage = Literal[
    "strategy_import",
    "param_validation",
    "data_load",
    "decision_generation",
]

GenerateDecisions = Callable[
    [Sequence[Mapping[str, object]], Mapping[str, object]],
    list[TargetDecision],
]


@dataclass(frozen=True)
class StrategyExecutionResult:
    generate_decisions: GenerateDecisions
    validated_params: dict[str, Any]
    loaded_rows: Sequence[Mapping[str, Any]]
    normalized_rows: NormalizedRows
    frozen_rows: tuple[FrozenMapping, ...]
    frozen_params: FrozenMapping
    decisions: list[TargetDecision]
    normalized_rows_sha256: str
    evidence_quality: EvidenceQuality
    param_contract: str = "validated"
    execution_loaded_rows: Sequence[Mapping[str, Any]] | None = None
    execution_normalized_rows: NormalizedRows | None = None
    execution_normalized_rows_sha256: str | None = None
    # Valuation-only mark frame over the full execution window; consumed by the
    # portfolio foundation, never passed to the strategy (purity).
    mark_rows: Sequence[Mapping[str, Any]] = ()
    mark_repair: Mapping[str, Any] | None = None


class StrategyExecutionError(RunnerError):
    def __init__(
        self,
        stage: ExecutionStage,
        message: str,
        *,
        loaded_rows: Sequence[Mapping[str, Any]] | None = None,
        normalized_rows: NormalizedRows | None = None,
        evidence_quality: EvidenceQuality | None = None,
        violations: tuple[str, ...] = (),
        decision_count: int | None = None,
        execution_normalized_rows: NormalizedRows | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.loaded_rows = loaded_rows
        self.normalized_rows = normalized_rows
        self.normalized_rows_sha256 = (
            None if normalized_rows is None else normalized_rows.normalized_rows_sha256
        )
        self.evidence_quality = evidence_quality
        self.violations = violations
        self.decision_count = decision_count
        self.execution_normalized_rows = execution_normalized_rows


def execute_strategy_run(
    config: StrategyExecutionSpec,
    *,
    repo_root: Path,
    require_passed_row_contract: bool = False,
) -> StrategyExecutionResult:
    try:
        generate_decisions = _load_strategy(config.strategy_path, repo_root=repo_root)
    except SystemExit as exc:
        raise StrategyExecutionError(
            "strategy_import", f"strategy import exited: {_system_exit_message(exc)}"
        ) from exc
    except RunnerError as exc:
        raise StrategyExecutionError("strategy_import", str(exc)) from exc

    try:
        validated_params, had_param_validator = validate_strategy_params(
            generate_decisions,
            config.params,
            require_validator=config.require_param_validator,
        )
    except SystemExit as exc:
        raise StrategyExecutionError(
            "param_validation",
            f"param validation exited: {_system_exit_message(exc)}",
        ) from exc
    except Exception as exc:
        raise StrategyExecutionError(
            "param_validation",
            f"param validation failed: {exc}",
        ) from exc

    try:
        loaded = load_data(config)
    except RunnerError as exc:
        raise StrategyExecutionError("data_load", str(exc)) from exc

    if loaded.normalized_rows is not None:
        normalized_rows = loaded.normalized_rows
    elif isinstance(loaded.rows, NormalizedRows):
        normalized_rows = loaded.rows
    else:
        normalized_rows = NormalizedRows.from_rows(config, loaded.rows)
    execution_rows = normalized_rows.projection_rows()
    window_predicate = _strategy_window_predicate(config)
    if window_predicate is None:
        strategy_rows = execution_rows
        strategy_normalized_rows = normalized_rows
    else:
        # One predicate drives the empty/length guards, the subset selection, and the
        # re-normalize fallback, so the decision-window rule is expressed exactly once.
        keep_indices = [index for index, row in enumerate(execution_rows) if window_predicate(row)]
        strategy_rows = tuple(execution_rows[index] for index in keep_indices)
        if not strategy_rows:
            raise StrategyExecutionError(
                "data_load",
                "decision window returned no rows",
                loaded_rows=(),
                normalized_rows=None,
                evidence_quality=None,
                execution_normalized_rows=normalized_rows,
            )
        if len(keep_indices) == len(execution_rows):
            strategy_normalized_rows = normalized_rows
        elif normalized_rows.issue_count == 0:
            # Issue-free full window: slice the already-normalized rows (reuses
            # canonical lines/hash) instead of re-normalizing the subset.
            strategy_normalized_rows = normalized_rows.window_subset(keep_indices)
        else:
            strategy_normalized_rows = NormalizedRows.from_rows(config, strategy_rows)
    rows = strategy_normalized_rows.projection_rows()
    row_hash = strategy_normalized_rows.normalized_rows_sha256
    evidence = strategy_normalized_rows.evidence_quality()
    row_contract = strategy_normalized_rows.row_contract_summary()
    if require_passed_row_contract and row_contract["status"] != "passed":
        raise StrategyExecutionError(
            "data_load",
            _row_contract_failure_message(row_contract),
            loaded_rows=rows,
            normalized_rows=strategy_normalized_rows,
            evidence_quality=evidence,
        )
    strategy_rows = strategy_normalized_rows.frozen_rows()
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
                normalized_rows=strategy_normalized_rows,
                evidence_quality=evidence,
                violations=tuple(violations),
                decision_count=decision_count,
            )
    except StrategyExecutionError:
        raise
    except SystemExit as exc:
        raise StrategyExecutionError(
            "decision_generation",
            f"strategy execution exited: {_system_exit_message(exc)}",
            loaded_rows=rows,
            normalized_rows=strategy_normalized_rows,
            evidence_quality=evidence,
            decision_count=decision_count,
            execution_normalized_rows=normalized_rows,
        ) from exc
    except Exception as exc:
        raise StrategyExecutionError(
            "decision_generation",
            f"strategy execution failed: {exc}",
            loaded_rows=rows,
            normalized_rows=strategy_normalized_rows,
            evidence_quality=evidence,
            decision_count=decision_count,
            execution_normalized_rows=normalized_rows,
        ) from exc

    return StrategyExecutionResult(
        generate_decisions=generate_decisions,
        validated_params=validated_params,
        loaded_rows=rows,
        normalized_rows=strategy_normalized_rows,
        frozen_rows=strategy_rows,
        frozen_params=strategy_params,
        decisions=decisions,
        normalized_rows_sha256=row_hash,
        evidence_quality=evidence,
        param_contract="validated" if had_param_validator else "unvalidated_passthrough",
        execution_loaded_rows=execution_rows,
        execution_normalized_rows=normalized_rows,
        execution_normalized_rows_sha256=normalized_rows.normalized_rows_sha256,
        mark_rows=loaded.mark_rows,
        mark_repair=loaded.mark_repair,
    )


def _load_strategy(path: str | Path, *, repo_root: Path | None = None) -> GenerateDecisions:
    try:
        return load_decision_strategy(path, repo_root=repo_root)
    except DecisionStrategyLoadError as exc:
        raise StrategyLoadError(str(exc)) from exc


def _system_exit_message(exc: SystemExit) -> str:
    return str(exc) or repr(exc.code)


def _row_contract_failure_message(row_contract: Mapping[str, Any]) -> str:
    feedback = row_contract.get("quant_data_feedback")
    if isinstance(feedback, Sequence) and not isinstance(feedback, str):
        reasons = [str(item) for item in feedback if item]
        if reasons:
            return f"row contract failed: {'; '.join(reasons)}"
    return f"row contract {row_contract['status']}"


def _strategy_window_predicate(
    config: StrategyExecutionSpec,
) -> Callable[[Mapping[str, Any]], bool] | None:
    """Row-visibility predicate for the decision window, or ``None`` when none applies.

    ``None`` means no separate load window is configured, so every loaded row is
    strategy-visible. Otherwise the returned predicate is the single expression of
    the window rule that the strategy-window filter, the length/empty guards, and
    ``NormalizedRows.window_subset`` all select on.
    """
    if config.data.load_start is None and config.data.load_end is None:
        return None
    window = _date_window(config.data.start, config.data.end)
    return lambda row: _row_date(row.get("timestamp")) in window


def _date_window(start: date, end: date) -> range:
    return range(start.toordinal(), end.toordinal() + 1)


def _row_date(value: object) -> int:
    if isinstance(value, datetime):
        return value.date().toordinal()
    if isinstance(value, date):
        return value.toordinal()
    return -1
