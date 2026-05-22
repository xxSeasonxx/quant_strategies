# strategy-runner Specification

## Purpose
TBD - created by archiving change harden-runner-readiness. Update Purpose after archive.
## Requirements
### Requirement: Stable Config Path Resolution

The strategy runner SHALL resolve relative run-config paths against the
effective repository root before reading the config or copying it into a result
directory.

#### Scenario: API caller runs from another cwd

- **WHEN** a caller invokes `run_config("runs/demo.toml", repo_root=<repo>)`
  while the process cwd is outside `<repo>`
- **THEN** the runner loads `<repo>/runs/demo.toml`

#### Scenario: Missing config reports resolved path

- **WHEN** a relative config path cannot be read
- **THEN** the failure message identifies the resolved path that was attempted

### Requirement: Curated Run Config Readiness

The repository SHALL keep committed curated run configs under `runs/` and SHALL
verify that each committed `runs/*.toml` file parses without requiring live data
access.

#### Scenario: Committed configs are parseable

- **WHEN** the test suite validates committed run configs
- **THEN** every `runs/*.toml` file loads through the runner config parser

#### Scenario: Scratch configs remain allowed

- **WHEN** a test or caller passes an explicit scratch config path inside the
  repository
- **THEN** the runner may load it without requiring the file to live under
  `runs/`

### Requirement: Strategy Import Precedes Data Loading

After config validation, the strategy runner SHALL load the configured strategy
file before loading market data.

#### Scenario: Strategy file is invalid

- **WHEN** a run config points to a strategy file that cannot be imported or does
  not expose callable `generate_signals(bars, params)`
- **THEN** the run fails before calling any `quant_data` loader

### Requirement: Raw Strategy Inputs Are Preserved

The strategy runner SHALL write the raw rows passed into `generate_signals` as
`strategy_input_rows.csv` and `strategy_input_rows.jsonl` once data loading
succeeds.

#### Scenario: Funding fields are present

- **WHEN** loaded rows include fields such as `funding_rate`,
  `funding_timestamp`, or `has_funding_event`
- **THEN** `strategy_input_rows.csv` and `strategy_input_rows.jsonl` include
  those fields

#### Scenario: Quote fields are present

- **WHEN** loaded rows include quote fields such as `bid`, `ask`, or `mid`
- **THEN** `strategy_input_rows.csv` and `strategy_input_rows.jsonl` include
  those fields

#### Scenario: JSONL preserves raw value fidelity

- **WHEN** loaded rows include datetimes, booleans, null values, funding fields,
  and quote fields
- **THEN** `strategy_input_rows.jsonl` preserves those values in JSON-compatible
  form without dropping fields

### Requirement: Engine Request Is Preserved Separately

The strategy runner SHALL write the exact internal evaluator request as
`engine_request.json` after request construction succeeds.

#### Scenario: Strategy input contains non-engine fields

- **WHEN** strategy input rows contain fields not accepted by the internal
  evaluator
- **THEN** those fields are omitted from `engine_request.json` but retained in
  `strategy_input_rows.csv` and `strategy_input_rows.jsonl`

#### Scenario: Funding event fields are accepted by the internal evaluator

- **WHEN** strategy input rows contain `funding_timestamp`, `funding_rate`, and
  `has_funding_event`
- **THEN** those fields are preserved in `engine_request.json` for evaluator
  accounting

### Requirement: Signals Are Preserved After Generation

The strategy runner SHALL write `signals.csv` after strategy signal generation
succeeds, before engine request construction.

#### Scenario: Request build fails after signals

- **WHEN** signal generation succeeds but request construction fails
- **THEN** the result directory contains `signals.csv`, `strategy_input_rows.csv`,
  `strategy_input_rows.jsonl`, `summary.json`, and `notes.md`

### Requirement: Stage-Aware Failure Artifacts

The strategy runner SHALL write `summary.json` and `notes.md` for failures after
config validation, and the summary SHALL identify the failed stage.

