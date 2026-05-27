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

`validation` runs advisory researched-package checks. Advisory outcomes are
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

## Researched Packages

Validation-ready researched packages use the canonical layout:

```text
researched/<package>/
  manifest.json
  strategy.py
  validation.toml
```

The manifest must identify the package variant, lifecycle status, strategy
hash, and validation-config hash. Backend execution is blocked when layout,
manifest integrity, readiness metadata, or observation lineage fails.

Validation configs include minimal readiness metadata:

```toml
[readiness]
min_observations_per_decision = 1
required_observation_fields = ["close"]
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

## Package Validation

`quant-strategies validate path/to/researched/package` runs advisory validation
for a researched package. It checks package layout, manifest hashes, readiness
metadata, strategy import, parameter validation, data loading, decision output,
and observation lineage before backend execution.

For each validation window, the validator expands required and diagnostic
scenarios, runs the configured backend, and classifies the package as
`hard_no`, `mechanical_pass`, `watchlist`, or `paper_candidate`. A
`mechanical_pass` requires passing data audits, required backend scenarios,
valid backend metrics, and at least `10` trades per required scenario. A
`watchlist` captures unavailable or unsupported required backend semantics, or
positive evidence that misses paper-readiness gates. A `paper_candidate`
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

Package validation artifacts include:

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

## Commands

Use the `quant` conda environment for Python commands:

```bash
conda run -n quant pytest
conda run -n quant quant-strategies run path/to/config.toml
conda run -n quant quant-strategies validate path/to/researched/package
```

Run focused tests for narrow edits, then the full suite before claiming a reset
or contract change is complete.

## Downstream Consumers

Downstream research systems should own the research loop and modify only a
candidate `strategy.py` plus `experiment.toml`, while consuming the public
runner API for execution. See `docs/quant-autoresearch-consumer.md` for the
consumer contract.

## Promotion Discipline

`researched/` contains frozen packages produced by upstream research. It does
not mean market validation.

Moving a strategy to `tested/` requires the separate validation process Season
approves. Advisory validation artifacts can support review, but they do not
authorize paper trading, live trading, or promotion by themselves.
