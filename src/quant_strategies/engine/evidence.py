from __future__ import annotations

import json

from quant_strategies.engine.models import (
    EvaluationRequest,
    EvidencePacket,
    GatingReport,
    ScreeningResult,
)


def build_evidence_packet(
    request: EvaluationRequest,
    *,
    screening_result: ScreeningResult | None = None,
    validation_report: GatingReport | None = None,
) -> EvidencePacket:
    mode = "gate" if validation_report is not None else "screen"
    return EvidencePacket(
        mode=mode,
        strategy_id=request.spec.strategy_id,
        screening_result=screening_result,
        validation_report=validation_report,
    )


def evidence_json(packet: EvidencePacket) -> str:
    payload = packet.model_dump(mode="json", exclude_none=True)
    return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
