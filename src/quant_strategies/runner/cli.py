from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quant_strategies.runner import run_config
from quant_strategies.runner.events import jsonl_event_sink
from quant_strategies.validation import run_validation
from quant_strategies.validation.errors import ValidationError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quant-strategies")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run one strategy config")
    run_parser.add_argument("--repo-root", type=Path, default=None, help="repository root for relative config paths")
    run_parser.add_argument("--events-jsonl", action="store_true", help="write structured runner stage events to stderr")
    run_parser.add_argument("config", type=Path)

    validate_parser = subparsers.add_parser("validate", help="validate one validation TOML config")
    validate_parser.add_argument("--repo-root", type=Path, default=None, help="anchor for a relative validation config path")
    validate_parser.add_argument("config", type=Path)

    args = parser.parse_args(argv)

    if args.command == "run":
        if args.events_jsonl:
            result = run_config(
                args.config,
                repo_root=args.repo_root,
                event_sink=jsonl_event_sink(sys.stderr),
            )
        else:
            result = run_config(args.config, repo_root=args.repo_root)
        if result.success:
            print(result.result_dir)
            return 0
        if result.notes_path is not None:
            print(f"run failed; see {result.notes_path}")
        else:
            print(f"run failed: {result.message}")
        return 1

    if args.command == "validate":
        try:
            result = run_validation(args.config, repo_root=args.repo_root)
        except ValidationError as exc:
            print(f"validation failed: {exc}")
            return 1
        print(f"{result.message}; artifacts: {result.result_dir}")
        if result.decision.decision == "hard_no":
            return 1
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2
