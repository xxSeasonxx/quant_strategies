## MODIFIED Requirements

### Requirement: Quick run exposes retainability separately from completion
The quick-run result SHALL expose whether the scored evidence is retainable for
validation/evaluation. `succeeded` SHALL continue to mean the quick run completed
without a failure stage. `retainable` SHALL mean the completed evidence may be
advanced to retained-candidate validation/evaluation under the foundation
contract.

Retainability SHALL require a completed feasible final sized book,
retention-admissible causality evidence, a trusted operator-frozen envelope, and
a durable sizing report. A quick run that calibrates volatility SHALL be
retainable only when it records the frozen `book_scale` needed for downstream
`fixed_scale` validation and evaluation.

#### Scenario: Feasible trusted strict run is retainable
- **WHEN** a quick run completes with a feasible final sized book
- **AND** causality evidence is retention-admissible
- **AND** the envelope is declared operator-frozen and passes realism checks
- **AND** the sizing report records the final `book_scale`
- **THEN** `RunResult.succeeded` is true
- **AND** `RunResult.retainable` is true

#### Scenario: Completed non-retainable run remains distinguishable
- **WHEN** a quick run completes and scores but fails a retainability condition
- **THEN** `RunResult.succeeded` can remain true
- **AND** `RunResult.retainable` is false
- **AND** the result exposes an actionable retainability reason

#### Scenario: Missing frozen scale is non-retainable
- **WHEN** a quick run completes without a sizing report containing a positive `book_scale`
- **THEN** `RunResult.retainable` is false
- **AND** the retainability reason identifies risk-budget sizing

### Requirement: Retainability reasons are typed and artifacted
When a quick run is not retainable, the result and summary artifact SHALL expose
a typed reason. Reasons SHALL distinguish causality, envelope, risk-budget sizing,
and market-model financing failures rather than collapsing them into a generic
warning.

#### Scenario: Non-retainable result writes reason
- **WHEN** a quick run completes but is not retainable
- **THEN** `RunResult` exposes a retainability reason
- **AND** `summary.json` includes the same reason in a stable field

#### Scenario: Feasible but non-retainable does not imply promotion
- **WHEN** a quick run is not retainable
- **THEN** artifacts continue to indicate no promotion, paper-trade, or live-trade authority

#### Scenario: Capacity-bound calibration is explicit
- **WHEN** a quick run completes with `capacity_bound = true`
- **THEN** retainability remains governed by the configured policy and sizing report
- **AND** the summary artifact exposes the capacity-bound condition separately from the retainability reason