#### Scenario: Data loading fails

- **WHEN** data loading raises a runner data error
- **THEN** the result directory contains `summary.json` with stage `data_load`
  and `notes.md` with the failure message

#### Scenario: Strategy import fails

- **WHEN** strategy import raises a runner strategy error
- **THEN** the result directory contains `summary.json` with stage
  `strategy_import`, `notes.md` with the failure message, and no data loader is
  called

#### Scenario: Request build fails

- **WHEN** engine request construction raises a runner request-build error
- **THEN** the result directory contains prior-stage artifacts and
  `summary.json` with stage `request_build`

#### Scenario: Engine evaluation fails

- **WHEN** engine evaluation raises a runner evaluation error
- **THEN** the result directory contains all artifacts from prior successful
  stages and `summary.json` with stage `engine_evaluation`

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

### Requirement: Simple Success Artifact Contract

For successful runs, the strategy runner SHALL write `config.toml`,
`strategy_snapshot.py`, `strategy_input_rows.csv`, `strategy_input_rows.jsonl`,
`signals.csv`, `engine_request.json`, `summary.json`, `notes.md`, and
`evidence.json` when evaluator evidence is available.

#### Scenario: Successful validation run

- **WHEN** a validation run completes without runner errors
- **THEN** the result directory contains the simple success artifact set

#### Scenario: Screen mode run

- **WHEN** a screen-mode run completes and evaluator evidence is available
- **THEN** the result directory contains `summary.json`, `notes.md`, and
  `evidence.json`

### Requirement: Conservative Close-Fill Timing Safety

The strategy runner SHALL reject `fill_model.price = "close"` with
`entry_lag_bars = 0` unless `fill_model.allow_same_bar_close_fill = true` is
explicitly set.

#### Scenario: Unsafe close fill config

- **WHEN** a run config sets `fill_model.price = "close"` and
  `entry_lag_bars = 0` without setting `allow_same_bar_close_fill = true`
- **THEN** config validation fails before data loading

#### Scenario: Explicit same-bar close opt-in

- **WHEN** a run config sets `fill_model.price = "close"`, `entry_lag_bars = 0`,
  and `allow_same_bar_close_fill = true`
- **THEN** config validation may succeed

#### Scenario: Future-bar close fill config

- **WHEN** a run config sets `fill_model.price = "close"` and
  `entry_lag_bars >= 1`
- **THEN** config validation may succeed

### Requirement: Strategy Rationale Includes Provenance

Every committed strategy module SHALL include a module docstring with the exact
headings `Source / provenance:`, `Market rationale:`,
`Required observables:`, `Signal rule:`, `Assumptions:`, and `Falsifier:`.

#### Scenario: Tested strategy is documented

- **WHEN** a strategy lives under `tested/`
- **THEN** its module docstring includes the required rationale headings

#### Scenario: Untested strategy is documented

- **WHEN** a strategy lives under `untested/`
- **THEN** its module docstring includes the required rationale headings before
  the strategy is promoted

### Requirement: Engine Validation Is Smoke Evidence

The strategy runner SHALL document that internal evaluator screen and
validation outputs are runner smoke evidence and SHALL NOT present a single
passing run as sufficient evidence for market robustness or promotion.

#### Scenario: Successful run notes are written

- **WHEN** a run completes successfully
- **THEN** `notes.md` identifies the run mode and status without claiming market
  robustness

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

### Requirement: Data Manifest Captures Loaded Row Identity

When data loading succeeds, the strategy runner SHALL write `data_manifest.json`
summarizing the exact rows passed to the strategy. The manifest SHALL include
the configured data kind, dataset when present, requested symbols and window,
row counts by symbol, minimum and maximum timestamp by symbol, the
`strategy_input_rows.jsonl` SHA-256 hash, and simple metadata-field coverage
when availability or ingestion fields are present in loaded rows.

#### Scenario: Data load succeeds

