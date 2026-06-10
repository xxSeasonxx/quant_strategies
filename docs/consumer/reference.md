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
         causality_check, micro_probe_limit, micro_timeout_seconds,
         focused_probe_limit, focused_timeout_seconds, strict_probe_limit,
         foundation_enabled, foundation_subwindows, foundation_trial_count,
         foundation_benchmark_sharpe, foundation_cost_stress_multiplier,
         foundation_max_gross_exposure
```

`foundation_subwindows` is bounded to 1-64. `foundation_trial_count` is optional;
when omitted, foundation subwindow `dsr` values are null with a
`missing_trial_count` warning.
`foundation_max_gross_exposure` defaults to `1.0` and is bounded to values
`>= 1.0`; it controls only the quick-run portfolio foundation's active gross
target exposure limit.

`artifact_profile`: `full` (replayable — writes input rows, decision records,
engine request, evidence), `diagnostic` (compact + `diagnostics.json`), `summary`
(compact). Only `full` is replayable from artifacts. `strategy_path` is
resolved relative to the TOML file so candidate-local configs can use
`strategy_path = "strategy.py"`. `output.results_dir` remains repo-root-relative
and must live under ignored `results/`.

`causality_check` defaults to `"strict"` for backward compatibility. New
Train/autoresearch iteration should use `"micro"`: it runs a tiny bounded replay
sample, records probe/timeout evidence, and never blocks quick-run scoring.
Advanced callers may still set `"focused"` for source-hash replay,
`"emitted"` for deterministic + emitted-decision replay without full row-grid
no-emission replay, `"strict"` for audit replay, or `"off"` for explicit
profiling/debugging only. `strict_probe_limit` optionally caps strict
no-emission probes; capped strict runs are marked incomplete and do not claim
full strict replay evidence.

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
[causality_replay]? scope = "complete" | "bounded", probe_limit, timeout_seconds
[output] results_dir
[search_pressure] prior_search                # e.g. "none"
[mechanical_thresholds]?                       # optional
[agreement_oracle]?                            # optional opt-in VBT single-trade check
```

`crypto_perp_funding` additionally requires `close`, `funding_timestamp`,
`funding_rate`, `has_funding_event` observations per decision. `strategy_path` and
`output.results_dir` resolve relative to the config directory.
Validation defaults to complete replay. Use `[causality_replay] scope = "bounded"`
only for explicitly bounded large-panel research runs. In bounded replay,
`probe_limit` caps representative row-anchor probes; emitted-decision replay is
still included.

### Evaluation (`evaluation.toml`)

```
strategy_path, strategy_id                     # top-level
[[windows]] id, start, end
[data]   kind, dataset, symbols
[params], [fill_model], [cost_model]
[metrics] annualization_periods_per_year (int), min_annualized_samples (int, default 20)
[causality_replay]? scope = "complete" | "bounded", probe_limit, timeout_seconds
[readiness]?                                    # optional; defaults to >=1 obs + >=1 symbol per decision
[benchmark]?  symbol                            # must also be in data.symbols; passive evidence only
[[scenarios]]?  id, labels, required (bool), [scenarios.cost_model]?, [scenarios.fill_model]?
[output] results_dir
```

Evaluation defaults to complete replay. Use `[causality_replay] scope = "bounded"`
only when the run should produce portfolio evidence with bounded replay
provenance. In bounded replay, `probe_limit` caps representative row-anchor
probes; emitted-decision replay is still included.

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
| `foundation` | `RunPortfolioFoundation \| None` | diagnostic Train portfolio-return foundation metrics, populated on completed engine runs when enabled |
| `succeeded` | `bool` (property) | `outcome.completed and outcome.failure_stage is None` |

**`RunOutcome`**: `completed` (bool), `failure_stage` (str|None), `assessment_status`
(str; diagnostic, e.g. `runner_failed` on failure), `promotion_eligible` (bool;
always `False`), `param_contract` (`validated` / `unvalidated_passthrough` /
`unknown`).

**`RunEvidence`**: `replayable_from_artifacts` (bool|None), `data_availability_status`
(str|None), `availability_coverage` (dict|None), `row_contract` (dict|None),
`causality` (`RunCausalityEvidence`), `focused_causality`
(`RunFocusedCausalityEvidence`), `warnings` (tuple[str, …]).
**`RunCausalityEvidence`**: `causality_check` (`off` / `emitted` / `strict` / `focused` / `micro`),
`verified`, `deterministic_replay_verified`, `emitted_replay_verified`,
`strict_no_emission_verified`, `strict_replay_capped`, `strict_probe_count`,
`strict_probe_limit`, `skipped_probe_count`, `skipped_probe_reasons`,
`replay_scope`, `candidate_probe_count`, `selected_probe_count`,
`elapsed_seconds`, `timeout_seconds`, `timed_out`, and `replay_warning`.
`verified` is true only when complete availability, emitted replay, and strict
no-emission replay all passed. Emitted-only, capped-strict, and off-policy runs
are usable only as explicitly labeled development evidence.
**`RunFocusedCausalityEvidence`**: `status`, `scoring_allowed`,
`strategy_source_sha256`, `strategy_id`, `data_kind`, `profile_version`,
`normalized_rows_sha256`, `params_sha256`, `max_probes`,
`timeout_seconds_key`, `cache_hit`, `timeout_seconds`,
`candidate_probe_count`, `selected_probe_count`, and `rejection_reason`.
Focused evidence is present when focused replay is explicitly selected. For
Train/autoresearch quick runs, prefer micro replay fields on
`RunCausalityEvidence`.

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

