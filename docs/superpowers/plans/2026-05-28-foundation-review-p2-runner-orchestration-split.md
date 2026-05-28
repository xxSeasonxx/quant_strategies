# Runner Orchestration Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: This is a behavior-preserving
> refactor, not a behavior change. Use existing runner behavior tests as the
> invariant suite and request code review before commit.

**Goal:** Split `run_config()` into focused private stage helpers while
preserving every public runner behavior.

**Architecture:** `run_config()` remains the public coordinator. Private helpers
own one stage-shaped responsibility each and return plain values. Failure paths
still delegate to `_failure_result()`.

**Tech Stack:** Python 3.12, pytest via `conda run -n quant`.

---

## File Structure

- Modify `src/quant_strategies/runner/__init__.py`: private helper extraction.
- Modify `progress.md`.

## Implementation Steps

- [x] **Step 1: Extract data-artifact and execution-error helpers**

  Add helpers that write full-profile input-row snapshots and data manifests for
  successful execution and decision-generation failures. Preserve exact artifact
  conditions and evidence payloads.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_runner_api_cli.py::test_decision_generation_failure_writes_run_manifest tests/test_runner_api_cli.py::test_request_build_failure_preserves_prior_stage_artifacts -q
  ```

- [x] **Step 2: Extract success-stage helpers**

  Add helpers for causality/evidence preparation, request support/readiness
  checks, request build, engine evaluation, and completion artifact writing.
  Keep existing stage names and failure stages.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_writes_success_artifacts tests/test_runner_api_cli.py::test_runner_catches_hidden_lookahead_before_request_build tests/test_runner_api_cli.py::test_engine_failure_preserves_engine_request_and_writes_stage_summary tests/test_runner_api_cli.py::test_run_config_emits_structured_stage_events -q
  ```

- [x] **Step 3: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest tests/test_runner_api_cli.py tests/test_runner_execution.py tests/test_runner_artifact_profiles.py tests/test_runner_data_loader.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused checks
  plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

The tempting larger refactor is a runner class or a neutral kernel package. That
would mix this structural cleanup with broader architecture work. This phase
only makes the existing runner easier to reason about.

### Architecture Review

Target flow:

```text
run_config
  -> load config
  -> initialize artifacts
  -> execute strategy or handle execution failure
  -> prepare causality evidence + data manifest
  -> prepare engine request
  -> evaluate engine
  -> write completion artifacts
```

Private helpers should not own policy decisions outside their stage.

### Edge Cases

- Decision-generation failures with loaded rows must still write
  `data_manifest.json` and optional full-profile row snapshots.
- Causality failures must still write the data manifest before returning
  `runner_failed`.
- Request-build failures after causality must still preserve prior stage
  artifacts.
- Engine failures after request build must still preserve `engine_request.json`.

### Test Review

Existing focused tests cover the important failure branches and event stages.
The full runner API suite is the primary safety net for this behavior-preserving
refactor.
