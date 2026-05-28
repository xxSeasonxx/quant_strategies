# Retire Runner Strategy Loader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the redundant `quant_strategies.runner.strategy_loader` module while preserving canonical strategy loading and runner diagnostics.

**Architecture:** Strategy loading remains owned by `quant_strategies.decisions`. Runner execution imports that canonical loader directly and performs the runner-specific exception translation locally before raising `StrategyExecutionError`.

**Tech Stack:** Python 3.12, existing decisions/runner tests, pytest via `conda run -n quant`.

---

## File Structure

- Create `tests/test_decision_strategy_loader.py`: canonical tests for `load_decision_strategy`.
- Delete `tests/test_runner_strategy_loader.py`: old tests for the retired wrapper.
- Modify `src/quant_strategies/runner/execution.py`: import decisions loader and add private `_load_strategy()`.
- Delete `src/quant_strategies/runner/strategy_loader.py`.
- Modify `tests/test_runner_config.py`: import `load_decision_strategy`.
- Modify `tests/test_runner_execution.py`: monkeypatch `execution._load_strategy`.
- Modify `tests/test_validation_runner.py`: monkeypatch `execution._load_strategy`.
- Modify `progress.md`: record Phase 16 status and verification.

## Implementation Steps

- [x] **Step 1: Move loader tests to the canonical decisions API**

  Create `tests/test_decision_strategy_loader.py` with the existing valid and
  invalid strategy-loader tests, but import:

  ```python
  from quant_strategies.decisions import (
      DecisionStrategyLoadError,
      StrategyDecision,
      load_decision_strategy,
  )
  ```

  Expected invalid-file assertion:

  ```python
  with pytest.raises(DecisionStrategyLoadError, match="generate_decisions"):
      load_decision_strategy(strategy, repo_root=tmp_path)
  ```

  Verify:

  ```bash
  conda run -n quant pytest tests/test_decision_strategy_loader.py -q
  ```

- [x] **Step 2: Inline runner exception translation**

  In `src/quant_strategies/runner/execution.py`:

  - replace `from quant_strategies.runner.strategy_loader import load_strategy`
    with:

    ```python
    from quant_strategies.decisions import (
        DecisionStrategyLoadError,
        load_decision_strategy,
        validate_decision_output,
        validate_strategy_params,
    )
    ```

  - change `execute_strategy_run()` to call `_load_strategy(...)`.
  - add:

    ```python
    def _load_strategy(path: str | Path, *, repo_root: Path | None = None) -> GenerateDecisions:
        try:
            return load_decision_strategy(path, repo_root=repo_root)
        except DecisionStrategyLoadError as exc:
            raise StrategyLoadError(str(exc)) from exc
    ```

  Verify:

  ```bash
  conda run -n quant pytest tests/test_runner_execution.py::test_execute_strategy_run_maps_strategy_import_failure tests/test_validation_runner.py::test_run_validation_records_strategy_import_failure_details -q
  ```

- [x] **Step 3: Retire wrapper imports and files**

  - Delete `src/quant_strategies/runner/strategy_loader.py`.
  - Delete `tests/test_runner_strategy_loader.py`.
  - Update `tests/test_runner_config.py` to use `load_decision_strategy`.
  - Update monkeypatch paths in runner/validation tests from
    `execution.load_strategy` to `execution._load_strategy`.

  Verify:

  ```bash
  rg "quant_strategies\\.runner\\.strategy_loader|from quant_strategies.runner.strategy_loader|execution\\.load_strategy" src tests
  test ! -e src/quant_strategies/runner/strategy_loader.py
  conda run -n quant pytest tests/test_decision_strategy_loader.py tests/test_runner_config.py tests/test_runner_execution.py tests/test_validation_runner.py -q
  ```

- [x] **Step 4: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest tests/test_decision_strategy_loader.py tests/test_runner_config.py tests/test_runner_execution.py tests/test_validation_runner.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused checks
  plus the full suite.

## GSTACK REVIEW REPORT

### Scope Challenge

Deleting `StrategyLoadError` would be a larger behavior change because
validation failure artifacts currently expose it. The review finding is about
the runner wrapper module, so Phase 16 keeps the diagnostic type and removes the
redundant module only.

### Architecture Review

Target flow:

```text
decisions.load_decision_strategy()
        |
        v
runner.execution._load_strategy()
        |
        v
DecisionStrategyLoadError -> StrategyLoadError -> StrategyExecutionError
```

The canonical loader stays in `decisions`; runner-specific error translation is
at the runner boundary.

### Edge Cases

- Existing monkeypatch tests use the private runner execution seam.
- Validation artifacts continue to report `StrategyLoadError` for strategy
  import failures.
- Direct imports of the old runner wrapper are intentionally unsupported.

### Test Review

Tests cover canonical loader behavior, runner import-failure mapping, validation
failure details, absence of old wrapper imports, focused runner/validation
tests, full suite, diff check, and compile check.
