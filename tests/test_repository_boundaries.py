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
