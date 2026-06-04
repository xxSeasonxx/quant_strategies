from __future__ import annotations

import ast
import importlib.util
import subprocess
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOOP_MEMORY_MARKERS = (
    "ranking_method_version",
    '"top_variants"',
    '"passed_validation"',
    '"rerun_score"',
)
SCAN_SUFFIXES = {".json", ".jsonl", ".csv", ".toml", ".py"}
ARCHIVE_POINTER_SUFFIXES = {".md", ".py", ".toml", ".json", ".jsonl", ".csv"}
ARCHIVE_POINTER_FRAGMENTS = (
    "Personal/strategies",
    "quant_strategies/researched",
)
EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "docs",
    "results",
    "tests",
}
ARCHIVE_POINTER_EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "results",
    "tests",
}
DELETED_RUNNER_INTERNALS = (
    "execution.py",
    "data_loader.py",
    "engine_runner.py",
    "errors.py",
    "cli.py",
)


def _active_foundation_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if relative.suffix not in SCAN_SUFFIXES:
            continue
        files.append(relative)
    return sorted(files)


def _repository_text_files_for_archive_pointer_scan() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in ARCHIVE_POINTER_EXCLUDED_PARTS for part in relative.parts):
            continue
        if relative.suffix not in ARCHIVE_POINTER_SUFFIXES:
            continue
        files.append(relative)
    return sorted(files)


def test_researched_archive_is_not_in_foundation_repo():
    assert not (ROOT / "researched").exists()


def test_active_foundation_paths_do_not_contain_loop_memory_markers():
    offenders: list[str] = []
    for relative in _active_foundation_files():
        text = (ROOT / relative).read_text(errors="ignore")
        for marker in LOOP_MEMORY_MARKERS:
            if marker in text:
                offenders.append(f"{relative}: {marker}")

    assert offenders == []


def test_repository_does_not_keep_research_archive_pointer():
    offenders: list[str] = []
    for relative in _repository_text_files_for_archive_pointer_scan():
        text = (ROOT / relative).read_text(errors="ignore")
        for fragment in ARCHIVE_POINTER_FRAGMENTS:
            if fragment in text:
                offenders.append(f"{relative}: {fragment}")

    assert offenders == []


def test_generated_result_roots_are_ignored():
    ignored_roots = ("results/", "validation_results/", "evaluation_results/")
    result = subprocess.run(
        ["git", "check-ignore", *ignored_roots],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert set(result.stdout.splitlines()) == set(ignored_roots)


def test_makefile_exposes_single_local_check_command():
    text = (ROOT / "Makefile").read_text()

    assert ".PHONY: check check-vectorbtpro-smoke check-all" in text
    assert "check:" in text
    assert "conda run -n quant python -m pip install -e ." in text
    assert "conda run -n quant quant-strategies --help" in text
    assert "conda run -n quant pytest -q" in text
    assert "check-vectorbtpro-smoke:" in text
    assert (
        "conda run -n quant env RUN_VECTORBTPRO_SMOKE=1 pytest "
        "tests/test_evaluation_backend.py::test_vectorbtpro_evaluation_backend_real_smoke_if_installed"
    ) in text


def test_review_archive_marks_historical_reviews_superseded():
    text = (ROOT / "docs" / "reviews" / "README.md").read_text()

    expected_rows = [
        "| `2026-06-02-foundation-codex.md` | Historical broad review; superseded by `../../FOUNDATION_LOCK.md` and current tests/docs. |",
        "| `2026-06-02-foundation-codex-p3.md` | Historical P3 follow-up review; superseded by `../../FOUNDATION_LOCK.md` and current tests/docs. |",
        "| `review-claude.md` | Historical independent review; superseded by `../../FOUNDATION_LOCK.md` and current tests/docs. |",
        "| `review-codex.md` | Historical root-level working review copy; accepted findings are dispositioned and superseded by `../../FOUNDATION_LOCK.md` and current tests/docs. |",
    ]
    for row in expected_rows:
        assert row in text
    assert "once its accepted findings are dispositioned" not in text


def test_cli_entrypoint_is_neutral():
    payload = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert payload["project"]["scripts"]["quant-strategies"] == "quant_strategies.cli:main"


def test_shared_internals_are_not_runner_owned():
    for filename in DELETED_RUNNER_INTERNALS:
        assert not (ROOT / "src" / "quant_strategies" / "runner" / filename).exists()

    forbidden_modules = ("execution", "data_loader", "engine_runner", "errors", "cli")
    for module in forbidden_modules:
        assert importlib.util.find_spec(f"quant_strategies.runner.{module}") is None

    offenders = _forbidden_runner_imports(
        (ROOT / "src" / "quant_strategies").rglob("*.py"),
        forbidden_modules=forbidden_modules,
    )

    assert offenders == []


def test_validation_and_evaluation_do_not_import_runner_internals():
    paths = [
        *list((ROOT / "src" / "quant_strategies" / "validation").rglob("*.py")),
        *list((ROOT / "src" / "quant_strategies" / "evaluation").rglob("*.py")),
    ]

    assert _forbidden_runner_imports(paths, forbidden_modules=None) == []


def _forbidden_runner_imports(
    paths,
    *,
    forbidden_modules: tuple[str, ...] | None,
) -> list[str]:
    offenders: list[str] = []
    forbidden_prefix = "quant_strategies.runner"
    forbidden_names = set(forbidden_modules or ())
    for path in paths:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_forbidden_runner_module(alias.name, forbidden_prefix, forbidden_names):
                        offenders.append(f"{path.relative_to(ROOT)}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _is_forbidden_runner_module(module, forbidden_prefix, forbidden_names):
                    offenders.append(f"{path.relative_to(ROOT)}: from {module} import ...")
                    continue
                if module == forbidden_prefix:
                    for alias in node.names:
                        if not forbidden_names or alias.name in forbidden_names:
                            offenders.append(f"{path.relative_to(ROOT)}: from {module} import {alias.name}")
    return sorted(offenders)


def _is_forbidden_runner_module(
    module: str,
    forbidden_prefix: str,
    forbidden_names: set[str],
) -> bool:
    if not module.startswith(f"{forbidden_prefix}."):
        return False
    if not forbidden_names:
        return True
    tail = module.removeprefix(f"{forbidden_prefix}.").split(".", 1)[0]
    return tail in forbidden_names


def test_root_phase_plans_are_not_active_context():
    assert not (ROOT / "plans").exists()

    active_docs = [
        "README.md",
        "AGENTS.md",
        "FOUNDATION_LOCK.md",
        "TODOS.md",
        "docs/foundation-surfaces.md",
        "docs/vectorbtpro.md",
    ]
    offenders: list[str] = []
    for relative in active_docs:
        text = (ROOT / relative).read_text(errors="ignore")
        if "plans/phase" in text:
            offenders.append(relative)

    assert offenders == []


def test_active_docs_lock_quant_autoresearch_consumer_contract():
    foundation = (ROOT / "docs" / "foundation-surfaces.md").read_text(errors="ignore")

    required_snippets = [
        "from quant_strategies.runner import run_config",
        "from quant_strategies.validation import run_validation",
        "from quant_strategies.evaluation import run_evaluation",
        "result.outcome.completed and result.outcome.failure_stage is None",
        "result.run_completed and result.failure_stage is None",
        "validation labels are advisory evidence",
        "ranking, comparison, search memory, stopping rules, and promotion decisions remain outside this repo",
    ]
    for snippet in required_snippets:
        assert snippet in foundation
