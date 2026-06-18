## Why

The current foundation lets strategies choose absolute target weights, so a search
loop can converge on a tiny book whose statistical shape is good but whose deployed
return is economically irrelevant. The foundation should own the conversion from a
causal target-book shape to a deployable sized book because only the foundation has
the shared NAV path, leverage envelope, capacity limits, market-impact pricing, and
annualization contract needed to size honestly.

## What Changes

- **BREAKING**: Strategy-emitted targets become base **shape** weights, not final
  deployable portfolio weights. The foundation normalizes the emitted target-book
  shape and applies a recorded sizing policy before the book walk.
- Add a required `[risk_budget]` operator envelope across quick run, validation,
  and evaluation. It owns annualized volatility target, annualization cadence, and
  sizing mode.
- Add foundation-owned sizing modes:
  - `calibrate_vol`: calibrate a normalized shape to the requested annualized
    volatility, capped by leverage and capacity frontier, then score the sized
    book.
  - `fixed_scale`: apply a previously recorded scale to the normalized shape for
    validation/evaluation and fail closed if the final sized book breaches the
    envelope.
- Remove legacy compatibility modes for treating emitted raw targets as final
  weights. Existing strategies/configs are not compatibility constraints; they
  must be rewritten against the shape-plus-risk-budget contract.
- Split capacity frontier reporting from infeasibility. A requested volatility
  above the feasible frontier in `calibrate_vol` produces a scored sized book plus
  `capacity_bound = true` / `max_feasible_vol`, while genuine unpriced or
  impossible final books still fail closed.
- Add a `PortfolioSizingReport` to in-process results and artifacts, including
  sizing mode, shape normalization, `book_scale`, target/deployed/max-feasible
  annualized volatility, capacity-bound status, leverage/capacity frontier inputs,
  and final executable gross/net exposure.
- Require validation and evaluation to consume frozen sizing from the retained
  Train quick run via `fixed_scale`; they must not recalibrate scale per fold.
- Ensure quick-run economics and evaluation fold metrics report final executable
  weights and returns from the sized book, not raw shape weights.

## Capabilities

### New Capabilities
- `risk-budget-sizing`: Foundation-owned conversion from emitted target-book shape
  to final executable target weights under an operator risk budget.

### Modified Capabilities
- `portfolio-decision-contract`: Redefine emitted targets as base shape weights and
  require all execution surfaces to consume the foundation-sized executable book.
- `quick-run-portfolio-foundation`: Add risk-budget sizing, sizing reports, and
  capacity-bound scoring semantics to the quick-run foundation.
- `capacity-adv-market-impact`: Distinguish calibration frontier limits from
  fail-closed final-book capacity breaches.
- `quick-run-retainability`: Require retained evidence to carry a frozen sizing
  report and require downstream use of fixed scale.
- `evaluation-fold-returns`: Ensure evaluation consumes fixed sizing and never
  recalibrates OOS folds.
- `quick-run-economics`: Clarify that economics ledger weights and returns are
  derived from final executable sized weights.

## Impact

- Public config schemas for quick run, validation, and evaluation gain a required
  `[risk_budget]` section.
- `TargetDecision.target` semantics change from final deployable weight to base
  shape weight; strategy examples, candidates, and docs must be cut over rather
  than compatibility-shimmed.
- `build_portfolio_foundation`, `walk_portfolio_book`, validation spine backend,
  evaluation spine backend, result payloads, and artifact writers must carry a
  sizing policy/report.
- Active docs and OpenSpec specs must be updated together because the strategy
  contract, feasibility vocabulary, capacity semantics, retainability conditions,
  and evaluation evidence boundary all change.
