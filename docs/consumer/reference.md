# Reference — API, Schema, Config & Results

*Stable lookup tables for the public surface.* For orientation see
[README.md](README.md); for how-to and recipes see [usage-guide.md](usage-guide.md).

> This reference is hand-maintained from the source. It describes the **stable
> contract** (names, types, rules), not live data. If anything here drifts from the
> code, the code wins — please report it. Authoritative source modules:
> `quant_strategies/{runner,validation,evaluation}/__init__.py` and
> `quant_strategies/decisions/`.

---

## Public API surface

Import only these. Everything else (including `quant_strategies.engine` and any
`_`-prefixed module) is internal and not part of the contract.

| Import | Kind | Purpose |
|---|---|---|
| `quant_strategies.runner.run_config` | function | Run the quick-run surface |
| `quant_strategies.runner.RunResult` / `RunOutcome` / `RunEvidence` / `RunCausalityEvidence` | dataclass | Quick-run result types |
| `quant_strategies.runner.RunEconomics` / `RunTrade` | dataclass | Typed quick-run trade ledger + summary/slice economics |
| `quant_strategies.validation.run_validation` | function | Run the validation surface |
| `quant_strategies.validation.ValidationRunResult` | dataclass | Validation result type |
| `quant_strategies.evaluation.run_evaluation` | function | Run the evaluation surface |
| `quant_strategies.evaluation.EvaluationRunResult` | dataclass | Evaluation result type |
| `quant_strategies.evaluation.FoldReturnSeries` / `FoldScenarioMetrics` | dataclass | Typed per-fold OOS return series + summary scalars on the evaluation result |
| `quant_strategies.evaluation.EvaluationConfig` / `EvaluationScenarioConfig` / `BenchmarkConfig` | model | Evaluation config models (for typed construction) |
| `quant_strategies.decisions.StrategyDecision` | model | The decision your strategy returns |
| `quant_strategies.decisions.InstrumentRef` (alias `DecisionInstrument`) | model | Instrument reference |
| `quant_strategies.decisions.PositionTarget` / `ExitPolicy` / `ObservationRef` / `DecisionIntent` | model | Decision components |
| `quant_strategies.decisions.{InstrumentKind,Direction,DecisionAction,SizingKind}` | literal type | Allowed enum values |
| `quant_strategies.decisions.strategy_purity_violations` | function | Static purity self-check (returns a tuple of violations; `()` is clean) |
| `quant_strategies.decisions.validate_strategy_params` | function | Helper to apply a strategy's `validate_params` contract |
| `quant_strategies.decisions.validate_decision_output` | function | Helper to validate a list of decisions |
| `quant_strategies.decisions.load_decision_strategy` / `DecisionStrategyLoadError` / `StrategyGenerator` / `DecisionStrategyCallable` | function / types | Load a strategy file's callables (advanced/tooling) |

### Entry-point signatures

All three share the same shape and return a typed result (they do not raise on
ordinary run failures — they return a structured failure):

```python
run_config(config_path: str | Path, *, repo_root: Path | None = None,
           event_sink: RunnerEventSink | None = None) -> RunResult
run_validation(config_path: str | Path, *, repo_root: Path | None = None,
               event_sink=... | None = None) -> ValidationRunResult
run_evaluation(config_path: str | Path, *, repo_root: Path | None = None,
               event_sink=... | None = None) -> EvaluationRunResult
```

---

## Strategy module contract

A strategy file must expose:

| Callable | Required by | Signature | Contract |
|---|---|---|---|
| `generate_decisions` | all surfaces | `(rows: Sequence[Mapping], params: Mapping) -> list[StrategyDecision]` | Pure; reads only `rows`/`params`; no I/O, engines, clocks, RNG, or loops with side effects |
| `validate_params` | validation, evaluation (optional for quick run) | `(params: Mapping) -> Mapping` | Returns normalized params or raises on invalid input |

Plus a module docstring with: **Source / provenance** (specific), **Market
rationale**, **Required observables**, **Decision rule**, **Assumptions**,
**Falsifier**.

---

## Decision schema

`StrategyDecision` and its components are frozen, strict Pydantic models with
`extra="forbid"`. Enum (Literal) values:

| Type | Allowed values |
|---|---|
| `InstrumentKind` | `equity_or_etf`, `fx_pair`, `crypto_perp` |
| `Direction` | `long`, `short`, `flat` |
| `SizingKind` | `target_weight` |
| `DecisionAction` | `open` |

