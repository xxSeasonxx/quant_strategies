# Phase 27 Design: Validation Row Artifacts

Date: 2026-05-28
Mode: Builder
Source review: `review-codex.md`

## Problem

`review-codex.md` Finding 14 correctly says validation artifacts cannot fully
reproduce backend metrics. Validation currently writes aggregate backend metrics
and decision-record hashes, while data provenance only records row counts and a
row hash. A reviewer can verify that some row set existed, but cannot inspect
the actual input rows from the validation artifact bundle.

## Assignment

Add per-window validation input-row snapshots and link them from
`validation_manifest.json`. This is the first reconstructability step: it makes
the JSON-safe row representation used by strategy generation and backend
scenarios inspectable without changing backend execution math or policy
classification.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed
for Phase 27:

- Treat Finding 14 as partly true after this phase, not fully closed.
- Write one canonical JSONL row artifact for each window that successfully
  loads rows, including windows that later fail decision generation.
- Do not write row artifacts for data-load failures.
- Keep backend fill/trade/funding/cost ledgers out of scope until the backend
  contract exposes those details explicitly.
- Reuse the existing validation canonical JSONL encoder and JSON-safe
  normalization rules rather than introducing a separate row serializer.

## Scope

- Add row snapshot artifact writing in validation window handling.
- Add `rows_path` to validation data provenance entries and manifest data
  windows.
- Ensure row artifact bytes hash to the provenance `rows_sha256` value and are
  listed in manifest `core_hashes` and `artifacts`.
- Normalize non-finite numeric and other non-JSON ancillary row values to
  JSON-safe values instead of failing artifact writing.
- Update README artifact docs and `progress.md`.
- Add focused tests for success and data-load failure paths.

## Not In Scope

- Per-scenario fill, trade, order, funding, or cost contribution ledgers.
- Backend API changes.
- Recomputing backend metrics from artifacts in tests.
- Migrating old validation artifacts.

## Success Criteria

- Loaded validation windows write `data_rows/<safe_window_id>.jsonl`.
- Manifest data provenance includes `rows_path`, `row_count`, and
  `rows_sha256` for loaded windows.
- Row snapshots tolerate non-finite research fields through JSON-safe
  normalization.
- Data-load failures report `rows_path = null` and no row artifact.
- Manifest `core_hashes` and recursive artifacts include the row JSONL hash.
- Docs state that row snapshots improve reconstructability while backend
  execution ledgers remain future work.
