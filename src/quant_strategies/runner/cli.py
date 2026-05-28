from __future__ import annotations

import argparse
import sys
from pathlib import Path

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

    args = parser.parse_args(argv)

    if args.command == "run":
        if args.events_jsonl:
            result = run_config(
                args.config,
                repo_root=args.repo_root,
                event_sink=runner_jsonl_event_sink(sys.stderr),
            )
        else:
            result = run_config(args.config, repo_root=args.repo_root)
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
        print(f"{result.message}; artifacts: {result.result_dir}")
        return _validation_exit_code(result)

    parser.error(f"unknown command: {args.command}")
    return 2


def _run_exit_code(result: object) -> int:
    failure_stage = getattr(result, "failure_stage", None)
    if failure_stage in _DATA_FAILURE_STAGES:
        return 3
    if failure_stage is not None or not getattr(result, "run_completed", False):
        return 1
    return 0


def _validation_exit_code(result: object) -> int:
    failure_stage = getattr(result, "failure_stage", None)
    if failure_stage in _DATA_FAILURE_STAGES:
        return 3
    if failure_stage is not None or not getattr(result, "run_completed", False):
        return 1
    decision = getattr(getattr(result, "decision", None), "decision", None)
    if decision == "hard_no":
        return 2
    return 0
