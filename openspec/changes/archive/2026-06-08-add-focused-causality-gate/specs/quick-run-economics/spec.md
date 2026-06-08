## ADDED Requirements

### Requirement: Quick run supports focused causality for Train iteration
The public quick-run surface SHALL support a focused causality policy for
Train/autoresearch iteration. When focused causality is selected, quick run SHALL
run or reuse focused source-hash certification before engine scoring and SHALL
not require emitted replay or strict replay over the scoring window to complete
the quick run.

#### Scenario: Focused causality allows quick-run scoring
- **WHEN** a quick-run config selects focused causality
- **AND** the focused causality gate passes or has a current passed cache record
- **THEN** quick run can build the engine request, evaluate the request, and populate quick-run economics
- **AND** the result records focused causality evidence

#### Scenario: Focused causality failure blocks quick-run scoring
- **WHEN** a quick-run config selects focused causality
- **AND** the focused causality gate fails or times out
- **THEN** quick run fails before engine scoring
- **AND** the result records the focused causality rejection status

#### Scenario: Focused causality does not require emitted or strict scoring-window replay
- **WHEN** a quick-run config selects focused causality
- **THEN** the runner is not required to run emitted replay or strict replay over the full scoring window
- **AND** artifacts distinguish focused hygiene evidence from emitted or strict replay evidence

### Requirement: Quick-run focused causality preserves existing low-level replay modes
Existing explicit quick-run causality modes SHALL remain supported for advanced
or audit callers. Adding focused causality SHALL NOT remove support for explicit
`off`, emitted replay, strict replay, or strict probe limits. Focused causality
SHALL be the recommended Train/autoresearch policy, while validation and
evaluation remain the robust survivor gates.

#### Scenario: Existing explicit low-level modes remain valid
- **WHEN** an existing quick-run config explicitly selects an existing low-level causality mode
- **THEN** the runner preserves the existing behavior for that mode

#### Scenario: Autoresearch documentation prefers focused causality
- **WHEN** consumer documentation describes Train/autoresearch quick-run iteration
- **THEN** it presents focused causality as the research-loop policy
- **AND** it directs survivor/audit checks to validation or evaluation instead of requiring the strategy LLM to select emitted or strict replay

### Requirement: Quick-run artifacts report focused causality status
When focused causality is selected, quick-run result objects and artifacts SHALL
record focused causality status, source hash, focused profile version, cache
usage, timeout budget, probe counts, focused cache-key inputs, and whether the
run was allowed to score. These fields SHALL be sufficient for a downstream
consumer to reject unscored or rejected variants without reading low-level replay
internals. Focused quick-run artifacts SHALL NOT mark full emitted replay or
strict replay as verified merely because focused sampled probes passed.

#### Scenario: Focused pass appears in summary
- **WHEN** focused causality passes and quick run completes scoring
- **THEN** `summary.json` records focused causality status `passed`
- **AND** it records that scoring was allowed
- **AND** low-level emitted and strict replay verification fields remain false unless those full replay modes actually ran

#### Scenario: Focused reject appears in summary
- **WHEN** focused causality fails or times out before scoring
- **THEN** `summary.json` records the focused causality rejection status
- **AND** it records that scoring was not allowed

#### Scenario: Programmatic result carries focused evidence
- **WHEN** a programmatic caller receives a `RunResult` from a focused quick run
- **THEN** the result carries focused causality evidence without requiring artifact scraping
