# Retire Unused Validation Errors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the unused validation error subclasses while preserving the
validation exceptions that are actually raised.

**Architecture:** Validation keeps one base workflow exception
(`ValidationError`) and one concrete configuration exception
(`ValidationConfigError`). Data and backend failures continue to be represented
by existing audit/policy/backend result payloads rather than unused exception
types.

**Tech Stack:** Python 3.12, pytest via `conda run -n quant`.

---

## File Structure

- Create `tests/test_validation_errors.py`: regression for public error names.
- Modify `src/quant_strategies/validation/errors.py`: delete unused subclasses.
- Modify `progress.md`: record Phase 17 status and verification.

## Implementation Steps

- [x] **Step 1: Add the error-surface regression**

  Add a test that imports `quant_strategies.validation.errors` and asserts the
  public exported names are exactly:

  ```python
  {"ValidationError", "ValidationConfigError"}
  ```

  Verify it fails before implementation:

  ```bash
  conda run -n quant pytest tests/test_validation_errors.py -q
  ```

- [x] **Step 2: Delete unused error subclasses**

  Remove `ValidationDataError` and `ValidationBackendError` from
  `src/quant_strategies/validation/errors.py`.

  Verify:

  ```bash
  rg -n "ValidationBackendError|ValidationDataError" src tests
  conda run -n quant pytest tests/test_validation_errors.py tests/test_validation_config.py tests/test_validation_cli.py tests/test_validation_runner.py -q
  ```

- [x] **Step 3: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused checks
  plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

The review finding is about dead exception classes, not about replacing
validation result payloads with exceptions. Keeping this phase to deletion avoids
inventing new failure semantics.

### Architecture Review

The remaining exception hierarchy is intentionally small:

```text
ValidationError
        |
        v
ValidationConfigError
```

Runtime data, backend, and policy failures stay in their existing structured
result objects and artifacts.

### Edge Cases

- External imports of the retired classes fail by design.
- CLI handling remains broad enough because it catches `ValidationError`.
- Pydantic `ValidationError` imports in config/model tests are unrelated.

### Test Review

Tests cover the public error surface, existing validation config errors, CLI
handling, validation runner behavior, full suite, diff check, and compile check.
