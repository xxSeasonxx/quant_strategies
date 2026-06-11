from __future__ import annotations

import ast
import importlib.util
import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

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
    test_body = _makefile_target_body(text, "test")

    assert (
        ".PHONY: format fix lint typecheck test check check-quant-data-contract check-all"
    ) in text
    assert _makefile_target_header(text, "check") == "check: lint test"
    assert "format:" in text
    assert "fix:" in text
    assert "lint:" in text
    assert "typecheck:" in text
    assert "test:" in text
    assert "conda run -n quant ruff format ." in text
    assert "conda run -n quant ruff check . --fix" in text
    assert "conda run -n quant ruff format --check ." in text
    assert "conda run -n quant ruff check ." in text
    assert "conda run -n quant mypy src tests" in text
    assert "conda run -n quant python -m pip install -e ." in text
    assert "conda run -n quant quant-strategies --help" in text
    assert "conda run -n quant pytest -q" in test_body
    assert "check-quant-data-contract:" in text
    assert (
        "conda run -n quant env RUN_QUANT_DATA_CONTRACT_SMOKE=1 pytest "
        "tests/test_quant_data_contract_smoke.py"
    ) in text
    assert _makefile_target_header(text, "check-all") == (
        "check-all: check typecheck check-quant-data-contract"
    )


def _makefile_target_header(text: str, target: str) -> str:
    for line in text.splitlines():
        if line.startswith(f"{target}:"):
            return line
    raise AssertionError(f"target not found: {target}")


def _makefile_target_body(text: str, target: str) -> str:
    lines = text.splitlines()
    body: list[str] = []
    in_target = False
    for line in lines:
        if line.startswith(f"{target}:"):
            in_target = True
            continue
        if in_target and line and not line.startswith(("\t", " ")):
            break
        if in_target:
            body.append(line)
    return "\n".join(body)


def test_quant_data_dependency_is_version_bounded():
    payload = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dependencies = payload["project"]["dependencies"]
    quant_data_specs = [
        dependency
        for dependency in dependencies
        if dependency == "quant-data" or dependency.startswith("quant-data")
    ]

    assert quant_data_specs == ["quant-data>=0.1.0,<0.2.0"]


def test_data_loader_bars_use_contract_loaders_not_raw_layer():
    # Bars/universe must load via the strategy contract layer (causal available_at +
    # deterministic order), never the raw exploratory loader which carries neither.
    source = (ROOT / "src" / "quant_strategies" / "core" / "data_loader.py").read_text()
    assert "load_strategy_bars" in source
    assert "load_strategy_universe_bars" in source
    assert "load_bars" not in source
    assert "load_universe_bars" not in source


