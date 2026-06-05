from __future__ import annotations

from typing import ClassVar

from quant_strategies.core.events import (
    StageEmitter,
    StageEvent,
    StageEventSink,
    jsonl_event_sink,
)

EvaluationEvent = StageEvent
EvaluationEventSink = StageEventSink


class EvaluationStageEmitter(StageEmitter):
    event_type: ClassVar[str] = "evaluation_stage"


__all__ = [
    "EvaluationEvent",
    "EvaluationEventSink",
    "EvaluationStageEmitter",
    "jsonl_event_sink",
]
