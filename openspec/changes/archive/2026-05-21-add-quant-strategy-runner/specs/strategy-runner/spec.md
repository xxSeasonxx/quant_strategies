## ADDED Requirements

### Requirement: Config-driven strategy run

The system SHALL run one strategy experiment from an explicit TOML run config
that names the strategy file, strategy id, data source, symbols, date window,
strategy params, fill model, cost model, output directory, and run mode.
The system SHALL validate the parsed config with Pydantic models before loading
data or importing strategy code.
The system SHALL reject output result directories that resolve outside the
`quant_strategies` repository.

#### Scenario: Valid run config is accepted

- **WHEN** the user runs the strategy runner with a TOML config containing all
  required top-level fields and sections
- **THEN** the system validates the parsed config with Pydantic and begins the
  run

#### Scenario: Missing required config field is rejected

- **WHEN** the user runs the strategy runner with a config missing
  `strategy_path`, `strategy_id`, `data`, `fill_model`, `cost_model`, or
  `output`
- **THEN** Pydantic validation fails before loading data or importing the
  strategy

#### Scenario: Unknown run mode is rejected

- **WHEN** the config sets an output mode other than `screen` or `validate`
- **THEN** the system fails before loading data or importing the strategy

#### Scenario: Output directory is outside the repository

- **WHEN** `output.results_dir` resolves outside the `quant_strategies`
  repository
- **THEN** Pydantic validation fails before loading data or importing the
  strategy

### Requirement: File-path strategy loading

The system SHALL load a single strategy module from the configured file path and
require a callable `generate_signals(bars, params)` function.

#### Scenario: Strategy file exports generate_signals

- **WHEN** `strategy_path` points to a Python file with a callable
  `generate_signals`
- **THEN** the system imports the file and calls `generate_signals` with loaded
  bar rows and configured params

#### Scenario: Strategy file is missing generate_signals

- **WHEN** `strategy_path` points to a Python file without a callable
  `generate_signals`
- **THEN** the system records a strategy import failure and does not call the
  engine

#### Scenario: Strategy path is outside the repository

- **WHEN** `strategy_path` resolves outside the `quant_strategies` repository
- **THEN** the system rejects the config before importing the file

### Requirement: Public data-loader adapters

The system SHALL load strategy input rows through public `quant_data.loader`
APIs and SHALL NOT perform data materialization, refresh, backfill, repair, or
raw source joining.

#### Scenario: Generic bars adapter loads one symbol

- **WHEN** the config uses data kind `bars` with one symbol and a valid dataset
- **THEN** the system loads rows through `quant_data.loader.load_bars`

#### Scenario: Generic bars adapter loads multiple symbols

- **WHEN** the config uses data kind `bars` with multiple symbols and a valid
  dataset
- **THEN** the system loads rows through `quant_data.loader.load_universe_bars`

#### Scenario: Crypto funding adapter loads funding observables

- **WHEN** the config uses data kind `crypto_perp_funding`
- **THEN** the system loads rows through
  `quant_data.loader.load_crypto_perp_bars_with_funding`

#### Scenario: FX quotes adapter loads quote observables

- **WHEN** the config uses data kind `forex_with_quotes`
- **THEN** the system loads rows through
  `quant_data.loader.load_fx_bars_with_quotes`

#### Scenario: FX quotes adapter preserves executable quotes

- **WHEN** the config uses data kind `forex_with_quotes` and
  `fill_model.price = "quote"`
- **THEN** the system includes bid and ask fields in the engine request bars for
  quote-based execution

#### Scenario: Unknown data kind is rejected

- **WHEN** the config uses a data kind other than `bars`,
  `crypto_perp_funding`, or `forex_with_quotes`
- **THEN** the system fails before loading data

### Requirement: Strict data windows fail closed

The system SHALL honor configured symbol and date windows and SHALL fail closed
when strict data loading reports missing, stale, unavailable, or out-of-window
data.

#### Scenario: Strict data load fails

- **WHEN** strict data loading raises an availability, freshness, or clean-start
  error
- **THEN** the system records the failure and does not call the strategy

