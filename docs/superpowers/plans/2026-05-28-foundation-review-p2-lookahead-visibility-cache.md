# Lookahead Visibility Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development where practical. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Goal:** Reduce hidden-lookahead replay overhead by parsing row visibility
metadata once and caching visible row slices per decision boundary.

**Architecture:** `check_hidden_lookahead()` should build an internal immutable
visibility index once, then use it to retrieve frozen visible rows for each
decision. Replay output validation and fingerprint comparison remain unchanged.

**Tech Stack:** Python 3.12, pytest via `conda run -n quant`.

---

## File Structure

- Modify `src/quant_strategies/causality.py`: visibility metadata/cache.
- Modify `tests/test_validation_lookahead.py`: scaling/behavior regressions.
- Modify `progress.md`.

## Implementation Steps

- [x] **Step 1: Add failing scaling regression**

  Add tests that:

  - monkeypatch `quant_strategies.causality.parse_aware_datetime` and assert row
    timestamp/availability parsing is bounded by row count, not multiplied by
    baseline decision count.
  - assert shared decision boundaries reuse the same visible row tuple passed to
    the strategy.

  Verify the parse-count test fails before implementation:

  ```bash
  conda run -n quant pytest tests/test_validation_lookahead.py::test_hidden_lookahead_parses_row_visibility_once_per_check -q
  ```

- [x] **Step 2: Implement visibility index/cache**

  Add private helpers to precompute parsed row metadata once and cache frozen
  visible rows by `(as_of_time, decision_time)`. Reuse `frozen_params(params)`
  once per check.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_validation_lookahead.py tests/test_runner_api_cli.py::test_runner_catches_hidden_lookahead_before_request_build -q
  ```

- [ ] **Step 3: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest tests/test_validation_lookahead.py tests/test_runner_api_cli.py tests/test_validation_runner.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused
  checks plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

The review recommendation mentions pre-indexing visible row slices and adding
validation performance budgets. This phase handles the shared root cause inside
the causality checker and uses a deterministic parse-count regression. A larger
validation benchmark can still be added later if real data exposes another
bottleneck.

### Architecture Review

Target flow:

```text
rows -> visibility index with parsed timestamp/available_at once
decision -> cached visible frozen rows
visible rows + frozen params -> replay strategy
```

This keeps runner and validation aligned because both already call
`quant_strategies.causality.check_hidden_lookahead()`.

### Edge Cases

- Invalid optional `available_at` remains timestamp-only visibility, preserving
  current evidence-quality semantics.
- Missing/invalid timestamps remain invisible.
- Decisions with unique boundaries still filter row metadata per decision, but
  without reparsing datetimes.
- Strategy replay exceptions and invalid replay outputs keep current failure
  strings.

### Test Review

Tests should cover existing behavior, parse-count scaling, cache reuse for
shared boundaries, runner hidden-lookahead failure, full suite, diff check, and
compile check.
