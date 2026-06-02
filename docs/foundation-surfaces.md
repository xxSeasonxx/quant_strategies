# Foundation I/O

This is the first document to read when you need to know what
`quant_strategies` accepts and what it returns. It is factual: it describes the
project surfaces, not Season's broader methodology or promotion policy.

```text
quick run      input: strategy.py + experiment.toml
               output: RunResult + quick-run artifacts

validation run input: candidate strategy.py + validation.toml
               output: ValidationRunResult + validation artifacts

evaluation run input: candidate strategy.py + evaluation.toml
               output: EvaluationRunResult + evaluation artifacts
```

## What It Does

`quant_strategies` turns a pure strategy function plus explicit config into
structured research evidence.

- It loads rows through `quant_data`.
- It passes those rows and params into `generate_decisions(rows, params)`.
- It validates the emitted `StrategyDecision` objects.
- It checks for hidden lookahead and deterministic replay failures.
- It computes trade-level results with the shared engine.
- It writes artifacts that explain what ran, what data was used, what decisions
  were emitted, and what evidence was produced.

The quick run is the fast surface for one strategy version. The validation run
is the advisory surface for a retained candidate across windows and generated
cost/fill scenarios. The evaluation run is the stateless surface for
frozen-candidate portfolio, economic, and path evidence.

## Shared Strategy Input

All surfaces import a single strategy file.

Required for quick run, validation, and evaluation:

```python
generate_decisions(rows, params) -> list[StrategyDecision]
```

Required for validation and evaluation, optional for quick run:

```python
validate_params(params) -> Mapping
```

Strategy files must stay pure: use only the `rows` and `params` passed in; do
not load data, call engines, write artifacts, run autonomous loops, or mutate
inputs. Each strategy module docstring should state thesis, observables, rule,
assumptions, provenance, and falsifier.

Rows are loaded through `quant_data`, normalized at the boundary, and passed to
the strategy as plain mapping rows. Strategies do not receive row model objects.

## Quick Run

Quick run diagnoses one strategy version. It is not validation.

Command:

```bash
conda run -n quant quant-strategies run path/to/experiment.toml
```

Python API:

```python
from quant_strategies.runner import run_config

result = run_config("path/to/experiment.toml")
```

### Quick-Run Config

Minimum shape:

```toml
strategy_path = "examples/strategies/simple_momentum.py"
strategy_id = "simple_momentum"
row_contract = "search"  # optional; "search" default, or "validation"

[data]
kind = "bars"
dataset = "equity_1min"
symbols = ["SPY"]
start = "2024-01-01"
end = "2024-01-31"
strict = true

[params]
weight = 1.0
max_hold_bars = 1

[fill_model]
price = "close"
entry_lag_bars = 1
exit_lag_bars = 0

[cost_model]
fee_bps_per_side = 0.0
slippage_bps_per_side = 0.0

[output]
results_dir = "results"
quick_checks = false
artifact_profile = "diagnostic"
diagnostic_sample_trades = 5
```

Top-level fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `strategy_path` | yes | Strategy file path. Relative paths resolve inside the repo. |
| `strategy_id` | yes | Non-empty run identity. |
| `row_contract` | no | `search` default, or `validation` for stricter row availability. |

`[data]` fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `kind` | yes | `bars`, `crypto_perp_funding`, or `forex_with_quotes`. |
| `dataset` | for `bars` | Dataset name required when `kind = "bars"`. |
| `symbols` | yes | Non-empty list of symbols. |
| `start`, `end` | yes | Inclusive data window dates; `end` must be on or after `start`. |
| `strict` | no | Data-loader strictness, default `true`. |

`[params]` is strategy-specific. The quick run may run without
`validate_params`, but then the result is marked as an unvalidated params
contract.

`[fill_model]` fields:

| Field | Required | Default | Meaning |
| --- | --- | --- | --- |
| `price` | no | `close` | Fill price source: `open`, `close`, or `quote`. |
| `entry_lag_bars` | no | `1` | Bars between decision and entry fill. |
| `exit_lag_bars` | no | `0` | Bars between exit trigger and exit fill. |
| `allow_same_bar_close_fill` | no | `false` | Required if using `price = "close"` with `entry_lag_bars = 0`. |

