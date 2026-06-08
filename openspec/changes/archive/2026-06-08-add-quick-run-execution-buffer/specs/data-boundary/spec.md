## ADDED Requirements

### Requirement: Quick-run load windows preserve strict upstream loading
When quick-run config declares execution/load window fields, `quant_strategies`
SHALL load rows through the same strict upstream loader contracts used for the
decision window. The widened load window SHALL NOT relax strictness, repair
rows locally, or change upstream-owned row ordering.

#### Scenario: Buffered bars load remains strict
- **WHEN** a quick-run `bars` config uses `data.load_start` or `data.load_end`
- **THEN** data loading calls the same strict `quant_data` contract loader with the load window
- **AND** it preserves the upstream row order into normalized execution rows

#### Scenario: Buffered crypto funding load remains strict
- **WHEN** a quick-run `crypto_perp_funding` config uses `data.load_start` or `data.load_end`
- **THEN** data loading calls the same strict crypto perp funding loader with the load window for each symbol
- **AND** each row still satisfies the row contract before engine use

### Requirement: Strategy-visible row projection is bounded by the decision window
When the loaded execution rows cover a wider window than the decision window,
the shared execution path SHALL derive a separate strategy-visible row set
bounded by `data.start` and `data.end`. Strategy-input hashes and causality
evidence SHALL be based on that strategy-visible row set.

#### Scenario: Post-window rows are execution-only
- **WHEN** loaded rows include timestamps after `data.end`
- **THEN** those rows are available for engine execution
- **AND** they are excluded from strategy-visible rows and causality replay inputs

#### Scenario: Strategy evidence hash excludes buffer rows
- **WHEN** a quick run writes strategy-input hashes or rows
- **THEN** the hash or rows cover only the decision-window strategy input rows

### Requirement: Load window validation protects decision-window coverage
Quick-run config validation SHALL require any explicit load window to cover the
decision window. The runner MUST reject a load window that starts after
`data.start` or ends before `data.end`.

#### Scenario: Load end before decision end fails
- **WHEN** a quick-run config sets `data.load_end` before `data.end`
- **THEN** config loading fails before data loading

#### Scenario: Load start after decision start fails
- **WHEN** a quick-run config sets `data.load_start` after `data.start`
- **THEN** config loading fails before data loading
