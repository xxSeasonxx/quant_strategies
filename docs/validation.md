# Validation reference

`quant-strategies validate path/to/candidate/validation.toml` runs advisory
validation for a config and its referenced strategy. See the [README](../README.md)
for the overall design; validation reuses the same execution kernel as the quick run.

Validation is mechanical only. Verdict labels are advisory inputs to human review,
never autonomous promotion signals; `promotion_eligible`, `paper_trade_eligible`, and
`live_eligible` always remain false.

## Config layout

```text
candidate_workspace/
  strategy.py
  validation.toml
```

Relative paths in `validation.toml` resolve from the config file directory.
`strategy_path` and `[output] results_dir` must stay inside that directory. The
validator does not special-case `researched/`, package manifests, family/variant
directories, or any repository layout.

Every config includes minimal readiness metadata:

```toml
strategy_path = "strategy.py"
strategy_id = "candidate"

[readiness]
min_observations_per_decision = 1
required_observation_fields = ["close"]

[output]
results_dir = "validation_results/candidate"
```

This proves the strategy declared enough local row lineage for backend execution. It
is intentionally small — not a dependency DSL and not market evidence.

## Paper-readiness gates

```toml
[paper_readiness]
enabled = true
min_windows = 2
min_total_trades = 30
min_positive_window_fraction = 0.5
max_stressed_net_loss = -0.02
max_fill_lag_net_loss = -0.02
```

The stress and fill-lag loss floors apply to the worst required scenario net return
across validation windows. `[paper_readiness] enabled = true` also applies the retained
row-contract mode. It no longer governs replay strictness — strict replay is always on
(see below).

## Search pressure

```toml
[search_pressure]
candidate_count = 120
trial_count = 18
parameter_search_space = { lookback = [12, 24, 48] }
selection_rule = "top risk-adjusted smoke score"
split_ids = ["validation_2026_h1", "validation_2026_h2"]
```

These fields are artifact metadata only — they make missing overfit/search context
explicit; they do not compute statistical corrections or change eligibility flags.
When non-empty search pressure would otherwise produce a `mechanical_review_candidate`,
validation downgrades the verdict to `watchlist` and records
`multiple_testing_not_corrected_advisory_only` in the reasons.

## Verdict PnL source and the agreement oracle

The verdict PnL source is the engine smoke kernel: the number a human audits is the
number the verdict is computed from. VectorBT Pro is not a co-equal verdict backend; it
is available only as an opt-in agreement oracle. (The legacy `backend` config field has
been removed; a config that still sets it fails to load with migration guidance.)

To cross-check the engine verdict against VectorBT Pro:

```toml
[agreement_oracle]
enabled = true
tolerance_abs = 1e-6
tolerance_rel = 1e-3
```

```bash
conda run -n quant python -m pip install -e '.[vectorbtpro]'
```

When enabled, the oracle cross-checks each applicable scenario's price path against
VectorBT Pro and fails the run with `backend_agreement_failed` if they diverge beyond
tolerance. It compares the engine's `gross_return` (which feeds the gated `net_return`)
against vbt's zero-cost total return, and is sound only where the engine's linear
per-trade sum equals a NAV path — a single-trade, close-fill, threshold-free scenario;
it reports `skipped` otherwise. If the oracle is enabled but VectorBT Pro cannot be
imported, the cross-check is recorded as unavailable and the engine verdict stands.

## What a validation run checks

It checks readiness metadata, strategy import, parameter validation
(`validate_params` is **required** — a schema-less candidate is a `hard_no` with
`failure_stage = "param_validation"`), data loading, decision output, and observation
lineage before backend execution.

It then runs a hidden-lookahead replay check. The check compares baseline decisions
against decisions generated from rows available within each decision's information set;
a mismatch becomes `hidden_lookahead_detected`, replay errors become
`hidden_lookahead_check_failed`. Strict replay runs by default (for both the quick run
and validation): it also checks no-emission row-grid boundaries, so a strategy that
suppresses an otherwise-emitted decision by peeking at future rows fails with
`hidden_lookahead_suppression_detected`.

## The verdict ladder

For each window, the validator expands required and diagnostic scenarios, runs the
engine verdict kernel (and, when enabled, the agreement oracle), and classifies:

- **`mechanical_pass`** — passing data audits, required backend scenarios, valid backend
  metrics, and at least `10` trades per required scenario. With paper-readiness enabled,
  nonpositive realistic-cost evidence is a `hard_no`.
- **`mechanical_review_candidate`** — mechanical validation plus paper-readiness gates:
  multiple windows, enough realistic-cost trades, no zero-trade windows, positive
  realistic-cost evidence, sufficient positive-window fraction, stressed-cost and
  fill-lag loss floors, and empty search pressure.
- **`watchlist`** — positive evidence that misses paper-readiness gates or carries
  uncorrected search pressure.
- **`hard_no`** — failed audits, or a required scenario the engine ontology cannot
  represent (flat targets, non-`target_weight` sizing, options/futures/multi-leg). A
  required backend scenario with unsupported execution semantics is a `hard_no` because
  the mechanical check did not execute. Because the engine is the verdict kernel,
  threshold exits and quote/open fills are *executed*, not rejected.

## Metric semantics

Validation backend summaries include `metric_semantics` for the engine verdict metrics:
`net_return`, `trade_count`, `gross_return`, `funding_return`, and `cost_return`. The
payloads stay flat for artifact readability, while policy reads them through a typed
metric schema with declared unit, base, comparability, tolerance, and asymmetry.

`net_return` is the engine's funding-inclusive signed trade-activity sum — the audited
smoke net — so funding is part of the gated number, not a side diagnostic
(`net_return = gross_return + funding_return - cost_return`). `gross_return` is the
funding- and cost-exclusive price path the agreement oracle cross-checks against
VectorBT Pro. `net_return` declares no cross-backend tolerance because it is a linear
per-trade sum, not a NAV path.

## Artifacts

Validation artifacts (under ignored result directories):

- `decision_records.jsonl`
- `data_rows/<window_id>.jsonl` for each window that loaded rows
- `data_audit.json`
- `backend_runs/summary.json`
- `backend_runs/trade_ledgers/<scenario_id>.jsonl` — per-scenario engine trade ledger
- `robustness_matrix.json`
- `validation_decision.json`
- `validation_manifest.json`
- `environment.json`
- `validation_report.md`

Manifests hash the core artifacts needed to audit what code, config, data, and decisions
produced a run. Data provenance links each loaded window to its canonical JSON-safe row
snapshot (`rows_path`, `row_count`, `rows_sha256`), included in `core_hashes` and
`artifacts`.

The engine verdict backend emits a per-scenario per-trade ledger
(`backend_runs/trade_ledgers/<scenario_id>.jsonl`, one `Trade` record per line with
entry/exit prices and gross/funding/cost/net returns), hash-pinned in the manifest. The
gated `net_return` is therefore recomputable from artifacts as `sum(trade.net_return)`
per scenario; the manifest sets `verdict_replayable` and
`verdict_replay_basis = "engine_trade_ledger"`. The opt-in VectorBT Pro oracle is a
price-path cross-check and emits no ledger of its own. `validation_decision.json` and
`robustness_matrix.json` include `failure_details` for fatal setup failures, while stable
policy reason strings remain unchanged.
