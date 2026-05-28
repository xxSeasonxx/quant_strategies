# Phase 10 Design: Backend-Owned Capabilities

Date: 2026-05-28
Mode: Builder
Source reviews: `review-claude.md`, `review-codex.md`

## Problem

`validation.capabilities` owns backend-specific capability records and switches on
backend names such as `fake` and `vectorbtpro`. The reviews correctly flag this
as a boundary leak: execution capability is a backend concern, while the artifact
writer should only combine backend-declared capabilities with observed
unsupported semantics.

## Assignment

Move static capability declarations onto backend implementations while preserving
the existing `backend_capability_matrix.json` shape.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 10:

- Preserve the existing artifact schema:
  `{"backend", "observed_unsupported_semantics", "semantics"}`.
- Keep observed unsupported semantic extraction centralized, because it is based
  on `ScenarioBackendRunResult` artifacts rather than backend internals.
- Add a small capability-record helper in `validation.backends` so backend
  implementations can declare records without importing `validation.capabilities`.
- Require first-party backends to expose `capability_records(observed_unsupported)`.
- Keep a generic unknown-backend fallback for backend-selection failures and
  ad-hoc injected test backends.
- Do not redesign policy gates or unsupported-semantics severity in this phase.

## Scope

- Extend `ValidationBackend` with `capability_records()`.
- Implement capability declarations on `FakeBackend`.
- Move VectorBT Pro static capability declarations into
  `validation.vectorbtpro_backend`.
- Reduce `validation.capabilities` to observed-semantics extraction and matrix
  assembly.
- Update validation artifact writing to pass the selected backend object.
- Update capability tests to assert backend-owned records and artifact shape.
- Update progress tracking.

## Not In Scope

- Changing capability record field names or semantics.
- Changing validation policy behavior for unsupported required scenarios.
- Adding new backend capability dimensions.
- Removing the `ValidationBackend` Protocol.

## Success Criteria

- `validation.capabilities` no longer switches on `backend_name == "vectorbtpro"`
  or `backend_name == "fake"`.
- `FakeBackend` and `VectorBTProBackend` own their static capability records.
- Existing capability matrix JSON remains byte-shape compatible.
- Validation artifacts still include `backend_capability_matrix.json`.
- Focused capability and validation tests pass.
- Full suite, diff check, compile check, and code review pass.
