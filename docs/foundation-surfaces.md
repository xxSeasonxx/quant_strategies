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
Validation and evaluation also require declared decision observations for
candidate-level evidence. Evaluation defaults to at least one observation and
one observed symbol per decision; validation configs can require additional
observation fields.

Rows are loaded through public `quant_data` APIs — the strategy contract loaders
for bars/universe and the derived-join loaders for FX/crypto, all strict —
normalized at the boundary, and passed to strategies as plain mapping rows.
Package metadata bounds the supported upstream data contract as
`quant-data>=0.1.0,<0.2.0`. `quant_data` owns deterministic row ordering and the
causal `available_at` stamp for supplied rows; `quant_strategies` preserves the
supplied row order for strategy input, hashing, and execution and does not sort
rows locally before hashing or execution. `available_at` is an unconditional
hard requirement on every row; causal replay gates valid rows strictly on
`available_at <= decision_time`, and a missing/invalid `available_at` fails the
row contract rather than the lookahead guard.

All three surfaces use one shared decision/spec kernel plus separate
price-evidence paths: quick run and validation use the engine trade-activity
path, while evaluation uses portfolio/NAV evidence through VectorBT Pro for
non-funding data or the project perp ledger for `crypto_perp_funding`.

Path anchoring:

- quick-run relative paths are repo-root-relative;
- validation/evaluation config paths are resolved from the current directory,
  or from `--repo-root` when the CLI flag/API argument is provided;
- after a validation/evaluation TOML is found, its `strategy_path` and
  `output.results_dir` fields are resolved relative to the config directory.

Foundation pre-run verification:

```bash
make check
make check-vectorbtpro-smoke

conda run -n quant python -m pip install -e .
conda run -n quant python -m pip install -e '.[evaluation]' -c constraints/evaluation.txt
conda run -n quant quant-strategies --help
conda run -n quant pytest
conda run -n quant env RUN_VECTORBTPRO_SMOKE=1 pytest tests/test_evaluation_backend.py::test_vectorbtpro_evaluation_backend_real_smoke_if_installed
```

Run `make check` when the local `quant` environment may have stale
console-script metadata. It refreshes the editable install, checks the CLI,
runs the full pytest suite, and runs the real VectorBT Pro evaluation smoke.
The smoke is skipped by default only when the test is invoked without
`RUN_VECTORBTPRO_SMOKE=1`; when enabled, missing `pandas`, `pyarrow`, or
`vectorbtpro` fails the check. Run `make check-vectorbtpro-smoke` directly when
only the real backend smoke matters.
Controlled evaluation runs should install the optional evaluation stack with
`constraints/evaluation.txt`; `pyproject.toml` keeps broad optional dependency
ranges for installability.

## Status And Result Interpretation

The public workflow vocabulary is `run`, `validate`, and `evaluate`.
Implementation labels such as engine screen/gate modes are artifact-level
details, not promotion language.

| Surface | Python status fields | Success condition | Failure interpretation |
| --- | --- | --- | --- |
| Quick run | `RunResult.succeeded`, `RunResult.outcome.completed`, `RunResult.outcome.failure_stage`, `RunResult.outcome.assessment_status` | `result.succeeded` | `outcome.completed` is false, `outcome.failure_stage` names the failed stage, and `outcome.assessment_status` stays diagnostic-only |
| Validation run | `ValidationRunResult.succeeded`, `ValidationRunResult.run_completed`, `ValidationRunResult.failure_stage`, `ValidationRunResult.decision` | `result.succeeded`; `decision.decision` may still be `mechanical_fail` | advisory retained-candidate evidence only |
| Evaluation run | `EvaluationRunResult.succeeded`, `EvaluationRunResult.run_completed`, `EvaluationRunResult.failure_stage`, `EvaluationRunResult.assessment_status` | `result.succeeded` | stateless frozen-candidate evidence only |

Quick-run Python evidence is nested under `RunResult.evidence`, including
`evidence.replayable_from_artifacts`, `evidence.row_contract`,
`evidence.causality.verified`, and `evidence.warnings`. There are no flat
compatibility aliases for the previous runner result fields.

Downstream consumers such as `quant_autoresearch` should use only the public
surface imports:

```python
from quant_strategies.runner import run_config
from quant_strategies.validation import run_validation
from quant_strategies.evaluation import run_evaluation
```

The supported success check is `result.succeeded` for quick run, validation,
and evaluation; validation labels are advisory evidence, and `mechanical_fail`
is not promotion logic. Artifacts are evidence and rerunnable; ranking,
comparison, search memory, stopping rules, and promotion decisions remain
outside this repo.

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

