from __future__ import annotations


class ValidationError(ValueError):
    """Base error for validation workflow failures."""


class ValidationConfigError(ValidationError):
    """Raised when validation configuration cannot be parsed."""
