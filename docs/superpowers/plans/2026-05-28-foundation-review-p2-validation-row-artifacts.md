# Validation Row Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use TDD for behavior changes and
> request code review before commit. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Snapshot validation input rows per loaded window and link those
snapshots from the manifest without claiming full backend metric replayability.

**Architecture:** Validation window execution writes a canonical JSON-safe JSONL
row artifact immediately after data is loaded. Data provenance records the
relative path and hash. Manifest core hashes include `data_rows/` artifacts, and
artifact discovery already recursively hashes files under the validation result
directory.

**Tech Stack:** Python 3.12, pytest via `conda run -n quant`.

---

## File Structure

- Modify `tests/test_validation_runner.py`: row snapshot expectations.
- Modify `src/quant_strategies/validation/__init__.py`: write row snapshots and
  provenance links.
- Modify `README.md`: validation artifact contract.
- Modify `progress.md`.

## Implementation Steps

- [x] **Step 1: Add failing artifact regressions**

  Extend validation runner tests to assert:

  - loaded windows write `data_rows/<safe_window_id>.jsonl`;
  - the row JSONL bytes are canonical and match `rows_sha256`;
  - manifest `data.windows[*].rows_path` points to the row artifact;
  - manifest `core_hashes` and `artifacts` include the row artifact hash;
  - non-finite research fields are normalized to JSON-safe values;
  - data-load failures keep `rows_path` null.

  Verify the focused test fails before implementation:

  ```bash
  conda run -n quant pytest tests/test_validation_runner.py::test_run_validation_writes_watchlist_artifacts_for_one_positive_window tests/test_validation_runner.py::test_run_validation_records_data_audit_failure -q
  ```

- [x] **Step 2: Write loaded-window row snapshots**

  Add a private helper that writes
  `data_rows/<safe_window_id>.jsonl` with `canonical_jsonl_lines()`, returns
  the relative path and SHA-256, and is called after successful data load and
  after decision-generation failures that still expose loaded rows.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_validation_runner.py::test_run_validation_writes_watchlist_artifacts_for_one_positive_window tests/test_validation_runner.py::test_run_validation_records_data_audit_failure tests/test_validation_runner.py::test_run_validation_rejects_non_decision_output -q
  ```

- [x] **Step 3: Docs, full verification, and review**

  Update README and progress. Run:

  ```bash
  conda run -n quant pytest tests/test_validation_runner.py tests/test_validation_artifacts.py -q
  conda run -n quant pytest tests/test_validation_lookahead.py tests/test_runner_api_cli.py tests/test_validation_runner.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused checks
  plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

The review recommendation includes rows, decisions, fills, exits, funding/cost
contributions, and config. Decisions and config are already artifacted; rows are
the missing base input. Backend execution ledgers need backend-level contracts
and should not be guessed from aggregate metrics in this patch.

### Architecture Review

Target validation artifact flow:

```text
execute_strategy_run -> loaded_rows
loaded_rows -> data_rows/<window>.jsonl
loaded_rows + rows_path + rows_sha256 -> data provenance
data provenance -> validation_manifest.json
row artifact hashing -> manifest core_hashes and artifacts
```

Keeping row artifact writing in validation, not in runner, preserves the runner
artifact-profile contract and keeps validation reconstructability independent of
runner summary/full output profiles.

### Edge Cases

- Data-load failure has no trusted row set, so `rows_path` and `rows_sha256`
  stay null.
- Decision-generation failures after data load still write the row snapshot
  because those rows shaped the failed validation attempt.
- Unsafe window IDs are sanitized with the same conservative artifact path
  policy used for scenario decision records.
- Duplicate window IDs would overwrite row artifacts, matching the existing
  collision risk for scenario artifacts; changing config validation is out of
  scope.

### Test Review

Tests should assert artifact bytes and hashes rather than only parsed payloads,
so regressions in canonical JSONL encoding or manifest wiring are caught.
