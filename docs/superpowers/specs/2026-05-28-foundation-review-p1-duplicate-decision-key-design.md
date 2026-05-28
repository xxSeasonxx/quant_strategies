# Phase 11 Design: Duplicate Decision Execution Keys

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

The adversarial review flags that two decisions with the same `(symbol,
decision_time)` can silently double-count smoke PnL when they have different
`decision_id` values. Current output validation rejects duplicate
`decision_id`, but not duplicate execution keys.

## Assignment

Reject duplicate same-symbol, same-decision-time strategy outputs before runner
or validation execution builds requests.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 11:

- Treat the current engine as one active decision per `instrument.symbol` and
  `decision_time`.
- Enforce the invariant in `validate_decision_output()` so runner and validation
  share the same behavior.
- Keep `decision_id` duplicate detection unchanged.
- Do not redesign multi-leg or intent semantics in this phase. A future broader
  ontology can relax or replace this invariant deliberately.

## Scope

- Add a duplicate execution-key check to `validate_decision_output()`.
- Add tests proving different `decision_id` values do not bypass the duplicate
  `(symbol, decision_time)` guard.
- Update progress tracking.

## Not In Scope

- Same-bar-entry causality.
- Empty-decision strategy classification.
- Multi-leg execution semantics.
- Engine request model changes.

## Success Criteria

- `validate_decision_output()` rejects the second decision for a duplicate
  `(instrument.symbol, decision_time)` key.
- Existing duplicate `decision_id` behavior is unchanged.
- Runner and validation inherit the guard through their existing
  `validate_decision_output()` calls.
- Focused decision tests, full suite, diff check, compile check, and code review
  pass.
