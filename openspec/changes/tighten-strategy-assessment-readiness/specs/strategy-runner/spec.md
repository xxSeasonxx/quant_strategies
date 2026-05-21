## ADDED Requirements

### Requirement: Explicit Assessment Metadata

The strategy runner SHALL expose explicit assessment metadata separately from
the existing success flag so callers can distinguish runner completion, smoke
assessment status, and promotion eligibility.

#### Scenario: Screen run assessment metadata

- **WHEN** a screen-mode run completes without runner errors
- **THEN** the run result and `summary.json` report
  `assessment_status = "screened"`
- **AND** they report `run_completed = true`
- **AND** they report `promotion_eligible = false`

#### Scenario: Validation pass assessment metadata

- **WHEN** a validation-mode run completes and validation gates pass
- **THEN** the run result and `summary.json` report
  `assessment_status = "smoke_passed"`
- **AND** they report `run_completed = true`
- **AND** they report `promotion_eligible = false`

#### Scenario: Validation failure assessment metadata

- **WHEN** a validation-mode run completes but validation gates fail
- **THEN** the run result and `summary.json` report
  `assessment_status = "smoke_failed"`
- **AND** they report `run_completed = true`
- **AND** they report `promotion_eligible = false`

#### Scenario: Runner failure assessment metadata

- **WHEN** a run fails after config validation
- **THEN** the run result and `summary.json` report
  `assessment_status = "runner_failed"`
- **AND** they report `run_completed = true`
- **AND** they report `promotion_eligible = false`

### Requirement: CLI Explicit Repository Root

The strategy runner CLI SHALL allow callers to pass an explicit repository root
for config path resolution and repository-scoped artifacts.

#### Scenario: CLI run uses explicit repository root

- **WHEN** a caller invokes
  `quant-strategies run --repo-root <repo> runs/demo.toml`
- **THEN** the CLI calls the runner with `<repo>` as the effective repository
  root
- **AND** the relative config path resolves under `<repo>`

### Requirement: Strategy Purity Static Enforcement

The repository SHALL enforce pure, flat strategy modules with static tests over
committed strategy files.

#### Scenario: Strategy imports forbidden runner or data packages

- **WHEN** a strategy module under `tested/` or `untested/` imports
  `quant_data`, `quant_strategies.runner`, or `quant_strategies.engine`
- **THEN** the strategy-boundary test fails

#### Scenario: Strategy performs forbidden side-effect calls

- **WHEN** a strategy module under `tested/` or `untested/` calls common file
  writing, subprocess, or network primitives
- **THEN** the strategy-boundary test fails

#### Scenario: Strategy layout remains flat

- **WHEN** a Python strategy implementation is committed below a nested
  directory under `tested/` or `untested/`
- **THEN** the strategy-boundary test fails unless the file is an allowed package
  marker

### Requirement: Signal Decision Row Readiness

The strategy runner SHALL reject emitted signals whose matching decision row was
unavailable after the decision time when availability or ingestion metadata is
present on a row matching the signal's symbol and decision timestamp.

#### Scenario: Matching decision row is available

- **WHEN** a signal decision row contains availability metadata at or before the
  signal decision time
- **THEN** the runner may continue to engine request construction

#### Scenario: Matching decision row is unavailable

- **WHEN** a signal decision row contains availability metadata after the signal
  decision time
- **THEN** the run fails before engine request construction
- **AND** the failure stage identifies data readiness

#### Scenario: No matching readiness metadata exists

- **WHEN** no matching decision row contains availability or ingestion metadata
- **THEN** the readiness check does not block the run

### Requirement: Promotion Discipline Remains Explicit

The strategy runner SHALL NOT mark any current screen or validation output as
promotion eligible.

#### Scenario: Current runner output is smoke evidence only

- **WHEN** any current runner screen or validation run reaches a terminal
  summary
- **THEN** `promotion_eligible` is false
- **AND** documentation states that promotion to `tested/` requires separate
  research evidence beyond a single runner screen or validation output

## MODIFIED Requirements

### Requirement: Stable Summary Schema

The strategy runner SHALL write `summary.json` with the same top-level keys on
successful completion and post-config failure: `strategy_id`, `mode`, `success`,
`status`, `stage`, `message`, `artifacts`, `engine`, `run_completed`,
`assessment_status`, and `promotion_eligible`.

#### Scenario: Successful validation run summary

- **WHEN** a validation run completes and validation gates pass
- **THEN** `summary.json` includes the fixed top-level keys, reports stage
  `completed`, reports status `passed`, reports `engine.passed = true`, reports
  `assessment_status = "smoke_passed"`, and reports
  `promotion_eligible = false`

#### Scenario: Failed validation gates summary

- **WHEN** a validation run completes but validation gates fail
- **THEN** `summary.json` includes the fixed top-level keys, reports stage
  `completed`, reports status `failed`, reports `engine.passed = false`,
  reports `assessment_status = "smoke_failed"`, and reports
  `promotion_eligible = false`

#### Scenario: Completed screen summary

- **WHEN** a screen-mode run completes without runner errors
- **THEN** `summary.json` includes the fixed top-level keys, reports stage
  `completed`, reports status `screened`, does not report screen completion as
  `engine.passed = true`, reports `assessment_status = "screened"`, and reports
  `promotion_eligible = false`

#### Scenario: Failure summary

- **WHEN** a run fails after config validation
- **THEN** `summary.json` includes the fixed top-level keys, reports the failed
  stage, reports `assessment_status = "runner_failed"`, and reports
  `promotion_eligible = false`

#### Scenario: Summary artifact list is accurate

- **WHEN** `summary.json` is written
- **THEN** its `artifacts` list contains only files that exist in the result
  directory at the time the summary is written

### Requirement: Run Manifest Captures Minimal Code Identity

The strategy runner SHALL write `run_manifest.json` for every run that creates a
result directory. The manifest SHALL include best-effort repository identity,
Python version, installed package versions for `quant-strategies`, `quant-data`,
and `pydantic`, internal evaluator evidence schema identity, dirty worktree
hashes when available, and SHA-256 hashes for key artifacts that exist when the
manifest is finalized.

#### Scenario: Completed run writes run manifest

- **WHEN** a run reaches engine evaluation or completion
- **THEN** the result directory contains `run_manifest.json`
- **AND** the manifest includes the config hash, strategy snapshot hash when a
  strategy snapshot exists, strategy input hash when data loading succeeded,
  signal hash when signal generation succeeded, and engine request hash when
  request construction succeeded

#### Scenario: Early failure writes run manifest

- **WHEN** a run fails after creating a result directory but before request
  construction
- **THEN** the result directory contains `run_manifest.json`
- **AND** the manifest hashes the artifacts that exist at the failed stage

#### Scenario: Repository identity is unavailable

- **WHEN** git metadata or package-version lookup is unavailable
- **THEN** the runner still writes `run_manifest.json`
- **AND** the manifest records the unavailable field as null or records a
  non-fatal capture error

#### Scenario: Repository worktree is dirty

- **WHEN** git metadata is available and tracked or untracked files differ from
  the recorded commit outside the generated result directory
- **THEN** `run_manifest.json` records the repository as dirty
- **AND** the manifest includes hashes of the porcelain status and tracked diff
