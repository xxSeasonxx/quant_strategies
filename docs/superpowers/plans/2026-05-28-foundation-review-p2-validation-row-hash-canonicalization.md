# Validation Row Hash Canonicalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use TDD for behavior changes and
> request code review before commit. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Collapse validation row snapshot hashing onto the runner canonical row
JSONL implementation and avoid rereading freshly written row snapshots just to
compute their hash.

**Architecture:** `runner.artifact_profiles` owns row canonicalization. Runner
execution hashes rows through that helper, and validation row snapshots write the
same canonical JSONL payload before hashing those bytes in memory.

**Tech Stack:** Python 3.12, pytest via `conda run -n quant`.

---

## File Structure

- Modify `tests/test_validation_runner.py`: focused no-reread regression.
- Modify `src/quant_strategies/runner/artifact_profiles.py`: add
  `canonical_rows_jsonl()`.
- Modify `src/quant_strategies/validation/__init__.py`: use canonical row JSONL
  for row snapshots and hash the written payload.
- Modify `src/quant_strategies/validation/manifest.py`: remove duplicate row
  hash helper.
- Modify `progress.md`.

## Implementation Steps

- [x] **Step 1: Add failing row-snapshot hash regression**

  Monkeypatch validation's local `file_sha256` import to fail if `_write_window_rows`
  tries to hash a `data_rows/*.jsonl` file. Assert the manifest still records a
  row hash equal to the data row file hash.

  Verify failure before implementation:

  ```bash
  conda run -n quant pytest tests/test_validation_runner.py::test_validation_row_snapshot_hash_uses_written_payload -q
  ```

- [x] **Step 2: Share canonical row JSONL**

  Add `canonical_rows_jsonl(rows)` beside `normalized_rows_sha256(rows)` and use
  it from both runner hashing and validation row snapshot writing.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_validation_runner.py::test_validation_row_snapshot_hash_uses_written_payload tests/test_validation_runner.py::test_run_validation_writes_watchlist_artifacts_for_one_positive_window tests/test_validation_runner.py::test_run_validation_normalizes_nonfinite_research_fields_in_row_snapshot tests/test_runner_artifact_profiles.py::test_normalized_rows_sha256_is_stable_for_json_equivalent_rows -q
  ```

- [x] **Step 3: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest tests/test_validation_runner.py tests/test_validation_artifacts.py tests/test_runner_artifact_profiles.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused checks
  plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

The larger performance finding also mentions engine caching and broader hash
propagation. This phase should not invent a cache or change manifest semantics;
it should remove the local row-canonicalization duplication that is visible
today.

### Architecture Review

Target row hash flow:

```text
runner.artifact_profiles.canonical_rows_jsonl(rows)
  -> runner normalized_rows_sha256(rows)
  -> validation data_rows/*.jsonl payload
  -> validation rows_sha256 from the same payload bytes
```

Generic validation artifacts keep using validation's existing JSONL helper.

### Edge Cases

- Nonfinite optional row values must remain normalized to JSON `null`.
- Data provenance failures with no rows still record `rows_sha256 = null`.
- Manifest `core_hashes` still hashes artifact files independently for audit.

### Test Review

The regression should fail only because `_write_window_rows()` rereads
`data_rows/*.jsonl`. Existing manifest tests continue to prove row provenance
hashes match actual file bytes.
