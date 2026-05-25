from __future__ import annotations

import argparse
from pathlib import Path

from quant_strategies.runner import run_config
from quant_strategies.validation import run_validation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quant-strategies")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run one strategy config")
    run_parser.add_argument("--repo-root", type=Path, default=None, help="repository root for relative config paths")
    run_parser.add_argument("config", type=Path)

    validate_parser = subparsers.add_parser("validate", help="validate one researched strategy package")
    validate_parser.add_argument("--repo-root", type=Path, default=None, help="repository root for relative paths")
    validate_parser.add_argument("package_or_config", type=Path)

    args = parser.parse_args(argv)

    if args.command == "run":
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
        result = run_validation(args.package_or_config, repo_root=args.repo_root)
        print(f"{result.message}; artifacts: {result.result_dir}")
        if result.decision.decision == "clear_yes":
            return 0
        if result.decision.decision == "hard_no":
            return 1
        return 2

    parser.error(f"unknown command: {args.command}")
    return 2
