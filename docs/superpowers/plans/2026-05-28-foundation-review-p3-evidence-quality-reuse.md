# Evidence Quality Reuse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use TDD for behavior changes and
> request code review before commit. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Stop recomputing runner evidence quality on successful runs; reuse the
execution payload and update only causality fields after replay.

**Architecture:** `execute_strategy_run()` owns row loading and row-contract
evaluation. `run_config()` owns causality replay. After replay, `run_config()`
should call an evidence helper that adjusts `causality_verified` and
`evidence_quality_warnings` from the already-computed availability status.

**Tech Stack:** Python 3.12, pytest via `conda run -n quant`.

---

## File Structure

- Modify `tests/test_runner_api_cli.py`: single evidence-quality walk
  regression.
- Modify `src/quant_strategies/runner/artifacts.py`: causality update helper.
- Modify `src/quant_strategies/runner/__init__.py`: reuse execution evidence
  payload.
- Modify `progress.md`.

## Implementation Steps

- [x] **Step 1: Add failing single-walk regression**

  Monkeypatch `runner.artifacts.row_contract_status` and assert a successful
  `run_config()` calls it once.

  Verify failure before implementation:

  ```bash
  conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_reuses_execution_evidence_quality_after_causality -q
  ```

- [x] **Step 2: Add causality update helper**

  Add a helper such as `with_causality_verification(payload,
  causality_verified=...)` that returns a copied payload with only
  `causality_verified` and `evidence_quality_warnings` updated according to
  `data_availability_status`.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_reuses_execution_evidence_quality_after_causality tests/test_runner_api_cli.py::test_run_config_marks_complete_available_at_coverage tests/test_runner_api_cli.py::test_run_config_marks_partial_available_at_coverage tests/test_runner_api_cli.py::test_run_config_rejects_invalid_available_at_for_causality_claim -q
  ```

- [x] **Step 3: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest tests/test_runner_api_cli.py tests/test_runner_execution.py tests/test_runner_artifact_profiles.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused checks
  plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

The larger performance work includes engine caching and full end-to-end
benchmarks. This phase handles the clear duplicate O(N) row walk without
touching external data connections or broad runner orchestration.

### Architecture Review

Target evidence flow:

```text
execute_strategy_run -> evidence_quality(rows, causality_verified=false)
run_config causality replay -> with_causality_verification(existing payload)
data_manifest + summary + RunResult -> updated payload
```

This keeps row-contract evaluation at the row-loading boundary and causality
status at the causality boundary.

### Edge Cases

- Decision-generation failures keep using the original execution evidence
  payload because causality replay never ran.
- Complete availability can become causality-verified only when replay passes.
- Partial, missing, and invalid availability never become causality-verified
  even if replay passes under timestamp-only semantics.

### Test Review

Tests should prove both performance shape and behavior: single row-contract
evaluation, complete coverage warning removal, and partial/invalid warning
preservation.
