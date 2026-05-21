# Product Requirements: quant_strategies

## 1. Product Summary

`quant_strategies` is a flat, auditable quantitative strategy library with an
explicit config-driven runner for one run at a time.

The product should let a researcher move from a strategy idea to a reproducible
screen or validation artifact without mixing strategy logic, data access,
engine evaluation, or autonomous research orchestration.

## 2. Current Project Reveal

The inspected repository currently contains:

- Flat strategy files in `tested/` and `untested/`.
- A Python package under `src/quant_strategies/runner/`.
- A CLI entry point, `quant-strategies run <config>`.
- A Python API, `quant_strategies.runner.run_config(config_path)`.
- Pydantic-validated TOML run configs.
- Data adapters that call public `quant_data.loader` APIs.
- Engine request construction and evaluation through `quant_engine`.
- Artifact writing under ignored `results/` directories.
- Focused tests for config validation, strategy loading, data loading, engine
request construction, CLI behavior, and strategy signal rules.

The current strategy contract is:

```python
def generate_signals(bars, params) -> list[dict[str, object]]:
    ...
```

Strategy modules must stay pure: no engine calls, data loading, autonomous
loops, artifact writing, or filesystem side effects.

## 3. Problem Statement

Quant strategy research becomes hard to trust when strategy code, data loading,
backtest execution, run configuration, and artifact generation are mixed
together. That makes it difficult to audit provenance, reproduce results, catch
lookahead errors, or hand work to downstream consumers such as
`quant_autoresearch`.

`quant_strategies` must provide a disciplined research surface where each run is
explicit, deterministic, and inspectable.

## 4. Target Users

- **Primary user: quantitative researcher.** Writes and tests pure strategy
files, creates run configs, inspects results, and decides whether a strategy
remains untested, moves to tested, or is discarded.
- **Secondary user: automation agent.** Creates or edits one strategy file and
one run config, runs the explicit runner, and summarizes generated artifacts.
- **Secondary user: downstream consumer.** Calls the public Python API or CLI
instead of maintaining a duplicate runner harness.

## 5. Goals

- Keep strategy research auditable from thesis to generated evidence.
- Preserve a flat strategy library: one strategy per Python file unless
explicitly approved otherwise.
- Run one explicit experiment from one TOML config.
- Validate configs before importing strategies or loading data.
- Load data only through public `quant_data` APIs.
- Evaluate signals only through `quant_engine`.
- Write deterministic, reviewable run artifacts.
- Support both manual CLI usage and programmatic consumption.
- Make promotion from `untested/` to `tested/` depend on focused tests.

## 6. Non-Goals

- No autonomous strategy selection.
- No strategy registry or plugin framework.
- No paper-trading approval workflow.
- No data materialization, backfill, repair, or source joining in this repo.
- No engine logic inside strategy files.
- No separate runner harness in `quant_autoresearch`.
- No claim that a single passing run proves market robustness.

## 7. Core User Journeys

### 7.1 Researcher Adds a Strategy

1. Add one Python strategy file under `untested/`.
2. Include a rationale docstring with exact provenance, market rationale,
   required observables, signal rule, assumptions, and falsifier sections.
3. Implement `generate_signals(bars, params)`.
4. Add focused tests for signal timing, side, weight, holding period,
   degenerate inputs, and no-lookahead behavior.
5. Create or update one TOML run config under `runs/`.
6. Run `conda run -n quant quant-strategies run <config>`.
7. Inspect `results/<timestamp>-<strategy_id>/`.

### 7.2 Automation Agent Runs an Experiment

1. Create or edit one strategy file.
2. Create or edit one TOML run config.
3. Call `quant_strategies.runner.run_config(...)` or the CLI.
4. Read `notes.md`, `summary.json`, `engine_request.json`, `signals.csv`,
   raw strategy input artifacts, and `evidence.json` when present.
5. Report keep, discard, or crash with file-backed evidence.

### 7.3 Downstream Consumer Integrates Runner

1. Import `run_config` from `quant_strategies.runner`.
2. Pass a repo-local TOML config path.
3. Receive a `RunResult` with success status, result directory, notes path, and
  message.
