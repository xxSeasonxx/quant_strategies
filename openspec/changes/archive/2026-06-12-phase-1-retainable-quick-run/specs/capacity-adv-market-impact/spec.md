## ADDED Requirements

### Requirement: Retained evidence requires a trusted realistic envelope

Quick-run evidence SHALL be retainable only when the scoring envelope is
explicitly declared operator-frozen and passes minimal realism checks. The
envelope includes costs, capacity, and the configured leverage budget, including
the conservative default leverage budget when no `[leverage_budget]` section is
present. A run MAY still score for diagnostics when the envelope is not trusted,
but it SHALL NOT be retainable.

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
