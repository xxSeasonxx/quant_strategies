# portfolio-decision-contract Specification

## Purpose
Define the strategy decision contract for causal target-book simulation. This
spec keeps signed weight-of-NAV targets, same-symbol netting, idempotence,
engine-enforced price-path risk rules, and fail-closed portfolio feasibility
semantics explicit.
## Requirements
### Requirement: Strategies declare a standing signed weight-of-NAV target book

`generate_decisions(rows, params)` SHALL return a causal stream of target
decisions. Each decision SHALL declare, for exactly one instrument and as of a
causal `as_of_time` effective at `decision_time`, a **target** expressed as a
**signed weight of NAV** (positive = long, negative = short, `0` = flat/close).
A target SHALL be **standing**: it remains the instrument's target until a later
decision for that instrument changes it. A target SHALL size to a held quantity
at its decision bar and SHALL be held as that quantity until the next decision
for the instrument; the engine SHALL NOT continuously rebalance to hold a constant
weight between decisions.

#### Scenario: A target sets a signed position
- **WHEN** a strategy emits a target of `+0.20` for an instrument
- **THEN** the engine establishes a long position sized to 0.20 of NAV at the decision bar's fill
- **AND** a target of `-0.20` establishes a short position of the same magnitude

#### Scenario: A standing target persists until changed
- **WHEN** a strategy emits a target for an instrument and emits no further decision for it
- **THEN** the position is held until the end of the run without re-trading each bar

#### Scenario: A zero target closes the position
- **WHEN** an instrument holds a non-zero position and the strategy emits a target of `0` for it
- **THEN** the engine flattens that instrument at the decision

#### Scenario: Held quantity is fixed at the decision bar
- **WHEN** a target sizes a position at its decision bar and the mark later moves
- **THEN** the held quantity is unchanged until the next decision for that instrument
- **AND** holding a constant weight requires the strategy to emit explicit rebalancing decisions

### Requirement: Targets are idempotent and same-symbol exposure nets

Re-emitting an instrument's current target SHALL trade nothing. Multiple
decisions for one instrument SHALL resolve to a single netted position equal to
the latest effective target, never an additive stack of independent tickets. The
contract SHALL provide no way to express additive same-symbol stacking.

#### Scenario: Re-emitting the current target is a no-op
- **WHEN** an instrument's position already equals its target and the strategy emits the same target again
- **THEN** no order is generated and no cost is charged

#### Scenario: Same-symbol decisions net rather than stack
- **WHEN** a strategy emits target `+0.20` and later target `+0.30` for the same instrument
- **THEN** the resulting position is `+0.30` of NAV, not `+0.50`

#### Scenario: Stacking is structurally inexpressible
- **WHEN** a strategy attempts to increase exposure by emitting repeated targets for one instrument
- **THEN** the engine interprets each as the new total target, so repeated identical signals cannot accumulate gross exposure

### Requirement: Price-path exits are declared engine-enforced risk rules

The engine SHALL enforce an optional declared `RiskRule` — limited to `stop_loss`,
`take_profit`, and `trailing` thresholds — causally on the instrument's net
position. Thresholds SHALL be evaluated against the bar's **intrabar range**
(high/low), so a barrier pierced intrabar fires even if the close recovered, and the
exit SHALL fill at the barrier level, worsened to the bar open on a gap-through
(`take_profit` SHALL NOT take a gap-favorable bonus). When a single bar touches both
an adverse barrier (`stop_loss`/`trailing`) and `take_profit`, the adverse barrier
SHALL win. A target MAY carry such a `RiskRule`. A fired `RiskRule` SHALL latch the
instrument flat until the strategy emits a new (different) target for it. Exits that
are derivable from data or time (signal reversal, fixed hold horizon) SHALL be
expressed as explicit target decisions, not as `RiskRule` thresholds.

#### Scenario: A stop fires on the intrabar low even when the close recovers
- **WHEN** a long position carries a `stop_loss` and the bar's low pierces the stop level while the close recovers above it
- **THEN** the engine flattens the position at that bar, filling at the stop level (worsened to the bar open on a gap-through)
- **AND** the flatten is attributable to the stop in the result

