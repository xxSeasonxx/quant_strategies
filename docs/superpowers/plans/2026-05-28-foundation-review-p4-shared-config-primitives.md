# Shared Config Primitives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Add the ownership regression
> before moving classes and request code review before commit.

**Goal:** Move shared data/fill/cost config primitives out of runner ownership
so validation no longer depends on `runner.config` for neutral experiment
settings.

**Architecture:** `quant_strategies.core.config` owns shared immutable Pydantic
models. `runner.config` composes those primitives into `RunConfig` and
re-exports them for existing imports. `validation.config` imports shared
primitives from the neutral module and imports only `RunConfig`/`OutputConfig`
from `runner.config` for explicit runner conversion.

**Tech Stack:** Python 3.12, Pydantic, pytest via `conda run -n quant`.

---

## File Structure

- Add `src/quant_strategies/core/__init__.py`.
- Add `src/quant_strategies/core/config.py`.
- Modify `src/quant_strategies/runner/config.py`.
- Modify `src/quant_strategies/validation/config.py`.
- Modify `tests/test_validation_config.py`.
- Modify `progress.md`.

## Implementation Steps

- [x] **Step 1: Add failing ownership regression**

  Add a focused test proving shared primitives are owned by
  `quant_strategies.core.config`, remain importable from `runner.config`, and
  are used by validation config fields.

  Verify failure before implementation:

  ```bash
  conda run -n quant pytest tests/test_validation_config.py::test_shared_config_primitives_are_neutral_not_runner_owned -q
  ```

- [x] **Step 2: Move shared models**

  Create `quant_strategies.core.config`, move shared primitive definitions into
  it, import/re-export them from `runner.config`, and update
  `validation.config` to import shared primitives from the neutral module.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_validation_config.py tests/test_runner_config.py tests/test_runner_engine_runner.py -q
  ```

- [x] **Step 3: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused
  checks plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

Moving all runner config would create a broader path-resolution migration and
blur the runner/validation boundary in the opposite direction. The root issue is
only shared primitive ownership, so this phase moves the reusable models and
leaves runner orchestration models in place.

### Architecture Review

Target dependency direction:

```text
core.config
  <- runner.config
  <- validation.config only for RunConfig conversion

validation.config -> core.config for shared primitives
validation.config -> runner.config for explicit to_run_config()
```

This keeps validation from treating runner as the owner of data/fill/cost
configuration, while preserving the existing stable runner import surface.

### Edge Cases

- Existing tests and consumers importing `FillModelConfig` or `CostModelConfig`
  from `runner.config` should keep working.
- Pydantic validation errors and field defaults must remain unchanged.
- `DataConfig.validate_window()` must keep the same dataset requirement for
  `kind = "bars"`.

### Test Review

The new test is intentionally architectural: it fails until the neutral module
owns the classes. Existing config and engine-runner tests cover behavior and
field-level validation.
