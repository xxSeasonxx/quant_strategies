from __future__ import annotations

import ast
import re
from pathlib import Path

from quant_strategies.decisions import strategy_purity_violations


REQUIRED_HEADINGS = (
    "Source / provenance:",
    "Market rationale:",
    "Required observables:",
    "Assumptions:",
    "Falsifier:",
)
RULE_HEADINGS = ("Decision rule:", "Signal rule:")
PROVENANCE_ANCHOR_PATTERN = re.compile(
    r"https?://|\binternal_note\s*:|\bdoi\b|\bssrn\b",
    re.IGNORECASE,
)


def strategy_files() -> list[Path]:
    return sorted(
        path
        for path in Path("untested").glob("*.py")
        if path.name != "__init__.py"
    )


def example_strategy_files() -> list[Path]:
    return sorted(Path("examples/strategies").glob("*.py"))


def all_strategy_files_for_contract() -> list[Path]:
    return strategy_files() + example_strategy_files()


def strategy_python_files() -> list[Path]:
    return sorted(
        path
        for path in Path("untested").rglob("*.py")
        if "__pycache__" not in path.parts
    )


def test_strategy_docstrings_include_required_rationale_headings():
    files = all_strategy_files_for_contract()
    assert files, "expected committed strategy modules"

    for path in files:
        docstring = ast.get_docstring(ast.parse(path.read_text())) or ""
        missing = [heading for heading in REQUIRED_HEADINGS if heading not in docstring]
        if not any(heading in docstring for heading in RULE_HEADINGS):
            missing.append("Decision rule: or Signal rule:")
        assert missing == [], f"{path} missing headings: {missing}"


def test_strategy_docstrings_include_auditable_provenance_anchor():
    offenders: list[str] = []
    for path in all_strategy_files_for_contract():
        docstring = ast.get_docstring(ast.parse(path.read_text())) or ""
        source_section = _docstring_section(docstring, "Source / provenance:")
        if not PROVENANCE_ANCHOR_PATTERN.search(source_section):
            offenders.append(f"{path}: Source / provenance lacks DOI, SSRN, URL, or internal_note:")

    assert offenders == []


def test_strategy_layout_is_flat():
    offenders = [
        path
        for path in strategy_python_files()
        if path.name != "__init__.py" and path.parent != Path("untested")
    ]

    assert offenders == []


def test_strategy_modules_satisfy_static_purity_contract():
    offenders: list[str] = []
    for path in all_strategy_files_for_contract():
        offenders.extend(strategy_purity_violations(path))

    assert offenders == []


def _docstring_section(docstring: str, heading: str) -> str:
    headings = set(REQUIRED_HEADINGS) | set(RULE_HEADINGS)
    lines = docstring.splitlines()
    try:
        start = next(index + 1 for index, line in enumerate(lines) if line.strip() == heading)
    except StopIteration:
        return ""

    body: list[str] = []
    for line in lines[start:]:
        if line.strip() in headings:
            break
        body.append(line)
    return "\n".join(body).strip()
