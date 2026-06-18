## MODIFIED Requirements

### Requirement: Strategies declare a standing signed weight-of-NAV target book
`generate_decisions(rows, params)` SHALL return a causal stream of target
decisions. Each decision SHALL declare, for exactly one instrument and as of a
causal `as_of_time` effective at `decision_time`, a **base target shape** expressed
as a signed weight-like scalar (positive = long, negative = short, `0` = flat).
A base target SHALL be **standing**: it remains the instrument's shape target
until a later decision for that instrument changes it. The foundation SHALL
normalize the emitted base target-book shape and apply the configured risk-budget
sizing policy before it establishes final executable signed weights. A target
SHALL size to a held quantity at its decision bar after foundation sizing and
SHALL be held as that quantity until the next decision for the instrument; the
engine SHALL NOT continuously rebalance to hold a constant weight between
decisions.

#### Scenario: A target sets a signed shape
- **WHEN** a strategy emits a target of `+0.20` for an instrument
- **THEN** the emitted book declares long shape exposure for that instrument
- **AND** the final deployable weight is determined by the foundation sizing policy

#### Scenario: A standing target persists until changed
- **WHEN** a strategy emits a target for an instrument and emits no further decision for it
- **THEN** the shaped position is held until the end of the run without re-trading each bar

#### Scenario: A zero target closes the position
- **WHEN** an instrument holds a non-zero position and the strategy emits a target of `0` for it
- **THEN** the sized book flattens that instrument at the decision

#### Scenario: Held quantity is fixed at the decision bar
- **WHEN** a sized target establishes a position at its decision bar and the mark later moves
- **THEN** the held quantity is unchanged until the next decision for that instrument
- **AND** holding a constant weight requires the strategy to emit explicit rebalancing decisions

### Requirement: Targets are idempotent and same-symbol exposure nets
Re-emitting an instrument's current base target SHALL trade nothing after
foundation sizing. Multiple decisions for one instrument SHALL resolve to a single
netted shaped position equal to the latest effective base target, never an
additive stack of independent tickets. The contract SHALL provide no way to
express additive same-symbol stacking.

#### Scenario: Re-emitting the current target is a no-op
- **WHEN** an instrument's shaped position already equals its target and the strategy emits the same target again
- **THEN** no order is generated and no cost is charged

#### Scenario: Same-symbol decisions net rather than stack
- **WHEN** a strategy emits target `+0.20` and later target `+0.30` for the same instrument
- **THEN** the resulting shape target is `+0.30`, not `+0.50`

#### Scenario: Stacking is structurally inexpressible
- **WHEN** a strategy attempts to increase exposure by emitting repeated targets for one instrument
- **THEN** the engine interprets each as the new total base target, so repeated identical signals cannot accumulate gross exposure

### Requirement: The target-book contract is the single contract for all execution surfaces
The target-book decision contract SHALL be the only strategy decision contract
consumed by the quick-run, validation, and evaluation surfaces. No surface SHALL
define or accept a separate decision shape (for example an `open`-only auto-exit
ticket). All surfaces SHALL pass the emitted base target book through the shared
foundation sizing policy before walking the executable portfolio book.

#### Scenario: Quick run consumes the target book
- **WHEN** a quick run executes a strategy
- **THEN** it interprets the emitted base target book through the shared sizing policy and single accounting book

#### Scenario: Validation and evaluation consume the same contract
- **WHEN** validation or evaluation executes the same strategy
- **THEN** they consume the identical target-book contract
- **AND** no surface translates decisions into a different decision model

#### Scenario: Flat and leveraged shape targets are valid contract inputs
- **WHEN** a strategy emits a `0` flat target or a set of raw shape targets whose gross exceeds `1.0`
- **THEN** the execution surfaces accept them as valid shape decisions rather than rejecting them as unsupported decision semantics
- **AND** final executable exposure beyond the leverage budget is handled by the feasibility verdict after sizing
