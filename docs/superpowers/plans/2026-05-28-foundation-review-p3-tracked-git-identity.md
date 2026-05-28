# Tracked Git Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use TDD for behavior changes and
> request code review before commit. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Make repository identity hashes deterministic by ignoring untracked
local detritus while preserving tracked dirty-state detection.

**Architecture:** `git_identity()` is the shared provenance boundary used by
runner and validation manifests. It should compute dirty state from tracked
status plus tracked diff, while artifact snapshots handle the exact config and
strategy files used by a run.

**Tech Stack:** Python 3.12, git CLI, pytest via `conda run -n quant`.

---

## File Structure

- Modify `tests/test_runner_api_cli.py`: repository identity regressions.
- Modify `src/quant_strategies/provenance.py`: tracked-only status.
- Modify `progress.md`.

## Implementation Steps

- [x] **Step 1: Add failing repository identity regression**

  Add a test proving that an untracked scratch file alone does not dirty
  repository identity. Adjust the existing dirty-worktree test so it expects the
  tracked-only status hash, not a hash of untracked files.

  Verify the untracked-only test fails before implementation:

  ```bash
  conda run -n quant pytest tests/test_runner_api_cli.py::test_run_manifest_ignores_untracked_detritus_for_repository_identity -q
  ```

- [x] **Step 2: Implement tracked-only git status**

  Change `git_identity()` to call:

  ```text
  git status --porcelain --untracked-files=no
  ```

  Keep scoped path exclusions and `git diff --binary HEAD` unchanged.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_runner_api_cli.py::test_run_manifest_marks_dirty_git_worktree tests/test_runner_api_cli.py::test_run_manifest_ignores_untracked_detritus_for_repository_identity -q
  ```

- [x] **Step 3: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest tests/test_runner_api_cli.py tests/test_validation_runner.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused checks
  plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

Hashing every untracked file looks more conservative, but it makes reproducible
artifact identity depend on editor scratch files and other local debris. The
actual run inputs are already copied and hashed separately. Repository identity
should describe the tracked source baseline and tracked modifications.

### Architecture Review

Repository identity flow:

```text
tracked git status + tracked diff
  -> repository dirty/hash fields
config snapshot + strategy snapshot + row/decision artifacts
  -> exact run input evidence
```

This keeps validation and runner aligned because both consume the shared
`git_identity()` helper.

### Edge Cases

- Repos without git still return `None` identity fields through existing error
  handling.
- Staged additions are tracked-index changes and still appear in tracked status.
- Untracked configured strategies are still snapshotted and hashed by artifacts;
  they just do not perturb repository identity.
- Ignored result directories remain excluded by scoped path args.

### Test Review

Tests should cover both sides: tracked README edits still dirty the repo, while
untracked scratch files alone do not.
