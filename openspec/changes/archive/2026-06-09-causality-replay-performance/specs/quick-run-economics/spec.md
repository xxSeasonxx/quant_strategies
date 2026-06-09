## ADDED Requirements

### Requirement: Quick run supports non-blocking micro causality replay
The public quick-run surface SHALL support `output.causality_check = "micro"`
for Train/autoresearch iteration. Micro causality replay SHALL be diagnostic
and SHALL NOT block request building or engine evaluation when micro replay
fails, times out, or is incomplete. A completed quick run under micro replay
MUST expose engine economics when request building and engine evaluation
succeed, even if micro causality evidence is unverified.

#### Scenario: Micro replay pass allows scoring
- **WHEN** a quick-run config selects micro causality
- **AND** micro replay completes without violations
- **THEN** quick run can build the engine request, evaluate the request, and populate quick-run economics
- **AND** the result records micro replay scope and probe metadata

#### Scenario: Micro replay failure still scores
- **WHEN** a quick-run config selects micro causality
- **AND** micro replay detects a replay failure
- **THEN** quick run can still build the engine request, evaluate the request, and populate quick-run economics
- **AND** the result and artifacts mark causality evidence as unverified with the micro replay failure reason

#### Scenario: Micro replay timeout still scores
- **WHEN** a quick-run config selects micro causality
- **AND** micro replay exceeds its configured timeout budget
- **THEN** quick run can still build the engine request, evaluate the request, and populate quick-run economics
- **AND** the result and artifacts mark causality evidence as unverified with timeout metadata

### Requirement: Quick-run micro replay reports probe and timing evidence
When micro causality replay runs, quick-run result objects and artifacts SHALL
record replay scope, selected probe count, candidate probe count when cheap to
know, elapsed seconds, timeout budget, timeout status, replay warning or
failure reason, and whether causality was verified. Micro replay MUST NOT mark
emitted replay or strict replay as verified unless those replay modes actually
ran.

#### Scenario: Micro evidence appears in summary
- **WHEN** a quick run uses micro causality replay and completes engine scoring
- **THEN** `summary.json` records micro replay scope and probe metadata
- **AND** low-level emitted and strict replay verification fields remain false unless those full replay modes actually ran

#### Scenario: Programmatic result carries micro evidence
- **WHEN** a programmatic caller receives a `RunResult` from a micro quick run
- **THEN** the result carries micro causality evidence without requiring artifact scraping

## MODIFIED Requirements

### Requirement: Quick-run causality policy is configurable
The public quick-run config SHALL allow callers to select the causality replay
policy under `[output]` using `causality_check = "off" | "emitted" | "strict" | "focused" | "micro"`.
The default SHALL be `strict` when the field is omitted. The public `run_config`
Python signature SHALL remain unchanged.

#### Scenario: Existing config keeps strict replay
- **WHEN** a quick-run config omits `output.causality_check`
- **THEN** `run_config` runs strict hidden-lookahead replay
- **AND** existing strict evidence semantics are preserved

#### Scenario: Emitted replay mode is selected from config
- **WHEN** a quick-run config sets `output.causality_check = "emitted"`
- **THEN** `run_config` verifies deterministic full replay and emitted-decision replay
- **AND** it does not require strict no-emission replay to complete the run

#### Scenario: Micro replay mode is selected from config
- **WHEN** a quick-run config sets `output.causality_check = "micro"`
- **THEN** `run_config` runs micro causality replay as non-blocking diagnostic evidence
- **AND** engine scoring is controlled by request-building and engine-evaluation success, not by micro replay pass/fail status

#### Scenario: Replay can be explicitly disabled for profiling
- **WHEN** a quick-run config sets `output.causality_check = "off"`
- **THEN** `run_config` skips hidden-lookahead replay
- **AND** the result and artifacts mark causality replay as unverified

#### Scenario: Invalid causality mode is rejected
- **WHEN** a quick-run config sets `output.causality_check` to an unsupported value
- **THEN** config loading fails with a clear validation error before strategy execution

### Requirement: Quick-run focused causality preserves existing low-level replay modes
Existing explicit quick-run causality modes SHALL remain supported for advanced
or audit callers. Adding micro causality SHALL NOT remove support for explicit
`off`, emitted replay, strict replay, strict probe limits, or focused replay.
Micro causality SHALL be the recommended Train/autoresearch policy, while
validation and evaluation remain the survivor evidence surfaces.

#### Scenario: Existing explicit low-level modes remain valid
- **WHEN** an existing quick-run config explicitly selects an existing low-level causality mode
- **THEN** the runner preserves the existing behavior for that mode

#### Scenario: Existing focused mode remains valid
- **WHEN** an existing quick-run config explicitly selects focused causality
- **THEN** the runner preserves focused causality behavior and evidence fields

#### Scenario: Autoresearch documentation prefers micro causality
- **WHEN** consumer documentation describes Train/autoresearch quick-run iteration
- **THEN** it presents micro causality as the research-loop policy
- **AND** it directs survivor checks to validation or evaluation instead of requiring the strategy LLM to select emitted, strict, or focused replay
