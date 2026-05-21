## ADDED Requirements

### Requirement: Run Manifest Captures Minimal Code Identity

The strategy runner SHALL write `run_manifest.json` when a run reaches request
construction or engine evaluation. The manifest SHALL include best-effort
repository identity, Python version, installed package versions for
`quant-strategies`, `quant-data`, and `pydantic`, internal evaluator evidence
schema identity, dirty worktree hashes when available, and SHA-256 hashes for
key artifacts that exist when the manifest is finalized.

#### Scenario: Completed run writes run manifest

- **WHEN** a run reaches engine evaluation or completion
- **THEN** the result directory contains `run_manifest.json`
- **AND** the manifest includes the config hash, strategy snapshot hash when a
  strategy snapshot exists, strategy input hash when data loading succeeded,
  signal hash when signal generation succeeded, and engine request hash when
  request construction succeeded

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

The FX triangular residual strategy SHALL emit a `decision_time` that represents
the completed residual decision timestamp, and the configured fill model SHALL
be the only source of entry delay in the runner.

#### Scenario: FX residual quote config timing trace

- **WHEN** the FX triangular residual strategy emits a signal from a completed
  residual observation
- **THEN** the tested signal `decision_time` matches the intended decision
  timestamp
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

## MODIFIED Requirements

### Requirement: Stable Summary Schema

The strategy runner SHALL write `summary.json` with the same top-level keys on
successful completion and post-config failure: `strategy_id`, `mode`, `success`,
`status`, `stage`, `message`, `artifacts`, and `engine`.

#### Scenario: Successful validation run summary

- **WHEN** a validation run completes and validation gates pass
- **THEN** `summary.json` includes the fixed top-level keys, reports stage
  `completed`, reports status `passed`, and reports `engine.passed = true`

#### Scenario: Failed validation gates summary

- **WHEN** a validation run completes but validation gates fail
- **THEN** `summary.json` includes the fixed top-level keys, reports stage
  `completed`, reports status `failed`, and reports `engine.passed = false`

#### Scenario: Completed screen summary

- **WHEN** a screen-mode run completes without runner errors
- **THEN** `summary.json` includes the fixed top-level keys, reports stage
  `completed`, reports status `screened`, and does not report screen completion
  as `engine.passed = true`

#### Scenario: Failure summary

- **WHEN** a run fails after config validation
- **THEN** `summary.json` includes the fixed top-level keys and reports the
  failed stage

#### Scenario: Summary artifact list is accurate

- **WHEN** `summary.json` is written
- **THEN** its `artifacts` list contains only files that exist in the result
  directory at the time the summary is written

### Requirement: Simple Success Artifact Contract

For completed runs, the strategy runner SHALL write `config.toml`,
`strategy_snapshot.py`, `strategy_input_rows.csv`, `strategy_input_rows.jsonl`,
`data_manifest.json`, `signals.csv`, `engine_request.json`,
`run_manifest.json`, `summary.json`, `notes.md`, and `evidence.json` when engine
evidence is available.

#### Scenario: Successful validation run

- **WHEN** a validation run completes without runner errors
- **THEN** the result directory contains the completed-run artifact set

#### Scenario: Screen mode run

- **WHEN** a screen-mode run completes and engine evidence is available
- **THEN** the result directory contains `summary.json`, `notes.md`,
  `run_manifest.json`, `data_manifest.json`, and `evidence.json`

### Requirement: Engine Validation Is Smoke Evidence

The strategy runner SHALL document that internal evaluator screen and
validation outputs are runner smoke evidence and SHALL NOT present a single
passing run as sufficient evidence for market robustness or promotion. Screen
mode SHALL be labeled as screen completion, not as a validation pass.

#### Scenario: Validation run notes are written

- **WHEN** a validation run completes
- **THEN** `notes.md` identifies the run mode and validation status without
  claiming market robustness

#### Scenario: Screen run notes are written

- **WHEN** a screen-mode run completes
- **THEN** `notes.md` identifies the run as screened without claiming validation
  pass, market robustness, or promotion evidence
