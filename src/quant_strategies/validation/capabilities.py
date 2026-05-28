from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from quant_strategies.validation.backends import ScenarioBackendRunResult


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
    backend_name: str,
    backend_results: Iterable[ScenarioBackendRunResult],
) -> dict[str, Any]:
    observed_unsupported = _observed_unsupported_semantics(backend_results)
    return {
        "backend": backend_name,
        "observed_unsupported_semantics": sorted(observed_unsupported),
        "semantics": _semantic_records(backend_name, observed_unsupported),
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


def _semantic_records(
    backend_name: str,
    observed_unsupported: set[str],
) -> list[dict[str, Any]]:
    if backend_name == "fake":
        return [
            _record(
                "test_double",
                "supported",
                "Deterministic validation test double.",
                observed_unsupported=observed_unsupported,
            )
        ]
    if backend_name == "vectorbtpro":
        return _vectorbtpro_records(observed_unsupported)
    return _unknown_backend_records(observed_unsupported)


def _vectorbtpro_records(observed_unsupported: set[str]) -> list[dict[str, Any]]:
    rows = [
        _record(
            "close_fills",
            "supported",
            "Close-price fills are supported.",
            observed_unsupported=observed_unsupported,
        ),
        _record(
            "target_weight_sizing",
            "supported",
            "Target-weight sizing is supported.",
            observed_unsupported=observed_unsupported,
        ),
        _record(
            "portfolio_target_weight",
            "conditional",
            (
                "Supported under close-fill execution with target-weight sizing, "
                "no threshold exits, no same-symbol overlap, no leverage, and gross "
                "active target weight less than or equal to 1.0."
            ),
            observed_unsupported=observed_unsupported,
        ),
        _record(
            "crypto_perp_funding_linear_additive_adjustment",
            "conditional",
            "Crypto perp funding is modeled as a linear additive return adjustment.",
            observed_unsupported=observed_unsupported,
        ),
        _record(
            "non_close_fill_price",
            "unsupported",
            "Non-close fill prices are unsupported.",
            observed_unsupported=observed_unsupported,
        ),
        _record(
            "threshold_exit_policy",
            "unsupported",
            "Stop-loss, take-profit, and trailing-stop exits are unsupported.",
            observed_unsupported=observed_unsupported,
        ),
        _record(
            "non_target_weight_sizing",
            "unsupported",
            "Sizing kinds other than target_weight are unsupported.",
            observed_unsupported=observed_unsupported,
        ),
        _record(
            "flat_target",
            "unsupported",
            "Flat targets are unsupported.",
            observed_unsupported=observed_unsupported,
        ),
        _record(
            "leveraged_target_weight",
            "unsupported",
            "Leveraged target weights are unsupported.",
            observed_unsupported=observed_unsupported,
        ),
        _record(
            "same_symbol_overlap",
            "unsupported",
            "Overlapping active decision windows for the same symbol are unsupported.",
            observed_unsupported=observed_unsupported,
        ),
        _record(
            "non_open_intent",
            "unsupported",
            "Close, adjust, and roll intents are unsupported.",
            observed_unsupported=observed_unsupported,
        ),
        _record(
            "future_instrument",
            "unsupported",
            "Futures are representable in StrategyDecision but unsupported by this backend.",
            observed_unsupported=observed_unsupported,
        ),
        _record(
            "option_instrument",
            "unsupported",
            "Options are representable in StrategyDecision but unsupported by this backend.",
            observed_unsupported=observed_unsupported,
        ),
        _record(
            "multi_leg_decision",
            "unsupported",
            "Multi-leg decisions are representable in StrategyDecision but unsupported by this backend.",
            observed_unsupported=observed_unsupported,
        ),
    ]
    return rows


def _unknown_backend_records(observed_unsupported: set[str]) -> list[dict[str, Any]]:
    return [
        _record(
            semantic,
            "unsupported",
            "Observed as unsupported by backend execution.",
            observed_unsupported=observed_unsupported,
        )
        for semantic in sorted(observed_unsupported)
    ]


def _record(
    semantic: str,
    status: str,
    details: str,
    *,
    observed_unsupported: set[str],
) -> dict[str, Any]:
    return {
        "semantic": semantic,
        "status": status,
        "details": details,
        "observed_unsupported": semantic in observed_unsupported,
    }


def _semantic_for_observed_code(code: str) -> str:
    return _OBSERVED_UNSUPPORTED_SEMANTIC_MAP.get(code, code)


def _semantic_for_warning(warning: str) -> str | None:
    prefix = warning.split(":", 1)[0]
    return _OBSERVED_UNSUPPORTED_SEMANTIC_MAP.get(prefix)
