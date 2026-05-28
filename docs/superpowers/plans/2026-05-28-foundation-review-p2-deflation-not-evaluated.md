# Deflation Not Evaluated Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make validation mechanical-review outputs explicitly disclose that search-pressure deflation was not evaluated.

**Architecture:** Keep the existing advisory policy flow. Compute `overfit_controls` exactly once, then in the `finish()` helper add `deflation_not_evaluated` to `mechanical_review_candidate` reasons when the copied search-pressure fields are non-empty.

**Tech Stack:** Python 3.12, Pydantic v2 policy model, existing validation policy/artifact tests, pytest via `conda run -n quant`.

---

## File Structure

- Modify `src/quant_strategies/validation/policy.py`: add search-pressure presence helper and reason injection.
- Modify `tests/test_validation_backends_and_policy.py`: assert policy reasons with and without search pressure.
- Modify `tests/test_validation_runner.py`: assert `validation_decision.json`, robustness matrix, and report preserve the reason.
- Modify `README.md` and `docs/quant-autoresearch-consumer.md`: document the reason and its advisory interpretation.
- Modify `progress.md`: record Phase 15 status and verification.

## Implementation Steps

- [x] **Step 1: Add policy and artifact regressions**

  In `tests/test_validation_backends_and_policy.py`:

  - keep `test_policy_mechanical_review_candidate_when_all_paper_gates_pass`
    expecting `reasons == ()`;
  - update `test_policy_records_search_pressure_inputs_for_mechanical_review_candidate`
    to assert `decision.reasons == ("deflation_not_evaluated",)`.

  In `tests/test_validation_runner.py`, update
  `test_run_validation_writes_mechanical_review_candidate_artifacts_for_two_robust_windows`
  to assert:

  ```python
  assert result.decision.reasons == ("deflation_not_evaluated",)
  assert decision_payload["reasons"] == ["deflation_not_evaluated"]
  assert robustness_matrix["decision"]["reasons"] == ["deflation_not_evaluated"]
  assert "Reasons: deflation_not_evaluated" in report
  ```

  Verify:

  ```bash
  conda run -n quant pytest tests/test_validation_backends_and_policy.py::test_policy_records_search_pressure_inputs_for_mechanical_review_candidate tests/test_validation_runner.py::test_run_validation_writes_mechanical_review_candidate_artifacts_for_two_robust_windows -q
  ```

  Expected before implementation: fails because reasons are empty.

- [x] **Step 2: Add policy reason injection**

  In `src/quant_strategies/validation/policy.py`, update `finish()`:

  ```python
  def finish(decision: ValidationPolicyDecision) -> ValidationPolicyDecision:
      reasons = decision.reasons
      if decision.decision == "mechanical_review_candidate" and _has_search_pressure(overfit_controls):
          reasons = tuple(dict.fromkeys((*reasons, "deflation_not_evaluated")))
      return decision.model_copy(
          update={
              "reasons": reasons,
              "overfit_controls": overfit_controls,
          }
      )
  ```

  Add:

  ```python
  def _has_search_pressure(overfit_controls: dict[str, Any | None]) -> bool:
      return any(
          (
              overfit_controls.get("candidate_count") is not None,
              overfit_controls.get("trial_count") is not None,
              bool(overfit_controls.get("parameter_search_space")),
              overfit_controls.get("selection_rule") is not None,
              bool(overfit_controls.get("split_ids")),
          )
      )
  ```

  Verify:

  ```bash
  conda run -n quant pytest tests/test_validation_backends_and_policy.py::test_policy_mechanical_review_candidate_when_all_paper_gates_pass tests/test_validation_backends_and_policy.py::test_policy_records_search_pressure_inputs_for_mechanical_review_candidate tests/test_validation_runner.py::test_run_validation_writes_mechanical_review_candidate_artifacts_for_two_robust_windows -q
  ```

- [x] **Step 3: Update docs and progress**

  Update docs to say retained candidates with `[search_pressure]` and mechanical
  review status carry `deflation_not_evaluated`; this is disclosure, not a
  statistical correction or block.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_readme_contract.py -q
  ```

- [x] **Step 4: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest tests/test_validation_backends_and_policy.py tests/test_validation_runner.py tests/test_readme_contract.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused checks
  plus the full suite.

## GSTACK REVIEW REPORT

### Scope Challenge

The review asked for real deflation or, at minimum, explicit disclosure. Real
deflation needs statistical design choices and is outside this small phase. The
root problem this phase can safely fix is the missing machine-readable
limitation on an otherwise strong advisory label.

### Architecture Review

Target flow:

```text
[search_pressure]
      |
      v
overfit_controls copied into ValidationPolicyDecision
      |
      v
mechanical_review_candidate + non-empty search pressure
      |
      v
reasons += deflation_not_evaluated
```

### Edge Cases

- Default `SearchPressureConfig` with all-empty fields does not add the reason.
- Hard-no setup failures keep their existing reasons but still carry
  `overfit_controls`.
- Watchlist and mechanical-pass outcomes keep their existing reasons.
- Eligibility flags remain advisory-only.

### Test Review

Tests cover policy-level behavior with and without search pressure, validation
artifact serialization, report text, focused validation tests, full suite, diff
check, and compile check.
