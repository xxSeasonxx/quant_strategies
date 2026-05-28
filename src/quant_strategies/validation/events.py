from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TextIO


ValidationEvent = dict[str, object]
ValidationEventSink = Callable[[ValidationEvent], None]


@dataclass
class _ActiveStage:
    emitter: ValidationStageEmitter
    stage: str
    started: float
    fields: dict[str, object]
    terminal_emitted: bool = False

    def fail(self, error: str, **fields: object) -> None:
        self.terminal_emitted = True
        self.emitter._emit(
            self.stage,
            "failed",
            duration_ms=_elapsed_ms(self.started),
            error=error,
            **self.fields,
            **fields,
        )


@dataclass(frozen=True)
class ValidationStageEmitter:
    sink: ValidationEventSink | None = None

    @contextmanager
    def stage(self, stage: str, **fields: object) -> Iterator[_ActiveStage]:
        started = time.perf_counter()
        active = _ActiveStage(self, stage, started, dict(fields))
        if self.sink is None:
            yield active
            return

        self._emit(stage, "started", **fields)
        try:
            yield active
        except Exception as exc:
            if not active.terminal_emitted:
                active.fail(f"{type(exc).__name__}: {exc}")
            raise
        if not active.terminal_emitted:
            self._emit(stage, "completed", duration_ms=_elapsed_ms(started), **fields)

    def _emit(self, stage: str, status: str, **fields: object) -> None:
        if self.sink is None:
            return
        self.sink(
            {
                "event": "validation_stage",
                "stage": stage,
                "status": status,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **fields,
            }
        )


def jsonl_event_sink(stream: TextIO) -> ValidationEventSink:
    def emit(event: ValidationEvent) -> None:
        print(json.dumps(event, sort_keys=True, separators=(",", ":")), file=stream, flush=True)

    return emit


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)