### `StrategyDecision`

| Field | Type | Default | Rule |
|---|---|---|---|
| `strategy_id` | `str` | — | non-empty |
| `instrument` | `InstrumentRef` | — | — |
| `decision_time` | `datetime` | — | timezone-aware |
| `as_of_time` | `datetime` | — | timezone-aware; **`as_of_time <= decision_time`** |
| `target` | `PositionTarget` | — | — |
| `exit_policy` | `ExitPolicy` | — | — |
| `observations` | `tuple[ObservationRef, ...]` | `()` | declare the rows the rule used |
| `intent` | `DecisionIntent` | `action="open"` | — |
| `metadata` | `Mapping[str, Any]` | `{}` | must be JSON-compatible; frozen on construction |
| `decision_id` | `str \| None` | auto | derived deterministically from content if `None` |

### `InstrumentRef`

| Field | Type | Rule |
|---|---|---|
| `kind` | `InstrumentKind` | one of the enum values |
| `symbol` | `str` | non-empty |

### `PositionTarget`

| Field | Type | Default | Rule |
|---|---|---|---|
| `direction` | `Direction` | — | — |
| `sizing_kind` | `SizingKind` | `target_weight` | — |
| `size` | `float` | — | finite, `>= 0`; `flat` ⇒ `0`; `long`/`short` ⇒ `> 0` |

### `ExitPolicy`

Stop / take-profit / trailing values are **bar-sampled against the configured fill
price**, not intrabar OHLC barrier orders.

| Field | Type | Default | Rule |
|---|---|---|---|
| `max_hold_bars` | `int` | — | `>= 1` |
| `stop_loss_bps` | `float \| None` | `None` | if set: finite, `> 0` |
| `take_profit_bps` | `float \| None` | `None` | if set: finite, `> 0` |
| `trailing_stop_bps` | `float \| None` | `None` | if set: finite, `> 0` |

### `ObservationRef`

| Field | Type | Default | Rule |
|---|---|---|---|
| `symbol` | `str` | — | non-empty |
| `timestamp` | `datetime` | — | timezone-aware; must be causally available by `decision_time` |
| `field` | `str \| None` | `None` | non-empty if set |
| `source` | `str \| None` | `None` | non-empty if set |

---

## Config reference

Common sections, then per-surface differences. Dates are ISO strings
(`"2024-01-31"`). `[params]` is passed verbatim to your strategy.

### Shared sections

**`[data]`**

| Key | Type | Notes |
|---|---|---|
| `kind` | `str` | `bars`, `forex_with_quotes`, or `crypto_perp_funding` |
| `dataset` | `str` | **required for `kind="bars"`** (`equity_1min`, `equity_daily`, `crypto_perp_1min`, `forex_1min`, `forex_daily`, …); inferred for derived kinds |
| `symbols` | `list[str]` | one entry = single name; many = universe panel (missing symbol raises) |
| `start` / `end` | `str` (date) | **quick run only** — strategy-visible decision/scoring window |
| `load_start` / `load_end` | `str` (date, optional) | **quick run only** — wider execution/load window; must cover `start`/`end`; omitted means same as decision window |

**`[fill_model]`** — `price` (`"close"` or `"quote"`; use `quote` for
`forex_with_quotes`), `entry_lag_bars` (int), `exit_lag_bars` (int).

**`[cost_model]`** — `fee_bps_per_side` (float), `slippage_bps_per_side` (float).

### Quick run (`experiment.toml`)

```
strategy_path, strategy_id            # top-level
[data]   kind, dataset, symbols, start, end
[params] …
[fill_model] price, entry_lag_bars, exit_lag_bars
[cost_model] fee_bps_per_side, slippage_bps_per_side
[output] results_dir, quick_checks (bool), artifact_profile, diagnostic_sample_trades (int),
         causality_check, focused_probe_limit, focused_timeout_seconds, strict_probe_limit
```

`artifact_profile`: `full` (replayable — writes input rows, decision records,
engine request, evidence), `diagnostic` (compact + `diagnostics.json`), `summary`
(compact). Only `full` is replayable from artifacts. Relative paths are
repo-root-relative (or pass `--repo-root`).

