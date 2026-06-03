from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from quant_strategies.evaluation.errors import EvaluationError


class EvaluationDependencyError(EvaluationError):
    """Raised when the required evaluation optional dependencies are unavailable."""


@dataclass(frozen=True)
class EvaluationDependencies:
    pandas: Any
    pyarrow: Any
    vectorbtpro: Any


def require_evaluation_dependencies() -> EvaluationDependencies:
    try:
        pd = import_module("pandas")
    except ImportError as exc:
        raise EvaluationDependencyError(f"pandas import failed: {exc}") from exc
    try:
        pa = import_module("pyarrow")
    except ImportError as exc:
        raise EvaluationDependencyError(f"pyarrow import failed: {exc}") from exc
    try:
        vbt = import_module("vectorbtpro")
    except ImportError as exc:
        raise EvaluationDependencyError(f"vectorbtpro import failed: {exc}") from exc
    return EvaluationDependencies(pandas=pd, pyarrow=pa, vectorbtpro=vbt)


def require_pandas_dependency() -> Any:
    try:
        return import_module("pandas")
    except ImportError as exc:
        raise EvaluationDependencyError(f"pandas import failed: {exc}") from exc
