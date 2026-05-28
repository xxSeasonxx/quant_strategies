# Runner Observation Dependency Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development for implementation when practical. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce declared `ObservationRef` dependency causality in the runner while keeping validation behavior unchanged.

**Architecture:** Move the existing observation audit helper from `validation.dependencies` to a neutral `quant_strategies.observation_dependencies` module. Validation data audit and runner both consume the neutral helper. Runner runs a new `observation_audit` stage after strategy execution and before causality replay or engine request construction.

**Tech Stack:** Python 3.12, pytest via `conda run -n quant`.

---

## File Structure

- Create `src/quant_strategies/observation_dependencies.py`: neutral audit helper.
- Modify `src/quant_strategies/validation/dependencies.py`: compatibility import from the neutral helper.
- Modify `src/quant_strategies/validation/data_audit.py`: import the neutral helper.
- Modify `src/quant_strategies/runner/__init__.py`: add runner observation audit stage.
- Modify `tests/test_runner_api_cli.py`: add runner failure regression and update stage event expectation.
- Modify `progress.md`.

## Implementation Steps

- [x] **Step 1: Add failing runner regression**

  Add a test strategy that declares an `ObservationRef` timestamp after
  `as_of_time`. Assert `run_config()` returns failure with summary
  `stage == "observation_audit"`, `assessment_status == "runner_failed"`, and
  no engine request artifact.

  Verify failure before implementation:

  ```bash
  conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_rejects_future_declared_observation_before_request_build -q
  ```

- [x] **Step 2: Share and call observation audit**

  Move the audit function to `quant_strategies.observation_dependencies`, update
  validation imports, and call it from runner in a new `observation_audit` stage
  before causality replay. Raise `DataReadinessError` with the joined violation
  messages when the audit returns violations.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_rejects_future_declared_observation_before_request_build tests/test_validation_dependencies.py -q
  ```

- [x] **Step 3: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest tests/test_runner_api_cli.py tests/test_validation_dependencies.py tests/test_validation_runner.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused
  checks plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

The review suggested requiring non-empty observations in the decision schema.
That would break runner smoke-screen workflows and duplicate validation
readiness policy. The narrower root-cause fix is to audit declared observations
where they exist and leave minimum-observation requirements to validation
configs.

### Architecture Review

Target dependency direction:

```text
observation_dependencies
  <- validation.data_audit
  <- runner
```

Runner should not import `validation`. The neutral helper keeps the kernel
contract shared without reversing module ownership.

### Edge Cases

- Empty observations remain valid for runner screens.
- Validation readiness still blocks missing observations when a validation
  config requires them.
- Declared future observation timestamps fail before hidden-lookahead replay,
  even when replay would otherwise pass.
- Missing observation fields and late `available_at` keep the existing
  validation violation strings.

### Test Review

The focused runner regression covers the gap directly. Existing validation
dependency tests prove the helper move preserves all violation messages. Runner
event tests should include the new successful `observation_audit` stage.
