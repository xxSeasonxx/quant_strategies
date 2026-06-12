## ADDED Requirements

### Requirement: Micro replay evidence controls quick-run retainability

Micro replay MAY remain a scoreable quick-run iteration mode, but it SHALL NOT
make a quick run retainable when micro evidence detects replay violations,
times out, skips required probes, or otherwise records incomplete retention
proof. The result SHALL surface a typed retainability reason for the failed
causality dimension.

#### Scenario: Micro replay violation is non-retainable
- **WHEN** a quick run uses `causality_check = "micro"`
- **AND** micro replay records a hidden-lookahead or determinism violation
- **THEN** the run is not retainable
- **AND** the retainability reason identifies causality

#### Scenario: Micro replay timeout is non-retainable
- **WHEN** a quick run uses `causality_check = "micro"`
- **AND** micro replay times out
- **THEN** the run is not retainable
- **AND** the retainability reason identifies causality timeout

#### Scenario: Strict replay remains retainable when complete
- **WHEN** a quick run uses complete strict replay
- **AND** strict replay verifies deterministic, emitted, and suppression replay
- **THEN** causality satisfies the retainability condition
