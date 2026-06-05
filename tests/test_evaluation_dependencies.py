from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

import quant_strategies.evaluation.dependencies as deps_module
from quant_strategies.evaluation.dependencies import (
    EvaluationDependencyError,
    require_evaluation_dependencies,
)


def test_require_evaluation_dependencies_returns_imported_modules(monkeypatch: pytest.MonkeyPatch):
    fake_pandas = SimpleNamespace(__name__="pandas")
    fake_pyarrow = SimpleNamespace(__name__="pyarrow")
    fake_vectorbtpro = SimpleNamespace(__name__="vectorbtpro")

    def fake_import_module(name: str):
        if name == "pandas":
            return fake_pandas
        if name == "pyarrow":
            return fake_pyarrow
        if name == "vectorbtpro":
            return fake_vectorbtpro
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(deps_module, "import_module", fake_import_module)

    deps = require_evaluation_dependencies()

    assert deps.pandas is fake_pandas
    assert deps.pyarrow is fake_pyarrow
    assert deps.vectorbtpro is fake_vectorbtpro


@pytest.mark.parametrize("missing", ["pandas", "pyarrow", "vectorbtpro"])
def test_require_evaluation_dependencies_fails_without_jsonl_fallback(
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
):
    def fake_import_module(name: str):
        if name == missing:
            raise ImportError(f"missing {name}")
        if name == "pyarrow":
            return SimpleNamespace(__name__="pyarrow")
        if name == "pandas":
            return SimpleNamespace(__name__="pandas")
        if name == "vectorbtpro":
            return SimpleNamespace(__name__="vectorbtpro")
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(deps_module, "import_module", fake_import_module)

    with pytest.raises(EvaluationDependencyError, match=f"{missing} import failed"):
        require_evaluation_dependencies()


def test_pyproject_declares_evaluation_extra_dependencies():
    payload = tomllib.loads(Path("pyproject.toml").read_text())
    evaluation = payload["project"]["optional-dependencies"]["evaluation"]

    assert "vectorbtpro" in evaluation
    assert any(item.startswith("pandas>=") for item in evaluation)
    assert any(item.startswith("pyarrow>=") for item in evaluation)
