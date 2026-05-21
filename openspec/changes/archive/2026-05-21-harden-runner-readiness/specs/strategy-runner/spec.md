## ADDED Requirements

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
success and post-config failure: `strategy_id`, `mode`, `success`, `status`,
`stage`, `message`, `artifacts`, and `engine`.

#### Scenario: Successful run summary

- **WHEN** a run completes successfully
- **THEN** `summary.json` includes the fixed top-level keys and reports stage
  `completed`

#### Scenario: Failure summary

- **WHEN** a run fails after config validation
- **THEN** `summary.json` includes the fixed top-level keys and reports the
  failed stage

#### Scenario: Summary artifact list is accurate

- **WHEN** `summary.json` is written
- **THEN** its `artifacts` list contains only files that exist in the result
  directory at the time the summary is written

### Requirement: Simple Success Artifact Contract

For successful runs, the strategy runner SHALL write `config.toml`,
`strategy_snapshot.py`, `strategy_input_rows.csv`, `strategy_input_rows.jsonl`,
`signals.csv`, `engine_request.json`, `summary.json`, `notes.md`, and
`evidence.json` when engine evidence is available.

#### Scenario: Successful validation run

- **WHEN** a validation run completes without runner errors
- **THEN** the result directory contains the simple success artifact set

#### Scenario: Screen mode run

- **WHEN** a screen-mode run completes and engine evidence is available
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
