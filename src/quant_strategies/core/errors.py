from __future__ import annotations


class RunnerError(ValueError):
    """Base error for failed runner steps."""


class ConfigError(RunnerError):
    """Raised when a run config cannot be parsed or validated."""


class StrategyLoadError(RunnerError):
    """Raised when a strategy file cannot be loaded."""


class DataLoadError(RunnerError):
    """Raised when configured data cannot be loaded."""


class DataReadinessError(RunnerError):
    """Raised when loaded rows are not ready by a decision time."""


class RequestBuildError(RunnerError):
    """Raised when loaded rows and decisions cannot form an engine request."""


class EvaluationRunError(RunnerError):
    """Raised when engine evaluation crashes instead of returning a report."""


class PreparedDataMismatchError(Exception):
    """Raised when preloaded data does not match a run config's data identity.

    A caller precondition violation (reusing a ``PreparedRunData`` against a config with
    a different data window/symbols/identity), not a run outcome — so it propagates as a
    hard error rather than a ``RunResult`` failure, and must never masquerade as a failed
    research attempt. Deliberately not a ``RunnerError`` so ``run_config``'s
    ``except RunnerError`` handlers do not swallow it.
    """