`[cost_model]` fields:

| Field | Required | Default | Meaning |
| --- | --- | --- | --- |
| `fee_bps_per_side` | no | `0.0` | Fee per side, in basis points. |
| `slippage_bps_per_side` | no | `0.0` | Slippage per side, in basis points. |

`[output]` fields:

| Field | Required | Default | Meaning |
| --- | --- | --- | --- |
| `results_dir` | yes | none | Generated artifact root. Must be inside the repo and outside source/input directories. |
| `quick_checks` | no | `false` | Adds optional quick checks; still not validation. |
| `artifact_profile` | no | `diagnostic` | `diagnostic`, `summary`, or `full`; controls artifact verbosity. |
| `diagnostic_sample_trades` | no | `5` | Winner/loser samples per side in `diagnostics.json`; 1 to 20. |

### Quick-Run Output

The Python API returns `RunResult`. The CLI prints the result directory on
success.

`RunResult` includes:

| Field | Meaning |
| --- | --- |
| `result_dir` | Artifact directory when one was created. |
| `notes_path` | Human-readable notes path when one was created. |
| `message` | Human-readable run message. |
| `run_completed` | Whether the run completed as a structured run. |
| `failure_stage` | Structured failure stage, or `None`. |
| `assessment_status` | Quick-run status, such as `diagnostics_complete`, `quick_check_passed`, `quick_check_failed`, `quick_check_unverified`, or `runner_failed`. |
| `promotion_eligible` | Always false for quick runs. |
| `param_contract` | `validated`, `unvalidated_passthrough`, or `unknown`. |
| `replayable_from_artifacts` | Whether emitted artifacts alone can replay reported quick-run metrics. |
| `data_availability_status`, `availability_coverage` | Data availability evidence when data loading is reached. |
| `row_contract` | Row schema and availability evidence when row normalization is reached. |
| `causality_verified`, `emitted_replay_verified`, `strict_no_emission_verified` | Lookahead/replay evidence flags. |
| `evidence_quality_warnings` | Evidence-quality warning strings. |

Common quick-run artifacts:

| Artifact | Present when |
| --- | --- |
| `config.toml` | artifact initialization succeeds |
| `strategy_snapshot.py` | strategy file is available |
| `run_manifest.json`, `environment.json`, `summary.json`, `notes.md` | artifacts are finalized |
| `data_manifest.json` | data loading is reached |
| `diagnostics.json` | completed diagnostic-profile run |
| `artifact_profile_summary.json` | completed summary-profile run |
| `strategy_input_rows.jsonl`, `decision_records.jsonl`, `engine_request.json`, `evidence.json` | full-profile run reaches the relevant stages |

## Validation Run

Validation runs a retained candidate across configured windows and generated
cost/fill scenarios. It returns advisory evidence only. It does not provide
market proof, statistical proof, paper-trading authorization, live-trading
authorization, or promotion authority.

Command:

```bash
conda run -n quant quant-strategies validate path/to/candidate/validation.toml
```

Python API:

```python
from quant_strategies.validation import run_validation

result = run_validation("path/to/candidate/validation.toml")
```

### Validation Config

Validation config paths are candidate-local: `strategy_path` and
`[output].results_dir` resolve relative to the validation config directory and
must stay inside it.

Minimum shape:

```toml
strategy_path = "strategy.py"
strategy_id = "candidate"
verdict_source = "engine"  # optional; default and only current verdict source

[[windows]]
id = "validation_2024_01"
start = "2024-01-01"
end = "2024-01-31"

[data]
kind = "bars"
dataset = "equity_1min"
symbols = ["SPY"]
start = "2024-01-01"
end = "2024-01-31"
strict = true

[params]
weight = 1.0
max_hold_bars = 1

[fill_model]
price = "close"
entry_lag_bars = 1
exit_lag_bars = 0

[cost_model]
fee_bps_per_side = 0.0
slippage_bps_per_side = 0.0

[readiness]
min_observations_per_decision = 1
required_observation_fields = ["close"]

[output]
results_dir = "validation_results/candidate"

[search_pressure]
prior_search = "none"
```

