# Review Archive Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the empty `docs/reviews/` scaffold by documenting its archive
purpose without moving active review inputs.

**Architecture:** `review-codex.md` and `review-claude.md` stay at repository
root while they drive the active phase workflow. `docs/reviews/` becomes the
place for dated review archives once reviews are published or retired.

**Tech Stack:** Markdown, shell checks, pytest via `conda run -n quant`.

---

## File Structure

- Create `docs/reviews/README.md`: review archive purpose and naming convention.
- Modify `progress.md`: record Phase 20 status and verification.

## Implementation Steps

- [x] **Step 1: Add review archive README**

  Create `docs/reviews/README.md` with:

  - the directory purpose
  - a note that root `review-codex.md` and `review-claude.md` are active inputs
  - dated archive naming convention
  - required archived-review metadata

  Verify:

  ```bash
  test -s docs/reviews/README.md
  ```

- [x] **Step 2: Verification and review**

  Run:

  ```bash
  git diff --check
  conda run -n quant pytest -q
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused checks
  plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

Moving the root review files would create churn and weaken traceability during
the active overnight workflow. A README resolves the empty-directory drift while
preserving the active inputs exactly where the user named them.

### Architecture Review

Documentation flow:

```text
active review inputs -> repo root
retired/published review artifacts -> docs/reviews/YYYY-MM-DD-...
phase plans/specs -> docs/superpowers/
```

### Edge Cases

- Empty directories are not tracked by git, so the committed README is the
  durable fix.
- The README must not imply that root review files are permanent archival
  locations.
- This phase should not rewrite `review-codex.md` or `review-claude.md`.

### Test Review

Checks cover README existence, diff whitespace, full test suite, compile check,
and code review.