def test_evaluation_constraints_pin_numeric_backend_versions():
    constraints = ROOT / "constraints" / "evaluation.txt"

    assert constraints.exists()
    lines = {
        line.strip()
        for line in constraints.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    assert "pandas==2.3.3" in lines
    assert "pyarrow==23.0.1" in lines


def test_review_archive_index_points_to_current_disposition_anchor():
    text = (ROOT / "docs" / "reviews" / "README.md").read_text()

    assert "Current disposition anchor:" in text
    assert "../../FOUNDATION_LOCK.md" in text
    assert "current tests/docs" in text
    assert "Future foundation reviews should be disposition-aware delta reviews" in text


def test_review_archive_marks_historical_reviews_superseded_when_opted_in():
    if os.environ.get("RUN_REVIEW_ARCHIVE_CHECK") != "1":
        pytest.skip(
            "set RUN_REVIEW_ARCHIVE_CHECK=1 to run exact archive disposition maintenance checks"
        )

    text = (ROOT / "docs" / "reviews" / "README.md").read_text()

    expected_rows = [
        "| `2026-06-02-foundation-codex.md` | Historical broad review; superseded by `../../FOUNDATION_LOCK.md` and current tests/docs. |",
        "| `2026-06-02-foundation-codex-p3.md` | Historical P3 follow-up review; superseded by `../../FOUNDATION_LOCK.md` and current tests/docs. |",
        "| `2026-06-03-foundation-claude-independent.md` | Historical independent review; superseded by `../../FOUNDATION_LOCK.md` and current tests/docs. |",
        "| `2026-06-03-foundation-claude-disposition.md` | Historical root-level Claude working review copy; accepted findings are dispositioned and superseded by `../../FOUNDATION_LOCK.md` and current tests/docs. |",
        "| `2026-06-03-foundation-codex-delta.md` | Historical Codex delta review; superseded by `../../FOUNDATION_LOCK.md` and current tests/docs. |",
        "| `2026-06-03-foundation-codex-disposition.md` | Historical root-level Codex working review copy; accepted findings are dispositioned and superseded by `../../FOUNDATION_LOCK.md` and current tests/docs. |",
    ]
    for row in expected_rows:
        assert row in text
    assert "once its accepted findings are dispositioned" not in text


def test_review_archive_artifacts_are_dated():
    dated_review_name = re.compile(r"^\d{4}-\d{2}-\d{2}-.+\.md$")
    review_files = [
        path.name for path in (ROOT / "docs" / "reviews").glob("*.md") if path.name != "README.md"
    ]

    assert review_files
    assert all(dated_review_name.match(name) for name in review_files)


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


def test_data_audit_is_core_owned_not_validation_owned():
    assert importlib.util.find_spec("quant_strategies.core.data_audit") is not None
    assert importlib.util.find_spec("quant_strategies.validation.data_audit") is None


def test_validation_and_evaluation_do_not_import_runner_internals():
    paths = [
        *list((ROOT / "src" / "quant_strategies" / "validation").rglob("*.py")),
        *list((ROOT / "src" / "quant_strategies" / "evaluation").rglob("*.py")),
    ]

    assert _forbidden_runner_imports(paths, forbidden_modules=None) == []


def test_p3_simplification_uses_explicit_module_boundaries():
    evaluation = ROOT / "src" / "quant_strategies" / "evaluation"
    validation = ROOT / "src" / "quant_strategies" / "validation"

    assert not (evaluation / "backend.py").exists()
    assert not (evaluation / "runner.py").exists()
    # The retired alternate evaluation backends are gone (D9): the single causal
    # netted portfolio book is the only evaluation money model.
    assert not (evaluation / "project_perp_ledger.py").exists()
    assert (evaluation / "spine_backend.py").exists()
    assert (evaluation / "results.py").exists()
    assert (evaluation / "_pipeline.py").exists()
    assert (validation / "results.py").exists()
    assert (validation / "_pipeline.py").exists()


def test_evaluation_pipeline_uses_protocols_not_reflective_dispatch():
    pipeline = ROOT / "src" / "quant_strategies" / "evaluation" / "_pipeline.py"
    if not pipeline.exists():
        pipeline = ROOT / "src" / "quant_strategies" / "evaluation" / "runner.py"
    text = pipeline.read_text()

    assert "signature(" not in text
    assert "Parameter" not in text
    assert "hasattr(context.selected_backend" not in text
    assert "PreparedEvaluationBackend" in text
    # No data-kind routing hook: the single book prices every asset class (D9).
    assert "DataKindNamedEvaluationBackend" not in text
    assert "name_for_data_kind" not in text


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
                            offenders.append(
                                f"{path.relative_to(ROOT)}: from {module} import {alias.name}"
                            )
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
    ]
    offenders: list[str] = []
    for relative in active_docs:
        text = (ROOT / relative).read_text(errors="ignore")
        if "plans/phase" in text:
            offenders.append(relative)

    assert offenders == []


def test_active_docs_lock_quant_autoresearch_consumer_contract():
    foundation = " ".join(
        (ROOT / "docs" / "foundation-surfaces.md").read_text(errors="ignore").split()
    )

    required_snippets = [
        "from quant_strategies.runner import run_config",
        "from quant_strategies.validation import run_validation",
        "from quant_strategies.evaluation import run_evaluation",
        "result.succeeded",
        "validation labels are advisory evidence",
        "ranking, comparison, search memory, stopping rules, and promotion decisions remain outside this repo",
    ]
    for snippet in required_snippets:
        assert snippet in foundation
