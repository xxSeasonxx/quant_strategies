"""Deterministic quant screening and validation engine."""

from quant_strategies.engine.evaluation import screen, validate
from quant_strategies.engine.evidence import build_evidence_packet, evidence_json
from quant_strategies.engine.models import (
    Bar,
    CostModel,
    EVIDENCE_SCHEMA_VERSION,
    EvaluationRequest,
    EvidencePacket,
    FillModel,
    GateResult,
    ScreeningResult,
    Side,
    Signal,
    StrategySpec,
    Trade,
    ValidationConfig,
    ValidationReport,
)

__all__ = [
    "Bar",
    "CostModel",
    "EVIDENCE_SCHEMA_VERSION",
    "EvaluationRequest",
    "EvidencePacket",
    "FillModel",
    "GateResult",
    "ScreeningResult",
    "Side",
    "Signal",
    "StrategySpec",
    "Trade",
    "ValidationConfig",
    "ValidationReport",
    "build_evidence_packet",
    "evidence_json",
    "screen",
    "validate",
]