- top-level `strategy_path`, `strategy_id`;
- `[data]` loaded through `quant_data`;
- `[params]`, `[fill_model]`, `[cost_model]`;
- `[output]` with repo-local generated `results_dir` under `results/`, artifact
profile, and diagnostic sizing.

Output: `RunResult`. The CLI prints the result directory on success. Python
callers read terminal status from `result.outcome` and evidence quality from
`result.evidence`.

Common artifacts include `config.toml`, `strategy_snapshot.py`,
`run_manifest.json`, `summary.json`, `environment.json`, `notes.md`,
`data_manifest.json` when data loading is reached, and optional diagnostic or
full-profile artifacts. Completed quick-run `summary.json` files include
`economic_metrics`, a compact summary derived from the engine trade
ledger. Diagnostic-profile runs additionally write `diagnostics.json` with
`economic_slices`.
Failed quick-run `summary.json` files set `run_completed` to `false` and
`failure_stage` to the failed runner stage.

Engine stop-loss, take-profit, and trailing thresholds are sampled threshold
exits: they are evaluated on the configured bar fill price (`close` or `quote`)
at bar timestamps, not as intrabar high/low barrier orders.

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
- reject levered or aggregate-overexposed target-weight evidence before backend
  scenarios;
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

Validation window IDs must be unique and must not collide after artifact-path
sanitization. `[readiness]` requires at least one observation and one observed
symbol per decision by default, plus `required_observation_fields`. For
`crypto_perp_funding`, validation also requires `close`, `funding_timestamp`,
`funding_rate`, and `has_funding_event` observations on every decision.

Output: `ValidationRunResult`. Validation is mechanical evidence validation,
not research evaluation. Its decision labels are advisory and never authorize
promotion, paper trading, or live trading.
Config-load failures return `result_dir=None`, `run_completed=False`, and
`failure_stage="config_load"` instead of raising from the public API.

Common artifacts include `validation_config.toml`, `strategy_snapshot.py`,
`decision_records.jsonl`, `data_audit.json`, `backend_runs/summary.json`,
trade-ledger JSONL files, `cost_fill_sensitivity.json`,
`validation_decision.json`, `validation_manifest.json`, `environment.json`, and
`validation_report.md`. Per-scenario backend summaries always include an
`agreement_oracle` status; the raw `agreement` payload appears only when the
opt-in oracle actually ran.

CLI exit codes:


| Exit code | Meaning                                                      |
| --------- | ------------------------------------------------------------ |
| `0`       | validation completed with a non-`mechanical_fail` advisory decision |
| `2`       | validation completed with `mechanical_fail`                  |
| `3`       | data load, readiness, row-contract, validation-readiness, or audit failure |
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
- run strict row-contract, decision-row data audit, and complete causal replay
  preflight;
- fan out configured `[[scenarios]]` per window, or the default fixed
  six-scenario cost/fill matrix when no custom scenarios are configured;
- produce portfolio, economic, and path evidence through VectorBT Pro for
  non-funding data and `project_perp_ledger_v1` for `crypto_perp_funding`.

Evaluation fails before scenario expansion when the decision-row/observation
dependency audit fails or when deterministic, emitted, or strict suppression
replay proof is incomplete. Data-audit failures return
`failure_stage="data_audit"`; replay-preflight failures return
`failure_stage="preflight"`. Both use
`assessment_status="evaluation_preflight_failed"`.

For `crypto_perp_funding`, evaluation uses a project-owned perpetual futures
ledger. Its NAV path includes price PnL, configured fees/slippage, and funding
cashflows. VectorBT Pro `cash_dividends` is not used for funding because its
contract does not match perp funding cashflows.
Annualized metrics use full-grid portfolio returns from the `portfolio_path`
trace, including flat/no-position bars. The configured
`annualization_periods_per_year` must match the bar cadence; completed runs emit
an advisory `annualization_cadence` summary with warnings for cadence mismatches
or insufficient observed spacing.
Annualized/risk metrics (`annualized_return`, `volatility`, `sharpe`,
`sortino`, and `calmar`) are emitted only when `annualization_cadence.status`
is `ok` and `return_sample_count` meets the minimum return-sample floor,
`[metrics].min_annualized_samples` (default `20`). Any non-ok cadence status or
insufficient samples null that annualized/risk metrics family without nulling
core economics such as `total_return`, `ending_value`, `max_drawdown`,
`return_sample_count`, or `worst_period_return`.
Sortino uses downside semivariance over the full return sample and returns
`None`, not infinity, when undefined.

