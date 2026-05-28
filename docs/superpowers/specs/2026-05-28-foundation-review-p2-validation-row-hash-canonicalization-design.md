# Phase 32 Design: Validation Row Hash Canonicalization

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` flags duplicate normalized row hashing. Current runner code
owns canonical row hashing in `runner.artifact_profiles.normalized_rows_sha256`,
while validation owns a separate `validation.manifest.rows_sha256` helper and
hashes freshly written `data_rows/*.jsonl` files by rereading them.

Phase 27 made validation row snapshots audit-visible, but left canonical row
serialization split between runner and validation.

## Assignment

Make validation row snapshots use the same canonical row JSONL serialization as
runner row hashing. Compute the row snapshot hash from the exact payload written
instead of rereading the file in `_write_window_rows()`.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed
for Phase 32:

- Keep validation `rows_sha256` values byte-identical to the row snapshot file
  hashes.
- Keep generic validation JSONL serialization for decision records and other
  non-row artifacts.
- Do not change manifest field names or artifact paths.
- Do not remove manifest `core_hashes` or `artifacts` file hashing.

## Scope

- Add a focused regression that validation row snapshot hashing does not reread
  `data_rows/*.jsonl` through the validation window writer.
- Add a runner-owned `canonical_rows_jsonl()` helper and reuse it for
  `normalized_rows_sha256()`.
- Use that helper for validation data row snapshots.
- Remove the duplicate validation row hash helper.
- Update `progress.md`.

## Not In Scope

- Caching database engines or loader output.
- Removing file hashes from validation manifests.
- Changing backend metric or scenario artifact schemas.
- Changing row snapshot content.

## Success Criteria

- Validation data provenance `rows_sha256` still equals the actual
  `data_rows/*.jsonl` file hash.
- Validation row snapshot hashing no longer rereads the just-written data row
  file in `_write_window_rows()`.
- Runner and validation row hash canonicalization use one implementation.
- Focused validation tests and the full suite pass.
