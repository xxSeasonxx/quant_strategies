from __future__ import annotations

import hashlib
import importlib.metadata
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def python_identity() -> dict[str, str]:
    return {"version": sys.version.split()[0]}


def package_versions(package_names: Iterable[str]) -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in package_names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def artifact_hashes(
    result_dir: Path,
    *,
    exclude_names: Iterable[str] = (),
    recursive: bool = True,
) -> dict[str, dict[str, str]]:
    excluded = set(exclude_names)
    paths = result_dir.rglob("*") if recursive else result_dir.iterdir()
    hashes: dict[str, dict[str, str]] = {}
    for path in sorted(paths):
        if not path.is_file() or path.name in excluded:
            continue
        name = path.relative_to(result_dir).as_posix()
        hashes[name] = {"sha256": file_sha256(path)}
    return hashes


def git_identity(repo_root: Path, *, exclude_paths: Iterable[Path] = ()) -> dict[str, Any]:
    status = _git_output(
        repo_root,
        *_git_scoped_args(
            repo_root,
            exclude_paths,
            "status",
            "--porcelain",
            "--untracked-files=no",
        ),
    )
    diff = _git_output(
        repo_root,
        *_git_scoped_args(repo_root, exclude_paths, "diff", "--binary", "HEAD"),
    )
    return {
        "commit": _git_output(repo_root, "rev-parse", "HEAD"),
        "short_commit": _git_output(repo_root, "rev-parse", "--short", "HEAD"),
        "dirty": None if status is None else bool(status),
        "status_porcelain_sha256": text_sha256(status) if status else None,
        "tracked_diff_sha256": text_sha256(diff) if diff else None,
    }


def _git_scoped_args(repo_root: Path, exclude_paths: Iterable[Path], *args: str) -> list[str]:
    scoped_args = [*args, "--", "."]
    for path in exclude_paths:
        try:
            relative = path.resolve().relative_to(repo_root.resolve())
        except ValueError:
            continue
        scoped_args.append(f":(exclude){relative.as_posix()}")
    return scoped_args


def _git_output(repo_root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.rstrip("\n")
