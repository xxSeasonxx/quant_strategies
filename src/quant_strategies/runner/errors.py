from __future__ import annotations


class RunnerError(ValueError):
    """Base error for failed runner steps."""


class ConfigError(RunnerError):
    """Raised when a run config cannot be parsed or validated."""


class StrategyLoadError(RunnerError):
    """Raised when a strategy file cannot be loaded."""


class DataLoadError(RunnerError):
    """Raised when configured data cannot be loaded."""


class RequestBuildError(RunnerError):
    """Raised when loaded rows and signals cannot form an engine request."""


class EvaluationRunError(RunnerError):
    """Raised when engine evaluation crashes instead of returning a report."""
