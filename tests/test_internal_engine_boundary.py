from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_DISTRIBUTION = "quant" + "-engine"
LEGACY_IMPORT = "quant" + "_engine"


def test_project_does_not_depend_on_legacy_distribution():
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()

    assert LEGACY_DISTRIBUTION not in pyproject


def test_first_party_source_does_not_import_legacy_package():
    offenders: list[str] = []
    for path in (REPO_ROOT / "src").rglob("*.py"):
        text = path.read_text()
        if f"from {LEGACY_IMPORT}" in text or f"import {LEGACY_IMPORT}" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert offenders == []
