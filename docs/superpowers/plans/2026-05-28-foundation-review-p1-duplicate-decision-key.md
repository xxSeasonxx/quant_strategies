# Duplicate Decision Execution Key Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject duplicate same-symbol, same-time decisions before smoke or validation execution can double-count them.

**Architecture:** `validate_decision_output()` remains the shared decision-output boundary for runner and validation. It will keep existing shape/type/strategy/decision-id checks and add a second uniqueness check keyed by `(instrument.symbol, decision_time)`.

**Tech Stack:** Python 3.12, Pydantic `StrategyDecision`, pytest via `conda run -n quant`.

---

## File Structure

- Modify `src/quant_strategies/decisions/output_validation.py`: add execution-key uniqueness validation.
- Modify `tests/test_decision_models.py`: add focused duplicate execution-key regression.
- Modify `progress.md`: record Phase 11 status and verification.

## Implementation Steps

- [x] **Step 1: Add duplicate execution-key regression**

  Add a test that creates two valid `StrategyDecision` objects with different
  `decision_id` values but the same `instrument.symbol` and `decision_time`.
  Assert only the first decision is accepted and the second produces a duplicate
  execution-key violation.

  Verify: `conda run -n quant pytest tests/test_decision_models.py::test_validate_decision_output_rejects_duplicate_symbol_decision_time -q` fails before implementation.

- [x] **Step 2: Implement shared output validation**

  Track seen `(item.instrument.symbol, item.decision_time)` keys after the
  existing strategy-id and decision-id checks. Reject subsequent decisions with a
  stable violation string.

  Verify: focused duplicate test passes.

- [x] **Step 3: Docs/progress, verification, review**

  Update `progress.md`; run focused tests, full suite, diff checks, compile
  checks, and code review before commit.

## Verification Commands

```bash
conda run -n quant pytest tests/test_decision_models.py tests/test_runner_api_cli.py tests/test_validation_runner.py -q
conda run -n quant pytest -q
git diff --check
conda run -n quant python -m compileall -q src tests
```

## GSTACK REVIEW REPORT

### Scope Challenge

This guard is intentionally current-engine-specific. Future multi-intent or
multi-leg execution can replace it with a richer execution plan key, but today's
silent double-counting risk is real and should be blocked now.

### Architecture Review

Target flow:

```text
strategy generate_decisions output
        |
        v
validate_decision_output()
        |
        v
reject duplicate decision_id or duplicate (symbol, decision_time)
        |
        v
runner/validation execution receives de-duplicated decision list
```

### Edge Cases

- Same `decision_id`: existing `duplicate_decision_id` behavior wins.
- Different `decision_id`, same `(symbol, decision_time)`: new duplicate
  execution-key violation.
- Same symbol at different decision times: allowed.
- Different symbols at the same decision time: allowed.

### Test Review

Tests must cover:

- existing duplicate `decision_id` behavior remains unchanged;
- duplicate `(symbol, decision_time)` with different IDs is rejected;
- full runner/validation suites still pass.
