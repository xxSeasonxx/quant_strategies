# Phase 7 Design: Deterministic JSON Artifact Encoding

Date: 2026-05-28
Mode: Builder
Source reviews: `review-claude.md`, `review-codex.md`

## Problem

PRD NFR-DETERMINISM requires byte-identical artifacts for the same code,
config, and data. Phase 3 added repeated-run regression coverage, but runner
and validation decision-record artifacts still use pydantic
`model_dump_json()`. That encoding is stable within one installed pydantic
build, but it does not sort keys and can silently change artifact hashes across
patch versions.

## Assignment

Write all decision-record JSONL artifacts through a canonical encoder:
`model_dump(mode="json")` followed by `json.dumps(..., sort_keys=True,
separators=(",", ":"), allow_nan=False)`.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 7:

- Scope this phase to decision-record JSONL artifacts called out by the review.
- Keep pretty-printed summary/manifests as they already use `sort_keys=True` and
  serve human review.
- Do not change artifact filenames or schemas.
- Keep JSONL newline behavior unchanged: one newline after non-empty payloads.

## Scope

- Canonicalize runner `decision_records.jsonl`.
- Canonicalize validation base `decision_records.jsonl`.
- Canonicalize validation per-scenario decision-record JSONL files.
- Add tests against raw JSONL text ordering/spacing.
- Update README/progress and Phase 7 plan.

## Not In Scope

- Reworking git dirty-tree identity hashing.
- Dropping duplicate CSV/JSONL input-row artifacts.
- Changing row-hash algorithms.
- Validation artifact reconstructability expansion.

## Success Criteria

- `rg "model_dump_json\\(" src` finds no artifact writers.
- Runner and validation decision-record JSONL lines are sorted, compact JSON.
- Existing deterministic full-run regression still passes.
- Full test suite, diff check, and compile check pass.