- **WHEN** the runner successfully writes `strategy_input_rows.jsonl`
- **THEN** the result directory contains `data_manifest.json`
- **AND** the manifest includes row counts and timestamp ranges by symbol

#### Scenario: Availability fields are present

- **WHEN** loaded rows include fields such as `available_at`, `bar_ingested_at`,
  `quote_ingested_at`, `funding_ingested_at`, or `joined_refreshed_at`
- **THEN** `data_manifest.json` reports coverage counts for those fields
- **AND** the raw strategy input artifacts preserve those fields

### Requirement: FX Strategy Timing Matches Configured Fill Lag

The FX triangular residual strategy SHALL emit an `as_of_time` that represents
the completed residual observation timestamp and a `decision_time` that is after
the observation can be available. The configured fill model SHALL remain the
only source of entry delay after the decision time in the runner.

#### Scenario: FX residual quote config timing trace

- **WHEN** the FX triangular residual strategy emits a signal from a completed
  residual observation
- **THEN** the tested signal `as_of_time` matches the residual observation
  timestamp
- **AND** the tested signal `decision_time` is no earlier than the observation
  availability timestamp
- **AND** the engine entry timestamp is determined only by the configured
  `fill_model.entry_lag_bars`

### Requirement: Funding Strategy Evidence Is Funding-Aware

When loaded rows include funding event fields, the runner SHALL pass those
fields into the engine request so crypto-perp funding strategy evidence can
include `funding_return` separately from price `gross_return`.

#### Scenario: Crypto funding strategy run notes

- **WHEN** a run uses `data.kind = "crypto_perp_funding"`
- **THEN** generated notes or summary messaging state that supplied funding
  events are included when they fall inside engine-held intervals

#### Scenario: Crypto funding fields reach engine request

- **WHEN** loaded rows include `funding_timestamp`, `funding_rate`, and
  `has_funding_event`
- **THEN** `engine_request.json` preserves those fields for internal evaluator
  accounting

### Requirement: Runner Is The Only Supported Experiment Execution Path

Configured strategy experiments SHALL evaluate through
`quant_strategies.runner.run_config` or the `quant-strategies run` CLI. External
first-party projects SHALL NOT bypass the runner by calling raw evaluator APIs
or shelling a raw engine CLI.

#### Scenario: Autoresearch evaluates a configured run

- **WHEN** `quant_autoresearch` evaluates a strategy attempt
- **THEN** it calls `quant_strategies.runner.run_config` or the
  `quant-strategies run` CLI with a TOML run config
- **AND** the attempt receives runner-managed artifacts, notes, summaries, and
  manifests

#### Scenario: Raw engine CLI is unavailable

- **WHEN** first-party workflows are searched
- **THEN** they do not invoke `quant-engine screen` or `quant-engine validate`

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

### Requirement: Signal Data Availability Readiness

The strategy runner SHALL reject emitted signals whose declared as-of row was
unavailable after the decision time when `available_at` metadata is present.
When a signal includes `as_of_time`, that timestamp identifies the completed row
used by the signal; otherwise the signal's `decision_time` is used as the as-of
timestamp. Ingestion and refresh timestamps are audit metadata and SHALL NOT be
treated as historical market availability.

#### Scenario: Matching as-of row is available

- **WHEN** a signal as-of row contains `available_at` metadata at or before the
  signal `decision_time`
- **THEN** the runner may continue to engine request construction

#### Scenario: Matching as-of row is unavailable

- **WHEN** a signal as-of row contains `available_at` metadata after the signal
  `decision_time`
- **THEN** the run fails before engine request construction
- **AND** the failure stage identifies data readiness

#### Scenario: Signal declares completed as-of row

- **WHEN** a signal includes `as_of_time` at or before `decision_time`
- **THEN** the runner checks the row matching the signal symbol and `as_of_time`
- **AND** it does not reject the signal because the later decision-time row has
  not yet become available

#### Scenario: No matching readiness metadata exists

- **WHEN** no matching as-of row contains `available_at` metadata
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
