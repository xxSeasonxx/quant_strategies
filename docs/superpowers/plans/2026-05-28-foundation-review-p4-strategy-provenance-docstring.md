# Strategy Provenance Docstring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make strategy provenance docstrings auditable by requiring a concrete
source anchor in the `Source / provenance:` section.

**Architecture:** Keep the existing AST docstring scan. Add a small section
extractor and a regex that accepts DOI, SSRN, URL, or `internal_note:` anchors.
This remains a lightweight repository contract test, not an external citation
validator.

**Tech Stack:** Python 3.12, pytest via `conda run -n quant`.

---

## File Structure

- Modify `tests/test_strategy_docstrings.py`: add provenance anchor test helper.
- Modify `examples/strategies/simple_momentum.py`: add `internal_note:` anchor.
- Modify `progress.md`: record Phase 19 status and verification.

## Implementation Steps

- [x] **Step 1: Add failing provenance anchor regression**

  Add `test_strategy_docstrings_include_auditable_provenance_anchor()` that
  checks each committed strategy module's `Source / provenance:` section for one
  of:

  ```text
  DOI
  SSRN
  http://
  https://
  internal_note:
  ```

  Verify it fails before fixing the smoke fixture:

  ```bash
  conda run -n quant pytest tests/test_strategy_docstrings.py::test_strategy_docstrings_include_auditable_provenance_anchor -q
  ```

- [x] **Step 2: Add the missing internal-note anchor**

  Update `examples/strategies/simple_momentum.py` so its provenance block starts
  with an `internal_note:` path and retains the explanation that it is a
  deterministic smoke fixture rather than an external source.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_strategy_docstrings.py -q
  ```

- [x] **Step 3: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused checks
  plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

This phase should not become a citation-research project. The review finding is
that vague provenance can pass, so the minimal useful contract is an auditable
anchor token in the provenance section.

### Architecture Review

The test remains static and local:

```text
strategy file -> AST module docstring -> Source / provenance section -> anchor regex
```

No runtime loader behavior changes.

### Edge Cases

- `DOI` may be followed by a wrapped DOI value on the next line; accepting the
  token is intentional.
- `SSRN` is accepted because repository instructions name SSRN as an acceptable
  paper identifier.
- `internal_note:` is accepted for internal fixtures or notes that are auditable
  inside the repository.
- URLs are not fetched.

### Test Review

Tests cover current committed strategies, researched variant strategy files,
example strategies, existing docstring headings, layout, import purity,
side-effect bans, full suite, diff check, and compile check.
