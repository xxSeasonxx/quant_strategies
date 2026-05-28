# Engine Gating Names Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use a failing API regression
> before renaming and request code review before commit.

**Goal:** Remove misleading engine `validate` naming and use smoke-gate names
that do not collide with the validation harness.

**Architecture:** The engine still screens requests and can run smoke gates over
the screening result. The smoke-gate function is named `gate_screen()`, and the
models are `GatingConfig` and `GatingReport`. Runner `mode="validate"` remains
the user-facing mode and calls `gate_screen()` internally.

**Tech Stack:** Python 3.12, pytest via `conda run -n quant`.

---

## File Structure

- Modify `tests/test_engine_validate_and_evidence.py`: import/call gating names
  and assert old engine names are not exported.
- Modify `src/quant_strategies/engine/models.py`: rename model classes.
- Modify `src/quant_strategies/engine/evaluation.py`: rename `validate()` to
  `gate_screen()`.
- Modify `src/quant_strategies/engine/evidence.py`: update type references.
- Modify `src/quant_strategies/engine/__init__.py`: export new names only.
- Modify `src/quant_strategies/runner/engine_runner.py`: call `gate_screen()`.
- Modify `progress.md`.

## Implementation Steps

- [x] **Step 1: Add failing public API regression**

  Add/adjust a test proving the engine exports `gate_screen`, `GatingConfig`,
  and `GatingReport`, and does not export `validate`, `ValidationConfig`, or
  `ValidationReport`.

  Verify failure before implementation:

  ```bash
  conda run -n quant pytest tests/test_engine_validate_and_evidence.py::test_engine_public_api_uses_gating_names -q
  ```

- [x] **Step 2: Rename engine smoke-gate API**

  Rename the engine function/classes and update runner/test imports. Keep gate
  math, report payload fields, and runner mode semantics unchanged.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_engine_validate_and_evidence.py tests/test_runner_engine_runner.py tests/test_runner_api_cli.py::test_run_config_writes_success_artifacts -q
  ```

- [x] **Step 3: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest tests/test_engine_validate_and_evidence.py tests/test_engine_screen.py tests/test_runner_engine_runner.py tests/test_runner_api_cli.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused checks
  plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

The larger engine ontology work includes config consolidation and backend
agreement tests. This phase handles only the stale engine validation names,
which are a narrow source of semantic confusion.

### Architecture Review

Target naming:

```text
engine.screen(request) -> ScreeningResult
engine.gate_screen(request, GatingConfig?) -> GatingReport
runner mode="validate" -> engine.gate_screen(...)
validation harness -> quant_strategies.validation.*
```

The function name should describe smoke gating, not full validation.

### Edge Cases

- Evidence artifacts can still have `mode="validate"` because runner mode names
  are separate from engine API names.
- `GatingReport.screening_result` remains optional on invalid inputs.
- No legacy aliases means source/tests/docs must stop importing old names.

### Test Review

The public API regression prevents old names from quietly staying as
compatibility shims. Existing engine and runner tests prove behavior remains
unchanged.