Engine funding is linear trade-activity funding folded into validation
`net_return`; evaluation funding is NAV-ledger cashflow through the project
perp ledger. Fillable crypto perp windows with no funding events in the open
interval accrue zero funding; flagged funding rows still fail when malformed,
conflicting, or mark-misaligned. hidden-lookahead replay proves point-in-time
causal replay; it does not prove out-of-sample validity and it does not prove
freedom from in-sample fitting.

Evaluation is not validation and does not authorize promotion, paper trading, or live trading.
Benchmark-relative metrics are evidence only: when optional `[benchmark]` is
configured, evaluation reports `benchmark_symbol`, `benchmark_total_return`,
and `excess_total_return` for each scenario without ranking or promotion
authority.

Primary config file: candidate-local `evaluation.toml`.
The checked-in minimal example is
`examples/strategies/simple_momentum_spy_daily_evaluation.toml`.

Important sections:

- top-level `strategy_path`, `strategy_id`;
- `[[windows]]`;
- `[data]`, `[params]`, `[fill_model]`, `[cost_model]`;
- `[metrics]` with `annualization_periods_per_year` and optional
  `min_annualized_samples`;
- optional `[readiness]` for decision observation requirements; defaults to at
  least one observation and one observed symbol per decision;
- optional `[benchmark]` with `symbol`, which must also be present in
  `data.symbols`;
- optional `[[scenarios]]` entries with `id`, labels, `required`, and optional
  nested `[scenarios.cost_model]` / `[scenarios.fill_model]` overrides;
- `[output]` with candidate-local `results_dir`.

Generated output roots `results/`, `validation_results/`, and
`evaluation_results/` are ignored by the repository and should be regenerated
instead of treated as source.

Output: `EvaluationRunResult`. The CLI prints the result directory on success,
exits `3` for data-load, row-contract, or data-audit failures, and exits `1`
for preflight causality failures.

Control artifacts:


| Artifact                   | Contents                                                                                                                   |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `evaluation_config.toml`   | copied evaluation config                                                                                                   |
| `strategy_snapshot.py`     | copied strategy file                                                                                                       |
| `data_manifest.json`       | per-window data config, row-contract summary, data-audit payload, row counts/ranges, normalized row hash, evidence quality, decision count, and audit artifact links |
| `evaluation_metrics.json`  | metric semantics, annualization cadence, evidence-quality warnings, and per-scenario portfolio metrics, including return-sample coverage |
| `scenario_summary.json`    | scenario counts, statuses, coverage, warnings, and unsupported semantics                                                   |
| `evaluation_manifest.json` | hashes, scenario coverage, annualization cadence, audit metadata, table metadata, metric semantics, replayability, provenance, and artifact inventory |
| `audit/input_rows/{safe_window}-{hash}.parquet` | normalized strategy input rows for each evaluation window that reaches strategy execution          |
| `audit/decision_records/{safe_window}-{hash}.jsonl` | typed strategy decisions for each evaluation window that reaches strategy execution             |
| `evaluation_failure.json`  | failure stage, status, message, warnings, unsupported semantics, data windows reached with any data-audit payload, and scenario coverage when failed |
| `environment.json`         | runtime and package environment, including `pandas`, `pyarrow`, and `vectorbtpro` when present                             |
| `notes.md`                 | human-readable evaluation notes                                                                                            |


Normalized row snapshots and detailed trace artifacts are Parquet only and
require pyarrow. There is no JSONL fallback path for evaluation row snapshots
or traces. Decision records are JSONL for direct audit.


| Trace artifact                           | Contents                                                                                                                                                 |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tables/portfolio_path.parquet`          | aggregate portfolio value, period return, and drawdown trace rows by `scenario_id`                                                                       |
| `tables/trades.parquet`                  | aggregate trade trace rows by `scenario_id`                                                                                                              |
| `tables/target_positions.parquet`        | aggregate target-position entry/exit events by `scenario_id`, timestamp, and asset; this is target schedule evidence, not realized broker position state |
| `tables/target_exposure_summary.parquet` | aggregate target exposure decision counts and target round-trip turnover by `scenario_id` and asset                                                      |
| `tables/funding_cashflows.parquet`       | aggregate funding cashflow rows by `scenario_id`, timestamp, and asset; empty but schema-valid for non-funding evaluations                               |


## What This Project Does Not Decide

- It does not choose which strategy ideas are worth researching, how to mutate
variants, how to rank candidates, or when an auto-research loop should stop.
- It does not acquire, refresh, repair, or join data; `quant_data` owns that.
  This repo pins the supported `quant-data` contract range instead of carrying
  local data-materialization compatibility code.
- It does not produce market proof, statistical proof, paper-trading permission,
live-trading permission, or promotion authority.
- It does not make generated artifacts true by construction; artifacts are
evidence to inspect.
