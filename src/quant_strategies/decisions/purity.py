"""Best-effort static purity lint for strategy files.

This is an AST denylist, **not** a runtime sandbox. It rejects the common ways a
strategy could load data or cause side effects (file reads/writes, dynamic
imports, network, non-deterministic clocks/RNG), but a determined strategy can
still escape it (e.g. ``getattr``-based or computed attribute access). The real
guarantee is the contract — strategies are pure ``generate_decisions(rows,
params)`` and load data only via ``quant_data`` upstream — plus human review;
this lint is the cheap first line of defense, not a security boundary.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path

BANNED_IMPORT_ROOTS = {
    "multiprocessing",
    "quant_data",
    "quant_strategies.engine",
    "quant_strategies.evaluation",
    "quant_strategies.runner",
    "quant_strategies.validation",
    "threading",
}
BANNED_CALL_NAMES = {
    "__import__",
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
    # Reads are data loading too (AGENTS.md: strategies must not load data; use the
    # quant_data loader, not files). Attribute-form bans are alias-proof: they catch
    # Path(...).read_text(), pd.read_csv(...), and pandas.read_csv(...) alike.
    "read_text",
    "read_bytes",
    "read_csv",
    "read_parquet",
    "read_json",
    "read_excel",
    "read_feather",
    "read_pickle",
    "read_hdf",
    "glob",
    "rglob",
    "iterdir",
    "to_csv",
    "to_parquet",
    "to_json",
    "to_excel",
    "to_feather",
    "to_pickle",
    "to_hdf",
}
BANNED_MODULE_CALLS = {
    ("datetime", "now"),
    ("datetime", "utcnow"),
    ("datetime.datetime", "now"),
    ("datetime.datetime", "utcnow"),
    ("os", "popen"),
    ("os", "remove"),
    ("os", "rmdir"),
    ("os", "system"),
    ("os", "unlink"),
    ("random", "*"),
    ("requests", "*"),
    ("httpx", "*"),
    ("socket", "*"),
    ("subprocess", "call"),
    ("subprocess", "check_call"),
    ("subprocess", "check_output"),
    ("subprocess", "run"),
    ("time", "time"),
    ("numpy.random", "*"),
    # Dynamic import and network access are import/data-loading escapes.
    ("importlib", "*"),
    ("urllib", "*"),
}


def strategy_purity_violations(path: str | Path) -> tuple[str, ...]:
    strategy_path = Path(path)
    try:
        tree = ast.parse(strategy_path.read_text())
    except SyntaxError as exc:
        line = f" line {exc.lineno}" if exc.lineno is not None else ""
        return (f"{strategy_path}: invalid Python syntax{line}: {exc.msg}",)

    violations: list[str] = []
    aliases = _import_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_banned_import(alias.name):
                    violations.append(f"{strategy_path}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _is_banned_import(module):
                violations.append(f"{strategy_path}: from {module} import ...")
            else:
                for alias in node.names:
                    imported_module = f"{module}.{alias.name}" if module else alias.name
                    if _is_banned_import(imported_module):
                        violations.append(f"{strategy_path}: from {imported_module} import ...")
        elif isinstance(node, ast.Call):
            call_name = _call_name(node.func, aliases)
            if _is_banned_call_name(call_name):
                violations.append(f"{strategy_path}: {call_name}()")
            elif _is_getattr_dynamic_import(node, aliases):
                violations.append(f"{strategy_path}: getattr(__import__(...), ...)()")
            elif isinstance(node.func, ast.Attribute) and node.func.attr in BANNED_CALL_ATTRIBUTES:
                violations.append(f"{strategy_path}: .{node.func.attr}()")

    return tuple(violations)


def _is_banned_import(module: str) -> bool:
    return any(
        module == banned or module.startswith(f"{banned}.") for banned in BANNED_IMPORT_ROOTS
    )


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".", 1)[0]
                aliases[local_name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                local_name = alias.asname or alias.name
                aliases[local_name] = f"{module}.{alias.name}" if module else alias.name
    return aliases


def _call_name(node: ast.expr, aliases: Mapping[str, str] | None = None) -> str:
    aliases = aliases or {}
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value, aliases)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _is_banned_module_call(call_name: str) -> bool:
    return any(
        call_name == f"{module}.{name}" if name != "*" else call_name.startswith(f"{module}.")
        for module, name in BANNED_MODULE_CALLS
    )


def _is_banned_call_name(call_name: str) -> bool:
    return (
        call_name in BANNED_CALL_NAMES
        or _is_dynamic_import_call_name(call_name)
        or _is_banned_module_call(call_name)
    )


def _is_getattr_dynamic_import(node: ast.Call, aliases: Mapping[str, str]) -> bool:
    if _call_name(node.func, aliases) != "getattr":
        return False
    return any(_is_dynamic_import_call(arg, aliases) for arg in node.args)


def _is_dynamic_import_call(node: ast.AST, aliases: Mapping[str, str]) -> bool:
    return isinstance(node, ast.Call) and _is_dynamic_import_call_name(
        _call_name(node.func, aliases)
    )


def _is_dynamic_import_call_name(call_name: str) -> bool:
    return call_name in {"__import__", "builtins.__import__"}
