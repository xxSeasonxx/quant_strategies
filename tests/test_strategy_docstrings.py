from __future__ import annotations

import ast
from pathlib import Path


REQUIRED_HEADINGS = (
    "Source / provenance:",
    "Market rationale:",
    "Required observables:",
    "Signal rule:",
    "Assumptions:",
    "Falsifier:",
)


def strategy_files() -> list[Path]:
    return sorted(
        path
        for directory in (Path("tested"), Path("untested"))
        for path in directory.glob("*.py")
        if path.name != "__init__.py"
    )


def test_strategy_docstrings_include_required_rationale_headings():
    files = strategy_files()
    assert files, "expected committed strategy modules"

    for path in files:
        docstring = ast.get_docstring(ast.parse(path.read_text())) or ""
        missing = [heading for heading in REQUIRED_HEADINGS if heading not in docstring]
        assert missing == [], f"{path} missing headings: {missing}"
