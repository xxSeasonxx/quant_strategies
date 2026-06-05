"""Internal deterministic quant screening and validation engine.

This package is the execution kernel used by the quick-run and validation
surfaces. It remains importable for project internals and tests, but it is not a
user-facing public surface.
"""

from quant_strategies.engine.evaluation import gate_screen, screen
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
    "gate_screen",
    "screen",
]
