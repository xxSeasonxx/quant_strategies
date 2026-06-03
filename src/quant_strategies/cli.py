from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quant_strategies.evaluation import run_evaluation
from quant_strategies.evaluation.events import jsonl_event_sink as evaluation_jsonl_event_sink
from quant_strategies.runner import run_config
from quant_strategies.runner.events import jsonl_event_sink as runner_jsonl_event_sink
from quant_strategies.validation import run_validation
from quant_strategies.validation.errors import ValidationError
from quant_strategies.validation.events import jsonl_event_sink as validation_jsonl_event_sink


_DATA_FAILURE_STAGES = {
    "data_readiness",
    "observation_audit",
    "data_audit",
    "validation_readiness",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quant-strategies")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run one strategy config")
    run_parser.add_argument("--repo-root", type=Path, default=None, help="repository root for relative config paths")
    run_parser.add_argument("--events-jsonl", action="store_true", help="write structured runner stage events to stderr")
    run_parser.add_argument("config", type=Path)

    validate_parser = subparsers.add_parser("validate", help="validate one validation TOML config")
    validate_parser.add_argument("--repo-root", type=Path, default=None, help="anchor for a relative validation config path")
    validate_parser.add_argument("--events-jsonl", action="store_true", help="write structured validation stage events to stderr")
    validate_parser.add_argument("config", type=Path)

    evaluate_parser = subparsers.add_parser("evaluate", help="evaluate one evaluation TOML config")
    evaluate_parser.add_argument("--repo-root", type=Path, default=None, help="anchor for a relative evaluation config path")
    evaluate_parser.add_argument("--events-jsonl", action="store_true", help="write structured evaluation stage events to stderr")
    evaluate_parser.add_argument("config", type=Path)

    args = parser.parse_args(argv)

    if args.command == "run":
        try:
            if args.events_jsonl:
                result = run_config(
                    args.config,
                    repo_root=args.repo_root,
                    event_sink=runner_jsonl_event_sink(sys.stderr),
                )
            else:
                result = run_config(args.config, repo_root=args.repo_root)
        except OSError as exc:
            # Backstop: run_config routes artifact failures to structured results,
            # but any filesystem error that still escapes becomes a clean exit, not
            # a traceback.
            print(f"run failed: {exc}")
            return 1
        if _run_exit_code(result) == 0:
            print(result.result_dir)
            return 0
        if result.notes_path is not None:
            print(f"run failed; see {result.notes_path}")
        else:
            print(f"run failed: {result.message}")
        return _run_exit_code(result)

    if args.command == "validate":
        try:
            if args.events_jsonl:
                result = run_validation(
                    args.config,
                    repo_root=args.repo_root,
                    event_sink=validation_jsonl_event_sink(sys.stderr),
                )
            else:
                result = run_validation(args.config, repo_root=args.repo_root)
        except ValidationError as exc:
            print(f"validation failed: {exc}")
            return 1
        except OSError as exc:
            # Backstop for filesystem errors that escape run_validation's structured
            # artifact-failure handling.
            print(f"validation failed: {exc}")
            return 1
        if result.result_dir is None:
            print(f"validation failed: {result.message}")
        else:
            print(f"{result.message}; artifacts: {result.result_dir}")
        return _validation_exit_code(result)

    if args.command == "evaluate":
        try:
            if args.events_jsonl:
                result = run_evaluation(
                    args.config,
                    repo_root=args.repo_root,
                    event_sink=evaluation_jsonl_event_sink(sys.stderr),
                )
            else:
                result = run_evaluation(args.config, repo_root=args.repo_root)
        except OSError as exc:
            print(f"evaluation failed: {exc}")
            return 1
        if _evaluation_exit_code(result) == 0:
            print(result.result_dir)
            return 0
        result_dir = getattr(result, "result_dir", None)
        if result_dir is not None and result_dir.exists():
            print(f"evaluation failed: {result.message}; artifacts: {result_dir}")
        else:
            print(f"evaluation failed: {result.message}")
        return _evaluation_exit_code(result)

    parser.error(f"unknown command: {args.command}")
    return 2


def _run_exit_code(result: object) -> int:
    outcome = result.outcome
    failure_stage = outcome.failure_stage
    if failure_stage in _DATA_FAILURE_STAGES:
        return 3
    if failure_stage is not None or not outcome.completed:
        return 1
    return 0


def _validation_exit_code(result: object) -> int:
    failure_stage = getattr(result, "failure_stage", None)
    if failure_stage in _DATA_FAILURE_STAGES:
        return 3
    if failure_stage is not None or not getattr(result, "run_completed", False):
        return 1
    decision = getattr(getattr(result, "decision", None), "decision", None)
    if decision == "mechanical_fail":
        return 2
    return 0


def _evaluation_exit_code(result: object) -> int:
    failure_stage = getattr(result, "failure_stage", None)
    if failure_stage in _DATA_FAILURE_STAGES or failure_stage == "data_load":
        return 3
    if failure_stage is not None or not getattr(result, "run_completed", False):
        return 1
    return 0