4. Avoid duplicating config parsing, data loading, engine request building, or
  artifact writing.

## 8. Functional Requirements

### FR1. Strategy File Contract

- Each strategy must be one Python file by default.
- Each strategy must expose callable `generate_signals(bars, params)`.
- The function must return a list of signal dictionaries containing at least:
`symbol`, `decision_time`, `side`, `weight`, and `hold_bars`.
- Strategy code must be pure and deterministic for a given `bars` and `params`
input.
- Strategy files must not load data, call `quant_engine`, write artifacts, start
loops, or read run configs.

### FR2. Strategy Rationale Contract

Each strategy module docstring must include these exact headings:

- `Source / provenance:`
- `Market rationale:`
- `Required observables:`
- `Signal rule:`
- `Assumptions:`
- `Falsifier:`

Provenance must be audit-ready: paper title/authors/year plus DOI, SSRN, or
URL; a web page or repository URL; or an internal note path plus the upstream
paper or web source it cites.

### FR3. Tested and Untested Strategy States

- `untested/` contains strategies still under implementation or validation.
- `tested/` contains strategies with focused behavior tests.
- Moving a strategy from `untested/` to `tested/` requires tests that cover the
strategy's executable rule and edge cases.
- Promotion must not depend on a single favorable backtest result.

### FR4. Run Config Contract

- Curated run configs must be TOML files under `runs/`.
- Explicit scratch configs may be used inside the repository for tests and
experiments.
- A run config must specify:
  - `strategy_path`
  - `strategy_id`
  - `[data]`
  - `[params]`
  - `[fill_model]`
  - `[cost_model]`
  - `[output]`
- `strategy_path` and `output.results_dir` must resolve inside the repository.
- Unsupported data kinds, output modes, malformed TOML, missing fields, path
escapes, and invalid date windows must fail before data loading.

### FR5. Supported Data Kinds

The runner must support these explicit data kinds:

- `bars`: generic OHLC bars through `quant_data.loader.load_bars` or
`load_universe_bars`.
- `crypto_perp_funding`: crypto perpetual bars with funding fields through
`load_crypto_perp_bars_with_funding`.
- `forex_with_quotes`: FX bars with quote fields through
`load_fx_bars_with_quotes`.

Adapters must fail closed in strict mode and must not fabricate missing data.

### FR6. Data Boundary

- This repo may request data and adapt returned rows for strategy inputs.
- This repo must not own data refresh, backfill, repair, catalog maintenance,
source joining, or readiness metadata.
- Any data limitation discovered while running strategies must be documented and
reported upstream to `quant-data`.

### FR7. Engine Boundary

- The runner must convert loaded rows and generated signals into a
`quant_engine.EvaluationRequest`.
- Evaluation must run through `quant_engine` Python APIs.
- Fill models and cost models must be explicit in the TOML config.
- `fill_model.price = "close"` with `entry_lag_bars = 0` must fail validation
unless `fill_model.allow_same_bar_close_fill = true` is explicitly set.
- Quote fills must require bid and ask fields on entry and exit bars.
- Unfillable signals must fail deterministically with notes.

### FR8. CLI

- The installed command must expose:

```bash
conda run -n quant quant-strategies run runs/<config>.toml
```

- Successful runs must print the result directory.
- Failed runs must print either the failure message or the generated `notes.md`
path.

### FR9. Python API

- The public consumer API must remain:

```python
from quant_strategies.runner import run_config

result = run_config("runs/<config>.toml")
```

- `run_config` must return a structured result with success status, result
directory, notes path, and message.
- `quant_autoresearch` must consume this API instead of owning a separate runner
harness.

### FR10. Run Artifacts

Each successful run must write a timestamped directory under `results/` with:

- `config.toml`
- `strategy_snapshot.py`
- `strategy_input_rows.csv`
- `strategy_input_rows.jsonl`
- `signals.csv`
- `engine_request.json`
- `summary.json`
- `notes.md`
- `evidence.json` when engine evidence is available

`strategy_input_rows.csv` is for human inspection. `strategy_input_rows.jsonl`
is for type-faithful downstream consumption. `engine_request.json` must contain
only the fields passed to `quant_engine`.

`summary.json` must keep a stable top-level schema:

