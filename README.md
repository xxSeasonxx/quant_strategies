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

The canonical default output is `StrategyDecision`. Decisions carry a stable
`decision_id`, instrument, open intent, decision time, as-of time, target,
`ExitPolicy(max_hold_bars=...)`, optional exit controls, metadata, and
`ObservationRef` lineage for consumed rows.

The default decision ontology is intentionally narrow: equities/ETFs, FX pairs,
and crypto perps with `open` intent and `target_weight` sizing. Extended
vocabulary for futures, options, multi-leg instruments, buy/sell book side,
close/adjust/roll actions, and `target_notional`, `target_contracts`, or
`target_vol` sizing lives behind explicit imports from
`quant_strategies.decisions.extended_ontology`. Runner smoke execution supports
only single-leg equity/ETF, FX, and crypto-perp `open` decisions with non-flat
`target_weight` sizing. Explicitly extended decisions are rejected by unsupported
smoke or backend paths instead of approximating their PnL.

## Boundaries

`decisions` defines the typed strategy contract.

`runner` loads TOML configs, fetches data through public `quant_data` loader
APIs, executes pure strategy functions, builds smoke-engine requests, and writes
ignored artifacts under `results/`.
Database engine creation and environment configuration are owned by
`quant_data`; the runner does not discover upstream `.env` files. Tests and
specialized callers can inject an explicit engine at the data-loader boundary.
When no explicit engine is provided, the runner reuses one default `quant_data`
engine per Python process.

Runner and validation share one internal execution boundary for strategy import,
parameter validation, data loading, frozen strategy execution, decision
validation, row hashing, and evidence-quality context. Runner remains the owner
of smoke-engine request construction and engine artifacts.

`engine` performs deterministic smoke screening and validation gates on supplied
bars and decisions. Aggregate smoke activity sums live under
`smoke_score.sum_signed_trade_activity_*`; they are not portfolio or NAV-path
returns. Runner artifacts include `metric_semantics` for each smoke score field,
including unit, base, aggregation, backend, return path model, comparability,
and declared asymmetry.

`validation` runs advisory checks from an explicit `validation.toml` plus the
referenced `strategy.py`. Advisory outcomes are
`hard_no`, `mechanical_pass`, `watchlist`, and `mechanical_review_candidate`;
`promotion_eligible`, `paper_trade_eligible`, and `live_eligible` remain false.

Data materialization, refresh, backfill, repair, and source joining belong in
`quant-data`, not this repository.

## Runner Runs

`quant-strategies run path/to/config.toml` executes one TOML experiment config.
The runner loads rows, calls pure `generate_decisions(rows, params)`, validates
the `StrategyDecision` contract, runs hidden-lookahead replay keyed by
`decision_id`, checks decision row availability, builds an engine request from
supported decisions, and writes result artifacts.

Runner rows are normalized once at the data-load boundary through the neutral
`quant_strategies.data_contract.NormalizedRows` contract. Strategies still
receive plain mapping rows typed as `Sequence[Mapping[str, Any]]`; they do not
receive row model objects.

With `[output] mode = "screen"`, the engine simulates entries and exits from
the decisions, fill model, cost model, and exit policy. It reports
`trade_count` plus `smoke_score.sum_signed_trade_activity_gross`,
`sum_signed_trade_activity_funding`, `sum_signed_trade_activity_cost`, and
`sum_signed_trade_activity_net`. A completed screen has
`assessment_status = "screened"`. If a strategy returns no decisions, the
screen still completes with `trade_count = 0` and zero smoke scores; this is a
zero-opportunity search signal, not a runner infrastructure failure.

With `[output] mode = "validate"`, the engine runs the same screen and applies
smoke gates: `valid_inputs`, `min_trades >= 1`, `positive_gross`, and
`positive_net`. Passing gates produce `assessment_status = "smoke_passed"` only
when hidden-lookahead replay passes and all rows carry `available_at`. Passing
gates with missing or partial `available_at` produce `assessment_status =
"smoke_unverified"`. Invalid `available_at` is a row contract failure. These
gates are mechanical checks only; they do not test statistical significance,
regime robustness, capacity, or execution quality.

A `mode = "validate"` run with no decisions also completes normally, but fails
the smoke gates as `assessment_status = "smoke_failed"` because `min_trades`
is not met.

Runner callers that need live progress can pass an `event_sink` callback to
`run_config()`. The callback receives structured `runner_stage` dictionaries
for stage start, completion, and failure events, with UTC timestamps and
`duration_ms` on terminal events. The CLI equivalent is
`quant-strategies run --events-jsonl ...`, which preserves stdout as the result
directory and writes JSONL stage events to stderr.
Validation callers can pass the same shape of callback to `run_validation()`;
those events use `event = "validation_stage"`. The CLI equivalent is
`quant-strategies validate --events-jsonl ...`.

CLI exit codes are part of the public contract: `0` means structured usable
evidence was produced, `1` means infrastructure or execution failed, `2` means
validation completed with `hard_no`, and `3` means data readiness or audit
failed. Programmatic callers should use `run_completed`, `failure_stage`,
`assessment_status`, verdicts, trust tier, causality/data fields, row contract,
and smoke metrics instead of any single completion flag.

Runner summaries and data manifests include evidence-quality fields:
`data_availability_status`, `availability_coverage`, `row_contract`,
`causality_verified`, and `evidence_quality_warnings`. Hidden-lookahead replay
failures stop the run as `runner_failed`. Runner smoke records missing or
partial availability as uncertainty with `smoke_unverified` and does not set
`causality_verified`.
Missing `available_at` in search mode is warning evidence; invalid
`available_at` is a row contract failure.

