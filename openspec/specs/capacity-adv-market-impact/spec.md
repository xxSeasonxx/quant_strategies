# capacity-adv-market-impact Specification

## Purpose
Define the explicit capacity and market-impact envelope for the shared netted
portfolio book. This spec keeps portfolio scale, ADV participation, impact-cost
charging, unsupported FX semantics, and capacity diagnostics auditable across
quick run, validation, and evaluation.
## Requirements
### Requirement: Capacity model is an operator-frozen scoring envelope

Quick-run, validation, and evaluation configs SHALL declare a capacity model
beside the fill, cost, and leverage envelopes. A non-flat traded book SHALL be
scoreable only when capacity is actively priced for the run's data kind. An
explicit capacity-disabled mode MAY exist for profiling, but a run that executes
non-zero notional while capacity is disabled SHALL fail closed with a typed
non-scoreable capacity verdict rather than silently scoring capacity-free.

#### Scenario: Missing capacity envelope is rejected
- **WHEN** a quick-run, validation, or evaluation config omits the capacity model
- **THEN** config loading fails before strategy execution

#### Scenario: Capacity disabled on a traded book is non-scoreable
- **WHEN** a run declares capacity disabled
- **AND** the book executes non-zero notional
- **THEN** the run fails closed with reason `capacity_unpriced`
- **AND** no scored success is emitted from a capacity-free traded book

#### Scenario: Capacity disabled on a flat book is allowed
- **WHEN** a run declares capacity disabled
- **AND** the book executes no non-zero notional
- **THEN** the run can complete as a flat/no-activity book without capacity impact

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

### Requirement: Impact cost is charged inside the single book walk

For each capacity-priced execution event, the book SHALL compute market impact
from the event's real executed notional and prior ADV notional volume, subtract
the normalized impact cash from the same account that receives base costs and
funding, and derive NAV from that impacted cash path. The book SHALL NOT compute
impact as an after-the-fact reporting adjustment outside the NAV path.

#### Scenario: Impact reduces NAV at execution
- **WHEN** an executed delta has positive ADV participation and a positive impact coefficient
- **THEN** the book subtracts a positive impact cost from cash on the execution bar
- **AND** the period return and final NAV include that impact

#### Scenario: Zero participation produces zero impact
- **WHEN** a run executes no non-zero delta
- **THEN** capacity impact cost is zero
- **AND** capacity diagnostics report zero executed notional and zero participation

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

### Requirement: Unsupported capacity semantics fail closed

Capacity-priced runs SHALL require calibrated notional liquidity semantics for
the run's data kind. `forex_with_quotes` SHALL be unsupported for ADV/impact
capacity pricing until a calibrated notional-volume contract exists, because its
`volume` field is tick-count activity rather than traded notional volume.

#### Scenario: FX capacity pricing is unsupported
- **WHEN** a `forex_with_quotes` run declares ADV/impact capacity pricing
- **THEN** the run fails closed with reason `capacity_unsupported_volume_semantics`
- **AND** it does not treat FX tick count as notional ADV

#### Scenario: Supported bars use notional volume
- **WHEN** a supported bars or crypto-perp run declares ADV/impact capacity pricing
- **THEN** capacity calculations use notional bar volume derived from row volume and price
- **AND** the model records the configured portfolio notional scale used for real-notional conversion

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