`causality_check` defaults to `"strict"` for backward compatibility. New
Train/autoresearch iteration should use `"focused"`: it runs or reuses bounded
source-hash focused causality evidence, rejects focused failures/timeouts before
scoring, and does not require full-window emitted or strict replay. Advanced
callers may still set `"emitted"` for deterministic + emitted-decision replay
without full row-grid no-emission replay, `"strict"` for audit replay, or `"off"`
for explicit profiling/debugging only. `strict_probe_limit` optionally caps
strict no-emission probes; capped strict runs are marked incomplete and do not
claim full strict replay evidence.

Quick runs can set optional `[data].load_start` / `[data].load_end` when the
engine needs extra rows outside the decision window for fills or exits. Strategy
generation, strategy-input artifacts, and causality replay still use only
`start` / `end`; execution-buffer rows are engine support, not scoreable entries.

### Validation (`validation.toml`)

```
strategy_path, strategy_id, verdict_source?   # top-level
[[windows]] id (unique), start, end           # one or more
[data]   kind, dataset, symbols               # no inline start/end
[params], [fill_model], [cost_model]
[readiness] min_observations_per_decision (int), required_observation_fields (list[str])
[output] results_dir
[search_pressure] prior_search                # e.g. "none"
[mechanical_thresholds]?                       # optional
[agreement_oracle]?                            # optional opt-in VBT single-trade check
```

`crypto_perp_funding` additionally requires `close`, `funding_timestamp`,
`funding_rate`, `has_funding_event` observations per decision. `strategy_path` and
`output.results_dir` resolve relative to the config directory.

### Evaluation (`evaluation.toml`)

```
strategy_path, strategy_id                     # top-level
[[windows]] id, start, end
[data]   kind, dataset, symbols
[params], [fill_model], [cost_model]
[metrics] annualization_periods_per_year (int), min_annualized_samples (int, default 20)
[readiness]?                                    # optional; defaults to >=1 obs + >=1 symbol per decision
[benchmark]?  symbol                            # must also be in data.symbols; passive evidence only
[[scenarios]]?  id, labels, required (bool), [scenarios.cost_model]?, [scenarios.fill_model]?
[output] results_dir
```

No `[[scenarios]]` ⇒ default fixed six-scenario cost/fill matrix per window.
`annualization_periods_per_year` must match bar cadence (e.g. minute bars
`525949`, daily `252`). Config paths resolve relative to the config directory.

---

## Result reference

Every result exposes `succeeded` — the supported success check. It is true when
the run completed and `failure_stage is None`.

### `RunResult` (quick run)

| Field | Type | Notes |
|---|---|---|
| `result_dir` | `Path \| None` | artifact directory (`None` on config-load failure) |
| `notes_path` | `Path \| None` | `notes.md` path |
| `message` | `str` | human-readable summary |
| `outcome` | `RunOutcome` | terminal status (below) |
| `evidence` | `RunEvidence` | evidence quality (below) |
| `economics` | `RunEconomics \| None` | per-trade after-cost economics, populated on completed engine runs even under compact artifact profiles |
| `succeeded` | `bool` (property) | `outcome.completed and outcome.failure_stage is None` |

**`RunOutcome`**: `completed` (bool), `failure_stage` (str|None), `assessment_status`
(str; diagnostic, e.g. `runner_failed` on failure), `promotion_eligible` (bool;
always `False`), `param_contract` (`validated` / `unvalidated_passthrough` /
`unknown`).

**`RunEvidence`**: `replayable_from_artifacts` (bool|None), `data_availability_status`
(str|None), `availability_coverage` (dict|None), `row_contract` (dict|None),
`causality` (`RunCausalityEvidence`), `focused_causality`
(`RunFocusedCausalityEvidence`), `warnings` (tuple[str, …]).
**`RunCausalityEvidence`**: `causality_check` (`off` / `emitted` / `strict` / `focused`),
`verified`, `deterministic_replay_verified`, `emitted_replay_verified`,
`strict_no_emission_verified`, `strict_replay_capped`, `strict_probe_count`,
`strict_probe_limit`, `skipped_probe_count`, and `skipped_probe_reasons`.
`verified` is true only when complete availability, emitted replay, and strict
no-emission replay all passed. Emitted-only, capped-strict, and off-policy runs
are usable only as explicitly labeled development evidence.
**`RunFocusedCausalityEvidence`**: `status`, `scoring_allowed`,
`strategy_source_sha256`, `strategy_id`, `data_kind`, `profile_version`,
`normalized_rows_sha256`, `params_sha256`, `max_probes`,
`timeout_seconds_key`, `cache_hit`, `timeout_seconds`,
`candidate_probe_count`, `selected_probe_count`, and `rejection_reason`.
For Train/autoresearch quick runs, use this focused evidence to decide whether
a source variant was eligible for scoring.

