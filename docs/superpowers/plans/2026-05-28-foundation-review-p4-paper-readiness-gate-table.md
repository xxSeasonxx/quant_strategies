# Paper Readiness Gate Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development for implementation when practical. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make validation paper-readiness gates auditable as a declarative ordered table without changing policy behavior.

**Architecture:** Keep `classify_validation()` and `_paper_readiness_decision()` as the policy entry points. Add a private ordered `_PAPER_READINESS_GATES` tuple and let `_paper_readiness_decision()` compute a local `gate_results` map, then iterate the table to produce the same `passed_gates`, `failed_gates`, and `gate_details` payloads.

**Tech Stack:** Python 3.12, pytest via `conda run -n quant`.

---

## File Structure

- Modify `tests/test_validation_backends_and_policy.py`: add a structural regression for the paper-readiness gate table.
- Modify `src/quant_strategies/validation/policy.py`: add the private ordered gate table and replace repeated gate blocks with table-driven evaluation.
- Modify `progress.md`.

## Implementation Steps

- [x] **Step 1: Add failing structural regression**

  Add a test that imports `quant_strategies.validation.policy` and asserts the
  private `_PAPER_READINESS_GATES` table declares these gate names in order:

  ```python
  (
      "min_windows",
      "min_total_trades",
      "no_zero_trade_windows",
      "aggregate_realistic_net_positive",
      "positive_window_fraction",
      "stressed_net_floor",
      "fill_lag_net_floor",
  )
  ```

  Verify failure before implementation:

  ```bash
  conda run -n quant pytest tests/test_validation_backends_and_policy.py::test_policy_declares_paper_readiness_gates_in_order -q
  ```

- [x] **Step 2: Refactor gate evaluation**

  Add `_PAPER_READINESS_GATES`, compute each gate's `(passed, detail)` tuple in
  a local `gate_results` map, then iterate the ordered table to populate
  `passed_gates`, `failed_gates`, and `gate_details`. Preserve all existing gate
  names, details, and final decision logic.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_validation_backends_and_policy.py -q
  ```

- [x] **Step 3: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest tests/test_validation_backends_and_policy.py tests/test_validation_runner.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused
  checks plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

This is a structure-only cleanup. Changing thresholds or policy outcomes would
increase risk and would mix a refactor with quant policy changes. The correct
small phase is to make the current gates explicit and keep behavior stable.

### Architecture Review

Target shape:

```text
_paper_readiness_decision()
  -> compute derived paper-readiness metrics once
  -> build local gate_results by gate name
  -> iterate _PAPER_READINESS_GATES for stable ordering
  -> final decision based on failed_gates and positive realistic evidence
```

The table owns gate names and evaluation order. The local result map owns each
gate's boolean and detail string, so the policy stays auditable without adding a
new helper layer.

### Edge Cases

- Missing realistic cost scenarios must still produce `missing cost scenarios`
  details for cost-derived gates.
- Missing `cost_stress` or `fill_lag` scenarios must still fail their floors
  with the existing missing-scenario details.
- Paper-readiness disabled must bypass the table and keep the existing
  `paper_readiness_disabled` result.
- A positive realistic aggregate with other failed gates must remain
  `watchlist`.
- Non-positive realistic evidence must remain `mechanical_pass` even when other
  gates fail.

### Test Review

Existing policy tests cover pass, watchlist, disabled, negative/zero realistic
evidence, funding-adjusted metric exclusion, and required backend hard-no
ordering. The new structural regression covers the review finding directly by
requiring the gate list to exist in one ordered table.
