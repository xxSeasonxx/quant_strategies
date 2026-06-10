"""Internal engine package.

The per-trade linear-sum scorer, the isolated exit engine, the bar/decision DTOs, and
the engine evidence packet were retired by the ``portfolio-book-spine`` change: the
single causal, single-account netted book (`core.portfolio_foundation`) is now the only
PnL/NAV computation on every surface, and the authoritative book is the scored object.
The only remaining export is the evidence-schema version constant. This is an internal
execution kernel, not a fourth public surface.
"""

from quant_strategies.engine.models import EVIDENCE_SCHEMA_VERSION

__all__ = ["EVIDENCE_SCHEMA_VERSION"]
