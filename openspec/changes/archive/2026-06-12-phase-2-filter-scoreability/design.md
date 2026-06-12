## Context

The shared portfolio book already emits typed `FeasibilityVerdict` values for
leverage-budget breaches, unpriced financing, zero-cost scoreable runs, and
insufficient at-risk samples. Quick run gates completion on those verdicts.

Validation and evaluation call the same book but do not consistently preserve the
same scoreability contract. Validation ignores non-raising verdicts returned by
`build_portfolio_foundation`, and evaluation uses `walk_portfolio_book`, which
does not apply the zero-cost or minimum-sample scoreability checks. Validation
also runs a preflight gross-exposure check with a fixed `1.0` ceiling before the
book sees the configured leverage budget.

## Goals / Non-Goals

**Goals:**

- Make `FeasibilityVerdict` visible on validation and evaluation scenario results.
- Fail required scoreability-bearing scenarios on non-scoreable verdicts.
- Keep zero-cost/reference scenarios diagnostic without letting them satisfy
  scoreability gates.
- Remove the validation gross `> 1.0` preflight and let the book enforce the
  configured leverage budget.

**Non-Goals:**

- Redesign validation/evaluation into a search, ranking, or promotion system.
- Add a second feasibility implementation outside the portfolio book.
- Change quick-run `RunResult.succeeded` or `RunResult.retainable` semantics.
- Reintroduce per-trade scoring or open-ticket validation semantics.

## Decisions

1. Add `scoreability_bearing` to validation/evaluation scenario models.

   Required/optional currently means scenario coverage. Scoreability is a
   different question: whether a scenario may count as tradeable filter evidence.
   Keeping it explicit avoids using `required=False` as a proxy for diagnostic
   semantics. Default generated zero-cost/reference scenarios set
   `scoreability_bearing=False`; realistic, stressed-cost, and fill-lag scenarios
   keep `True`.

   Alternative considered: mark zero-cost/reference scenarios optional. That is
   simpler but conflates coverage with evidence semantics and makes it harder to
   require diagnostic artifacts without treating them as gates.

2. Thread the book verdict through existing result objects.

   Add a `feasibility` field to validation `BackendRunResult` and evaluation
   `PortfolioEvaluationResult`. Store the existing `FeasibilityVerdict` object in
   memory and serialize it as a payload in artifacts. Default fake/backend results
   can use a feasible verdict so existing tests remain direct.

   Alternative considered: encode verdicts only as warning strings. That keeps
   schemas smaller but preserves the current root problem: consumers must parse
   warnings to recover scoreability.

3. Use the existing quick-run scoreability function for validation/evaluation.

   Validation can keep calling `build_portfolio_foundation`, then return metrics
   plus `foundation.feasible_verdict()`. Evaluation should compute the same
   scenario verdict from the walked NAV path and the configured metrics sample
   floor instead of relying on `walk_portfolio_book` alone.

   Alternative considered: duplicate a new validation/evaluation-only sample and
   zero-cost check. That adds a second contract owner and can drift from quick run.

4. Delete the validation exposure preflight path.

   The book already checks intended gross and net exposure against
   `LeverageBudgetConfig` before fills. Removing the preflight fixes the root cause:
   validation no longer has a second, hard-coded leverage budget.

   Alternative considered: parameterize the preflight with the leverage budget.
   That still duplicates book feasibility logic and leaves two owners.

## Risks / Trade-offs

- Some existing zero-cost/reference scenarios will carry `feasible=False` while
  still completing as diagnostics -> Artifacts and typed results must expose
  `scoreability_bearing` so consumers do not mistake them for scoreable evidence.
- Existing tests encode the old validation preflight and required zero-cost
  assumptions -> Update tests to assert the book-owned verdict contract.
- Evaluation needs the non-raising verdict without rebuilding a second path ->
  Reuse the book path and the same scoreability inputs rather than a separate
  scoring spine.
