"""Internal engine models.

This package holds the bar/decision models used by the validation and evaluation
surfaces. The per-trade linear-sum scorer, the isolated exit engine, and the engine
evidence packet were retired by the ``portfolio-book-spine`` change: the single causal,
single-account netted book (`core.portfolio_foundation`) is now the only PnL/NAV
computation, and the authoritative book is the scored object. These models remain
importable for project internals and tests, but they are not a user-facing public surface.
"""

from quant_strategies.engine.evaluation import EvaluationError
from quant_strategies.engine.models import (
    EVIDENCE_SCHEMA_VERSION,
    Bar,
    CostModel,
    EvaluationRequest,
    FillModel,
    StrategySpec,
)

__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "Bar",
    "CostModel",
    "EvaluationError",
    "EvaluationRequest",
    "FillModel",
    "StrategySpec",
]
