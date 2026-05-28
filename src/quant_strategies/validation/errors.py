from __future__ import annotations


class ValidationError(ValueError):
    """Base error for validation workflow failures."""


class ValidationConfigError(ValidationError):
    """Raised when validation configuration cannot be parsed."""


class ValidationDataError(ValidationError):
    """Raised when validation data or decision causality fails."""


class ValidationBackendError(ValidationError):
    """Raised when a validation backend cannot run the requested decisions."""
