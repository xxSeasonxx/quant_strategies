# Foundation Surfaces

This is the compact current-state map for what `quant_strategies` accepts and
what it returns. Product intent and ownership boundaries live in `PRD.md`;
agent operating rules live in `AGENTS.md`.

```text
quick run      input: strategy.py + experiment.toml
               output: RunResult + quick-run artifacts

validation run input: candidate strategy.py + validation.toml
               output: ValidationRunResult + validation artifacts

evaluation run input: candidate strategy.py + evaluation.toml
               output: EvaluationRunResult + evaluation artifacts
```

These are the public user surfaces. `quant_strategies.engine` is an internal
execution kernel used by quick-run and validation internals/tests; it is not a
fourth public API.

## Shared Input Contract

Every surface imports one pure strategy file:

```python
generate_decisions(rows, params) -> list[StrategyDecision]
```

`validate_params(params) -> Mapping` is optional for quick runs and required for
validation and evaluation. Strategies inspect only the provided `rows` and
`params`; they do not load data, call engines, write artifacts, or run
background loops.

Rows are loaded through public `quant_data` APIs, normalized at the boundary,
and passed to strategies as plain mapping rows.

## Quick Run

Command:

```bash
conda run -n quant quant-strategies run path/to/experiment.toml
```

Python API:

```python
from quant_strategies.runner import run_config

result = run_config("path/to/experiment.toml")
```

Purpose:

- diagnose one strategy version quickly;
- produce trade-level diagnostic evidence from the internal engine;
- support iteration feedback, not retained-candidate review, variant ranking, or
promotion.

Primary config file: `experiment.toml`.

Important sections:

- top-level `strategy_path`, `strategy_id`, optional `row_contract`;
- `[data]` loaded through `quant_data`;
- `[params]`, `[fill_model]`, `[cost_model]`;
- `[output]` with repo-local generated `results_dir` under `results/`, artifact
profile, and diagnostic sizing.

Output: `RunResult`. The CLI prints the result directory on success.

Common artifacts include `config.toml`, `strategy_snapshot.py`,
`run_manifest.json`, `summary.json`, `environment.json`, `notes.md`,
`data_manifest.json` when data loading is reached, and optional diagnostic or
full-profile artifacts. Completed quick-run `summary.json` files include
`economic_metrics`, a compact summary derived from the engine trade
ledger. Diagnostic-profile runs additionally write `diagnostics.json` with
`economic_slices`.

## Validation Run

Command:

```bash
conda run -n quant quant-strategies validate path/to/candidate/validation.toml
```

Python API:

```python
from quant_strategies.validation import run_validation

result = run_validation("path/to/candidate/validation.toml")
```

Purpose:

- audit retained-candidate evidence integrity across windows and fixed stress
scenarios;
- require `validate_params`;
- run strict row-contract, observation, and hidden-lookahead checks;
- emit an advisory validation decision from the validation policy.

Primary config file: candidate-local `validation.toml`.

Important sections:

- top-level `strategy_path`, `strategy_id`, optional `verdict_source`;
- `[[windows]]`;
- `[data]`, `[params]`, `[fill_model]`, `[cost_model]`;
- `[readiness]`;
- `[output]`;
- `[search_pressure]`, plus optional `[mechanical_thresholds]` and
`[agreement_oracle]`.

Output: `ValidationRunResult`. Validation is mechanical evidence validation,
not research evaluation. Its decision labels are advisory and never authorize
promotion, paper trading, or live trading.

Common artifacts include `validation_config.toml`, `strategy_snapshot.py`,
`decision_records.jsonl`, `data_audit.json`, `backend_runs/summary.json`,
trade-ledger JSONL files, `cost_fill_sensitivity.json`,
`validation_decision.json`, `validation_manifest.json`, `environment.json`, and
`validation_report.md`.

CLI exit codes:


