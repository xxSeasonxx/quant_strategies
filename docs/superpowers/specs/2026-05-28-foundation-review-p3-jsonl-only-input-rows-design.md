# Phase 21 Design: Keep One Input Row Artifact

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` flags that full-profile runner executions write both
`strategy_input_rows.csv` and `strategy_input_rows.jsonl`, duplicating the same
loaded data. JSONL is the richer replay artifact because it preserves nested
values, nulls, booleans, and timestamp strings without CSV coercion.

## Assignment

Stop writing the duplicate CSV input-row artifact. Keep
`strategy_input_rows.jsonl` as the full-profile input-row artifact and preserve
its hash in `data_manifest.json`.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 21:

- Keep JSONL and remove CSV for runner strategy input rows.
- Do not remove `strategy_input_rows.jsonl`.
- Keep `artifact_profile = "full"` default unchanged in this phase; default
  profile selection is a separate finding.
- Remove now-unused CSV writer code if it has no remaining callers.
- Update docs and tests that enumerate full-profile artifacts.

## Scope

- Update runner artifact tests to expect JSONL-only input rows.
- Remove CSV writing from `write_strategy_input_rows()`.
- Update README artifact wording.
- Update progress tracking.

## Not In Scope

- Flipping default `artifact_profile` to `summary`.
- Changing summary-profile behavior.
- Changing validation artifacts.
- Changing row hash semantics.

## Success Criteria

- Full-profile runs that load data write `strategy_input_rows.jsonl` and do not
  write `strategy_input_rows.csv`.
- Summary-profile runs still write no input-row artifacts.
- `data_manifest.json` still records `strategy_input_rows_jsonl_sha256` for
  full-profile runs.
- Focused runner artifact tests, full suite, diff check, compile check, and code
  review pass.