#### `RunEconomics` / `RunTrade`

`RunEconomics` is the in-process quick-run economics accessor. It is populated after
completed engine evaluation, independent of `artifact_profile`, and mirrors the same
trade-unit sample written to `summary.json` / `diagnostics.json`. It does **not** expose a
per-period return series, NAV path, or significance statistics.

| Field | Type | Notes |
|---|---|---|
| `schema_version` / `basis` | `str` | Same schema/basis markers as `summary.json["economic_metrics"]` |
| `trades` | `tuple[RunTrade, ...]` | Engine trade ledger in engine order |
| `trade_count`, win/loss/flat counts | `int` | Summary scalar counts |
| `hit_rate`, `average_trade_net`, `average_win_net`, `average_loss_net`, `profit_factor` | `float \| None` | Undeflated trade-unit scalars |
| `cost_share_of_abs_gross`, `funding_share_of_abs_gross` | `float \| None` | Cost/funding shares of absolute gross trade activity |
| `by_symbol`, `by_direction`, `by_exit_reason` | `dict[str, dict]` | Same economic slice groupings as diagnostics |
| `win_loss_distribution` | `dict[str, object]` | Largest/median/sum win-loss slice payload |
| `summary_payload()` | `dict[str, object]` | Dict equal to `summary.json["economic_metrics"]` |
| `slices_payload()` | `dict[str, object]` | Dict equal to diagnostic `economic_slices` |

`RunTrade` fields: `symbol`, `side`, `weight`, tz-aware `decision_time` /
`entry_time` / `exit_time`, `entry_price`, `exit_price`, `exit_reason`,
`gross_return`, `funding_return`, `cost_return`, `net_return`, and `decision_id`.
`net_return` is the engine after-cost value (`gross_return + funding_return -
cost_return`) for that trade.

### `ValidationRunResult`

| Field | Type | Notes |
|---|---|---|
| `result_dir` | `Path \| None` | `None` on config-load failure |
| `decision` | `ValidationPolicyDecision` | `.decision` is the advisory label; may be `mechanical_fail` |
| `message` | `str` | — |
| `run_completed` | `bool` | default `True` |
| `failure_stage` | `str \| None` | e.g. `config_load` |
| `succeeded` | `bool` (property) | `run_completed and failure_stage is None` |

`mechanical_fail` is an advisory verdict on a **successful** run, not a failure.

### `EvaluationRunResult`

| Field | Type | Notes |
|---|---|---|
| `result_dir` | `Path \| None` | — |
| `message` | `str` | — |
| `run_completed` | `bool` | default `False` |
| `failure_stage` | `str \| None` | e.g. `data_audit`, `preflight` |
| `assessment_status` | `str` | default `evaluation_failed`; `evaluation_preflight_failed` on preflight/audit fail |
| `evidence_quality_warnings` | `tuple[str, …]` | — |
| `fold_returns` | `tuple[FoldReturnSeries, …]` | per-`(window, scenario)` OOS return series, in-process (no Parquet); `()` unless completed |
| `scenario_metrics` | `tuple[FoldScenarioMetrics, …]` | per-`(window, scenario)` summary risk scalars + provenance; `()` unless completed |
| `causal_replay_passed` | `bool \| None` | Tier-0 causal-replay / decision-contract integrity: `True` on a completed run, `False` on a causal/audit failure stage (`data_audit`, `preflight`), `None` on a pre-causal failure |
| `provenance` | `Mapping[str, str]` | run provenance (backend, python + package versions, data-snapshot `normalized_rows_sha256`); `{}` unless populated |
| `succeeded` | `bool` (property) | `run_completed and failure_stage is None` |
| `window_ids` | `tuple[str, …]` (property) | distinct window ids with a completed series |
| `scenario_ids_for(window_id)` | `tuple[str, …]` | completed scenario ids for a window |
| `returns_for(window_id, scenario_id)` | `FoldReturnSeries \| None` | typed OOS return series for one fold |
| `metrics_for(window_id, scenario_id)` | `FoldScenarioMetrics \| None` | typed summary scalars for one fold |

