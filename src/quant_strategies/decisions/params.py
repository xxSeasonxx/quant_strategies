from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from quant_strategies.boundary import frozen_params


def validate_strategy_params(
    generate_decisions: Any,
    params: Mapping[str, Any],
    *,
    require_validator: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Validate params via the strategy's optional ``validate_params`` hook.

    Returns ``(validated_params, had_validator)``. When no validator is defined the
    raw params pass through unchanged and ``had_validator`` is ``False`` — so the
    caller can flag the run as exploratory. When ``require_validator`` is set (the
    validation run does this) a missing validator is an error: a paper-readiness
    verdict must not be sought on a strategy whose params are never validated.
    """
    validator = getattr(generate_decisions, "validate_params", None)
    if validator is None:
        if require_validator:
            raise ValueError("strategy must define validate_params for validation runs")
        return dict(params), False
    validated = validator(frozen_params(params))
    if not isinstance(validated, Mapping):
        raise ValueError("validate_params must return a mapping")
    return dict(validated), True
