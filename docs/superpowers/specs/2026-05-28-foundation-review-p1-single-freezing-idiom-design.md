# Phase 9 Design: Single Freezing Idiom

Date: 2026-05-28
Mode: Builder
Source reviews: `review-claude.md`, `review-codex.md`

## Problem

The reviews identify two related issues:

- `boundary.frozen_rows()` and `boundary.frozen_params()` deep-copy every row
  or params map before recursively freezing standard containers. This repeats a
  costly copy on large row sets even though recursive freezing already builds
  isolated immutable containers for mappings, lists, tuples, and sets.
- `validation.matrix` owns a private `_FrozenDict` and `_freeze_value`, giving
  the repository two freezing idioms despite PRD G3 requiring one declared
  freezing idiom.

## Assignment

Make `quant_strategies.boundary` the single freezing boundary for rows, params,
and validation matrix override maps.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 9:

- Preserve strategy mutation protection for rows and params.
- Preserve caller-mutation isolation for ordinary JSON-like nested structures.
- Use one boundary-owned `FrozenMapping` class backed by `MappingProxyType` so
  idempotence is trusted only for objects created by this package. External
  mapping proxies must still be copied and recursively frozen.
- Store frozen rows and params on `StrategyExecutionResult` so runner and
  validation can reuse the same frozen inputs instead of re-freezing loaded rows.
- Keep raw loaded rows for artifact writing, hashing, data provenance, and
  readiness checks.
- Leave broader validation lookahead indexing/performance work for a later
  phase.

## Scope

- Remove the redundant `deepcopy` dependency from `boundary`.
- Replace the raw `MappingProxyType` alias with boundary-owned `FrozenMapping`.
- Make `frozen_rows()` and `frozen_params()` idempotent for already-frozen
  boundary objects.
- Add frozen input fields to `StrategyExecutionResult`.
- Use frozen execution inputs in runner causality, validation audits, validation
  backend calls, and parameter scenario regeneration.
- Replace validation matrix private freezing helpers with the boundary helper.
- Add focused tests for idempotence and validation matrix immutability.
- Update progress tracking.

## Not In Scope

- Rewriting validation lookahead replay to pre-index visible row slices.
- Changing artifact payload rows from raw dicts to frozen mappings.
- Changing strategy public API shapes.
- Adding runtime sandboxing or broader candidate purity checks.

## Success Criteria

- `src/quant_strategies/boundary.py` is the only source freeze helper.
- `validation.matrix` no longer defines `_FrozenDict` or local recursive freeze
  helpers.
- Re-freezing already frozen rows/params preserves object identity.
- Freezing externally-created mapping proxies still isolates from caller
  mutation.
- Strategy row/param mutation tests still fail closed.
- Focused runner, validation, matrix, and boundary tests pass.
- Full suite, diff check, compile check, and code review pass.
