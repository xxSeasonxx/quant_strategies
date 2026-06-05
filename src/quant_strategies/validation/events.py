from __future__ import annotations

from typing import ClassVar

from quant_strategies.core.events import (
    StageEmitter,
    StageEvent,
    StageEventSink,
    jsonl_event_sink,
)

ValidationEvent = StageEvent
ValidationEventSink = StageEventSink


class ValidationStageEmitter(StageEmitter):
    event_type: ClassVar[str] = "validation_stage"


__all__ = [
    "ValidationEvent",
    "ValidationEventSink",
    "ValidationStageEmitter",
    "jsonl_event_sink",
]
