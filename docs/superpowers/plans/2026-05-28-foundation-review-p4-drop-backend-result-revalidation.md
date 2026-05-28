# Drop Backend Result Revalidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove redundant Pydantic revalidation of `ValidationBackend.run()`
results while preserving current failure artifacts for nonconforming injected
backends.

**Architecture:** Backend implementations own construction of
`BackendRunResult`. Validation scenario execution trusts that Protocol return
type when it is present and records `invalid_backend_result` only when an
injected backend returns a different runtime type.

**Tech Stack:** Python 3.12, pytest via `conda run -n quant`.

---

## File Structure

- Modify `tests/test_validation_runner.py`: add no-revalidation regression and
  adjust nonconforming backend expectations.
- Modify `src/quant_strategies/validation/__init__.py`: remove
  `BackendRunResult.model_validate()` in scenario backend execution.
- Modify `progress.md`: record Phase 18 status and verification.

## Implementation Steps

- [x] **Step 1: Add no-revalidation regression**

  Add a test that monkeypatches `BackendRunResult.model_validate` to raise and
  verifies a conforming backend result still completes without
  `invalid_backend_result`.

  Verify it fails before implementation:

  ```bash
  conda run -n quant pytest tests/test_validation_runner.py::test_run_validation_trusts_backend_run_result_without_pydantic_revalidation -q
  ```

- [x] **Step 2: Replace Pydantic revalidation with Protocol-type handling**

  In `_run_scenario_backend()`:

  - call `context.selected_backend.run(...)`
  - if the returned value is a `BackendRunResult`, assign it directly
  - otherwise create `_failed_backend_result(..., "invalid_backend_result: expected BackendRunResult, got <type>")`

  Update malformed backend tests so dict/None returns are treated as
  nonconforming Protocol returns rather than parsed backend result payloads.

  Verify:

  ```bash
  rg -n "BackendRunResult\\.model_validate" src
  conda run -n quant pytest tests/test_validation_runner.py::test_run_validation_trusts_backend_run_result_without_pydantic_revalidation tests/test_validation_runner.py::test_run_validation_writes_failure_artifacts_for_malformed_backend_result tests/test_validation_runner.py::test_run_validation_rejects_invalid_backend_status -q
  ```

- [x] **Step 3: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest tests/test_validation_runner.py tests/test_validation_backends_and_policy.py tests/test_validation_capabilities.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused checks
  plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

Dropping runner `FillModel`/`CostModel` construction would be wrong in this
phase. Those constructors adapt runner config objects into engine request
objects and intentionally drop the runner-only `allow_same_bar_close_fill`
field. Phase 18 should only remove validation backend result revalidation.

### Architecture Review

Target flow:

```text
ValidationBackend.run()
        |
        v
BackendRunResult instance -> store directly
other return value       -> failed BackendRunResult with invalid_backend_result warning
```

This keeps the typed backend contract as the source of truth while preserving
defensive artifact generation for test/custom backends that violate it.

### Edge Cases

- Backend exceptions remain `backend_exception`.
- `SystemExit` and other `BaseException` subclasses are still not swallowed by
  the existing `except Exception`.
- Dict returns are no longer parsed; backend implementations must construct the
  typed result they promise.
- Existing validation artifact writers still receive `BackendRunResult`.

### Test Review

Tests cover absence of `BackendRunResult.model_validate()` calls, malformed
backend returns, existing backend exception artifacts, focused validation
runner behavior, backend policy/capability tests, full suite, diff check, and
compile check.
