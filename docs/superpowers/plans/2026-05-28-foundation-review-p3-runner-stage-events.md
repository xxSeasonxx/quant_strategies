# Runner Stage Events Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development where practical. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Goal:** Give runner API and CLI users structured stage events for live
observability without changing existing stdout or result contracts.

**Architecture:** Add a tiny `runner.events` helper with an optional sink
callback and stage context manager. `run_config()` emits events around existing
stage boundaries. CLI `--events-jsonl` writes those event payloads to stderr as
canonical-ish JSON lines.

**Tech Stack:** Python 3.12, stdlib JSON/time/contextlib, pytest via
`conda run -n quant`.

---

## File Structure

- Add `src/quant_strategies/runner/events.py`: event types and emitter.
- Modify `src/quant_strategies/runner/__init__.py`: optional event sink and
  stage emissions.
- Modify `src/quant_strategies/runner/cli.py`: `--events-jsonl` flag.
- Modify `tests/test_runner_api_cli.py`: API and CLI event regressions.
- Modify `README.md`, `docs/quant-autoresearch-consumer.md`, and `progress.md`.

## Implementation Steps

- [x] **Step 1: Add failing event regressions**

  Add tests that prove:

  - `run_config(..., event_sink=events.append)` emits structured
    `runner_stage` start/completed events for core stages.
  - `quant-strategies run --events-jsonl` preserves stdout as the result dir and
    writes JSONL stage events to stderr.

  Verify they fail before implementation:

  ```bash
  conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_emits_structured_stage_events tests/test_runner_api_cli.py::test_cli_run_events_jsonl_writes_events_to_stderr -q
  ```

- [x] **Step 2: Implement runner event surface**

  Add event helper and wire events around:

  - `config_load`
  - `artifact_initialization`
  - `strategy_execution`
  - `causality_check`
  - `request_build`
  - `data_readiness`
  - `engine_evaluation`
  - `artifact_writes`

  Failure events should surface stage and error string without swallowing the
  existing runner error translation.

- [x] **Step 3: Docs, verification, and review**

  Update docs and progress, then run:

  ```bash
  conda run -n quant pytest tests/test_runner_api_cli.py tests/test_readme_contract.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused
  checks plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

This phase intentionally avoids global logging. A callback sink is enough for
`quant_autoresearch`, and an explicit CLI flag gives humans and scripts JSONL
without changing default output.

### Architecture Review

Target flow:

```text
run_config(event_sink=...) -> RunnerStageEmitter -> sink(dict)
CLI --events-jsonl        -> sink writes JSON to stderr
```

The helper is runner-owned and has no dependency on config, artifacts, engine,
or validation. That keeps the dependency direction simple.

### Edge Cases

- If the sink raises, the run should fail loudly instead of hiding
  observability failures.
- Config-load failures should still emit a failed `config_load` event when a
  sink is supplied.
- Existing CLI stdout remains a bare result directory on success.
- `duration_ms` is measured with `perf_counter()` and should only be asserted as
  a non-negative number.

### Test Review

Tests cover API event collection, CLI stderr JSONL output, stdout compatibility,
and focused runner/readme behavior.