| Exit code | Meaning                                                      |
| --------- | ------------------------------------------------------------ |
| `0`       | validation completed with a non-`mechanical_fail` advisory decision |
| `2`       | validation completed with `mechanical_fail`                  |
| `3`       | data readiness or audit failure                              |
| `1`       | config, infrastructure, artifact, or other execution failure |


## Evaluation Run

Command:

```bash
conda run -n quant quant-strategies evaluate candidate/evaluation.toml
```

Use `--events-jsonl` to stream structured `evaluation_stage` events to stderr.

Python API: `quant_strategies.evaluation.run_evaluation`

```python
from quant_strategies.evaluation import run_evaluation

result = run_evaluation("candidate/evaluation.toml")
```

Python callers that need stage observability can pass `event_sink`.

Purpose:

- evaluate a frozen candidate through a stateless portfolio evidence surface;
- require `validate_params`;
- run strict row-contract and complete causal replay preflight;
- fan out the fixed six-scenario cost/fill matrix per configured window;
- produce VectorBT Pro portfolio, economic, and path evidence.

Evaluation fails before scenario expansion when deterministic, emitted, or
strict suppression replay proof is incomplete. That failure returns
`failure_stage="preflight"` and
`assessment_status="evaluation_preflight_failed"`.

Evaluation is not validation and does not authorize promotion, paper trading, or live trading. Benchmark-relative metrics are deferred.

Primary config file: candidate-local `evaluation.toml`.

Important sections:

- top-level `strategy_path`, `strategy_id`;
- `[[windows]]`;
- `[data]`, `[params]`, `[fill_model]`, `[cost_model]`;
- `[metrics]` with `annualization_periods_per_year`;
- `[output]` with candidate-local `results_dir`.

Output: `EvaluationRunResult`. The CLI prints the result directory on success,
exits `3` for data-load or row-contract failures, and exits `1` for preflight
causality failures.

Control artifacts:


| Artifact                   | Contents                                                                                                                   |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `evaluation_config.toml`   | copied evaluation config                                                                                                   |
| `strategy_snapshot.py`     | copied strategy file                                                                                                       |
| `data_manifest.json`       | per-window data config, row-contract summary, row counts/ranges, normalized row hash, evidence quality, and decision count |
| `evaluation_metrics.json`  | metric semantics and per-scenario portfolio metrics                                                                        |
| `scenario_summary.json`    | scenario counts, statuses, coverage, warnings, and unsupported semantics                                                   |
| `evaluation_manifest.json` | hashes, scenario coverage, table metadata, metric semantics, replayability, provenance, and artifact inventory             |
| `environment.json`         | runtime and package environment, including `pandas`, `pyarrow`, and `vectorbtpro`                                          |
| `notes.md`                 | human-readable evaluation notes                                                                                            |


Detailed trace artifacts are Parquet only and require pyarrow.
There is no JSONL fallback path for evaluation traces.


| Trace artifact                           | Contents                                                                                                                                                 |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tables/portfolio_path.parquet`          | aggregate portfolio value, period return, and drawdown trace rows by `scenario_id`                                                                       |
| `tables/trades.parquet`                  | aggregate trade trace rows by `scenario_id`                                                                                                              |
| `tables/target_positions.parquet`        | aggregate target-position entry/exit events by `scenario_id`, timestamp, and asset; this is target schedule evidence, not realized broker position state |
| `tables/target_exposure_summary.parquet` | aggregate target exposure decision counts and target round-trip turnover by `scenario_id` and asset                                                      |


## What This Project Does Not Decide

- It does not choose which strategy ideas are worth researching, how to mutate
variants, how to rank candidates, or when an auto-research loop should stop.
- It does not acquire, refresh, repair, or join data; `quant_data` owns that.
- It does not produce market proof, statistical proof, paper-trading permission,
live-trading permission, or promotion authority.
- It does not make generated artifacts true by construction; artifacts are
evidence to inspect.
