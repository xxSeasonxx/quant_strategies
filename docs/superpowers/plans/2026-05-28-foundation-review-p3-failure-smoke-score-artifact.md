# Failure Smoke Score Artifact Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use TDD for behavior changes and
> request code review before commit. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Make runner failure summaries omit uncomputed `engine.smoke_score`
instead of emitting a null-valued score object.

**Architecture:** `_failure_result()` already passes a compact engine payload
with only `passed` and `trade_count`. `_summary_payload()` should preserve that
payload instead of adding a synthetic `smoke_score`. Completed engine runs flow
through `_compact_engine_summary()`, which carries real smoke-score values from
engine output.

**Tech Stack:** Python 3.12, pytest via `conda run -n quant`.

---

## File Structure

- Modify `tests/test_runner_api_cli.py`: failure summary and zero-trade
  regressions.
- Modify `src/quant_strategies/runner/__init__.py`: summary payload shape.
- Modify `progress.md`.

## Implementation Steps

- [x] **Step 1: Add failing artifact regression**

  Add assertions that:

  - data-load failure summaries omit `summary["engine"]["smoke_score"]`;
  - decision-generation failure summaries omit it too;
  - completed zero-decision summaries still include numeric smoke-score zeros.

  Verify the failure-summary test fails before implementation:

  ```bash
  conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_writes_data_failure_summary -q
  ```

- [x] **Step 2: Preserve engine payload shape in summaries**

  Remove `_summary_payload()`'s default null `smoke_score` insertion. Leave real
  completed-engine summaries untouched.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_writes_data_failure_summary tests/test_runner_api_cli.py::test_decision_generation_failure_writes_run_manifest tests/test_runner_api_cli.py::test_run_config_treats_empty_decisions_as_zero_trade_smoke_result -q
  ```

- [x] **Step 3: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest tests/test_runner_api_cli.py tests/test_runner_artifact_profiles.py tests/test_readme_contract.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused checks
  plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

The tempting larger refactor is to split the whole runner orchestrator. This
phase handles a concrete artifact contract bug first: consumers should not have
to treat a null-valued smoke-score object as "not computed."

### Architecture Review

Target summary payload:

```text
pre-engine failure -> engine: {passed: null, trade_count: null}
completed engine -> engine: {passed, trade_count, smoke_score}
```

The artifact shape now reflects whether the engine stage actually emitted a
score.

### Edge Cases

- Empty-decision completed runs compute real zero-valued smoke scores and keep
  `smoke_score`.
- Failure summaries still include top-level `metric_semantics` so consumers know
  the metric vocabulary for comparable successful runs.
- Existing `RunResult` fields remain unchanged.

### Test Review

Tests should assert absence for pre-engine failure and presence for completed
zero-trade runs to avoid replacing one ambiguity with another.
