# Phase 15 Design: Deflation Not Evaluated Reason

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` flags that validation copies `[search_pressure]` metadata
into `overfit_controls`, but no gate consumes it. The current code sets
`deflated_sharpe` and `monte_carlo` to `None` and can still emit
`mechanical_review_candidate` with `reasons == ()`. That is too easy to
overread as statistically deflated evidence.

## Assignment

When validation emits `mechanical_review_candidate` and non-empty search
pressure is present, add a machine-readable `deflation_not_evaluated` reason.
This makes the limitation explicit without blocking the advisory result or
pretending to compute statistical corrections.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 15:

- Use reason string `deflation_not_evaluated`.
- Add the reason only to `mechanical_review_candidate` outputs.
- Add the reason only when search pressure is materially present:
  `candidate_count`, `trial_count`, non-empty `parameter_search_space`,
  `selection_rule`, or non-empty `split_ids`.
- Do not add a failed gate; the current PRD says search-pressure metadata is not
  blocking.
- Do not compute deflated Sharpe, Monte Carlo, or statistical corrections in
  this phase.
- Keep eligibility flags false and manual approval required.

## Scope

- Add a small policy helper that detects non-empty search pressure from the
  existing `overfit_controls` payload.
- Add the reason in the policy finish path after the final advisory decision is
  known.
- Add focused policy and validation artifact regressions.
- Update docs to state that search-pressure-backed mechanical review candidates
  carry `deflation_not_evaluated`.
- Update progress tracking.

## Not In Scope

- Statistical deflation.
- Changing paper-readiness gates.
- Changing `watchlist`, `mechanical_pass`, or `hard_no` reasons.
- Changing validation config schema.
- Changing promotion, paper-trade, or live eligibility.

## Success Criteria

- A policy-level `mechanical_review_candidate` with non-empty search pressure
  includes `deflation_not_evaluated`.
- A policy-level `mechanical_review_candidate` without search pressure keeps
  `reasons == ()`.
- Validation artifacts and reports preserve the reason when `[search_pressure]`
  is configured.
- Focused tests, full suite, diff check, compile check, and code review pass.
