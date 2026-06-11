## ADDED Requirements

### Requirement: Foundation book includes capacity impact in scored NAV

The quick-run portfolio foundation SHALL charge capacity impact inside the same
single netted-book walk that applies target deltas, fees, slippage, funding, and
mark-to-market. Foundation return statistics SHALL be derived from the
capacity-impacted NAV path. Capacity impact SHALL NOT be reported as a separate
post-score adjustment.

#### Scenario: Capacity impact changes the scored path
- **WHEN** a quick run executes a non-zero delta with positive configured impact
- **THEN** the realistic-cost foundation scenario subtracts impact cost on the execution bar
- **AND** its NAV path and Train statistics reflect that impact

#### Scenario: Cost stress preserves capacity semantics
- **WHEN** the foundation builds its cost-stress scenario
- **THEN** the scenario applies the configured fee/slippage stress and the same capacity model
- **AND** it does not drop capacity impact from the stressed book walk

### Requirement: Foundation reports compact capacity diagnostics

Each quick-run foundation scenario SHALL report compact capacity diagnostics
derived from the book's execution events: executed turnover, impact cost, maximum
and mean bar participation, maximum and mean ADV participation, and capacity
verdict detail when a run is infeasible. Default summary and diagnostic artifacts
SHALL remain compact and SHALL NOT write full per-event traces unless a full
artifact profile later requires them.

#### Scenario: Completed capacity-priced run reports capacity diagnostics
- **WHEN** a quick run completes with capacity-priced executed deltas
- **THEN** `RunResult.foundation` and summary diagnostics include turnover, impact cost, and participation aggregates
- **AND** those aggregates are derived from the same execution events that updated NAV

#### Scenario: Capacity infeasibility is distinguishable
- **WHEN** a quick run fails because capacity is unpriced, unsupported, missing, insufficient, or breached
- **THEN** the feasibility verdict names the capacity reason
- **AND** `RunResult.succeeded` is false
