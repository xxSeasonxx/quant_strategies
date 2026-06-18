# risk-budget-sizing Specification

## Purpose
TBD - created by archiving change add-risk-budget-sizing. Update Purpose after archive.
## Requirements
### Requirement: Risk budget is a required operator sizing envelope
Quick-run, validation, and evaluation configs SHALL declare `[risk_budget]` beside
the fill, cost, capacity, leverage, and causality envelopes. The risk budget
SHALL own the sizing mode, annualization cadence, and the scalar input required
for that mode. Config loading SHALL fail before strategy execution when the
risk-budget section is missing or invalid.

#### Scenario: Missing risk budget is rejected
- **WHEN** a quick-run, validation, or evaluation config omits `[risk_budget]`
- **THEN** config loading fails before strategy execution

#### Scenario: Invalid mode-specific fields are rejected
- **WHEN** `[risk_budget].mode = "calibrate_vol"` omits a positive `target_volatility`
- **THEN** config loading fails before strategy execution
- **WHEN** `[risk_budget].mode = "fixed_scale"` omits a positive `book_scale`
- **THEN** config loading fails before strategy execution

#### Scenario: Annualization cadence is explicit
- **WHEN** a config declares `[risk_budget]`
- **THEN** it declares a positive `annualization_periods_per_year`
- **AND** the foundation records that cadence in the sizing report

### Requirement: Strategy-emitted targets are normalized as a shape book
The foundation SHALL interpret emitted target values as base shape weights rather
than final deployable weights. Before sizing, it SHALL derive a normalized shape
book by applying standing-target semantics over the decision stream and dividing
all non-zero raw targets by the maximum intended raw gross exposure observed over
the decision timeline. This normalization SHALL remove arbitrary global scale
while preserving signs, relative allocation, time-varying gross engagement, flat
periods, same-symbol netting, and idempotence.

#### Scenario: Global scale is removed
- **WHEN** two strategies emit identical target streams except every non-zero target in one stream is multiplied by a positive constant
- **THEN** their normalized shape books are identical
- **AND** `calibrate_vol` produces the same final executable target weights, subject to numeric tolerance

#### Scenario: Time-varying engagement is preserved
- **WHEN** a strategy emits a raw book whose intended gross is lower on some bars than its maximum raw gross
- **THEN** the normalized shape book preserves that lower relative engagement
- **AND** it does not normalize every active bar to full gross exposure

#### Scenario: Flat shape remains flat
- **WHEN** the emitted decision stream never creates non-zero intended gross exposure
- **THEN** the normalized shape book remains flat
- **AND** the run does not fabricate exposure to satisfy the risk budget

### Requirement: Volatility calibration sizes the book inside the foundation
When `[risk_budget].mode = "calibrate_vol"`, the foundation SHALL choose the final
book scale from the normalized shape, requested annualized volatility, leverage
budget, capacity envelope, cost model, fill model, and market-impact model. It
SHALL walk and score the final executable sized book after costs, slippage,
capacity impact, funding, and mark-to-market are applied.

#### Scenario: Target volatility is reached below the frontier
- **WHEN** the normalized shape can reach the requested annualized volatility without breaching leverage or capacity limits
- **THEN** the foundation records a positive `book_scale`
- **AND** the final realistic-cost sized book reports deployed annualized volatility within the configured tolerance of the target
- **AND** all reported returns and economics derive from that final sized book

#### Scenario: Post-cost calibration is priced
- **WHEN** market-impact or transaction costs are non-zero
- **THEN** the foundation calibrates using priced book walks or an equivalent priced calculation
- **AND** it does not infer deployed volatility solely by linear extrapolation from pre-cost or unit-scale returns

#### Scenario: Same scale is reused for stress scenarios
- **WHEN** a quick run builds realistic, cost-stress, and fill-stress foundation scenarios
- **THEN** the foundation calibrates one `book_scale` for the run
- **AND** each scenario walks the same final sized target book under its scenario frictions

### Requirement: Fixed scale applies frozen sizing without recalibration
When `[risk_budget].mode = "fixed_scale"`, the foundation SHALL apply the
configured `book_scale` to the normalized shape and walk the final executable book
directly. It SHALL NOT use realized returns, volatility, drawdown, or capacity
headroom from that same validation/evaluation window to choose a new scale.
Validation and evaluation SHALL reject `calibrate_vol` for retained-candidate
evidence before walking the book.

#### Scenario: Validation uses frozen scale
- **WHEN** validation runs with `[risk_budget].mode = "fixed_scale"`
- **THEN** it applies the configured `book_scale` to the normalized shape
- **AND** it does not recalibrate to that validation window's realized volatility

#### Scenario: Validation rejects calibration mode
- **WHEN** validation is configured with `[risk_budget].mode = "calibrate_vol"`
- **THEN** config loading fails before strategy execution
- **AND** validation does not choose scale from validation-window evidence

#### Scenario: Evaluation uses frozen scale
- **WHEN** evaluation runs with `[risk_budget].mode = "fixed_scale"`
- **THEN** every fold applies the configured `book_scale` to the normalized shape
- **AND** no fold chooses a different scale from that fold's realized returns or volatility

#### Scenario: Evaluation rejects calibration mode
- **WHEN** evaluation is configured with `[risk_budget].mode = "calibrate_vol"`
- **THEN** config loading fails before strategy execution
- **AND** evaluation does not choose scale from fold-window evidence

#### Scenario: Fixed-scale breach fails closed
- **WHEN** the fixed-scale final executable book breaches leverage, capacity, financing, cost-floor, or sample-scoreability constraints
- **THEN** the run receives the corresponding typed fail-closed feasibility verdict
- **AND** the book is not silently resized to fit

### Requirement: Sizing report is emitted with sized-book evidence
Every completed foundation run SHALL expose a `PortfolioSizingReport` in-process
and in artifacts that contain foundation evidence. The report SHALL identify the
sizing mode, normalization method and scalar, annualization cadence, `book_scale`,
target annualized volatility when configured, deployed annualized volatility,
maximum feasible annualized volatility when known, capacity-bound status, final
intended gross/net exposure, and binding frontier dimensions when any apply.

#### Scenario: Quick-run summary carries sizing report
- **WHEN** a quick run completes foundation scoring
- **THEN** `RunResult.foundation` exposes the sizing report
- **AND** `summary.json` includes the same sizing report fields

#### Scenario: Evaluation metrics carry sizing report
- **WHEN** evaluation completes a scenario
- **THEN** the scenario metrics expose the sizing report used for that fold
- **AND** the reported returns are from the final sized book described by that report

#### Scenario: Raw shape weights are not scored weights
- **WHEN** artifacts expose raw shape weights for audit
- **THEN** they also expose the final executable sized weights or sizing report needed to derive them
- **AND** no scored return or economics field labels raw shape weights as deployable exposure

