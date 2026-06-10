# quick-run-portfolio-foundation Specification

## Purpose

Provide diagnostic quick-run portfolio-return foundation metrics for Train
scoring without using the heavier evaluation backend.

## Requirements

### Requirement: Quick run exposes diagnostic portfolio foundation metrics

Completed quick runs SHALL attempt to expose a diagnostic portfolio-return
foundation object in-process on `RunResult`. The foundation SHALL be additive to
the existing trade-level economics object and SHALL be classified as
Train/autoresearch diagnostic evidence only. Foundation unavailability SHALL NOT
invalidate an otherwise completed quick run.

#### Scenario: Completed quick run returns foundation metrics
- **WHEN** `run_config` completes request building and engine evaluation
- **AND** portfolio-foundation construction succeeds
- **THEN** the returned `RunResult` includes a non-null portfolio foundation object
- **AND** the existing `RunResult.economics` trade ledger remains populated
- **AND** the foundation object identifies its evidence class as diagnostic Train evidence

#### Scenario: Foundation failure preserves engine economics
- **WHEN** `run_config` completes request building and engine evaluation
- **AND** portfolio-foundation construction cannot produce diagnostic metrics
- **THEN** the returned `RunResult` still completes with populated `economics`
- **AND** `RunResult.foundation` is `None`
- **AND** `RunResult.evidence.warnings` includes a portfolio-foundation unavailable warning

#### Scenario: Failed quick run omits foundation metrics
- **WHEN** a quick run fails before completed engine evaluation
- **THEN** `RunResult.foundation` is `None`
- **AND** no foundation metrics are written as successful artifacts

### Requirement: Foundation path avoids heavy evaluation dependencies

The quick-run portfolio foundation SHALL compute from normalized quick-run rows
and emitted decisions without importing or calling the evaluation backend. The
quick-run path MUST NOT import `quant_strategies.evaluation`, `vectorbtpro`,
`pandas`, or `numpy` to build foundation metrics.

#### Scenario: Quick-run foundation import wall is preserved
- **WHEN** the quick-run path imports `runner`, `engine`, `core`, and builds
  quick-run economics plus portfolio foundation metrics
- **THEN** `quant_strategies.evaluation`, `vectorbtpro`, `pandas`, and `numpy`
  are absent from imported modules

#### Scenario: Foundation uses quick-run execution rows
- **WHEN** a quick run uses a load window wider than its decision window
- **THEN** foundation metrics are computed from the execution rows needed to fill
  and mark emitted decisions
- **AND** strategy generation remains limited to decision-window rows

### Requirement: Foundation computes scenario portfolio paths once

The foundation SHALL build one causal after-cost portfolio path per configured
foundation scenario and SHALL slice that path into Train subwindows. It MUST NOT
replay strategy generation or rebuild the portfolio path independently for every
subwindow.

#### Scenario: Default scenarios include realistic and cost stress
- **WHEN** a quick run completes with default foundation settings
- **THEN** the foundation includes a realistic-cost scenario
- **AND** the foundation includes a cost-stressed scenario

#### Scenario: Subwindows are derived from the path
- **WHEN** a quick run configures N foundation subwindows within the supported
  1-64 range
- **THEN** each foundation scenario reports N subwindow metric records
- **AND** those records are computed by slicing the scenario's full Train path

#### Scenario: Excessive subwindow count is rejected
- **WHEN** a quick-run config sets `foundation_subwindows` above 64
- **THEN** config loading fails

#### Scenario: Configured max gross exposure controls foundation path admissibility
- **WHEN** a quick-run config sets `foundation_max_gross_exposure` to a value
  greater than or equal to 1.0
- **THEN** the foundation path permits active gross target exposure up to that
  configured limit
- **AND** values below 1.0 are rejected during config loading
- **AND** this setting does not change engine trade-ledger economics

### Requirement: Foundation reports subwindow metric inputs

Each foundation subwindow metric record SHALL report the foundation inputs needed
by downstream Train scoring: return sample count, mean return, return
volatility, effective sample size, Sharpe, Sharpe uncertainty inputs, skew,
kurtosis, DSR inputs, DSR value when computable, total return, max drawdown,
closed-trade count, and max symbol concentration.

