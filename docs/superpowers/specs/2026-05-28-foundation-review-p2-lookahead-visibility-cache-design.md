# Phase 26 Design: Cache Lookahead Row Visibility

Date: 2026-05-28
Mode: Builder
Source review: `review-codex.md`

## Problem

`review-codex.md` Finding 9 flags that hidden-lookahead replay scales poorly:
for every baseline decision, the checker filters every row, reparses
timestamps, freezes the visible slice, and reruns the strategy. Phase 9 already
made freezing idempotent, but row visibility parsing is still multiplied by the
number of decisions.

## Assignment

Optimize the shared causality checker without weakening hidden-lookahead
semantics. Parse row visibility metadata once per check, cache visible slices by
decision visibility boundary, and reuse frozen params across replays.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed
for Phase 26:

- Keep replay semantics identical: timestamp must be `<= as_of_time`; valid
  `available_at` must be `<= decision_time`; invalid optional availability
  falls back to timestamp-only visibility.
- Do not batch strategy replays or change decision fingerprinting.
- Keep the optimization in `quant_strategies.causality`, because runner and
  validation both use that checker.
- Add a deterministic regression around parse-call count instead of a flaky wall
  clock assertion.

## Scope

- Add row visibility metadata/cache helpers in `src/quant_strategies/causality.py`.
- Reuse a single frozen params object for all replay calls.
- Add tests for parse-count scaling and visibility cache reuse.
- Update docs/progress.

## Not In Scope

- Parallel replay execution.
- Relaxing hidden-lookahead detection.
- Validation-level benchmark harnesses with live data.
- Full validation artifact reconstructability.

## Success Criteria

- Row timestamp/availability parsing is O(rows), not O(rows × decisions), in
  `check_hidden_lookahead()`.
- Multiple decisions sharing the same `(as_of_time, decision_time)` reuse the
  same visible row tuple.
- Existing lookahead behavior remains unchanged.
- Focused tests, full suite, diff check, compile check, and code review pass.