Top-level fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `strategy_path` | yes | Candidate strategy file, inside the validation config directory. |
| `strategy_id` | yes | Non-empty candidate identity. |
| `verdict_source` | no | Defaults to `engine`; this is the only current verdict source. |
| `params` | no | Strategy-specific params passed to `validate_params` and `generate_decisions`. |

`[[windows]]` fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Non-empty validation window id. |
| `start`, `end` | yes | Window dates; `end` must be on or after `start`. |

`[data]`, `[fill_model]`, and `[cost_model]` use the same fields as quick run.
Validation applies each window to the data config and expands generated
scenarios from the base fill/cost settings. Users do not configure individual
scenario lists in v1.

`[readiness]` fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `min_observations_per_decision` | yes | Minimum strategy observation refs per decision. |
| `required_observation_fields` | yes | Non-empty list of fields each decision must cite, such as `["close"]`. |

`[output]` fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `results_dir` | yes | Generated validation artifact root, inside the candidate workspace. |

`[search_pressure]` fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `prior_search` | yes | `none`, `known`, or `unknown`. |
| `candidate_count`, `trial_count`, `selection_rule` | only when `prior_search = "known"` | Required disclosure for known prior search. |
| `parameter_search_space`, `split_ids` | no | Optional audit context for known prior search. |

Optional `[paper_readiness]` fields:

| Field | Default |
| --- | --- |
| `enabled` | `true` |
| `min_windows` | `2` |
| `min_total_trades` | `30` |
| `min_positive_window_fraction` | `0.5` |
| `max_stressed_net_loss` | `-0.02` |
| `max_fill_lag_net_loss` | `-0.02` |

Optional `[agreement_oracle]` fields:

| Field | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | Enables the VectorBT Pro agreement check. |
| `tolerance_abs` | `1e-6` | Absolute tolerance. |
| `tolerance_rel` | `1e-3` | Relative tolerance. |

### Validation Output

The Python API returns `ValidationRunResult`.

`ValidationRunResult` includes:

| Field | Meaning |
| --- | --- |
| `result_dir` | Artifact directory when one was created. |
| `decision` | `ValidationPolicyDecision`, an advisory validation decision object. |
| `message` | Human-readable validation message. |
| `run_completed` | Whether validation completed as a structured run. |
| `failure_stage` | Structured failure stage, or `None`. |

`ValidationPolicyDecision` includes:

| Field | Meaning |
| --- | --- |
| `decision` | Advisory label: `hard_no`, `mechanical_complete`, `watchlist`, or `mechanical_review_candidate`. |
| `reasons` | Stable reason strings. |
| `advisory_decision` | Additional advisory value when present. |
| `evidence_class` | Evidence class for the decision. |
| `promotion_eligible`, `paper_trade_eligible`, `live_eligible` | Always false. |
| `requires_manual_approval` | Always true. |
| `passed_gates`, `failed_gates`, `gate_details` | Mechanical policy details. |
| `overfit_controls` | Search-pressure disclosure copied into the decision payload. |

Validation artifacts:

| Artifact | Contents |
| --- | --- |
| `validation_config.toml` | copied validation config |
| `strategy_snapshot.py` | copied strategy file |
| `decision_records.jsonl` | emitted strategy decisions |
| `data_rows/<window_id>.jsonl` | canonical row snapshot per loaded window |
| `data_audit.json` | row and observation audit payload |
| `backend_runs/summary.json` | per-scenario backend metrics and metadata |
| `backend_runs/decision_records/<scenario_id>.jsonl` | per-scenario decision records |
| `backend_runs/trade_ledgers/<scenario_id>.jsonl` | per-scenario engine trade ledger |
| `cost_fill_sensitivity.json` | cost/fill scenario summary |
| `validation_decision.json` | serialized `ValidationPolicyDecision` |
| `validation_manifest.json` | hashes, replayability, provenance, artifact inventory |
| `environment.json` | runtime and package environment |
| `validation_report.md` | human-readable validation report |

### What Validation Validates