#### Scenario: Subwindow metrics include statistical inputs
- **WHEN** a subwindow has finite observed portfolio returns
- **THEN** its metric record includes `return_sample_count`,
  `mean_return`, `return_volatility`, `effective_sample_size`, `sharpe`,
  `sharpe_standard_error`, `skew`, `kurtosis`, `dsr_inputs`, and `dsr`

#### Scenario: Subwindow metrics include gate inputs
- **WHEN** a subwindow contains portfolio path and trade activity
- **THEN** its metric record includes `total_return`, `max_drawdown`,
  `closed_trade_count`, and `max_symbol_concentration`

#### Scenario: Closed trades are counted by exit time
- **WHEN** a trade enters before a subwindow and exits inside that subwindow
- **THEN** it contributes to that subwindow's `closed_trade_count`
- **AND** it does not contribute to the prior subwindow's closed-trade count

### Requirement: Foundation reports full-Train metric inputs

Each foundation scenario SHALL report a compact `full_train` metric record
computed from the same scenario portfolio path used to derive subwindow metrics.
The `full_train` record SHALL include the return-statistic inputs needed by
downstream PSR scoring and minimal gate inputs that require upstream path
accounting. Downstream systems SHALL NOT need raw period-return traces to
calculate a PSR score from foundation statistics.

#### Scenario: Full-Train metric includes statistical inputs
- **WHEN** a scenario has finite observed Train portfolio returns
- **THEN** its `full_train` record includes `return_sample_count`,
  `effective_sample_size`, `mean_return`, `return_volatility`, `sharpe`,
  `sharpe_standard_error`, `skew`, `kurtosis`, and `warnings`
- **AND** those statistics are computed from the scenario's full Train scoring
  path, not from subwindow summaries

#### Scenario: Full-Train metric includes gate inputs
- **WHEN** a scenario contains Train portfolio path and trade activity
- **THEN** its `full_train` record includes `total_return`, `max_drawdown`,
  `closed_trade_count`, and `max_symbol_concentration`

#### Scenario: Foundation artifacts remain compact
- **WHEN** a completed quick run writes foundation metrics
- **THEN** `summary.json["portfolio_foundation"]` includes each scenario's
  compact `full_train` record
- **AND** `diagnostics.json["portfolio_foundation"]` includes each scenario's
  compact `full_train` record and subwindow matrix
- **AND** neither artifact includes full NAV or period-return traces by default

#### Scenario: Full-Train metric is emitted for cost scenarios
- **WHEN** the foundation emits `realistic_costs` and `cost_stress` scenarios
- **THEN** each scenario includes its own `full_train` record computed under
  that scenario's cost multiplier

### Requirement: DSR is explicit about missing inputs

The foundation SHALL compute DSR only when the required inputs are present and
valid. If attempted-trial count, benchmark Sharpe threshold, or statistical
inputs are missing or invalid, the DSR value SHALL be `None` and the metric
record SHALL include a warning reason.

#### Scenario: Missing trial count yields null DSR
- **WHEN** a quick run completes foundation metrics without an attempted-trial count
- **THEN** each affected subwindow reports `dsr` as `None`
- **AND** each affected subwindow reports a warning indicating missing trial count

#### Scenario: Supplied trial count enables DSR
- **WHEN** a quick run supplies attempted-trial count and benchmark Sharpe threshold
- **AND** a subwindow has sufficient finite returns for DSR inputs
- **THEN** that subwindow reports a finite DSR value
- **AND** its `dsr_inputs` include the sample length, effective sample size,
  skew, kurtosis, attempted-trial count, benchmark Sharpe threshold, and
  formula identifier

### Requirement: Default artifacts stay compact and diagnostic

Quick-run foundation artifacts SHALL be compact by default. Default diagnostic
and summary artifacts SHALL include foundation metric summaries, not full
per-period return traces.

#### Scenario: Diagnostic artifacts include compact foundation metrics
- **WHEN** a completed quick run writes default diagnostic artifacts
- **THEN** `summary.json` includes compact foundation metrics
- **AND** `diagnostics.json` includes the foundation metric matrix
- **AND** neither artifact contains the full per-period return trace by default

#### Scenario: Foundation evidence is not promotion authority
- **WHEN** a quick run writes foundation artifacts
- **THEN** the artifacts continue to indicate the run is not promotion eligible,
  paper-trade eligible, or live eligible
