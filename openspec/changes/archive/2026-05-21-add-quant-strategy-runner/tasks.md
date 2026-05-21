## 1. Package Setup

- [x] 1.1 Update `pyproject.toml` so `quant_strategies` is installable from `src/` and exposes `quant-strategies`.
- [x] 1.2 Add the Pydantic dependency for runner config validation.
- [x] 1.3 Add `results/` to `.gitignore` while keeping curated `runs/` configs trackable.
- [x] 1.4 Create the `src/quant_strategies/runner/` package skeleton.

## 2. Config And Strategy Loading

- [x] 2.1 Write tests for valid config parsing, missing required fields, unknown output modes, unsupported data kinds, strategy path escape rejection, and output path escape rejection.
- [x] 2.2 Implement `config.py` with `tomllib` parsing and Pydantic models for run config validation.
- [x] 2.3 Write tests for loading a strategy file with `generate_signals` and rejecting one without it.
- [x] 2.4 Implement `strategy_loader.py` for repository-local file-path imports.
- [x] 2.5 Add a test that `fill_model.price = "quote"` fails clearly when the installed `quant_engine` lacks quote-fill support.

## 3. Data Loading

- [x] 3.1 Write monkeypatched tests for the `bars` adapter with one symbol and multiple symbols.
- [x] 3.2 Write monkeypatched tests for `crypto_perp_funding` and `forex_with_quotes` adapters.
- [x] 3.3 Write a monkeypatched test proving `forex_with_quotes` preserves bid/ask fields for quote fill requests.
- [x] 3.4 Implement `data_loader.py` using public `quant_data.loader` APIs only.
- [x] 3.5 Add empty-data and strict-loader-failure tests that prove the strategy is not called.

## 4. Engine Request And Evaluation

- [x] 4.1 Write tests for converting loaded rows into engine OHLC bars and strategy input rows.
- [x] 4.2 Write tests for zero signals, missing decision bars, and insufficient entry/exit bars.
- [x] 4.3 Write tests for quote fill requests with missing bid/ask fields.
- [x] 4.4 Implement `engine_runner.py` to build `quant_engine.EvaluationRequest` and reject unfillable signals before evaluation.
- [x] 4.5 Implement screen and validate execution through `quant_engine` Python APIs, including evidence generation.

## 5. Artifacts And Public Entrypoints

- [x] 5.1 Write tests for success artifacts and pre-engine failure artifacts.
- [x] 5.2 Write tests proving quote fields survive in `bars.csv` and `request.json` artifacts.
- [x] 5.3 Implement `artifacts.py` to write config, strategy snapshot, bars, signals, request, summaries, evidence, and notes.
- [x] 5.4 Implement `runner.__init__.run_config` as the public Python API.
- [x] 5.5 Implement `cli.py` so `quant-strategies run <config>` delegates to `run_config`.
- [x] 5.6 Add a CLI smoke test that uses monkeypatched data loading and verifies the result directory.

## 6. Documentation And Examples

- [x] 6.1 Add one curated example run config under `runs/`.
- [x] 6.2 Update `README.md` to explain the strategy-file boundary, runner command, config shape, artifact layout, and quote fill dependency.
- [x] 6.3 Update `AGENTS.md` to state that strategy code remains pure while explicit experiments run through the runner package.
- [x] 6.4 Document that `quant_autoresearch` should consume this runner instead of owning a separate harness.

## 7. Verification

- [x] 7.1 Verify dependent `quant_engine` change `add-quote-based-engine-fills` has been implemented before enabling quote-fill configs.
- [x] 7.2 Run `conda run -n quant pytest` in `quant_strategies`.
- [x] 7.3 Run `conda run -n quant pytest` in `quant_engine` to verify the evaluator boundary still passes.
- [x] 7.4 Run `git diff --check`.
- [x] 7.5 Report changed-line counts split across source, tests, docs, and generated/OpenSpec files.
