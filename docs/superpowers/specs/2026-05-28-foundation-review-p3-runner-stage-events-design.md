# Phase 25 Design: Runner Structured Stage Events

Date: 2026-05-28
Mode: Builder
Source review: `review-codex.md`

## Problem

`review-codex.md` Finding 8 flags that structured stage observability is
missing. Runner and CLI users only get a final result path or failure message,
so long autonomous sweeps cannot see which stage is active, how long stages
took, or where a failure occurred without waiting for artifacts.

## Assignment

Add a minimal structured event surface to the runner path. The Python API should
let `quant_autoresearch` pass an event sink, and the CLI should expose JSONL
events without changing its existing stdout contract.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed
for Phase 25:

- Scope this phase to `quant_strategies.runner.run_config`, not validation.
- Use an optional callback sink rather than configuring global logging.
- Keep stdout unchanged; CLI stage events go to stderr behind an explicit flag.
- Emit start/completed/failed status and duration for stage boundaries.
- Do not persist event logs as runner artifacts in this phase.

## Scope

- Add a small runner event helper.
- Extend `run_config(..., event_sink=None)` compatibly.
- Add `quant-strategies run --events-jsonl`.
- Add focused API and CLI tests.
- Update docs and progress.

## Not In Scope

- Validation stage events.
- A logging framework or dashboard.
- Artifact persistence for stage event logs.
- Changing `RunResult` fields.

## Success Criteria

- API callers can collect structured runner stage events by passing a sink.
- CLI users can opt into JSONL stage events on stderr.
- Stage events include `event`, `stage`, `status`, UTC timestamp, and
  `duration_ms` for completed/failed events.
- Existing CLI stdout and `RunResult` behavior stay compatible.
- Focused tests, full suite, diff check, compile check, and code review pass.
