from __future__ import annotations

from pathlib import Path

from quant_strategies.evaluation import EvaluationRunResult
from quant_strategies.runner import RunOutcome, RunResult
from quant_strategies.validation import ValidationRunResult
from quant_strategies.validation.policy import ValidationPolicyDecision


def test_run_result_succeeded_is_derived_from_completed_outcome_without_failure_stage():
    successful = RunResult(
        result_dir=Path("results/run"),
        notes_path=Path("results/run/notes.md"),
        message="completed",
        outcome=RunOutcome(completed=True, failure_stage=None),
    )
    completed_with_failure_stage = RunResult(
        result_dir=Path("results/run"),
        notes_path=Path("results/run/notes.md"),
        message="failed",
        outcome=RunOutcome(completed=True, failure_stage="engine"),
    )
    incomplete = RunResult(
        result_dir=None,
        notes_path=None,
        message="failed",
        outcome=RunOutcome(completed=False, failure_stage=None),
    )

    assert successful.succeeded is True
    assert completed_with_failure_stage.succeeded is False
    assert incomplete.succeeded is False


def test_validation_result_succeeded_is_derived_from_completed_run_without_failure_stage():
    successful = ValidationRunResult(
        result_dir=Path("validation_results/run"),
        decision=ValidationPolicyDecision(decision="mechanical_caution"),
        message="validation decision: mechanical_caution",
        run_completed=True,
        failure_stage=None,
    )
    completed_with_failure_stage = ValidationRunResult(
        result_dir=Path("validation_results/run"),
        decision=ValidationPolicyDecision(decision="mechanical_fail"),
        message="validation decision: mechanical_fail",
        run_completed=True,
        failure_stage="data_audit",
    )
    incomplete = ValidationRunResult(
        result_dir=None,
        decision=ValidationPolicyDecision(decision="mechanical_fail"),
        message="config failed",
        run_completed=False,
        failure_stage=None,
    )

    assert successful.succeeded is True
    assert completed_with_failure_stage.succeeded is False
    assert incomplete.succeeded is False


def test_evaluation_result_succeeded_is_derived_from_completed_run_without_failure_stage():
    successful = EvaluationRunResult(
        result_dir=Path("evaluation_results/run"),
        message="evaluation completed",
        run_completed=True,
        failure_stage=None,
        assessment_status="completed",
    )
    completed_with_failure_stage = EvaluationRunResult(
        result_dir=Path("evaluation_results/run"),
        message="portfolio failed",
        run_completed=True,
        failure_stage="portfolio_evaluation",
        assessment_status="portfolio_failed",
    )
    incomplete = EvaluationRunResult(
        result_dir=None,
        message="config failed",
        run_completed=False,
        failure_stage=None,
        assessment_status="evaluation_failed",
    )

    assert successful.succeeded is True
    assert completed_with_failure_stage.succeeded is False
    assert incomplete.succeeded is False
