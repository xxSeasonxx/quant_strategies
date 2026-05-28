# Foundation Review P0 Design

Date: 2026-05-28
Mode: Builder
Sources: `PRD.md`, `review-codex.md`, `review-claude.md`, `AGENTS.md`

## Problem

The two review files agree on three P0 semantic issues:

- Runner outputs can complete as `smoke_passed` without running hidden-lookahead replay.
- Validation can emit `paper_candidate` even though the PRD forbids paper-sounding labels without statistical evidence.
- Smoke aggregate fields use `return` names for sums of weighted trade activity, which can be mistaken for portfolio/NAV returns.

Season explicitly asked for no overnight questions. Decisions below were auto-selected from the PRD and review evidence.

## Chosen Approach

Fix the contract names and causality boundary directly, without compatibility aliases for old artifacts.

1. Extract hidden-lookahead replay into a neutral top-level causality module so runner and validation can both use it without `runner -> validation` imports.
2. Run hidden-lookahead replay in `runner.run_config` after strategy execution and before engine evaluation.
3. Mark runner evidence as `causality_verified = true` only when replay passes and `available_at` coverage is complete.
4. If replay fails, return `runner_failed` with stage `causality`.
5. If replay passes but availability coverage is missing, partial, or invalid, keep the run completed but use `assessment_status = "smoke_unverified"` instead of `smoke_passed`.
6. Rename validation's overclaiming `paper_candidate` decision to `mechanical_review_candidate`.
7. Rename smoke aggregate score fields from `sum_weighted_trade_*_return` to `sum_signed_trade_activity_*`.

## False-Positive Triage

| Review item | Current triage | Evidence |
|---|---|---|
| Runner skips hidden-lookahead replay | True | `runner.run_config` does not call replay today; validation does. |
| `paper_candidate` overstates evidence | True | `validation/policy.py` emits it from mechanical gates; eligibility flags are false but label is still misleading. |
| Smoke score `return` names overstate units | True | Engine sums per-trade weighted quantities, not a NAV return path. |
| Runner and validation have no shared kernel | Partly true | `runner.execution` is shared, but causality is validation-owned. P0 fixes the causality portion only. |
| Public API re-export mismatch | Real docs/PRD drift, not a P0 code bug | Repo `AGENTS.md` says `quant_autoresearch` should consume `quant_strategies.runner.run_config`. |
| Full futures/options/multi-leg execution missing | True but deferred | PRD requires expression, but reviews warn not to overbuild execution support in this phase. |

## Success Criteria

- A hidden-lookahead strategy cannot produce `smoke_passed`.
- A run with complete `available_at` coverage and passing replay records `causality_verified = true`.
- A run with missing, partial, or invalid `available_at` coverage does not claim `smoke_passed`.
- Validation artifacts no longer use `paper_candidate`.
- Runner, engine, docs, and tests use smoke activity names that do not contain `return`.
- Existing tests are updated and targeted tests prove the behavior.