#### Scenario: A same-bar stop and take-profit resolves to the adverse stop
- **WHEN** a bar touches both the `stop_loss` and `take_profit` levels of a position
- **THEN** the adverse `stop_loss` fires rather than the `take_profit`

#### Scenario: A fired rule latches the instrument flat
- **WHEN** a `RiskRule` has fired and flattened an instrument whose standing target is still non-zero
- **THEN** the engine does not re-enter the instrument on the next bar
- **AND** the instrument re-enters only after the strategy emits a new, different target for it

#### Scenario: Time and signal exits are explicit targets
- **WHEN** a strategy wants to exit after a fixed hold horizon or on a signal reversal
- **THEN** it emits an explicit `0` (or new) target at the appropriate decision time
- **AND** no `RiskRule` is required to express that exit

#### Scenario: Causal stops cannot be self-placed from future data
- **WHEN** a protective stop depends on the realized price path after the decision
- **THEN** the strategy declares a `RiskRule` rather than reading future rows to place the exit itself
- **AND** strategy code that reads post-decision prices to time an exit fails causality replay

### Requirement: The target-book contract is the single contract for all execution surfaces

The target-book decision contract SHALL be the only strategy decision contract
consumed by the quick-run, validation, and evaluation surfaces. No surface SHALL
define or accept a separate decision shape (for example an `open`-only auto-exit
ticket).

#### Scenario: Quick run consumes the target book
- **WHEN** a quick run executes a strategy
- **THEN** it interprets the emitted target book through the single accounting book

#### Scenario: Validation and evaluation consume the same contract
- **WHEN** validation or evaluation executes the same strategy
- **THEN** they consume the identical target-book contract
- **AND** no surface translates decisions into a different decision model

#### Scenario: Flat and leveraged-intent targets are valid contract inputs
- **WHEN** a strategy emits a `0` (flat) target, or a set of targets whose intended gross exceeds 1.0
- **THEN** the execution surfaces accept them as valid decisions rather than rejecting them as unsupported decision shapes
- **AND** intended exposure beyond the leverage budget is handled by the feasibility verdict, not by a translation layer that bans flat or leveraged targets

### Requirement: Decisions remain pure and causal

`generate_decisions` SHALL remain a pure function of `(rows, params)` that emits
the complete decision timeline up front. Each decision SHALL satisfy
`as_of_time <= decision_time`. The contract SHALL NOT expose realized fills, NAV,
or book state to the strategy during a run; within-run realized-state feedback is
out of scope.

#### Scenario: Causal time invariant holds
- **WHEN** a decision sets `as_of_time` after `decision_time`
- **THEN** decision construction is rejected

#### Scenario: Generation is deterministic
- **WHEN** `generate_decisions` is called twice with identical `(rows, params)`
- **THEN** it returns identical decisions

#### Scenario: No within-run book feedback
- **WHEN** a strategy is executed
- **THEN** it receives no realized fills, NAV, or position state mid-run
- **AND** all targets are derived from `rows` and `params` only

### Requirement: Unpriced short financing fails closed

The portfolio book SHALL produce a typed fail-closed feasibility verdict for
intended short exposure in data kinds whose short financing or carry is not
modeled, rather than scoring free borrow/carry. Data kinds with modeled
financing, such as crypto-perp funding, are exempt from this verdict.

#### Scenario: Equity short exposure is unpriced
- **WHEN** a strategy targets a negative weight on an equity or ETF instrument
- **AND** the run has no modeled short-financing term for that data kind
- **THEN** the book fails closed with reason `unpriced_short_financing`
- **AND** no successful score is emitted from free short financing

#### Scenario: FX short exposure is unpriced
- **WHEN** a strategy targets a negative weight on an FX pair
- **AND** the run has no modeled carry or rollover term
- **THEN** the book fails closed with reason `unpriced_short_financing`

#### Scenario: Crypto-perp short exposure remains financed
- **WHEN** a crypto-perp funding run targets a negative weight
- **THEN** the short exposure is not rejected by `unpriced_short_financing`
- **AND** funding remains priced by the shared book

