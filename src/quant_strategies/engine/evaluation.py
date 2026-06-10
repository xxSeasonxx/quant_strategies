from __future__ import annotations


class EvaluationError(ValueError):
    """Raised when an evaluation request cannot be screened causally.

    The per-trade linear-sum scorer and the isolated ``_select_exit`` exit engine
    were retired by the ``portfolio-book-spine`` change: the single causal,
    single-account netted book (`core.portfolio_foundation`) is now the only
    PnL/NAV computation on the quick-run path. This error type is retained for the
    validation/evaluation surfaces, which are rebuilt on the same spine in a later
    phase.
    """
