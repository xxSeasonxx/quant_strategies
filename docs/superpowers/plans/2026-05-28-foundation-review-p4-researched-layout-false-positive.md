# Researched Layout Finding Rejection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development for implementation when practical. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject the `researched/` enforcement finding as a documented false positive and protect the intended layout-agnostic validation contract.

**Architecture:** No runtime behavior changes. The authoritative contract remains documentation plus tests: validation consumes explicit candidate workspaces, while promotion between repository lifecycle directories is a separate human process.

**Tech Stack:** Python 3.12, pytest via `conda run -n quant`.

---

## File Structure

- Modify `PRD.md`: reconcile C-6 promotion direction wording with AGENTS/README.
- Modify `tests/test_readme_contract.py`: add a docs-contract test for validation layout agnosticism and human promotion.
- Modify `progress.md`: record the false-positive triage decision and phase verification.

## Implementation Steps

- [x] **Step 1: Add docs-contract regression**

  Add a test that reads README, consumer docs, PRD, and AGENTS.md and asserts:

  - README says the validator does not special-case `researched/`.
  - Consumer docs say validation is not based on `researched/`, manifests, or
    family/variant layouts.
  - PRD C-4 allows candidate workspaces.
  - PRD C-6 says promotion into `tested/` from `untested/` or `researched/` is
    separate and the foundation never auto-promotes.
  - AGENTS.md says `researched/` is not market validated and `tested/`
    promotion needs Season-approved validation.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_readme_contract.py::test_docs_keep_validation_layout_agnostic_and_promotion_human_controlled -q
  ```

- [x] **Step 2: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest tests/test_readme_contract.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused
  checks plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

Path-based enforcement would conflate repository lifecycle folders with
candidate validation inputs. The PRD permits candidate workspaces, and the README
states validation does not special-case layouts. Adding runner enforcement would
make the repo less flexible and contradict current docs.

### Architecture Review

Correct boundary:

```text
runner/validation path rules -> resolve inside configured repo/candidate root
strategy lifecycle promotion -> human process outside runner/validation
researched/ packages -> frozen upstream artifacts, not market validation
```

The test should lock the contract rather than introduce code that rejects
candidate paths by directory name.

### Edge Cases

- A `researched/` package can still be copied into a normal candidate workspace
  with explicit `validation.toml`.
- Advisory validation artifacts can inform review but do not authorize
  promotion, paper trading, or live trading.
- Existing `tested/` and `untested/` flat layout checks for committed strategy
  files remain unchanged.

### Test Review

This is a false-positive phase, so the regression is documentary rather than a
red behavioral test. It prevents future docs drift that would re-open the same
finding.
