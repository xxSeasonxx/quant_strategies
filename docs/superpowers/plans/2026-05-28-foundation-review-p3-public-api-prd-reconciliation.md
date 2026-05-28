# Public API PRD Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use TDD for behavior changes and
> request code review before commit. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Close the public API re-export mismatch by updating the PRD and adding
a regression for the deliberate `quant_strategies.runner` public surface.

**Architecture:** This is a contract/documentation phase. The existing code
surface is already narrow: `src/quant_strategies/__init__.py` is minimal and
`src/quant_strategies/runner/__init__.py` exports `RunResult` and `run_config`.
The PRD should describe that shape instead of requiring a broader top-level API.

**Tech Stack:** Markdown contract docs, pytest via `conda run -n quant`.

---

## File Structure

- Modify `PRD.md`: reconcile G4 public surface language.
- Modify `tests/test_readme_contract.py`: add PRD/docs/API alignment
  regression.
- Modify `progress.md`.

## Implementation Steps

- [x] **Step 1: Add failing docs-contract regression**

  Add a test that asserts:

  - PRD names `quant_strategies.runner.run_config` and
    `quant_strategies.runner.RunResult`;
  - PRD no longer contains the stale "public consumer surface is re-exported"
    claim;
  - README and consumer docs name the same runner import path;
  - package root does not expose `run_config`.

  Verify the test fails before implementation:

  ```bash
  conda run -n quant pytest tests/test_readme_contract.py::test_prd_matches_runner_public_api_contract -q
  ```

- [x] **Step 2: Reconcile PRD wording**

  Replace the stale G4 bullet with the explicit runner-subpackage public surface
  and retain the misuse/fail-fast requirement.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_readme_contract.py::test_prd_matches_runner_public_api_contract -q
  ```

- [x] **Step 3: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest tests/test_readme_contract.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused checks
  plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

The smaller-looking fix would be adding `quant_strategies.run_config` at the
package root. That would satisfy one stale PRD sentence while creating a second
public API and contradicting the repo-local instruction that `quant_autoresearch`
consume `quant_strategies.runner.run_config`. The cleaner root-cause fix is to
make the PRD match the intended narrow surface.

### Architecture Review

Public consumer flow:

```text
quant_autoresearch
  -> from quant_strategies.runner import run_config
  -> RunResult + structured artifacts
```

Package root stays minimal, and subpackage internals remain private except for
the names exported by `runner.__all__`.

### Edge Cases

- Tests import the package root only; they do not load data or run experiments.
- Internal tests may keep importing lower-level modules because they test those
  modules directly; the consumer contract is narrower.
- Protocol language remains valid for strategy generation and backend extension
  points, but not as a requirement that `RunResult` itself be a Protocol.

### Test Review

The test should catch future regressions in PRD language and public import
promises without asserting unrelated prose or forcing a top-level facade.
