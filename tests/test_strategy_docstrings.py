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
BANNED_IMPORT_ROOTS = {
    "quant_data",
    "quant_strategies.engine",
    "quant_strategies.runner",
}
BANNED_CALL_NAMES = {
    "open",
    "exec",
    "eval",
    "compile",
}
BANNED_CALL_ATTRIBUTES = {
    "mkdir",
    "open",
    "write",
    "write_text",
    "write_bytes",
    "unlink",
    "remove",
    "rmdir",
}
BANNED_MODULE_CALLS = {
    ("os", "remove"),
    ("os", "rmdir"),
    ("os", "unlink"),
    ("requests", "delete"),
    ("requests", "get"),
    ("requests", "post"),
    ("socket", "socket"),
    ("subprocess", "call"),
    ("subprocess", "check_call"),
    ("subprocess", "check_output"),
    ("subprocess", "run"),
}


def strategy_files() -> list[Path]:
    return sorted(
        path
        for directory in (Path("tested"), Path("untested"))
        for path in directory.glob("*.py")
        if path.name != "__init__.py"
    )


def strategy_python_files() -> list[Path]:
    return sorted(
        path
        for directory in (Path("tested"), Path("untested"))
        for path in directory.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def test_strategy_docstrings_include_required_rationale_headings():
    files = strategy_files()
    assert files, "expected committed strategy modules"

    for path in files:
        docstring = ast.get_docstring(ast.parse(path.read_text())) or ""
        missing = [heading for heading in REQUIRED_HEADINGS if heading not in docstring]
        assert missing == [], f"{path} missing headings: {missing}"


def test_strategy_layout_is_flat():
    offenders = [
        path
        for path in strategy_python_files()
        if path.name != "__init__.py" and path.parent not in {Path("tested"), Path("untested")}
    ]

    assert offenders == []


def test_strategy_modules_do_not_import_data_runner_or_engine_packages():
    offenders: list[str] = []
    for path in strategy_files():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_banned_import(alias.name):
                        offenders.append(f"{path}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _is_banned_import(module):
                    offenders.append(f"{path}: from {module} import ...")

    assert offenders == []


def test_strategy_modules_do_not_call_common_side_effect_primitives():
    offenders: list[str] = []
    for path in strategy_files():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                call_name = _call_name(node.func)
                if call_name in BANNED_CALL_NAMES or _is_banned_module_call(call_name):
                    offenders.append(f"{path}: {call_name}()")
                elif isinstance(node.func, ast.Attribute) and node.func.attr in BANNED_CALL_ATTRIBUTES:
                    offenders.append(f"{path}: .{node.func.attr}()")

    assert offenders == []


def _is_banned_import(module: str) -> bool:
    return any(module == banned or module.startswith(f"{banned}.") for banned in BANNED_IMPORT_ROOTS)


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _is_banned_module_call(call_name: str) -> bool:
    return any(call_name == f"{module}.{name}" for module, name in BANNED_MODULE_CALLS)