#### `RunPortfolioFoundation`

`RunPortfolioFoundation` is the in-process quick-run portfolio-return foundation
accessor. It is diagnostic Train evidence only. It is separate from
`RunEconomics`: the latter remains a trade-unit engine ledger, while the
foundation carries compact full-Train and per-subwindow portfolio-return
metrics for downstream scoring. The default scenarios are `realistic_costs` and
`cost_stress`; full per-period return traces are not included in default
artifacts.

Important payload fields include `schema_version`, `basis`, `evidence_class`,
and `scenarios`. Each scenario reports a compact `full_train` metric record and
subwindow metrics such as `return_sample_count`, `mean_return`,
`return_volatility`, `effective_sample_size`, `sharpe`,
`sharpe_standard_error`, `skew`, `kurtosis`, `dsr_inputs`, `dsr`,
`total_return`, `max_drawdown`, `closed_trade_count`, and
`max_symbol_concentration`.
When trial-count metadata is missing, `dsr` is `None` and the subwindow warning
list includes `missing_trial_count`. `dsr_inputs` includes a `formula` field so
consumers can pin the DSR threshold convention.

Scenario payload fields:

| Field | Type | Notes |
|---|---|---|
| `scenario_id` | `str` | `realistic_costs` or `cost_stress` |
| `cost_multiplier` | `float` | multiplier applied to configured fee + slippage bps |
| `full_train` | `dict` | compact metric record for the full Train scoring path |
| `subwindow_count` | `int` | configured `foundation_subwindows` |
| `min_dsr` / `median_dsr` | `float \| None` | subwindow DSR aggregates; not the keep-rule score |
| `dsr_available_count` / `dsr_null_count` | `int` | number of subwindows with / without DSR |
| `min_closed_trade_count` | `int` | weakest subwindow closed-trade count |
| `max_symbol_concentration` | `float` | maximum subwindow symbol concentration |
| `warning_counts` | `dict[str, int]` | counts of subwindow statistic warnings |
| `subwindows` | `list[dict]` | matrix payload only; omitted from compact summary |

Metric record fields (`full_train` and each subwindow):

| Field | Type | Notes |
|---|---|---|
| `window_id` | `str` | `full_train` or `train_<n>` |
| `start_time` / `end_time` | ISO datetime | metric window bounds |
| `total_return` | `float \| None` | full Train: ending NAV / starting NAV - 1; subwindow: compounded endpoint-assigned period returns |
| `max_drawdown` | `float \| None` | local peak-to-trough drawdown, negative or zero |
| `closed_trade_count` | `int` | trades counted by exit time |
| `max_symbol_concentration` | `float` | max active gross target-weight concentration by symbol |
| `return_sample_count` | `int` | finite fixed-frequency portfolio period returns |
| `mean_return` | `float \| None` | arithmetic mean of the period-return sample |
| `return_volatility` | `float \| None` | sample standard deviation of period returns |
| `effective_sample_size` | `float \| None` | lag-one autocorrelation adjustment, capped to `[1, sample_count]` |
| `sharpe` | `float \| None` | sample Sharpe = `mean_return / return_volatility`; not annualized |
| `sharpe_standard_error` | `float \| None` | skew/kurtosis-adjusted Sharpe SE using effective sample size |
| `skew` / `kurtosis` | `float \| None` | sample-shape inputs for Sharpe SE and DSR |
| `dsr_inputs` | `dict \| None` | DSR provenance, including formula and deflated threshold |
| `dsr` | `float \| None` | optional audit statistic; null when trial count or inputs are missing |
| `warnings` | `list[str]` | statistic warnings such as `missing_trial_count` |

Consumer rules:

- `summary_payload()` and `summary.json["portfolio_foundation"]` include
  scenario summaries and `full_train`, but not `subwindows`.
- `matrix_payload()` and `diagnostics.json["portfolio_foundation"]` include the
  same scenario summaries plus `subwindows`.
- Neither payload includes raw NAV arrays, period-return arrays, position traces,
  or per-period holdings.
- PSR and final Train score are not emitted here. Downstream consumers compute
  them from `sharpe`, `sharpe_standard_error`, and protocol-owned hurdle/gate
  settings.

Compact summary shape, used by `RunPortfolioFoundation.summary_payload()` and
`summary.json["portfolio_foundation"]`:

