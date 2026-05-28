# Phase 13 Design: Empty-Decision Screening

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` flags that a strategy returning zero decisions is classified
as `runner_failed`. Current strategy tests already treat `[]` as the normal
output for empty input, below-threshold signals, or degenerate history. The
runner contradicts that strategy contract by failing request construction before
the smoke engine can report `trade_count = 0`.

## Assignment

Make `[]` a valid no-op strategy output. A run with no decisions should still
load data, write artifacts, run the smoke engine, and produce machine-readable
zero-trade evidence. It must not be confused with malformed strategy output,
unsupported decisions, missing rows, or an engine crash.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 13:

- Treat an empty decision list as a valid strategy result.
- Keep invalid output shapes as `decision_generation` failures.
- Keep unsupported non-empty decisions as request-build failures.
- Fix the root contract in the engine request model instead of adding a
  runner-only special case.
- For `mode = "screen"`, a zero-decision run completes as `screened` with
  `success = True` and `trade_count = 0`.
- For `mode = "validate"`, a zero-decision run completes as `smoke_failed`
  with `success = False` because the `min_trades` gate fails. It is not
  `runner_failed`.
- Preserve full-profile audit artifacts: empty `decision_records.jsonl`,
  `engine_request.json` with an empty decisions array, and `evidence.json` with
  zero trades.

## Scope

- Allow `StrategySpec.decisions` to be empty while still requiring
  `strategy_id`.
- Remove the runner request-builder guard that rejects empty decision lists.
- Add engine and runner tests for zero-decision screen/validate behavior.
- Update consumer-facing docs to state how zero-opportunity runs should be
  interpreted.
- Update progress tracking.

## Not In Scope

- Changing validation harness policy for zero-trade validation windows.
- Adding statistical no-trade analysis.
- Changing malformed strategy-output failures.
- Changing unsupported decision semantics.
- Adding a new `assessment_status` value.

## Success Criteria

- `build_request(..., decisions=[])` returns an `EvaluationRequest`.
- `screen()` produces `trade_count = 0`, empty trades, and zero smoke scores for
  an empty-decision request.
- `validate()` treats zero decisions as valid inputs but fails the `min_trades`,
  `positive_gross`, and `positive_net` smoke gates.
- `run_config()` no longer classifies an empty-decision strategy as
  `runner_failed`.
- Full-profile runner artifacts remain reconstructable for zero-decision runs.
- Focused tests, full suite, diff check, compile check, and code review pass.