`row_contract` reports the loaded row schema status for the configured
`data.kind`, including missing required fields, timestamp awareness, duplicate
symbol/timestamp keys, and `quant_data_feedback` strings for upstream data
fixes. Stable issue reasons include `row_missing_required_field`,
`row_invalid_timestamp`, `row_invalid_numeric_field`, `row_invalid_ohlc_order`,
`row_duplicate_symbol_timestamp`, `row_invalid_available_at`,
`row_missing_available_at`, `row_missing_quote_field`, and
`row_invalid_funding_fields`. Runner artifacts may sample or compact
`row_contract.issues`, while `issue_count` and `issue_reasons` preserve
complete counts and reason summaries for consumers. `quant_data_feedback`
summarizes error handoff items for upstream data fixes. Search-mode missing
`available_at` warnings remain excluded from `quant_data_feedback`.

Runner artifacts also declare `artifact_trust_tier`. Summary-profile runs are
the default and are `search_only`: useful for fast ranking but not enough to
replay every reported number from artifacts alone. Full-profile runs are
`audit_replayable`: they include the row, decision, engine-request, and evidence
artifacts needed for audit replay of runner smoke metrics.

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
eligibility flags. When non-empty search pressure would otherwise produce a
`mechanical_review_candidate`, validation downgrades the advisory verdict to
`watchlist` and records `multiple_testing_not_corrected_advisory_only` in the
decision reasons.

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
When `[paper_readiness] enabled = true`, validation uses retained row-contract
mode and strict replay. Strict replay also checks no-emission row boundaries, so
a strategy that suppresses an otherwise emitted decision by peeking at future
rows fails with `hidden_lookahead_suppression_detected`.

For each validation window, the validator expands required and diagnostic
scenarios, runs the configured backend, and classifies the candidate as
`hard_no`, `mechanical_pass`, `watchlist`, or `mechanical_review_candidate`. A
`mechanical_pass` requires passing data audits, required backend scenarios,
valid backend metrics, and at least `10` trades per required scenario. A
required backend scenario with unsupported execution semantics is a `hard_no`
because the mechanical check did not execute. With paper-readiness enabled,
nonpositive realistic-cost evidence is also a `hard_no`. A `watchlist` captures
positive evidence that misses paper-readiness gates or carries uncorrected
search pressure. A `mechanical_review_candidate` requires mechanical validation,
paper-readiness gates such as multiple windows, enough realistic-cost trades, no
zero-trade windows, positive realistic-cost evidence, sufficient
positive-window fraction, stressed-cost and fill-lag loss floors, and empty
search pressure. Verdict labels are advisory inputs to human review, never
autonomous promotion signals, and eligibility flags still remain false.

Validation backend summaries include `metric_semantics` for required policy
metrics such as `net_return` and `trade_count`, plus optional funding metrics
such as `funding_return` and `linear_funding_adjusted_return`. The metric
payloads stay flat for artifact readability, while policy reads them through a
typed backend metric schema with declared unit, base, comparability, tolerance,
and asymmetry. Crypto-perp funding in the VectorBT Pro backend is a linear
additive diagnostic adjustment: it is reported as
`linear_funding_adjusted_return`, while policy gates continue to use the
backend price/cost `net_return`. `net_return` currently declares no
cross-backend tolerance until a second production backend or explicit agreement
test exists.

## Artifacts

Runner and validation artifacts are generated under ignored result directories.

After config loading succeeds, runner result dirs include `config.toml`;
`strategy_snapshot.py` is copied when the strategy file is available. Runs that
reach data loading include `data_manifest.json` and, for
`artifact_profile = "full"`, `strategy_input_rows.jsonl` even if decision
generation later fails. In full-profile runner runs,
`strategy_input_rows.jsonl` contains a JSON-safe canonical serialization of the
normalized projection used for strategy input; non-finite ancillary values are
written as `null`, and its file hash matches `normalized_rows_sha256` in
`data_manifest.json`. Runner failures still write `run_manifest.json`,
`environment.json`, `summary.json`, and `notes.md`. Successful default
`artifact_profile = "summary"` runs also write `artifact_profile_summary.json`
and declare `artifact_trust_tier = "search_only"`. Completed
`artifact_profile = "full"` runs that reach engine request construction also
write `decision_records.jsonl`,
`engine_request.json`, and `evidence.json`, and declare `artifact_trust_tier =
"audit_replayable"`.

Validation artifacts include:

- `decision_records.jsonl`
- `data_rows/<window_id>.jsonl` for each window that successfully loaded rows
- `data_audit.json`
- `backend_runs/summary.json`
- `robustness_matrix.json`
- `validation_decision.json`
- `validation_manifest.json`
- `environment.json`
- `validation_report.md`

Manifests hash the core artifacts needed to audit what code, config, data, and
decisions produced a run. Validation data provenance links each loaded window to
its canonical JSON-safe row snapshot with `rows_path`, `row_count`, and
`rows_sha256`, and row snapshots are included in manifest `core_hashes` and
`artifacts`. Non-finite numeric or otherwise non-JSON ancillary row values are
normalized to JSON-safe values in the snapshot; data-load failures leave row
snapshot fields null. Backend summaries still report aggregate backend metrics
and scenario decision records; per-backend fill, trade, funding, and cost ledgers
require a backend artifact contract and are not emitted yet.
`validation_decision.json` and `robustness_matrix.json` include
`failure_details` for fatal setup failures that validation catches, while stable
policy reason strings remain unchanged.

`run_manifest.json` and `validation_manifest.json` keep deterministic research
identity focused on source commit, config, data, decisions, and artifact hashes.
Python version, installed package versions, git dirty status, and tracked diff
hashes are written to `environment.json` instead. Manifest artifact hashes
exclude `environment.json`, so consumers should use manifests for input/artifact
identity and `environment.json` for machine/environment audit context.

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