The new fields are **additive** (all defaulted); existing programmatic consumers and
`succeeded` are unaffected. They let an in-process consumer read each fold's OOS return
series without scraping `tables/portfolio_path.parquet`. No significance statistics
(PSR/DSR/PBO) are added — significance stays with the consumer.

#### `FoldReturnSeries`

Per-`(window, scenario)` OOS return series at fixed grouped exposure, net of the
scenario's configured costs. Arrays are numpy; `values` use the same observed-return
definition as the summary metrics (drop the synthetic first return, exclude non-finite),
so they match the on-disk `period_return` trace.

| Field | Type | Notes |
|---|---|---|
| `window_id` | `str` | — |
| `scenario_id` | `str` | `"{window_id}/{cost}/{fill}"` (or `"{window_id}/{custom_id}"`) |
| `timestamps` | `np.ndarray` | `datetime64[ns]` (naive UTC), strictly increasing, aligned to `values` |
| `values` | `np.ndarray` | `float64` per-period returns (net of costs) |
| `periods_per_year` | `float` | the config's `metrics.annualization_periods_per_year` |
| `per_symbol` | `Mapping[str, FoldReturnSeries] \| None` | `None` for the current grouped cash-shared backends (no per-symbol return path is computed) |

#### `FoldScenarioMetrics`

Per-`(window, scenario)` undeflated summary risk scalars. Annualized/risk scalars honor
the annualized-metric trust boundary (they are `None` under a non-ok cadence or an
insufficient return sample), exactly as the artifact metrics.

| Field | Type | Notes |
|---|---|---|
| `window_id` / `scenario_id` | `str` | — |
| `sharpe` / `sortino` / `calmar` | `float \| None` | annualized; nulled under cadence/sample guards |
| `max_drawdown` / `worst_period_return` | `float \| None` | core economics |
| `trade_count` / `return_sample_count` | `int \| None` | — |
| `causal_ok` | `bool` | per-fold Tier-0 integrity (`True` for completed scenarios) |
| `provenance` | `Mapping[str, str]` | data-snapshot + version identity (FR-I1) |

---

## Failure stages & CLI exit codes

Stages treated as **data failures** (CLI exit `3`): `data_load`, `data_readiness`,
`observation_audit`, `data_audit`, `validation_readiness`.

| Command | `0` | `2` | `3` | `1` |
|---|---|---|---|---|
| `run` | succeeded | — | data-failure stage | any other failure |
| `validate` | succeeded, non-`mechanical_fail` | completed with `mechanical_fail` | data-failure stage | config / infra / other |
| `evaluate` | succeeded | — | data-failure stage (incl. `data_audit`) | preflight / other failure |

Other quick-run stages you may see in `failure_stage`: `config_load`,
`artifact_initialization`, `strategy_execution` (sub-stage `decision_generation`),
`causality`, `request_build`, `engine_evaluation`, `artifact_write`.

---

## Artifacts (summary)

Artifacts are evidence to inspect, not truth by construction. Generated roots
(`results/`, `validation_results/`, `evaluation_results/`) are git-ignored.

| Surface | Always written | Notable extras |
|---|---|---|
| Quick run | `config.toml`, `strategy_snapshot.py`, `run_manifest.json`, `summary.json` (with `economic_metrics`), `notes.md`, `environment.json`, `data_manifest.json` (when data loads) | `diagnostics.json` (`diagnostic`); decision records + evidence + engine request + strategy input rows (`full`) |
| Validation | `validation_config.toml`, `strategy_snapshot.py`, `decision_records.jsonl`, `data_audit.json`, `backend_runs/summary.json`, trade-ledger JSONL, `cost_fill_sensitivity.json`, `validation_decision.json`, `validation_manifest.json`, `environment.json`, `validation_report.md` | per-scenario `agreement_oracle` status; raw `agreement` only when the opt-in oracle ran |
| Evaluation | `evaluation_config.toml`, `strategy_snapshot.py`, `data_manifest.json`, `evaluation_metrics.json`, `scenario_summary.json`, `evaluation_manifest.json`, `environment.json`, `notes.md` | Parquet traces under `tables/` (requires `pyarrow`); `audit/` input rows + decision records; `evaluation_failure.json` on failure |

The exhaustive artifact inventory (per-window/per-scenario tables and their
schemas) lives in [`docs/foundation-surfaces.md`](../foundation-surfaces.md).
