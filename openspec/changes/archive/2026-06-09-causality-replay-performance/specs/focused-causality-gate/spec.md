## MODIFIED Requirements

### Requirement: Focused causality exposes pass/fail status without replay-mode vocabulary
When focused causality is selected, focused causality evidence SHALL expose
focused statuses (`passed`, `failed`, `timeout`, `not_run`, or `cache_hit`) and
SHALL NOT require callers to choose or reason about emitted replay or strict
replay. Low-level replay-mode fields MAY remain available for advanced
quick-run debugging and validation/evaluation internals. The recommended
autoresearch quick-run policy is micro replay; focused causality remains an
advanced source-oriented quick-run mode.

#### Scenario: Focused config uses focused vocabulary
- **WHEN** a quick-run config explicitly enables focused causality
- **THEN** it uses focused causality vocabulary
- **AND** it does not require the caller to choose emitted replay or strict replay

#### Scenario: Focused evidence records high-level status
- **WHEN** a focused causality gate completes or uses cache
- **THEN** the result and artifacts record focused causality status
- **AND** they record whether scoring was allowed or rejected under focused mode

### Requirement: Focused causality does not replace validation or evaluation gates
Focused causality evidence SHALL be classified as Train/autoresearch hygiene
evidence. It SHALL NOT claim promotion, validation, or evaluation eligibility by
itself. Validation and evaluation SHALL remain responsible for their configured
causality replay preflight gates.

#### Scenario: Focused pass is not promotion evidence
- **WHEN** a quick run scores a strategy after focused causality passes
- **THEN** the result remains Train/autoresearch evidence only
- **AND** promotion eligibility remains false

#### Scenario: Validation and evaluation replay policy remains separate
- **WHEN** validation or evaluation runs a candidate
- **THEN** their replay preflight behavior is controlled by their own replay configuration
- **AND** focused quick-run evidence does not replace validation or evaluation replay evidence
