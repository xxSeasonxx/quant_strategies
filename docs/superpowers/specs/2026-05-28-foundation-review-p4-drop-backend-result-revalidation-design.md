# Phase 18 Design: Drop Backend Result Revalidation

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` flags internal Pydantic revalidation across boundaries. The
validation path has a true case: `ValidationBackend.run()` is typed to return
`BackendRunResult`, but `_run_scenario_backend()` calls
`BackendRunResult.model_validate()` on that result before storing it. That makes
the validation orchestrator re-parse an internal Protocol return value.

The review also names runner `FillModel` and `CostModel` construction. That part
is not the same problem: runner config models intentionally adapt into engine
request models, and `FillModelConfig` has runner-only fields such as
`allow_same_bar_close_fill`. Keep that conversion.

## Assignment

Remove the Pydantic revalidation of conforming backend results while preserving
graceful failure artifacts for injected backends that do not return
`BackendRunResult`.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 18:

- Trust `ValidationBackend.run()` when it returns a `BackendRunResult`.
- Replace `BackendRunResult.model_validate()` with a direct assignment plus a
  cheap runtime type guard for nonconforming injected backends.
- Keep `backend_exception` handling unchanged.
- Keep `invalid_backend_result` artifacts for returns that are not
  `BackendRunResult`; do not parse dictionaries as backend results.
- Do not change runner `FillModelConfig`/`CostModelConfig` conversion into engine
  `FillModel`/`CostModel`.

## Scope

- Add a regression proving validation does not call
  `BackendRunResult.model_validate()` for conforming backend results.
- Replace the revalidation call in validation scenario execution.
- Update malformed backend tests to assert the new Protocol-type failure shape.
- Update progress tracking.

## Not In Scope

- Removing runner config-to-engine model construction.
- Changing backend metric schemas.
- Changing validation policy classification.
- Reworking the `ValidationBackend` Protocol into an ABC or concrete class.

## Success Criteria

- No source calls `BackendRunResult.model_validate()`.
- Conforming backend results are accepted without Pydantic revalidation.
- Nonconforming backend return values still produce failed backend artifacts
  rather than crashing artifact writing.
- Runner fill/cost model conversion remains unchanged.
- Focused validation tests, full suite, diff check, compile check, and code
  review pass.