Validation is mostly an execution-integrity and evidence-quality check, with a
small mechanical quant triage layer.

Code and harness checks:

- config shape is valid and stale fields are rejected;
- strategy and output paths stay inside the candidate workspace;
- strategy defines and passes `validate_params(params)`;
- data loads for each configured window;
- rows satisfy the strict validation row contract;
- `generate_decisions(rows, params)` returns valid `StrategyDecision` objects;
- decisions point to valid `as_of` rows and observation rows;
- `available_at` exists and is not after `decision_time`;
- hidden-lookahead, deterministic replay, emitted replay, and strict
  suppression replay checks pass;
- each decision satisfies `[readiness]` observation-count and required-field
  rules.

Mechanical quant triage checks:

- each validation window runs generated `base`, `realistic_costs`,
  `stressed_costs`, and `fill_lag_plus_1` scenarios;
- required scenarios complete with valid engine metrics;
- each required scenario has at least 10 trades;
- paper-readiness gates pass when enabled: enough windows, enough realistic-cost
  trades, no zero-trade realistic-cost windows, positive realistic-cost net
  activity, enough positive windows, stressed-cost loss floor, and fill-lag loss
  floor;
- search-pressure disclosure is present and can downgrade otherwise positive
  evidence to `watchlist`.

Validation does not prove alpha, statistical significance, regime robustness,
capacity, live tradability, portfolio/NAV quality, or promotion readiness.

### If Validation Fails

Validation failures are returned as structured results when possible. The API
still returns `ValidationRunResult`; inspect:

| Field | What to check |
| --- | --- |
| `run_completed` | `false` means the run failed before producing a normal completed validation result. |
| `failure_stage` | Stage name such as `config_load`, `artifact_initialization`, `strategy_import`, `param_validation`, `data_load`, `decision_generation`, `data_audit`, `validation_readiness`, `backend_selection`, or `artifact_write`. |
| `decision.decision` | Advisory outcome. Serious validation failures usually produce `hard_no`; weaker positive-but-imperfect evidence may produce `watchlist`. |
| `decision.reasons` | Stable reason strings explaining the decision. |
| `decision.failed_gates` and `decision.gate_details` | Mechanical gates that failed and their details. |
| `result_dir` | Artifact directory when one exists; failed runs may still write diagnostic artifacts. |
| `message` | Human-readable summary. |

CLI exit codes:

| Exit code | Meaning |
| --- | --- |
| `0` | validation completed with a non-`hard_no` advisory decision |
| `2` | validation completed with `hard_no` |
| `3` | data readiness or audit failure |
| `1` | config, infrastructure, artifact, or other execution failure |

## Evaluation Run

Evaluation runs a frozen candidate through the stateless research evaluation
surface and writes portfolio, economic, and path evidence. It uses VectorBT Pro
for portfolio evaluation. Evaluation is not validation and does not authorize promotion, paper trading, or live trading. Benchmark-relative metrics are deferred.

Command:

```bash
conda run -n quant quant-strategies evaluate path/to/candidate/evaluation.toml
```

Python API:

```python
from quant_strategies.evaluation import run_evaluation

result = run_evaluation("path/to/candidate/evaluation.toml")
```

### Evaluation Config

Evaluation config paths are candidate-local: `strategy_path` and
`[output].results_dir` resolve relative to the `evaluation.toml` directory and
must stay inside it.

Minimum shape:

```toml
strategy_path = "strategy.py"
strategy_id = "candidate"

[[windows]]
id = "evaluation_2024_01"
start = "2024-01-01"
end = "2024-01-31"

[data]
kind = "bars"
dataset = "equity_1min"
symbols = ["SPY"]
start = "2024-01-01"
end = "2024-01-31"
strict = true

[params]
weight = 1.0
max_hold_bars = 1

[fill_model]
price = "close"
entry_lag_bars = 1
exit_lag_bars = 0

[cost_model]
fee_bps_per_side = 0.0
slippage_bps_per_side = 0.0

[metrics]
annualization_periods_per_year = 252

[output]
results_dir = "evaluation_results/candidate"
```