- `strategy_id`
- `mode`
- `success`
- `status`
- `stage`
- `message`
- `artifacts`
- `engine`

Failed post-config runs should write as many prior-stage artifacts as are safely
available, plus `summary.json` and `notes.md`.

### FR11. Error Handling

- Config errors stop before data loading.
- Strategy import errors stop before data loading.
- Data errors stop before signal generation.
- Strategy import errors and strategy execution errors produce `notes.md`.
- Zero generated signals fail the run explicitly.
- Signals without matching decision bars fail the run explicitly.
- Missing entry or exit fill bars fail the run explicitly.
- Engine failures are translated into runner errors with useful context.

## 9. Non-Functional Requirements

- **Auditability:** Every run must be explainable from source strategy, config,
raw strategy inputs, signals, engine request, summary, evidence, and notes.
- **Determinism:** Re-running the same config against the same data snapshot and
dependency versions should produce equivalent signals and engine request
semantics.
- **Simplicity:** Prefer explicit files and functions over registries,
discovery loops, or framework behavior.
- **Safety:** Fail closed on invalid config, missing data, path escapes, and
unfillable signals.
- **Maintainability:** Keep runner responsibilities separated across config,
strategy loading, data loading, engine evaluation, artifacts, and CLI modules.
- **Testability:** Favor small synthetic tests and monkeypatched external
loaders over live database tests.
- **Environment consistency:** All Python commands should run through
`conda run -n quant`.

## 10. Success Metrics

- 100% of promoted `tested/` strategies have focused behavior tests.
- 100% of strategy files include audit-ready rationale docstrings.
- 100% of committed run configs validate before data loading.
- 100% of completed runs write the required artifact set and stable
`summary.json` schema.
- 0 known duplicate runner harnesses in downstream `quant_autoresearch`.
- 0 silent fallbacks from strict to non-strict data loading.
- Time from valid run config to inspectable result artifact is under one manual
command.

## 11. Acceptance Criteria

A release or major change is acceptable when:

- `conda run -n quant pytest` passes in this repository.
- CLI smoke usage works for at least one curated config.
- `run_config` works for the same config used by the CLI.
- A config failure produces no data load.
- A data failure produces notes and no signal generation.
- A strategy failure produces notes.
- A successful validation produces all required artifacts.
- Quote-fill runs preserve bid and ask fields in raw strategy input artifacts
and `engine_request.json`.
- Unsafe same-bar close-fill configs fail by default, and explicit opt-in is
tested.
- Documentation reflects any changed behavior, commands, artifact semantics, or
validation interpretation.

## 12. Dependencies

- Python 3.12 or newer.
- `pydantic` for config validation.
- `quant_data` for public data loader APIs and database engine creation.
- `quant_engine` for bars, signals, fill/cost models, screening, validation,
and evidence generation.
- Conda environment `quant` for local Python commands.

## 13. Current Gaps and Risks

- `runs/` is the intended home for curated configs; live success still depends
on available upstream `quant_data` rows for the requested windows.
- Strategy rationale docstrings exist, but each strategy must be checked against
the stricter audit-ready provenance requirement before promotion.
- Live run reliability depends on `quant_data` availability, strict window
coverage, and loader behavior outside this repository.
- Quote-fill behavior depends on installed `quant_engine` support.
- A passing synthetic strategy test does not establish market validity.
- Generated artifacts are ignored under `results/`, so durable research reports
must reference or preserve important result directories deliberately.

## 14. Open Questions

- What is the minimum evidence threshold for moving a strategy from `untested/`
  to `tested/` beyond focused behavior tests?
- Should curated run configs be versioned for every tested strategy, or only for
  strategies with active research interest?
- Should `notes.md` remain free-form, or should it eventually get a stable
  machine-readable companion beyond `summary.json`?
- Should strategy provenance be linted semantically before promotion, beyond
  checking exact docstring headings?
- Should result artifact directories include dependency versions and data
  snapshot metadata?

## 15. Product Principles

- Explicit beats automatic.
- Pure strategy logic beats convenient side effects.
- Failed closed beats silently approximate.
- Auditable artifacts beat transient console output.
- Focused tests beat broad but vague confidence.
