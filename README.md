# quant_strategies

`quant_strategies` is a disciplined research harness for pure strategy
functions, deterministic smoke runs, and advisory validation. The repository is
not a trading system and does not imply paper or live readiness.

## Contract

Strategies expose one callable:

```python
generate_decisions(rows, params) -> list[StrategyDecision]
```

Strategy files stay flat and pure. They may inspect the rows and params passed
to them, but they must not load data, call engines, write artifacts, run loops,
or mutate their inputs. Each strategy module documents thesis, observables,
rule, assumptions, provenance, and falsifier in its module docstring.

The canonical output is `StrategyDecision`. Decisions carry instrument,
decision time, as-of time, target, `ExitPolicy(max_hold_bars=...)`, optional
exit controls, metadata, and `ObservationRef` lineage for consumed rows.

## Boundaries

`decisions` defines the typed strategy contract.

`runner` loads TOML configs, fetches data through public `quant_data` loader
APIs, executes pure strategy functions, builds smoke-engine requests, and writes
ignored artifacts under `results/`.

`engine` performs deterministic smoke screening and validation gates on supplied
bars and decisions. Aggregate smoke totals live under
`smoke_score.sum_weighted_trade_*`.

`validation` runs advisory checks from an explicit `validation.toml` plus the
referenced `strategy.py`. Advisory outcomes are
`hard_no`, `mechanical_pass`, `watchlist`, and `paper_candidate`;
`promotion_eligible`, `paper_trade_eligible`, and `live_eligible` remain false.

Data materialization, refresh, backfill, repair, and source joining belong in
`quant-data`, not this repository.

## Runner Runs

`quant-strategies run path/to/config.toml` executes one TOML experiment config.
The runner loads rows, calls pure `generate_decisions(rows, params)`, validates
the `StrategyDecision` contract, checks decision row availability, converts
decisions to engine signals, builds an engine request, and writes result
artifacts.

With `[output] mode = "screen"`, the engine simulates entries and exits from
the decisions, fill model, cost model, and exit policy. It reports
`trade_count` plus `smoke_score.sum_weighted_trade_gross_return`,
`sum_weighted_trade_funding_return`, `sum_weighted_trade_cost_return`, and
`sum_weighted_trade_net_return`. A completed screen has
`assessment_status = "screened"`.

With `[output] mode = "validate"`, the engine runs the same screen and applies
smoke gates: `valid_inputs`, `min_trades >= 1`, `positive_gross`, and
`positive_net`. Passing gates produce `assessment_status = "smoke_passed"`.
These gates are mechanical checks only; they do not test statistical
significance, regime robustness, capacity, or execution quality.

Runner summaries and data manifests include evidence-quality fields:
`data_availability_status`, `availability_coverage`, `row_contract`,
`causality_verified`, and `evidence_quality_warnings`. Runner smoke keeps
missing availability non-fatal for search, but it records that uncertainty and
never claims hidden-lookahead causality verification. `row_contract` reports the
loaded row schema status for the configured `data.kind`, including missing
required fields, timestamp awareness, duplicate symbol/timestamp keys, and
`quant_data_feedback` strings for upstream data fixes.

## Validation Configs

Validation is addressed by an explicit TOML config file:

```text
candidate_workspace/
  strategy.py
  validation.toml
```

Relative paths in `validation.toml` resolve from the config file directory.
`strategy_path` and `[output] results_dir` must stay inside that directory.
The validator does not special-case `researched/`, package manifests,
family/variant directories, or any repository layout.

Every validation config includes minimal readiness metadata:

```toml
strategy_path = "strategy.py"
strategy_id = "candidate"

[readiness]
min_observations_per_decision = 1
required_observation_fields = ["close"]

[output]
results_dir = "validation_results/candidate"
```

This is intentionally small. It proves the strategy declared enough local row
lineage for backend execution; it is not a dependency DSL and not market
evidence.

Validation configs can also override the advisory paper-readiness gates:

```toml
[paper_readiness]
enabled = true
min_windows = 2
min_total_trades = 30
min_positive_window_fraction = 0.5
max_stressed_net_loss = -0.02
max_fill_lag_net_loss = -0.02
```

