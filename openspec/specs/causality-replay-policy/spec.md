# causality-replay-policy Specification

## Purpose
Define replay-scope evidence and bounded replay behavior shared by quick run,
validation, and evaluation. This spec lets consumers distinguish micro,
bounded, complete, and skipped replay evidence without inferring from low-level
implementation flags.
## Requirements
### Requirement: Replay evidence exposes replay scope
The system SHALL expose the causality replay scope for quick run, validation,
and evaluation evidence. Supported replay scopes SHALL include `micro`,
`bounded`, `complete`, and `off`. Consumers MUST be able to distinguish bounded
or micro replay from complete replay without inferring from multiple low-level
boolean flags.

#### Scenario: Quick-run replay scope is visible
- **WHEN** a quick run completes with a configured causality replay policy
- **THEN** its result or artifacts identify the replay scope used for causality evidence

#### Scenario: Validation replay scope is visible
- **WHEN** validation completes or fails at replay preflight
- **THEN** validation artifacts identify whether replay scope was `complete` or `bounded`

#### Scenario: Evaluation replay scope is visible
- **WHEN** evaluation completes or fails at replay preflight
- **THEN** evaluation result or provenance identifies whether replay scope was `complete` or `bounded`

### Requirement: Bounded replay is explicitly configured on survivor surfaces
Validation and evaluation SHALL keep complete replay as their default causality
preflight scope. They SHALL support an explicit bounded replay configuration for
large-panel research runs. Bounded replay SHALL record selected probe count,
candidate count when available without full enumeration, elapsed seconds,
timeout budget, timeout status, and replay warnings when applicable.

#### Scenario: Validation defaults to complete replay
- **WHEN** a validation config omits replay-scope configuration
- **THEN** validation runs complete replay preflight

#### Scenario: Evaluation defaults to complete replay
- **WHEN** an evaluation config omits replay-scope configuration
- **THEN** evaluation runs complete replay preflight

#### Scenario: Validation can select bounded replay
- **WHEN** a validation config selects bounded replay
- **THEN** validation uses bounded replay preflight
- **AND** validation artifacts record bounded replay scope and probe metadata

#### Scenario: Evaluation can select bounded replay
- **WHEN** an evaluation config selects bounded replay
- **THEN** evaluation uses bounded replay preflight
- **AND** evaluation result or provenance records bounded replay scope and probe metadata

### Requirement: Micro replay avoids full row-grid enumeration
Micro replay SHALL select a tiny deterministic probe set directly from
normalized rows and emitted decisions. It MUST NOT enumerate, hash, or heap-rank
the full row-grid candidate set before selecting probes.

#### Scenario: Large-panel micro planning is bounded
- **WHEN** micro replay plans probes for a large multi-symbol row panel
- **THEN** planning work is bounded by the configured micro probe cap and cheap row anchors
- **AND** it does not build one candidate per row-grid boundary

#### Scenario: Micro probes include row anchors
- **WHEN** strategy-visible rows are available
- **THEN** micro replay includes representative row-anchor probes from the beginning, middle, and end of the sample when those anchors are distinct

#### Scenario: Micro probes include emitted decisions
- **WHEN** baseline decisions are available
- **THEN** micro replay includes emitted-decision probes up to the configured cap

### Requirement: Replay harness reuses prepared replay state
Replay checks SHALL prepare row visibility, frozen row storage, baseline
decision indexes, and baseline payloads once per replay check. Replay prefix
construction SHALL reuse that prepared state rather than reparsing visibility or
refreezing all replay rows per probe when a safe slice is sufficient.

#### Scenario: Normalized row visibility is not reparsed per probe
- **WHEN** replay runs multiple probes over normalized rows
- **THEN** row visibility parsing is prepared once for the replay check

#### Scenario: Replay prefixes use frozen row storage
- **WHEN** replay constructs a prefix from rows that do not require availability filtering
- **THEN** the prefix can be returned from frozen row storage without refreezing each row

#### Scenario: Availability filtering remains causal
- **WHEN** replay rows have `available_at` later than a probe decision time
- **THEN** replay excludes those rows from the prefix for that probe

### Requirement: Unverified causality is non-scoreable by default
A `causality_check` of `off` runs no look-ahead replay, so the quick run SHALL be
non-scoreable by default — it SHALL fail closed with `failure_stage="causality"`
rather than producing a scored NAV path on unverified look-ahead. Every mode that
runs some replay (`micro`, `emitted`, `focused`, `strict`) SHALL remain scoreable.
The only override SHALL be an operator-frozen `[causality_policy]
allow_unverified_scoring` flag (default `false`); it SHALL NOT be an agent-editable
`[output]` key, so a climbing agent cannot relax the gate.

#### Scenario: Off is non-scoreable by default
- **WHEN** a quick run sets `causality_check = "off"` with default causality policy
- **THEN** the run fails closed with `failure_stage="causality"` and no economics

#### Scenario: An operator override re-admits off to scoring
- **WHEN** `[causality_policy] allow_unverified_scoring = true` and `causality_check = "off"`
- **THEN** the run completes and scores, with causality recorded as unverified

#### Scenario: The override is not agent-editable
- **WHEN** a config places `allow_unverified_scoring` in the `[output]` block
- **THEN** config loading fails
