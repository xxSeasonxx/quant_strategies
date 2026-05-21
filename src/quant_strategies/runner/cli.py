from __future__ import annotations

import argparse
from pathlib import Path

from quant_strategies.runner import run_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quant-strategies")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="run one strategy config")
    run_parser.add_argument("--repo-root", type=Path, default=None, help="repository root for relative config paths")
    run_parser.add_argument("config", type=Path)
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

    parser.error(f"unknown command: {args.command}")
    return 2