The stress and fill-lag loss floors apply to the worst required scenario net
return across validation windows.

Validation configs can optionally record the search pressure behind a retained
candidate:

```toml
[search_pressure]
candidate_count = 120
trial_count = 18
parameter_search_space = { lookback = [12, 24, 48] }
selection_rule = "top risk-adjusted smoke score"
split_ids = ["validation_2026_h1", "validation_2026_h2"]
```

These fields are artifact metadata only. They make missing overfit/search
context explicit; they do not compute statistical corrections or change
eligibility flags.

The default validation backend is `vectorbtpro`. Install the optional backend
dependencies before running real validation:

```bash
conda run -n quant python -m pip install -e '.[vectorbtpro]'
```

VectorBT Pro may require package access or private index configuration outside
this repository.

If the configured backend cannot be imported, validation records
`backend_unavailable` as a setup `hard_no`, not as a research `watchlist`.

## Validation Runs

`quant-strategies validate path/to/candidate/validation.toml` runs advisory
validation for the config and referenced strategy. It checks readiness metadata,
strategy import, parameter validation, data loading, decision output, and
observation lineage before backend execution.

Validation also runs a hidden-lookahead replay check before backend scenarios.
The check compares baseline decisions against decisions generated from rows
available within each decision's information set. A mismatch becomes
`hidden_lookahead_detected`; replay errors become
`hidden_lookahead_check_failed`.

For each validation window, the validator expands required and diagnostic
scenarios, runs the configured backend, and classifies the candidate as
`hard_no`, `mechanical_pass`, `watchlist`, or `paper_candidate`. A
`mechanical_pass` requires passing data audits, required backend scenarios,
valid backend metrics, and at least `10` trades per required scenario. A
`watchlist` captures unsupported required backend semantics, or positive
evidence that misses paper-readiness gates. A `paper_candidate`
requires mechanical validation plus paper-readiness gates such as multiple
windows, enough realistic-cost trades, no zero-trade windows, positive
realistic-cost evidence, sufficient positive-window fraction, and stressed-cost
and fill-lag loss floors. Eligibility flags still remain false.

## Artifacts

Runner and validation artifacts are generated under ignored result directories.

After config loading succeeds, runner result dirs include `config.toml`,
`run_manifest.json`, `summary.json`, and `notes.md`; `strategy_snapshot.py` is
copied when the strategy file is available. Data-loaded runs include
`data_manifest.json`. Completed `artifact_profile = "summary"` runs also write
`artifact_profile_summary.json`. Completed `artifact_profile = "full"` runs also
write `strategy_input_rows.csv`, `strategy_input_rows.jsonl`,
`decision_records.jsonl`, `signals.csv`, `engine_request.json`, and
`evidence.json`.

Validation artifacts include:

- `decision_records.jsonl`
- `data_audit.json`
- `backend_runs/summary.json`
- `backend_capability_matrix.json`
- `robustness_matrix.json`
- `validation_decision.json`
- `validation_manifest.json`
- `validation_report.md`

Manifests hash the core artifacts needed to audit what code, config, data, and
decisions produced a run.
`validation_decision.json` and `robustness_matrix.json` include
`failure_details` for fatal setup failures that validation catches, while stable
policy reason strings remain unchanged.

## Commands

Use the `quant` conda environment for Python commands:

```bash
conda run -n quant pytest
conda run -n quant quant-strategies run path/to/config.toml
conda run -n quant quant-strategies validate path/to/candidate/validation.toml
```

Run focused tests for narrow edits, then the full suite before claiming a reset
or contract change is complete.

## Downstream Consumers

Downstream research systems should own the research loop and modify only a
candidate `strategy.py` plus `experiment.toml`, while consuming the public
runner API for execution. `quant_strategies.runner.run_config` and
`quant_strategies.runner.RunResult` are the stable Python consumer surface; no
top-level facade is promised. See `docs/quant-autoresearch-consumer.md` for the
consumer contract.

## Promotion Discipline

`researched/` may contain frozen packages produced by upstream research. It does
not mean market validation, and validation does not treat it as special.

Moving a strategy to `tested/` requires the separate validation process Season
approves. Advisory validation artifacts can support review, but they do not
authorize paper trading, live trading, or promotion by themselves.
