# Phase 17 Design: Retire Unused Validation Errors

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` identifies `ValidationDataError` and
`ValidationBackendError` as validation error classes that are defined but never
raised. The active validation workflow uses `ValidationError` as the workflow
base class and `ValidationConfigError` for configuration parsing failures. The
extra subclasses imply data and backend failure semantics that the code does not
implement.

## Assignment

Retire the unused validation error classes and keep the validation error surface
limited to the errors that are actually raised by source code.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 17:

- Delete `ValidationDataError` and `ValidationBackendError`.
- Keep `ValidationError` as the base validation workflow exception.
- Keep `ValidationConfigError` as the configuration exception.
- Add a narrow regression test for the exported names in
  `quant_strategies.validation.errors`.
- Do not introduce replacement error classes or wrappers.

## Scope

- Add a focused validation error-surface test.
- Delete the two unused validation error subclasses.
- Update progress tracking.

## Not In Scope

- Reworking backend failure result modeling.
- Reworking data audit violation modeling.
- Changing CLI exception handling.
- Changing validation policy decisions.

## Success Criteria

- `quant_strategies.validation.errors` exposes only `ValidationError` and
  `ValidationConfigError` as public error classes.
- No source or test references remain for `ValidationDataError` or
  `ValidationBackendError`.
- Focused validation tests, full suite, diff check, compile check, and code
  review pass.
