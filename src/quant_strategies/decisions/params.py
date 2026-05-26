from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from quant_strategies.boundary import frozen_params


def validate_strategy_params(
    generate_decisions: Any,
    params: Mapping[str, Any],
) -> dict[str, Any]:
    validator = getattr(generate_decisions, "validate_params", None)
    if validator is None:
        return dict(params)
    validated = validator(frozen_params(params))
    if not isinstance(validated, Mapping):
        raise ValueError("validate_params must return a mapping")
    return dict(validated)
