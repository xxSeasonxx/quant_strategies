## ADDED Requirements

### Requirement: Evaluation consumes the target-book contract and one shared accounting model

The evaluation surface SHALL execute strategies through the same target-book
decision contract and the same single causal portfolio book as quick run, with no
open-ticket translation layer that rejects flat or leveraged-intent targets as
unsupported semantics. Evaluation SHALL report a single shared accounting/funding
model identity; the per-asset-class hand-rolled perp-ledger model name SHALL be
retired from the public metric contract, and any validation gate that enumerates
acceptable completed funding models SHALL reflect the single shared model rather
than requiring the removed perp-ledger model. A second backend MAY exist only as an
independent cross-check that must agree with the shared book, never as a divergent
money model the surface routes to by data kind.

#### Scenario: Evaluation accepts the target-book contract
- **WHEN** an evaluation run executes a strategy that emits flat (`0`) or net-or-gross-leveraged targets
- **THEN** the run accepts them through the shared book rather than rejecting them as unsupported decision semantics
- **AND** intended exposure beyond the leverage budget is handled by the feasibility verdict

#### Scenario: The retired perp-ledger model name is absent from the metric contract
- **WHEN** an evaluation run completes for a crypto-perp data kind
- **THEN** its metric payload identifies the single shared accounting model
- **AND** no field reports the removed `project_perp_ledger_v1` model name

#### Scenario: The completed-funding-model gate reflects the single model
- **WHEN** validation checks the completed funding/accounting model of an evaluation run
- **THEN** the gate accepts the single shared model
- **AND** it does not require the removed perp-ledger model identifier
