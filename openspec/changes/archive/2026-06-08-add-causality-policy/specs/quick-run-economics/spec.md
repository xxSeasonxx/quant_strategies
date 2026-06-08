## ADDED Requirements

### Requirement: Quick-run causality policy is configurable
The public quick-run config SHALL allow callers to select the causality replay
policy under `[output]` using `causality_check = "off" | "emitted" | "strict"`.
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

#### Scenario: Replay can be explicitly disabled for profiling
- **WHEN** a quick-run config sets `output.causality_check = "off"`
- **THEN** `run_config` skips hidden-lookahead replay
- **AND** the result and artifacts mark causality replay as unverified

#### Scenario: Invalid causality mode is rejected
- **WHEN** a quick-run config sets `output.causality_check` to an unsupported value
- **THEN** config loading fails with a clear validation error before strategy execution

### Requirement: Quick-run strict replay can be bounded
The public quick-run config SHALL support an optional
`output.strict_probe_limit` for strict replay. When strict replay is selected and
the derived strict probe count exceeds the limit, the runner SHALL record strict
suppression evidence as capped or incomplete unless every required strict probe
actually ran.

#### Scenario: Strict probe limit caps evidence
- **WHEN** `output.causality_check = "strict"` and the strict boundary count exceeds `output.strict_probe_limit`
- **THEN** the run does not report strict suppression replay as fully verified
- **AND** the result and artifacts record that strict replay was capped or incomplete

#### Scenario: Strict probe limit does not affect emitted mode
- **WHEN** `output.causality_check = "emitted"` and `output.strict_probe_limit` is present
- **THEN** the runner ignores the strict probe limit for replay execution
- **AND** emitted replay evidence is determined only by deterministic and emitted-decision replay

#### Scenario: Invalid strict probe limit is rejected
- **WHEN** a quick-run config sets `output.strict_probe_limit` to an invalid value
- **THEN** config loading fails with a clear validation error before strategy execution

### Requirement: Quick-run causality evidence is reported by replay dimension
The public quick-run result and runner artifacts SHALL report deterministic
replay, emitted-decision replay, and strict suppression replay as separate
evidence dimensions. Summary compatibility fields MAY remain, but they MUST NOT
mark strict suppression replay as verified unless strict no-emission replay
completed without skipped or capped required probes.

#### Scenario: Emitted-only evidence is distinguishable
- **WHEN** a quick run completes with `output.causality_check = "emitted"`
- **THEN** `RunResult.evidence.causality` reports deterministic replay verified
- **AND** it reports emitted-decision replay verified
- **AND** it reports strict suppression replay not verified

#### Scenario: Strict evidence is distinguishable
- **WHEN** a quick run completes strict replay without skipped or capped required probes
- **THEN** `RunResult.evidence.causality` reports deterministic replay verified
- **AND** it reports emitted-decision replay verified
- **AND** it reports strict suppression replay verified

#### Scenario: Artifact payloads preserve evidence dimensions
- **WHEN** a quick run writes `summary.json`, `data_manifest.json`, or diagnostic artifacts
- **THEN** those artifacts expose the selected causality policy and the replay evidence dimensions
- **AND** emitted-only, off, capped, and complete-strict runs are distinguishable from artifacts alone

### Requirement: Quick-run engine evaluation can complete under emitted replay
When `output.causality_check = "emitted"` and deterministic plus emitted replay
pass, `run_config` SHALL continue to request building and engine evaluation
without requiring strict suppression replay. The resulting economics SHALL remain
Train quick-run evidence and SHALL NOT imply paper, live, promotion, or strict
audit eligibility.

#### Scenario: Emitted replay allows Train quick-run economics
- **WHEN** emitted replay passes for a valid quick-run config
- **THEN** `run_config` can complete engine evaluation and populate typed quick-run economics
- **AND** the result records strict suppression replay as not verified

#### Scenario: Emitted replay failure still blocks engine evaluation
- **WHEN** `output.causality_check = "emitted"` and emitted replay fails
- **THEN** `run_config` fails at the causality stage before request building or engine evaluation

#### Scenario: Replay disabled evidence is not promoted
- **WHEN** `output.causality_check = "off"` and engine evaluation completes
- **THEN** the result and artifacts include causality-unverified warnings
- **AND** promotion or eligibility fields remain false
