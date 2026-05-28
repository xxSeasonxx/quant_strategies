# Phase 35 Design: Engine Gating Names

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` flags that the engine still exposes `validate`,
`ValidationConfig`, and `ValidationReport`, even though the repository also has
a separate `quant_strategies.validation` harness. Earlier phases collapsed the
runner-to-engine signal path and renamed validation policy outputs, but the
engine smoke-gate API names still imply full validation.

## Assignment

Rename the engine smoke-gate API to gating names:

- `validate()` -> `gate_screen()`
- `ValidationConfig` -> `GatingConfig`
- `ValidationReport` -> `GatingReport`

Do not change runner `[output] mode = "validate"` semantics or artifact
`mode = "validate"` values; those are runner user-facing modes. Do not add
compatibility aliases for the old engine API names.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed
for Phase 35:

- Keep the gate math and gate names unchanged.
- Keep evidence JSON field names unchanged unless required by type references;
  this phase is API naming, not an artifact schema migration.
- Update internal call sites and tests to the new names.
- Do not preserve old engine API aliases.

## Scope

- Add a focused public API regression for the new engine names and absence of
  old names.
- Rename the engine model classes and evaluation function.
- Update runner engine evaluation call site.
- Update tests that import or call the old engine names.
- Update `progress.md`.

## Not In Scope

- Renaming runner output mode `validate`.
- Changing validation harness names.
- Changing evidence schema version or JSON field names.
- Moving shared config primitives.

## Success Criteria

- `quant_strategies.engine` exports `gate_screen`, `GatingConfig`, and
  `GatingReport`.
- `quant_strategies.engine` no longer exports `validate`, `ValidationConfig`,
  or `ValidationReport`.
- Runner smoke-gate behavior remains unchanged.
- Focused engine and runner tests plus the full suite pass.
