# Phase 23 Design: Enforce Candidate Strategy Purity At Load

Date: 2026-05-28
Mode: Builder
Source review: `review-codex.md`

## Problem

`review-codex.md` flags that strategy purity is enforced only by repository
tests over committed strategy files. Runtime loading of arbitrary candidate
workspaces imports the configured Python file and checks only for
`generate_decisions`. A generated candidate can therefore load data, call runner
or engine APIs, write files, or make network calls before ranking.

## Assignment

Add a focused AST purity check at the strategy-loading boundary, enabled by
default. The check should reject the same categories already banned by committed
strategy tests before importing the candidate module.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 23:

- Enforce purity in `load_decision_strategy()` before `exec_module()`.
- Keep the check static and focused: forbidden imports and obvious side-effect
  calls only.
- Keep an explicit `enforce_purity` loader parameter for tests or deliberately
  trusted local experiments.
- Do not attempt sandboxing, runtime timeouts, or broad import whitelisting in
  this phase.
- Reuse the same purity implementation from committed-strategy tests to avoid
  drift.

## Scope

- Add loader tests for banned side-effect calls and optional opt-out.
- Add a reusable purity checker under `quant_strategies.decisions`.
- Call the checker from `load_decision_strategy()` by default.
- Update committed-strategy purity tests to use the shared checker.
- Update docs and progress tracking.

## Not In Scope

- Runtime sandboxing.
- Stage timeout policy.
- Moving strategies between directories.
- Full import whitelisting.
- Network or filesystem syscall interception.

## Success Criteria

- Loader rejects candidate files with banned imports/calls before importing
  them.
- Loader opt-out remains available for deliberately trusted experiments.
- Existing committed strategy purity tests still pass through the shared checker.
- Runner/validation import failures still surface as strategy-load failures.
- Focused loader/tests, full suite, diff check, compile check, and code review
  pass.
