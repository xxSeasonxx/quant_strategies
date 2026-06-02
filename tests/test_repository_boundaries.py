from __future__ import annotations

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
