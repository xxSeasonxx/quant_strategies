## ADDED Requirements

### Requirement: Focused causality gate certifies source variants before scoring
The system SHALL provide a focused causality gate for Train/autoresearch
iteration. The focused gate SHALL run when a strategy source variant has no
current focused certification for its cache key. A focused gate pass SHALL allow
the variant to proceed to scoring; a focused gate failure or timeout SHALL reject
the variant before scoring.

#### Scenario: New source hash runs focused gate
- **WHEN** a strategy source hash has no focused certification for the current focused profile
- **THEN** the runner executes the focused causality gate before producing scored quick-run evidence
- **AND** the focused gate result is recorded with the source hash and focused profile version

#### Scenario: Focused pass allows scoring
- **WHEN** the focused causality gate completes with status `passed`
- **THEN** the strategy source variant is eligible for quick-run scoring
- **AND** the quick-run result records focused causality as passed

#### Scenario: Focused failure rejects variant
- **WHEN** the focused causality gate completes with status `failed`
- **THEN** the strategy source variant is rejected before scoring
- **AND** the quick-run result records the focused causality failure reason

#### Scenario: Focused timeout rejects variant
- **WHEN** the focused causality gate exceeds its configured wall-time budget
- **THEN** the strategy source variant is rejected before scoring
- **AND** the quick-run result records focused causality status `timeout`

### Requirement: Focused causality evidence is cached by source-oriented key
The focused gate SHALL cache terminal focused causality evidence by a key
containing at least strategy source hash, strategy id, data kind, normalized
strategy-row hash, validated parameter hash, focused causality profile version,
probe cap, and timeout budget. A cache hit with status `passed` SHALL allow
scoring without rerunning focused replay. A cache hit with status `failed` or
`timeout` SHALL reject the variant without rerunning focused replay unless any
cache-key input changes.

#### Scenario: Passed cache hit skips replay
- **WHEN** a quick run requests focused causality for a source key with cached status `passed`
- **THEN** the runner does not rerun focused replay
- **AND** the quick-run result records focused causality status `passed`
- **AND** the result identifies the evidence as cache-derived

#### Scenario: Failed cache hit rejects variant
- **WHEN** a quick run requests focused causality for a source key with cached status `failed`
- **THEN** the runner rejects the source variant before scoring
- **AND** it does not rerun focused replay

#### Scenario: Profile version change invalidates cache
- **WHEN** the focused causality profile version changes
- **THEN** prior focused gate cache records for older profile versions are not treated as current certification

#### Scenario: Data or focused profile input change invalidates cache
- **WHEN** the normalized strategy-row hash, validated parameter hash, probe cap, or timeout budget changes
- **THEN** prior focused gate cache records for different key inputs are not treated as current certification

### Requirement: Focused causality uses bounded deterministic probes
The focused gate SHALL derive a deterministic bounded probe set from
strategy-visible rows and baseline decisions. The probe set SHALL include
representative emitted-decision probes when available, representative no-signal
probes, and row-grid coverage across early, middle, and late portions of the
sample. If candidate probes exceed the configured cap, the selected probes SHALL
be chosen deterministically from the focused cache key.

#### Scenario: Probe selection is deterministic
- **WHEN** focused causality is run twice with the same source key, rows, decisions, and focused profile
- **THEN** it selects the same probe boundaries in the same order

#### Scenario: Probe cap bounds replay work
- **WHEN** the number of possible focused probes exceeds the configured probe cap
- **THEN** the focused gate runs no more than the configured probe cap
- **AND** the result records the selected probe count and candidate probe count

#### Scenario: Slow focused replay times out
- **WHEN** a focused replay exceeds the configured wall-time budget
- **THEN** the focused gate records status `timeout`
- **AND** the source variant is not eligible for scoring

#### Scenario: Skipped sampled probe rejects focused gate
- **WHEN** a sampled focused probe cannot execute because the strategy raises on the prefix
- **THEN** the focused gate records status `failed`
- **AND** the source variant is not eligible for scoring

#### Scenario: Focused probes include emitted and no-signal coverage
- **WHEN** a strategy emits decisions inside the focused sample
- **THEN** the selected focused probes include representative emitted-decision probes
- **AND** they include representative no-signal probes when no-signal boundaries exist

### Requirement: Focused causality exposes pass/fail status without replay-mode vocabulary
Autoresearch-facing focused causality evidence SHALL expose focused statuses
(`passed`, `failed`, `timeout`, `not_run`, or `cache_hit`) and SHALL NOT require
the strategy-writing LLM to choose or reason about emitted replay or strict
replay. Low-level replay-mode fields MAY remain available for advanced quick-run
debugging and validation/evaluation internals, but focused autoresearch docs and
templates SHALL use focused causality vocabulary.

#### Scenario: Autoresearch config uses focused vocabulary
- **WHEN** an autoresearch-facing quick-run config or template enables the causality gate
- **THEN** it uses focused causality vocabulary
- **AND** it does not require the LLM to choose emitted replay or strict replay

#### Scenario: Focused evidence records high-level status
- **WHEN** a focused causality gate completes or uses cache
- **THEN** the result and artifacts record focused causality status
- **AND** they record whether scoring was allowed or rejected

### Requirement: Focused causality does not replace validation or evaluation gates
Focused causality evidence SHALL be classified as Train/autoresearch hygiene
evidence. It SHALL NOT claim promotion, validation, or evaluation eligibility by
itself. Validation and evaluation SHALL remain responsible for their existing
strict causality preflight gates.

#### Scenario: Focused pass is not promotion evidence
- **WHEN** a quick run scores a strategy after focused causality passes
- **THEN** the result remains Train/autoresearch evidence only
- **AND** promotion eligibility remains false

#### Scenario: Validation and evaluation strict gates remain
- **WHEN** validation or evaluation runs a candidate
- **THEN** their existing strict causality preflight behavior remains required unless a separate spec changes those surfaces
