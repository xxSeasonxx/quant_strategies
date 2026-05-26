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

`validation` runs advisory researched-package checks. Its best positive outcome
is `mechanical_pass`; `promotion_eligible`, `paper_trade_eligible`, and
`live_eligible` remain false.

Data materialization, refresh, backfill, repair, and source joining belong in
`quant-data`, not this repository.

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

## Artifacts

Runner and validation artifacts are generated under ignored result directories.
Important validation artifacts include:

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

## Promotion Discipline

`researched/` contains frozen packages produced by upstream research. It does
not mean market validation.

Moving a strategy to `tested/` requires the separate validation process Season
approves. Advisory validation artifacts can support review, but they do not
authorize paper trading, live trading, or promotion by themselves.
