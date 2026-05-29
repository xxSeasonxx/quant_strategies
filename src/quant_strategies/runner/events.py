from __future__ import annotations

from typing import ClassVar

from quant_strategies.core.events import (
    StageEmitter,
    StageEvent,
    StageEventSink,
    jsonl_event_sink,
)


RunnerEvent = StageEvent
RunnerEventSink = StageEventSink


class RunnerStageEmitter(StageEmitter):
    event_type: ClassVar[str] = "runner_stage"


__all__ = ["RunnerEvent", "RunnerEventSink", "RunnerStageEmitter", "jsonl_event_sink"]
