## ADDED Requirements

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

## MODIFIED Requirements

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

### Requirement: Engine Validation Is Smoke Evidence

The strategy runner SHALL document that internal evaluator screen and
validation outputs are runner smoke evidence and SHALL NOT present a single
passing run as sufficient evidence for market robustness or promotion.

#### Scenario: Successful run notes are written

- **WHEN** a run completes successfully
- **THEN** `notes.md` identifies the run mode and status without claiming market
  robustness

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
