from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from quant_strategies.validation.backends import (
    CapabilityRecord,
    ScenarioBackendRunResult,
    ValidationBackend,
    capability_record,
)


_OBSERVED_UNSUPPORTED_SEMANTIC_MAP = {
    "non_close_fill_price": "non_close_fill_price",
    "threshold_exit_policy": "threshold_exit_policy",
    "non_target_weight_sizing": "non_target_weight_sizing",
    "flat_target": "flat_target",
    "leveraged_target_weight": "leveraged_target_weight",
    "non_open_intent": "non_open_intent",
    "future_instrument": "future_instrument",
    "option_instrument": "option_instrument",
    "multi_leg_decision": "multi_leg_decision",
    "overlapping_decision_window": "same_symbol_overlap",
    "portfolio_target_weight_exceeds_one": "portfolio_target_weight",
}


def backend_capability_matrix(
    backend: ValidationBackend,
    backend_results: Iterable[ScenarioBackendRunResult],
) -> dict[str, Any]:
    observed_unsupported = _observed_unsupported_semantics(backend_results)
    return {
        "backend": backend.name,
        "observed_unsupported_semantics": sorted(observed_unsupported),
        "semantics": _backend_records(backend, observed_unsupported),
    }


def unknown_backend_capability_matrix(
    backend_name: str,
    backend_results: Iterable[ScenarioBackendRunResult],
) -> dict[str, Any]:
    observed_unsupported = _observed_unsupported_semantics(backend_results)
    return {
        "backend": backend_name,
        "observed_unsupported_semantics": sorted(observed_unsupported),
        "semantics": _unknown_backend_records(observed_unsupported),
    }


def _observed_unsupported_semantics(
    backend_results: Iterable[ScenarioBackendRunResult],
) -> set[str]:
    observed: set[str] = set()
    for item in backend_results:
        observed.update(
            _semantic_for_observed_code(code)
            for code in item.result.unsupported_semantics
        )
        observed.update(
            semantic
            for warning in item.result.warnings
            if (semantic := _semantic_for_warning(warning)) is not None
        )
    return observed


def _backend_records(
    backend: ValidationBackend,
    observed_unsupported: set[str],
) -> list[CapabilityRecord]:
    capability_records = getattr(backend, "capability_records", None)
    if callable(capability_records):
        return list(capability_records(observed_unsupported))
    return _unknown_backend_records(observed_unsupported)


def _unknown_backend_records(observed_unsupported: set[str]) -> list[CapabilityRecord]:
    return [
        capability_record(
            semantic,
            "unsupported",
            "Observed as unsupported by backend execution.",
            observed_unsupported=observed_unsupported,
        )
        for semantic in sorted(observed_unsupported)
    ]


def _semantic_for_observed_code(code: str) -> str:
    return _OBSERVED_UNSUPPORTED_SEMANTIC_MAP.get(code, code)


def _semantic_for_warning(warning: str) -> str | None:
    prefix = warning.split(":", 1)[0]
    return _OBSERVED_UNSUPPORTED_SEMANTIC_MAP.get(prefix)
