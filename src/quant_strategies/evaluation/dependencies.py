from __future__ import annotations

from importlib import import_module
from typing import Any

from quant_strategies.evaluation.errors import EvaluationError


class EvaluationDependencyError(EvaluationError):
    """Raised when a required evaluation optional dependency is unavailable."""


def require_pandas_dependency() -> Any:
    try:
        return import_module("pandas")
    except ImportError as exc:
        raise EvaluationDependencyError(f"pandas import failed: {exc}") from exc
