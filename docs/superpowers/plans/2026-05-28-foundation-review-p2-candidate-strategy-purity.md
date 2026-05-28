# Candidate Strategy Purity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject impure generated strategy candidates at load time before their
module code executes.

**Architecture:** Add a small AST purity checker in `quant_strategies.decisions`
and call it from `load_decision_strategy()` before import. Existing
`tests/test_strategy_docstrings.py` should delegate its import/call purity
checks to the same helper so test and runtime contracts do not drift.

**Tech Stack:** Python 3.12 AST, pytest via `conda run -n quant`.

---

## File Structure

- Add `src/quant_strategies/decisions/purity.py`: shared AST purity rules.
- Modify `src/quant_strategies/decisions/strategy_loader.py`: enforce purity
  before import.
- Modify `src/quant_strategies/decisions/__init__.py`: export purity helper if
  needed by tests.
- Modify `tests/test_decision_strategy_loader.py`: loader regressions.
- Modify `tests/test_strategy_docstrings.py`: use shared purity helper.
- Modify `docs/quant-autoresearch-consumer.md` and `progress.md`.

## Implementation Steps

- [x] **Step 1: Add failing loader purity regressions**

  Add tests that:

  - a candidate calling `open(...).write(...)` is rejected before creating the
    file
  - a candidate importing `quant_data` is rejected
  - `enforce_purity=False` preserves an explicit trusted opt-out

  Verify the first two fail before implementation:

  ```bash
  conda run -n quant pytest tests/test_decision_strategy_loader.py::test_load_decision_strategy_rejects_side_effect_calls_before_import tests/test_decision_strategy_loader.py::test_load_decision_strategy_rejects_banned_imports_before_import -q
  ```

- [x] **Step 2: Implement shared AST purity checker**

  Add `strategy_purity_violations(path)` returning a tuple of violation strings.
  Detect:

  - imports rooted at `quant_data`, `quant_strategies.engine`, or
    `quant_strategies.runner`
  - direct calls to `open`, `exec`, `eval`, `compile`
  - attribute calls to common write/delete primitives
  - known module calls such as `subprocess.run`, `requests.get`, and
    `socket.socket`

  Call it from `load_decision_strategy(..., enforce_purity=True)` before import.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_decision_strategy_loader.py tests/test_strategy_docstrings.py -q
  ```

- [x] **Step 3: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest tests/test_runner_execution.py tests/test_validation_runner.py tests/test_decision_strategy_loader.py tests/test_strategy_docstrings.py tests/test_readme_contract.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused checks
  plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

This is not a sandbox. It is a static guardrail at the candidate boundary. That
matches the review recommendation and keeps false positives understandable for
generated candidates.

### Architecture Review

Target flow:

```text
strategy_path -> AST purity check -> import module -> callable contract checks
```

The runner and validation paths already use `load_decision_strategy()`, so one
boundary change covers both.

### Edge Cases

- A syntax error should still become a strategy load error.
- Static false positives are possible for `.write()` on non-file objects; the
  existing committed-strategy contract already treats those calls as banned.
- `enforce_purity=False` is explicit and should not be used by normal runner or
  validation flows.
- The checker does not inspect runtime dynamic imports.

### Test Review

Tests cover direct loader rejection, pre-import side-effect prevention, opt-out,
committed strategy purity reuse, runner/validation import-failure mapping, full
suite, diff check, and compile check.
