# Phase 31 Design: Evidence Quality Reuse

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` flags that runner evidence quality walks rows more than once.
Current code computes evidence quality inside `execute_strategy_run()` after
data load, then `run_config()` recomputes it after causality replay just to
change `causality_verified` and warnings. That repeats availability scanning and
row-contract evaluation on every successful run.

## Assignment

Reuse the evidence-quality payload produced at the execution boundary and update
only the causality fields after replay. Preserve existing artifact semantics.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed
for Phase 31:

- Keep evidence quality computed once when rows are first loaded and frozen.
- Add a helper that derives causality fields from the existing
  `data_availability_status`.
- Do not remove evidence-quality payloads from `StrategyExecutionError`; failure
  paths still need them.
- Do not change row-contract semantics or availability status names.

## Scope

- Add a focused regression that a successful runner call evaluates the row
  contract once.
- Add an artifact helper to update causality evidence without rewalking rows.
- Use that helper in `run_config()`.
- Update `progress.md`.

## Not In Scope

- Reworking `runner.run_config()` orchestration.
- Changing evidence-quality artifact field names.
- Changing causality replay behavior.
- Optimizing `write_data_manifest()` metadata field coverage.

## Success Criteria

- Successful runs call row-contract evaluation once, not twice.
- Complete `available_at` coverage plus passing causality still yields
  `causality_verified = true` and no evidence-quality warnings.
- Missing, partial, or invalid availability still keeps
  `runner_causality_not_verified` warnings.
- Focused runner tests and the full suite pass.
