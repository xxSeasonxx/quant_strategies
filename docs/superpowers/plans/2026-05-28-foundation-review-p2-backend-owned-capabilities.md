# Backend-Owned Capabilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move validation backend capability declarations from name-based switches into backend implementations while preserving capability artifact semantics.

**Architecture:** `validation.capabilities` extracts observed unsupported semantics from backend run results and asks the selected backend for static capability records. First-party backends implement `capability_records(observed_unsupported)`, using a shared `capability_record()` helper from `validation.backends`.

**Tech Stack:** Python 3.12, Protocol typing, dataclasses/Pydantic validation models, pytest via `conda run -n quant`.

---

## File Structure

- Modify `src/quant_strategies/validation/backends.py`: add `CapabilityRecord`, `capability_record()`, and `ValidationBackend.capability_records()`.
- Modify `src/quant_strategies/validation/vectorbtpro_backend.py`: add VectorBT Pro capability declarations.
- Modify `src/quant_strategies/validation/capabilities.py`: remove backend-name-specific records; assemble from backend object.
- Modify `src/quant_strategies/validation/__init__.py`: pass the selected backend object into artifact writing.
- Modify `tests/test_validation_capabilities.py`: instantiate backend objects instead of passing backend names.
- Modify `tests/test_validation_runner.py`: ensure injected test backends still produce a generic capability matrix.
- Modify `progress.md`: record Phase 10 status and verification.

## Implementation Steps

- [x] **Step 1: Add backend capability contract**

  Add a `capability_records(observed_unsupported)` method to
  `ValidationBackend` and implement it for `FakeBackend`.

  Verify: capability tests for fake backend still pass.

- [x] **Step 2: Move VectorBT Pro capability records**

  Move the existing VectorBT Pro semantic rows out of `validation.capabilities`
  and into `VectorBTProBackend.capability_records()`.

  Verify: VectorBT Pro capability tests still pass with `VectorBTProBackend()`.

- [x] **Step 3: Reduce capability matrix assembly**

  Change `backend_capability_matrix()` to accept a backend object, extract
  observed unsupported semantics, call backend-owned records, and keep the
  unknown-backend fallback only for missing capability methods or backend
  selection failure.

  Verify: no backend-name string switch remains in `validation.capabilities`.

- [x] **Step 4: Thread backend object through validation artifacts**

  Pass `selected_backend` into `_write_validation_artifacts()` and
  `_failure_result()` after backend selection succeeds. Use unknown fallback only
  when selection fails before an object exists.

  Verify: validation artifact tests still pass.

- [x] **Step 5: Docs/progress, verification, review**

  Update `progress.md`; run focused tests, full suite, diff checks, compile
  checks, and code review before commit.

## Verification Commands

```bash
conda run -n quant pytest tests/test_validation_capabilities.py tests/test_validation_runner.py -q
conda run -n quant pytest tests/test_validation_capabilities.py tests/test_validation_runner.py tests/test_validation_backends_and_policy.py tests/test_vectorbtpro_backend.py -q
conda run -n quant pytest -q
git diff --check
conda run -n quant python -m compileall -q src tests
```

## GSTACK REVIEW REPORT

### Scope Challenge

This phase changes ownership, not semantics. Unsupported-semantics severity and
policy decisions stay unchanged because they are separate review findings.

### Architecture Review

Target flow:

```text
backend run results
        |
        v
validation.capabilities extracts observed unsupported semantics
        |
        v
selected backend declares static capability records
        |
        v
backend_capability_matrix.json preserves existing schema
```

### Edge Cases

- Backend selection fails before an object exists: artifact writer emits unknown
  backend records from observed semantics.
- Injected custom backend lacks `capability_records()`: artifact writer emits
  unknown backend records instead of crashing.
- VectorBT Pro unavailable at runtime: capability declaration still works because
  `VectorBTProBackend` imports VectorBT Pro only inside `run()`.

### Test Review

Tests must cover:

- VectorBT Pro records are declared by `VectorBTProBackend`.
- Fake backend records are declared by `FakeBackend`.
- Observed unsupported semantics are still flagged.
- Validation artifacts preserve the capability matrix shape.
- Generic injected backends do not crash artifact writing.
