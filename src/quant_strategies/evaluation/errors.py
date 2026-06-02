from __future__ import annotations


class EvaluationError(Exception):
    """Base exception for evaluation-surface failures."""


class EvaluationConfigError(EvaluationError):
    """Raised when an evaluation config cannot be loaded or validated."""