```json
{
  "schema_version": "quant_strategies.quick_run.portfolio_foundation/v1",
  "basis": "quick_run_lightweight_portfolio_path",
  "evidence_class": "quick_run_portfolio_foundation_diagnostic",
  "scenarios": {
    "realistic_costs": {
      "scenario_id": "realistic_costs",
      "cost_multiplier": 1.0,
      "full_train": {
        "window_id": "full_train",
        "start_time": "2024-01-01T00:00:00Z",
        "end_time": "2024-01-07T23:59:59.999999Z",
        "total_return": 0.03,
        "max_drawdown": -0.01,
        "closed_trade_count": 12,
        "max_symbol_concentration": 1.0,
        "return_sample_count": 1440,
        "mean_return": 0.00002,
        "return_volatility": 0.001,
        "effective_sample_size": 900.0,
        "sharpe": 0.25,
        "sharpe_standard_error": 0.08,
        "skew": -0.1,
        "kurtosis": 3.2,
        "dsr_inputs": {
          "sample_length": 1440,
          "effective_sample_size": 900.0,
          "skew": -0.1,
          "kurtosis": 3.2,
          "trial_count": 25,
          "benchmark_sharpe": 0.0,
          "deflated_sharpe_threshold": 0.12,
          "formula": "bailey_lopez_de_prado_expected_max_sharpe"
        },
        "dsr": 0.94,
        "warnings": []
      },
      "subwindow_count": 6,
      "min_dsr": 0.94,
      "median_dsr": 0.94,
      "dsr_available_count": 6,
      "dsr_null_count": 0,
      "min_closed_trade_count": 0,
      "max_symbol_concentration": 1.0,
      "warning_counts": {}
    },
    "cost_stress": {
      "...": "same shape"
    }
  }
}
```

Diagnostic matrix shape, used by `RunPortfolioFoundation.matrix_payload()` and
`diagnostics.json["portfolio_foundation"]`, adds per-subwindow records under
each scenario:

```json
{
  "schema_version": "quant_strategies.quick_run.portfolio_foundation/v1",
  "basis": "quick_run_lightweight_portfolio_path",
  "evidence_class": "quick_run_portfolio_foundation_diagnostic",
  "scenarios": {
    "realistic_costs": {
      "scenario_id": "realistic_costs",
      "cost_multiplier": 1.0,
      "full_train": {
        "...": "same metric shape as summary"
      },
      "subwindow_count": 6,
      "min_dsr": 0.94,
      "median_dsr": 0.94,
      "dsr_available_count": 6,
      "dsr_null_count": 0,
      "min_closed_trade_count": 0,
      "max_symbol_concentration": 1.0,
      "warning_counts": {},
      "subwindows": [
        {
          "window_id": "train_1",
          "start_time": "2024-01-01T00:00:00Z",
          "end_time": "2024-01-02T00:00:00Z",
          "total_return": 0.004,
          "max_drawdown": -0.01,
          "closed_trade_count": 3,
          "max_symbol_concentration": 1.0,
          "return_sample_count": 240,
          "mean_return": 0.00002,
          "return_volatility": 0.001,
          "effective_sample_size": 180.0,
          "sharpe": 0.25,
          "sharpe_standard_error": 0.08,
          "skew": -0.1,
          "kurtosis": 3.2,
          "dsr_inputs": {
            "sample_length": 240,
            "effective_sample_size": 180.0,
            "skew": -0.1,
            "kurtosis": 3.2,
            "trial_count": 25,
            "benchmark_sharpe": 0.0,
            "deflated_sharpe_threshold": 0.12,
            "formula": "bailey_lopez_de_prado_expected_max_sharpe"
          },
          "dsr": 0.94,
          "warnings": []
        }
      ]
    },
    "cost_stress": {
      "...": "same shape"
    }
  }
}
```

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
| Quick run | `config.toml`, `strategy_snapshot.py`, `run_manifest.json`, `summary.json` (with `economic_metrics` and optional compact `portfolio_foundation`), `notes.md`, `environment.json`, `data_manifest.json` (when data loads) | `diagnostics.json` (`diagnostic`, includes `economic_slices` and portfolio-foundation matrix); decision records + evidence + engine request + strategy input rows (`full`) |
| Validation | `validation_config.toml`, `strategy_snapshot.py`, `decision_records.jsonl`, `data_audit.json`, `backend_runs/summary.json`, trade-ledger JSONL, `cost_fill_sensitivity.json`, `validation_decision.json`, `validation_manifest.json`, `environment.json`, `validation_report.md` | per-scenario `agreement_oracle` status; raw `agreement` only when the opt-in oracle ran |
| Evaluation | `evaluation_config.toml`, `strategy_snapshot.py`, `data_manifest.json`, `evaluation_metrics.json`, `scenario_summary.json`, `evaluation_manifest.json`, `environment.json`, `notes.md` | Parquet traces under `tables/` (requires `pyarrow`); `audit/` input rows + decision records; `evaluation_failure.json` on failure |

The exhaustive artifact inventory (per-window/per-scenario tables and their
schemas) lives in [`docs/foundation-surfaces.md`](../foundation-surfaces.md).
