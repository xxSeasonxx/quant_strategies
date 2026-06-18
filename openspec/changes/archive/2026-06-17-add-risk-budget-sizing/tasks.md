## 1. Config And Contract Cutover

- [x] 1.1 Add shared `RiskBudgetConfig` with `calibrate_vol` and `fixed_scale` validation, including required `annualization_periods_per_year`.
- [x] 1.2 Require `[risk_budget]` in quick-run, validation, and evaluation config models with no default or legacy fallback.
- [x] 1.3 Update strategy decision docs and tests so `TargetDecision.target` is treated as a base shape weight, not final deployable exposure.
- [x] 1.4 Delete or rewrite configs, examples, and fixtures that rely on raw emitted targets being final weights.

## 2. Sizing Core

- [x] 2.1 Add value objects for normalized shape metadata and `PortfolioSizingReport`.
- [x] 2.2 Implement deterministic standing-target shape normalization using maximum intended raw gross exposure over the decision timeline.
- [x] 2.3 Refactor `_DecisionPlan` or its builder so final executable signed weights are produced from normalized shape weights plus `book_scale`.
- [x] 2.4 Implement frontier measurement for leverage and capacity limits using the normalized shape book.
- [x] 2.5 Implement priced `calibrate_vol` scale selection with bounded deterministic candidate walks, not post-cost linear extrapolation.
- [x] 2.6 Implement `fixed_scale` application and fail-closed behavior for final executable book breaches.

## 3. Quick-Run Foundation And Economics

- [x] 3.1 Wire risk-budget sizing into `build_portfolio_foundation` before scenario walks.
- [x] 3.2 Reuse the calibrated/fixed `book_scale` across realistic-cost, cost-stress, and fill-stress scenarios.
- [x] 3.3 Report capacity-bound calibration as `PortfolioSizingReport.capacity_bound`, not as a feasibility failure.
- [x] 3.4 Keep genuine unpriced, unsupported, missing, under-sampled, cost-floor, financing, leverage, and final-book capacity breaches fail-closed.
- [x] 3.5 Update quick-run economics so ledger `weight` and returns are derived from final executable sized weights.

## 4. Validation And Evaluation

- [x] 4.1 Pass `RiskBudgetConfig` through validation execution specs and the validation spine backend.
- [x] 4.2 Enforce `fixed_scale` for validation evidence and reject recalibration in validation configs.
- [x] 4.3 Pass `RiskBudgetConfig` through evaluation execution specs, backend protocol, and spine backend.
- [x] 4.4 Enforce `fixed_scale` for evaluation fold evidence and reject fold-level recalibration.
- [x] 4.5 Expose sizing reports on validation/evaluation result objects and evaluation metrics artifacts.

## 5. Payloads, Artifacts, And Retainability

- [x] 5.1 Add sizing report payloads to `RunPortfolioFoundation.summary_payload()` and matrix payloads.
- [x] 5.2 Add sizing report fields to `summary.json`, `diagnostics.json`, and any foundation/evaluation manifests that describe scoring evidence.
- [x] 5.3 Update `RunResult.retainability` logic so retainable quick runs require trusted envelope, admissible causality, and a frozen positive `book_scale`.
- [x] 5.4 Keep capacity-bound status separate from retainability reason and feasibility verdicts in result and artifact payloads.

## 6. Active Docs And Specs

- [x] 6.1 Update `AGENTS.md`, `PRD.md`, `FOUNDATION_LOCK.md`, `README.md`, and foundation/consumer docs to state the current shape-plus-risk-budget contract directly.
- [x] 6.2 Remove stale active-doc language that describes emitted targets as final deployable weights.
- [x] 6.3 Document the required `[risk_budget]` schema and Train `calibrate_vol` versus downstream `fixed_scale` workflow.
- [x] 6.4 Add any useful historical rationale to `HISTORY.md`, keeping active docs current-state only.

## 7. Tests And Verification

- [x] 7.1 Add config tests for required `[risk_budget]`, invalid mode-specific fields, and explicit annualization cadence.
- [x] 7.2 Add shape-normalization tests proving global raw target scaling does not change final sized weights or quick-run metrics.
- [x] 7.3 Add `calibrate_vol` tests for hitting target volatility below frontier and reporting capacity-bound frontier sizing above it.
- [x] 7.4 Add `fixed_scale` tests proving validation/evaluation do not recalibrate and fail closed on final-book envelope breaches.
- [x] 7.5 Add payload/artifact tests for `PortfolioSizingReport`, capacity-bound status, and executable economics weights.
- [x] 7.6 Run focused pytest suites for config, portfolio foundation, runner API/CLI, validation, evaluation, and docs.
- [x] 7.7 Run `openspec validate add-risk-budget-sizing --strict`, `openspec validate --all --strict`, `git diff --check`, and `make check`.
