from __future__ import annotations

import ast
from pathlib import Path


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


def strategy_purity_violations(path: str | Path) -> tuple[str, ...]:
    strategy_path = Path(path)
    try:
        tree = ast.parse(strategy_path.read_text())
    except SyntaxError as exc:
        line = f" line {exc.lineno}" if exc.lineno is not None else ""
        return (f"{strategy_path}: invalid Python syntax{line}: {exc.msg}",)

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_banned_import(alias.name):
                    violations.append(f"{strategy_path}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _is_banned_import(module):
                violations.append(f"{strategy_path}: from {module} import ...")
        elif isinstance(node, ast.Call):
            call_name = _call_name(node.func)
            if call_name in BANNED_CALL_NAMES or _is_banned_module_call(call_name):
                violations.append(f"{strategy_path}: {call_name}()")
            elif isinstance(node.func, ast.Attribute) and node.func.attr in BANNED_CALL_ATTRIBUTES:
                violations.append(f"{strategy_path}: .{node.func.attr}()")

    return tuple(violations)


def _is_banned_import(module: str) -> bool:
    return any(
        module == banned or module.startswith(f"{banned}.")
        for banned in BANNED_IMPORT_ROOTS
    )


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _is_banned_module_call(call_name: str) -> bool:
    return any(call_name == f"{module}.{name}" for module, name in BANNED_MODULE_CALLS)
