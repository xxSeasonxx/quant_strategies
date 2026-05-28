# Phase 12 Design: RunResult Evidence Quality

Date: 2026-05-28
Mode: Builder
Source review: `review-codex.md`

## Problem

`review-codex.md` flags that `RunResult` exposes `success`,
`run_completed`, `assessment_status`, and `artifact_trust_tier`, but not the
evidence-quality fields that consumers must use before ranking a run. The
artifact payload already includes `data_availability_status`,
`availability_coverage`, `row_contract`, `causality_verified`, and
`evidence_quality_warnings`; the typed return object does not.

## Assignment

Expose runner evidence quality on `quant_strategies.runner.RunResult` so
`quant_autoresearch` can use the stable Python API without parsing artifacts for
first-pass rankability filters.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 12:

- Preserve existing `RunResult` fields and defaults.
- Add evidence-quality fields with defaults so tests and simple callers that
  instantiate `RunResult` directly keep working.
- Populate the fields from the same evidence-quality payload written to
  `summary.json` and `data_manifest.json`.
- For config-load failures, where no data config or result directory exists,
  leave the fields `None` or conservative false/empty defaults.
- Do not introduce a second summary object in this phase.

## Scope

- Add evidence-quality fields to `RunResult`.
- Populate them in success and failure returns.
- Add focused tests that `RunResult` mirrors summary evidence-quality fields.
- Update the consumer docs field list.
- Update progress tracking.

## Not In Scope

- Validation result evidence fields.
- Runtime purity checks.
- Structured stage logging.
- Replacing dict payloads with Pydantic result models.

## Success Criteria

- `RunResult` exposes `data_availability_status`, `availability_coverage`,
  `row_contract`, `causality_verified`, and `evidence_quality_warnings`.
- Successful and failed runner calls populate those fields from the same payload
  written to `summary.json`.
- Existing direct `RunResult(...)` instantiations still work.
- Focused runner/API/docs tests, full suite, diff check, compile check, and code
  review pass.