Top-level fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `strategy_path` | yes | Candidate strategy file, inside the evaluation config directory. |
| `strategy_id` | yes | Non-empty candidate identity. |
| `params` | no | Strategy-specific params passed to `validate_params` and `generate_decisions`. |

`[[windows]]` fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Non-empty evaluation window id. |
| `start`, `end` | yes | Window dates; `end` must be on or after `start`. |

`[data]`, `[fill_model]`, and `[cost_model]` use the same fields as quick run.
Evaluation applies each window to the data config and expands six fixed
scenarios per window: zero, realistic, and stressed costs crossed with base fill
and `fill_lag_plus_1`.

`[metrics]` fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `annualization_periods_per_year` | yes | Positive annualization factor for portfolio path metrics. |

`[output]` fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `results_dir` | yes | Generated evaluation artifact root, inside the candidate workspace. |

### Evaluation Output

The Python API returns `EvaluationRunResult`.

`EvaluationRunResult` includes:

| Field | Meaning |
| --- | --- |
| `result_dir` | Artifact directory when one was created. |
| `message` | Human-readable evaluation message. |
| `run_completed` | Whether evaluation completed as a structured run. |
| `failure_stage` | Structured failure stage, or `None`. |
| `assessment_status` | Evaluation status, such as `evaluation_complete`, `evaluation_failed`, `evaluation_preflight_failed`, `portfolio_backend_unavailable`, or `portfolio_evaluation_failed`. |
| `evidence_quality_warnings` | Evidence-quality warning strings. |

Evaluation artifacts:

| Artifact | Contents |
| --- | --- |
| `evaluation_config.toml` | copied evaluation config |
| `strategy_snapshot.py` | copied strategy file |
| `data_manifest.json` | per-window data config, row-contract summary, row counts/ranges, normalized row hash, evidence quality, and decision count |
| `evaluation_metrics.json` | metric semantics and per-scenario portfolio metrics |
| `scenario_summary.json` | scenario counts, statuses, coverage, warnings, and unsupported semantics |
| `tables/portfolio_path.parquet` | aggregate portfolio value, period return, and drawdown trace rows by `scenario_id` |
| `tables/trades.parquet` | aggregate trade trace rows by `scenario_id` |
| `tables/positions.parquet` | aggregate position trace rows by `scenario_id` |
| `tables/per_asset_metrics.parquet` | aggregate per-asset metrics by `scenario_id` |
| `evaluation_manifest.json` | hashes, scenario coverage, table metadata, metric semantics, replayability, provenance, and artifact inventory |
| `environment.json` | runtime and package environment, including `pandas`, `pyarrow`, and `vectorbtpro` |
| `notes.md` | human-readable evaluation notes |

Detailed trace artifacts are Parquet only and require pyarrow.
There is no JSONL fallback path for evaluation traces.

### What Evaluation Evaluates

Evaluation runs the shared execution kernel once per configured window, requires
`validate_params`, checks the strict validation row contract, and runs strict
hidden-lookahead preflight before portfolio evaluation. It then fans out the
fixed scenario matrix from the same normalized rows and decisions.

Evaluation produces portfolio/NAV-path evidence through VectorBT Pro. It is
separate from validation policy: it does not emit validation decisions, does not
prove alpha or market durability, and does not grant promotion authority.

CLI exit codes:

| Exit code | Meaning |
| --- | --- |
| `0` | evaluation completed |
| `3` | data-load or row-contract failure |
| `1` | config, preflight, portfolio backend, artifact, or other execution failure |

## What This Project Does Not Decide

- It does not choose which strategy ideas are worth researching.
- It does not acquire, refresh, repair, or join data; `quant_data` owns that.
- It does not produce market proof, statistical proof, paper-trading permission,
  live-trading permission, or promotion authority.
- It does not make generated artifacts true by construction; artifacts are
  evidence to inspect.

## Reference Docs

- [runner.md](runner.md) has detailed quick-run behavior and artifact semantics.
- [validation.md](validation.md) has detailed validation policy and artifact
  semantics.
- [quant-autoresearch-consumer.md](quant-autoresearch-consumer.md) has the stable
  consumer contract for `quant_autoresearch`.
