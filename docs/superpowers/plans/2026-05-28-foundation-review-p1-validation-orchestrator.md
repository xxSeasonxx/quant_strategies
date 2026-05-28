# Phase 4 Plan: Validation Orchestrator Split

Date: 2026-05-28
Design: `docs/superpowers/specs/2026-05-28-foundation-review-p1-validation-orchestrator-design.md`

## Goal

Address the confirmed validation orchestrator god-function finding while
preserving behavior and artifact contracts.

## Implementation Steps

- [x] **Step 1: Add private context/state helpers**

  Add small dataclasses for immutable run context and mutable accumulated state.
  Keep them private to `validation/__init__.py`.

  Verify: no public exports change.

- [x] **Step 2: Extract window execution handling**

  Move per-window `execute_strategy_run` and `StrategyExecutionError`
  translation into helpers. Preserve all current continue-vs-terminal behavior.

  Verify: validation runner tests covering import, params, data load, and
  decision-generation failures still pass.

- [x] **Step 3: Extract audit/readiness/scenario stages**

  Move audit/lookahead/readiness into one helper and scenario/backend execution
  into another. Preserve scenario result ordering and decision-record artifact
  paths.

  Verify: validation artifacts, backend summary, manifest, and policy tests pass.

- [x] **Step 4: Verification, review, docs/progress**

  Update `progress.md`, run focused validation tests and the full suite, request
  code review, and fix valid findings.

  Verify: all required commands pass before commit.

## Verification Commands

```bash
conda run -n quant pytest tests/test_validation_runner.py tests/test_validation_backends_and_policy.py tests/test_validation_artifacts.py tests/test_validation_lookahead.py tests/test_validation_capabilities.py -q
conda run -n quant pytest -q
git diff --check
conda run -n quant python -m compileall -q src tests
```

## GSTACK REVIEW REPORT

### Scope Challenge

This touches a large file but should not change semantics. Extracting helpers is
justified because the current function interleaves independent stages and makes
future schema work difficult. A smaller doc-only fix would leave the PRD G3
finding intact.

### Architecture Review

Target shape:

```text
run_validation
  -> setup context/state
  -> select backend
  -> run each window
       -> execute strategy run
       -> handle execution failure
       -> audit/lookahead/readiness
       -> run scenarios
  -> classify
  -> write artifacts
```

The key boundary is preserving terminal failures for backend selection,
strategy import, and param validation while preserving continued per-window
hard-no accumulation for data-load, decision-generation, audit, lookahead, and
readiness issues.

### Code Quality Review

- Keep helpers private.
- Avoid new abstractions that imply a reusable framework.
- Keep state mutation explicit in one `_ValidationState` object.
- Do not rename policy reason strings or artifact fields.

### Test Review

Focused validation tests already cover most behavior this refactor can break:
backend summary ordering, decision-record path hashes, validation manifest core
hashes, backend unavailable/setup failures, hidden-lookahead failures, and
policy classification. Add tests only if the refactor exposes a specific
untested branch.

### Performance Review

This phase should not add row iteration or backend calls. It is acceptable if
the function-call count rises; the work is dominated by data loading, replay,
and backend execution.

### Not In Scope

- Reducing repeated `frozen_rows` calls.
- Backend metrics schema.
- Cross-backend agreement policy.
- Validation artifact replayability expansion.
