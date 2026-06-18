## Context

`quant_strategies` currently treats each emitted `TargetDecision.target` as the
final signed weight of NAV to trade. That lets a research loop alter economic
scale inside strategy params and still optimize scale-invariant or nearly
scale-invariant statistics. The result can be a book with acceptable statistical
shape but too little deployed risk and return to matter.

The shared book already owns the right primitives: one causal target-book walk,
operator-frozen cost/fill/capacity/leverage envelopes, capacity impact charged in
NAV, and typed fail-closed feasibility verdicts. The missing root concept is a
foundation-owned sizing layer that converts a causal emitted shape into final
executable target weights under an operator risk budget.

This change is intentionally breaking. Existing strategies and configs are not
compatibility constraints; they must be rewritten to the shape-plus-risk-budget
contract.

## Goals / Non-Goals

**Goals:**
- Make strategy output describe portfolio shape, not final deployable size.
- Make risk-budget sizing a first-class foundation responsibility across quick
  run, validation, and evaluation.
- Price costs, slippage, capacity, funding, and impact at the final executable
  size before any score is consumed.
- Preserve fail-closed semantics for genuinely untradeable final books.
- Report capacity-frontier limits as sizing information when calibration cannot
  reach the requested volatility.
- Prevent validation/evaluation from recalibrating OOS folds with future window
  information.
- Remove compatibility modes that preserve raw emitted targets as final weights.

**Non-Goals:**
- Do not add objective scores such as Calmar, PSR, DSR, or search-pressure
  policy to `quant_strategies`; consumers still own scoring.
- Do not add paper-trading, live-trading, order routing, or promotion authority.
- Do not preserve old candidate behavior, old artifact replay, or old configs.
- Do not implement universe selection; `quant_autoresearch` owns universe rules
  and passes resolved symbols.

## Decisions

### Decision 1: Strategy targets become shape weights

`TargetDecision.target` remains a signed float but its contract changes: it is a
base shape weight, not the final deployable signed weight. The foundation derives
a normalized shape book from the full decision stream before it walks the book.

The normalizer is the maximum intended raw gross exposure observed across the
decision timeline after standing targets are applied. Each raw target is divided
by that scalar. This removes arbitrary global scale while preserving:

- signs,
- relative cross-sectional allocation,
- time-varying gross engagement,
- flat periods,
- same-symbol netting and idempotence.

If the emitted book has no non-zero intended gross, the normalized book remains
flat and the existing insufficient/no-activity evidence paths apply.

Alternative considered: normalize every decision timestamp to gross one. That
would destroy time-varying engagement and turn "be in cash" into an always-full
portfolio. Global max-gross normalization is the smaller and more faithful
transformation.

### Decision 2: Add required `RiskBudgetConfig`

Add a shared config model beside `CapacityModelConfig` and
`LeverageBudgetConfig`.

```text
[risk_budget]
mode = "calibrate_vol" | "fixed_scale"
annualization_periods_per_year = <positive int>
target_volatility = <positive float>  # calibrate_vol
book_scale = <positive float>         # fixed_scale
```

No default mode is supplied. Missing `[risk_budget]` is a config error on quick
run, validation, and evaluation.

Alternative considered: keep an `as_emitted` mode for old configs. Rejected
because the goal is a corrected root contract, not compatibility with old
strategy semantics.

### Decision 3: Calibrate Train, freeze downstream

`calibrate_vol` is the Train sizing mode. It:

1. Builds the normalized shape book.
2. Computes the feasible frontier from leverage and capacity limits.
3. Chooses a final `book_scale` that targets annualized volatility when feasible.
4. Scores one final sized book at that scale, including impact at deployed size.

`fixed_scale` is the validation/evaluation mode. It applies a previously recorded
`book_scale` to the normalized shape and walks the final book directly. It does
not measure the same OOS window to choose a new scale. If the fixed scale breaches
capacity, leverage, financing, cost, sample, or row-contract constraints, the run
fails closed with the existing typed verdict path.

Alternative considered: let every evaluation fold recalibrate to target vol.
Rejected because it uses realized OOS window information to choose scale and
turns evidence into ex-post sizing.

### Decision 4: Use priced calibration, not linear post-cost extrapolation

Capacity frontier ratios for gross/net and participation are linear in scale, but
deployed volatility and return are not guaranteed linear once market impact and
costs are charged. `calibrate_vol` MUST therefore price candidate scales through
the book walk and choose the largest feasible scale at or below target volatility
within tolerance, or the closest feasible frontier scale when the target cannot be
reached.

The foundation may use the unit-shape walk to bound the search, but it must not
claim exact deployed volatility from a one-pass linear extrapolation after costs.

### Decision 5: Capacity-bound is a sizing report, not a failure

If `calibrate_vol` cannot reach the requested volatility before the frontier, the
foundation walks and scores the frontier-sized book and reports:

- `capacity_bound = true`,
- `target_volatility`,
- `deployed_volatility`,
- `max_feasible_volatility`,
- `book_scale`,
- binding frontier dimensions.

This is not a feasibility verdict because the final executable book is feasible.
Genuine infeasibility remains fail-closed: unpriced capacity, unsupported volume
semantics, missing volume/ADV history, unpriced short financing, unfinanced
leverage, zero cost/slippage on a scoreable run, insufficient sample, and final
fixed-scale capacity or leverage breaches.

### Decision 6: Sizing report is part of the public evidence

Add `PortfolioSizingReport` to `RunPortfolioFoundation`, validation backend
results, evaluation scenario metrics, summary artifacts, and diagnostics. It is
the durable bridge between Train calibration and downstream fixed-scale evidence.

At minimum it carries:

- schema/version,
- sizing mode,
- normalization method and scalar,
- target/deployed/max-feasible annualized volatility,
- annualization periods per year,
- `book_scale`,
- `capacity_bound`,
- final max intended gross/net,
- frontier ratios and binding dimensions.

Quick-run economics and evaluation fold returns use final executable weights; raw
shape weights are report/debug metadata only.

## Risks / Trade-offs

- Breaking strategy semantics -> Mitigation: cut over docs, examples, tests, and
  candidates in one change; do not add compatibility shims.
- Calibration cost increases from additional priced walks -> Mitigation: keep the
  search bounded and deterministic; reuse row indexes and decision plans; do not
  import heavy evaluation dependencies into quick run.
- Volatility targeting can still overfit if used on OOS folds -> Mitigation:
  allow `calibrate_vol` for Train quick runs only in retainable workflows; require
  `fixed_scale` for validation/evaluation.
- Capacity-bound books can look like successful evidence while under-deployed ->
  Mitigation: expose `capacity_bound` and `max_feasible_volatility` in result and
  artifacts; downstream gates can reject books below mandate return/vol needs.
- Annualization cadence can be misconfigured -> Mitigation: make cadence explicit
  in `[risk_budget]` and include it in the sizing report; evaluation keeps its
  existing cadence guard for annualized metrics.

## Migration Plan

1. Add the shared risk-budget config and remove acceptance of configs without it.
2. Change decision semantics and docs from final weights to base shape weights.
3. Implement shape normalization and sizing report value objects.
4. Implement `calibrate_vol` in quick-run foundation and `fixed_scale` in all
   public surfaces.
5. Route validation/evaluation through fixed sizing and fail closed on final-book
   breaches.
6. Update result payloads, summary/diagnostic artifacts, active docs, examples,
   and tests.
7. Delete or rewrite any old strategy/config/test fixture that depends on raw
   emitted targets being final deployable weights.