#### Scenario: Empty loaded data is rejected

- **WHEN** the data adapter returns no rows for the configured symbols and
  window
- **THEN** the system records a data failure and does not call the strategy

#### Scenario: Non-strict data load succeeds

- **WHEN** the config explicitly sets strict loading to false and the public
  loader returns rows
- **THEN** the system continues with those returned rows without silently
  changing the requested config

### Requirement: Engine-compatible request building

The system SHALL convert loaded rows and generated signals into a
`quant_engine.EvaluationRequest` containing engine-compatible OHLC bars, signals,
fill model, and cost model.

#### Scenario: Generated signals are fillable

- **WHEN** generated signals have matching decision bars and enough future bars
  for configured entry and exit fills
- **THEN** the system builds an engine request and evaluates it

#### Scenario: No generated signals

- **WHEN** the strategy returns an empty signal list
- **THEN** the system records a failed run and does not call the engine

#### Scenario: Signal decision time is missing from bars

- **WHEN** a generated signal has no matching decision-time bar for its symbol
- **THEN** the system rejects the signal set before engine evaluation

#### Scenario: Signal exit fill is outside available bars

- **WHEN** a generated signal does not have enough future bars for entry and
  exit fills
- **THEN** the system rejects the signal set before engine evaluation

#### Scenario: Quote fill request requires quote fields

- **WHEN** the config uses `fill_model.price = "quote"` and selected entry or
  exit bars lack bid or ask fields
- **THEN** the system rejects the request before or during engine evaluation and
  records the failure

### Requirement: Engine evaluation through Python API

The system SHALL evaluate strategy runs through `quant_engine` Python APIs
rather than by shelling out to the `quant-engine` CLI.

#### Scenario: Screen mode run

- **WHEN** the config output mode is `screen`
- **THEN** the system calls the `quant_engine.screen` API and writes screening
  output

#### Scenario: Validate mode run

- **WHEN** the config output mode is `validate`
- **THEN** the system calls the `quant_engine.validate` API and writes
  validation output

#### Scenario: Validation gates fail

- **WHEN** `quant_engine.validate` returns failed gates
- **THEN** the system records the failed validation as a completed run rather
  than a crash

### Requirement: Deterministic run artifacts

The system SHALL write one result directory per run containing enough artifacts
to reproduce and audit the engine request.

#### Scenario: Successful validation run writes artifacts

- **WHEN** a validate-mode run completes
- **THEN** the result directory contains `config.toml`, `strategy_snapshot.py`,
  `bars.csv`, `signals.csv`, `request.json`, `screen_summary.json`,
  `validate_summary.json`, `evidence.json`, and `notes.md`

#### Scenario: Quote fields are reproducible from artifacts

- **WHEN** a run uses quote-based fills with bid and ask fields in engine bars
- **THEN** `bars.csv` and `request.json` preserve the quote fields needed to
  reproduce the engine request

#### Scenario: Failed pre-engine run writes notes

- **WHEN** a run fails before engine evaluation
- **THEN** the result directory contains `config.toml`, `strategy_snapshot.py`
  when import is possible, and `notes.md` with the failure reason

#### Scenario: Result directory names are unique

- **WHEN** two runs use the same strategy id
- **THEN** the system writes separate timestamped result directories

#### Scenario: Generated results are ignored by git

- **WHEN** the implementation creates generated run artifacts under `results/`
- **THEN** the repository ignores those artifacts by default

### Requirement: Consumer API and CLI

The system SHALL expose the runner through both a Python API and a CLI, with the
CLI delegating to the same implementation used by the Python API.

#### Scenario: Python consumer runs config

- **WHEN** a consumer imports `quant_strategies.runner.run_config` and passes a
  config path
- **THEN** the system executes the same run flow used by the CLI

#### Scenario: CLI runs config

- **WHEN** the user runs `quant-strategies run <config>`
- **THEN** the system executes the run and prints or returns the result
  directory path

#### Scenario: CLI reports failure

- **WHEN** a run fails before or during evaluation
- **THEN** the CLI exits non-zero and points to the run notes when a result
  directory exists
