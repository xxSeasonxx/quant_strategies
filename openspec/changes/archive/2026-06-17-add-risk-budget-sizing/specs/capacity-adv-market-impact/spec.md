## ADDED Requirements

### Requirement: Calibration frontier is sizing information
The foundation SHALL report feasible calibration frontiers as sizing information,
not as fail-closed capacity verdicts. When a `calibrate_vol` run computes a
feasible frontier below the requested volatility, the foundation SHALL report the
binding capacity or leverage dimension as sizing information rather than as a
fail-closed capacity verdict, provided the final frontier-sized executable book
itself is feasible.

#### Scenario: Frontier-bound calibration reports capacity bound
- **WHEN** the requested risk budget requires a scale above the capacity or leverage frontier
- **THEN** the foundation sizes to the frontier
- **AND** the sizing report identifies `capacity_bound = true` and the binding dimension
- **AND** the capacity feasibility verdict remains feasible for the final sized book

#### Scenario: Frontier report includes maximum feasible volatility
- **WHEN** calibration is capacity-bound
- **THEN** the sizing report includes `max_feasible_volatility`
- **AND** downstream consumers can distinguish under-capacity from an unpriced capacity failure

## MODIFIED Requirements

### Requirement: Executed deltas produce capacity execution events
The shared netted portfolio book SHALL emit one capacity execution event for each
non-zero final sized executed delta. Each event SHALL carry the symbol, execution
timestamp, event reason, side, fill price, signed delta units, normalized executed
notional, real executed notional at the configured portfolio scale, base
transaction cost, impact cost, total transaction cost, bar notional volume, ADV
notional volume, bar participation, ADV participation, and available decision
metadata.

#### Scenario: Target change records an execution event
- **WHEN** a final sized target decision changes an instrument's net quantity
- **THEN** the book records one execution event for the traded delta
- **AND** the event's notional and costs match the cash update applied to NAV

#### Scenario: Risk-rule flatten records an execution event
- **WHEN** a `RiskRule` flattens a live net position
- **THEN** the flattening trade records a capacity execution event
- **AND** the event reason identifies the risk-rule exit

### Requirement: Participation limits fail closed
The capacity model SHALL enforce frozen maximum bar participation and maximum ADV
participation on final executable sized deltas. If a final execution event
breaches either limit, the run SHALL fail closed with reason
`capacity_limit_breach` and include the breached dimension and observed
participation in the verdict detail. The book SHALL NOT clamp, scale down, split,
or defer a final fixed-scale order to fit the capacity limit.

#### Scenario: Bar participation breach is infeasible
- **WHEN** a final execution event's real notional exceeds the configured maximum bar participation
- **THEN** the run fails closed with `capacity_limit_breach`
- **AND** the order is not resized to fit the bar volume

#### Scenario: ADV participation breach is infeasible
- **WHEN** a final execution event's real notional exceeds the configured maximum ADV participation
- **THEN** the run fails closed with `capacity_limit_breach`
- **AND** the order is not resized to fit ADV

### Requirement: Retained evidence requires a trusted realistic envelope
Quick-run evidence SHALL be retainable only when the scoring envelope is
explicitly declared operator-frozen and passes minimal realism checks. The
envelope includes costs, capacity, the configured leverage budget, and the
configured risk budget. A run MAY still score for diagnostics when the envelope
is not trusted, but it SHALL NOT be retainable.

#### Scenario: Missing envelope provenance is non-retainable
- **WHEN** a quick run omits the operator-frozen envelope declaration
- **THEN** the run is not retainable
- **AND** the retainability reason identifies envelope provenance

#### Scenario: Zero base costs are non-retainable
- **WHEN** a quick run declares zero fee plus zero slippage
- **THEN** the run is not retainable
- **AND** the retainability reason identifies the cost floor

#### Scenario: ADV impact needs positive impact pricing
- **WHEN** a quick run uses `capacity_model.mode = "adv_impact"`
- **AND** `impact_coefficient_bps` is zero
- **THEN** the run is not retainable
- **AND** the retainability reason identifies capacity impact pricing

#### Scenario: Participation limits must be bounded
- **WHEN** a quick run sets bar or ADV participation limits above `1.0`
- **THEN** the run is not retainable
- **AND** the retainability reason identifies participation bounds

#### Scenario: Risk budget must be trusted
- **WHEN** a quick run lacks a valid operator-frozen risk budget
- **THEN** the run is not retainable
- **AND** the retainability reason identifies risk-budget provenance
