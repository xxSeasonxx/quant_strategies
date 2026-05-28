# JSONL-Only Input Rows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the duplicate CSV strategy-input row artifact while preserving
the richer JSONL artifact and manifest hash.

**Architecture:** Runner full-profile row replay continues to flow through
`write_strategy_input_rows()`, but that helper writes only
`strategy_input_rows.jsonl` and returns its SHA-256. CSV-specific helper code is
removed if unused.

**Tech Stack:** Python 3.12, pytest via `conda run -n quant`.

---

## File Structure

- Modify `tests/test_runner_api_cli.py`: expect JSONL-only input rows for full
  profile.
- Modify `src/quant_strategies/runner/artifacts.py`: remove CSV row artifact.
- Modify `README.md`: document singular JSONL input-row artifact.
- Modify `progress.md`: record Phase 21 status and verification.

## Implementation Steps

- [x] **Step 1: Update artifact expectations first**

  Update focused runner tests so full-profile artifact sets and failure-stage
  assertions expect `strategy_input_rows.jsonl` but not
  `strategy_input_rows.csv`.

  Verify the focused tests fail before source changes:

  ```bash
  conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_writes_success_artifacts tests/test_runner_api_cli.py::test_raw_inputs_preserve_quote_and_funding_fields_in_engine_request tests/test_runner_api_cli.py::test_request_build_failure_preserves_prior_stage_artifacts -q
  ```

- [x] **Step 2: Remove CSV row artifact writing**

  In `src/quant_strategies/runner/artifacts.py`:

  - remove `write_csv()` use from `write_strategy_input_rows()`
  - delete unused CSV-specific helpers/imports if no callers remain
  - keep JSONL write and returned SHA-256 unchanged

  Verify:

  ```bash
  rg -n "write_csv|csv\\.DictWriter|import csv" src tests
  rg -n "strategy_input_rows\\.csv" src README.md docs/quant-autoresearch-consumer.md
  conda run -n quant pytest tests/test_runner_api_cli.py tests/test_runner_artifact_profiles.py tests/test_readme_contract.py -q
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

The review recommends both flipping the default artifact profile and removing
duplicate row artifacts. Those are related but separable. Phase 21 removes the
duplicate full-profile artifact without changing the default profile semantics;
the default-profile finding remains open for a later phase.

### Architecture Review

Target full-profile row artifact flow:

```text
loaded rows -> strategy_input_rows.jsonl -> data_manifest.strategy_input_rows_jsonl_sha256
```

CSV adds conversion risk and I/O cost without adding replay fidelity.

### Edge Cases

- Failure paths that load data before failing still write the JSONL row artifact
  under full profile.
- Summary profile still writes no row artifacts.
- Manifest artifact hashing will naturally stop listing the CSV file.
- Tests should not keep stale negative checks for `signals.csv` as evidence of
  this change; the direct invariant is absence of `strategy_input_rows.csv`.

### Test Review

Tests cover full-profile success artifacts, full-profile failure artifacts,
quote/funding field preservation through JSONL and engine request, summary
profile compact artifacts, full suite, diff check, and compile check.
