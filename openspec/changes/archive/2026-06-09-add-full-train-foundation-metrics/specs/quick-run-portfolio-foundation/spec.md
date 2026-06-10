## ADDED Requirements

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
