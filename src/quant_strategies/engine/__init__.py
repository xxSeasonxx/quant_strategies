"""Internal engine models and evidence shaping.

This package holds the bar/decision models and evidence packet used by the
validation and evaluation surfaces. The per-trade linear-sum scorer and the
isolated exit engine were retired by the ``portfolio-book-spine`` change: the
single causal, single-account netted book (`core.portfolio_foundation`) is now the
only PnL/NAV computation on the quick-run path. It remains importable for project
internals and tests, but it is not a user-facing public surface.
"""

from quant_strategies.engine.evaluation import EvaluationError
from quant_strategies.engine.evidence import build_evidence_packet, evidence_json
from quant_strategies.engine.models import (
    EVIDENCE_SCHEMA_VERSION,
    Bar,
    CostModel,
    EvaluationRequest,
    EvidencePacket,
    ExitReason,
    FillModel,
    GateResult,
    GatingConfig,
    GatingReport,
    ScreeningResult,
    Side,
    StrategySpec,
    Trade,
    TradeResult,
)

__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "Bar",
    "CostModel",
    "EvaluationError",
    "EvaluationRequest",
    "EvidencePacket",
    "ExitReason",
    "FillModel",
    "GateResult",
    "GatingConfig",
    "GatingReport",
    "ScreeningResult",
    "Side",
    "StrategySpec",
    "Trade",
    "TradeResult",
    "build_evidence_packet",
    "evidence_json",
]
