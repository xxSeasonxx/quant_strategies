"""Deterministic quant screening and validation engine."""

from quant_strategies.engine.evaluation import gate_screen, screen
from quant_strategies.engine.evidence import build_evidence_packet, evidence_json
from quant_strategies.engine.models import (
    Bar,
    CostModel,
    EVIDENCE_SCHEMA_VERSION,
    EvaluationRequest,
    EvidencePacket,
    ExitReason,
    FillModel,
    GatingConfig,
    GatingReport,
    GateResult,
    ScreeningResult,
    Side,
    TradeResult,
    StrategySpec,
    Trade,
)

__all__ = [
    "Bar",
    "CostModel",
    "EVIDENCE_SCHEMA_VERSION",
    "EvaluationRequest",
    "EvidencePacket",
    "ExitReason",
    "FillModel",
    "GatingConfig",
    "GatingReport",
    "GateResult",
    "ScreeningResult",
    "Side",
    "TradeResult",
    "StrategySpec",
    "Trade",
    "build_evidence_packet",
    "evidence_json",
    "gate_screen",
    "screen",
]
