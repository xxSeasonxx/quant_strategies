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
| `quant_strategies.runner.RunEconomics` / `RunTrade` | dataclass | Typed per-trade attribution ledger (derived from the book) + summary/slice economics |
| `quant_strategies.validation.run_validation` | function | Run the validation surface |
| `quant_strategies.validation.ValidationRunResult` | dataclass | Validation result type |
| `quant_strategies.evaluation.run_evaluation` | function | Run the evaluation surface |
| `quant_strategies.evaluation.EvaluationRunResult` | dataclass | Evaluation result type |
| `quant_strategies.evaluation.FoldReturnSeries` / `FoldScenarioMetrics` | dataclass | Typed per-fold OOS return series + summary scalars on the evaluation result |
| `quant_strategies.evaluation.EvaluationConfig` / `EvaluationScenarioConfig` / `BenchmarkConfig` | model | Evaluation config models (for typed construction) |
| `quant_strategies.decisions.TargetDecision` | model | The target-book decision your strategy returns |
| `quant_strategies.decisions.RiskRule` | model | Optional declared engine-enforced price-path exit |
| `quant_strategies.decisions.InstrumentRef` (alias `DecisionInstrument`) | model | Instrument reference |
| `quant_strategies.decisions.ObservationRef` | model | Declared observation evidence |
| `quant_strategies.decisions.InstrumentKind` | literal type | Allowed instrument-kind enum values |
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
| `generate_decisions` | all surfaces | `(rows: Sequence[Mapping], params: Mapping) -> Sequence[TargetDecision]` | Pure; reads only `rows`/`params`; emits the full target-book timeline up front; no I/O, engines, clocks, RNG, or loops with side effects |
| `validate_params` | validation, evaluation (optional for quick run) | `(params: Mapping) -> Mapping` | Returns normalized params or raises on invalid input |

Plus a module docstring with: **Source / provenance** (specific), **Market
rationale**, **Required observables**, **Decision rule**, **Assumptions**,
**Falsifier**.

---

## Decision schema

`TargetDecision` and its components are frozen, strict Pydantic models with
`extra="forbid"`. The decision is a **standing, signed weight-of-NAV target** per
instrument; there is no `open`/`close`/`direction` enum, no sizing-kind, and no
welded exit policy. Enum (Literal) values:

| Type | Allowed values |
|---|---|
| `InstrumentKind` | `equity_or_etf`, `fx_pair`, `crypto_perp` |

### `TargetDecision`

| Field | Type | Default | Rule |
|---|---|---|---|
| `strategy_id` | `str` | — | non-empty |
| `instrument` | `InstrumentRef` | — | — |
| `decision_time` | `datetime` | — | timezone-aware; the bar the target becomes effective |
| `as_of_time` | `datetime` | — | timezone-aware; **`as_of_time <= decision_time`** |
| `target` | `float` | — | finite signed weight of NAV: `+` long, `−` short, `0` = flat/close; standing + idempotent |
| `risk_rule` | `RiskRule \| None` | `None` | optional engine-enforced price-path exit on the net position |
| `observations` | `tuple[ObservationRef, ...]` | `()` | declare the rows the rule used |
| `metadata` | `Mapping[str, Any]` | `{}` | must be JSON-compatible; frozen on construction |
| `decision_id` | `str \| None` | auto | derived deterministically from content if `None` |

A target is **standing** (holds until the next decision for that instrument), sizes
to a held **quantity** at its decision bar (weight drifts with the mark between
decisions — hold a constant weight by emitting explicit rebalancing decisions), and
is **idempotent** (re-emitting the current target trades nothing). Same-symbol
targets net to the latest value; additive stacking is structurally inexpressible.
A `target` whose intended gross/net exceeds the operator-frozen leverage budget is a
valid decision — it is handled by the fail-closed feasibility verdict, not rejected
as an unsupported shape.

### `InstrumentRef`

| Field | Type | Rule |
|---|---|---|
| `kind` | `InstrumentKind` | one of the enum values |
| `symbol` | `str` | non-empty |

### `RiskRule`

An optional declared price-path exit the engine enforces causally on the net
position, flattening the instrument at the bar a threshold is crossed and **latching
it flat** until the strategy emits a new (different) target. Thresholds are
**fractions of the position's entry mark** (e.g. `stop_loss=0.05` = 5% adverse), not
bps, and are evaluated against the bar's **intrabar range** (high/low) — a barrier
pierced intrabar fires even if the close recovered. The exit fills at the barrier level,
worsened to the bar open on a gap-through; `take_profit` fills at the level with no
gap-favorable bonus, and an adverse barrier (`stop_loss`/`trailing`) wins a same-bar tie
with `take_profit`. Data/time exits (signal reversal, fixed hold horizon) are expressed
as explicit `target=0` decisions, not `RiskRule`s.

| Field | Type | Default | Rule |
|---|---|---|---|
| `stop_loss` | `float \| None` | `None` | if set: finite, `> 0` (fraction of entry mark) |
| `take_profit` | `float \| None` | `None` | if set: finite, `> 0` (fraction of entry mark) |
| `trailing` | `float \| None` | `None` | if set: finite, `> 0` (fraction of entry mark) |

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

**`[capacity_model]`** — required on quick run, validation, and evaluation.
Operator-frozen, peer to `[fill_model]` / `[cost_model]` / `[leverage_budget]`.
`mode = "adv_impact"` requires `portfolio_notional > 0`,
`adv_lookback_bars`, `adv_min_observations <= adv_lookback_bars`,
`max_bar_participation`, `max_adv_participation`, `impact_coefficient_bps`, and
`impact_exponent`; supported `bars` and `crypto_perp_funding` row contracts require
positive `volume`. `mode = "off"` is explicit, but a traded book is non-scoreable
via `capacity_unpriced`. `forex_with_quotes` with ADV impact is unsupported and
fails with `capacity_unsupported_volume_semantics`.

**`[leverage_budget]`** — `max_gross_exposure` (float, default `1.0`, `>= 1.0`),
`max_net_exposure` (float, default `1.0`, `>= 1.0`). Operator-frozen, peer to
`[fill_model]`/`[cost_model]` (**not** an agent-editable `[output]` key). Intended
gross/net exposure above either ceiling is non-scoreable via the feasibility verdict
(`leverage_budget_breach`), never clamped to fit; the default `1.0/1.0` admits an
unlevered book only, so a strategy that runs gross > 1 requires the operator to raise
the ceiling.

### Quick run (`experiment.toml`)

```
strategy_path, strategy_id            # top-level
[data]   kind, dataset, symbols, start, end
[params] …
[fill_model] price, entry_lag_bars, exit_lag_bars
[cost_model] fee_bps_per_side, slippage_bps_per_side
[capacity_model] mode, portfolio_notional, adv_lookback_bars, adv_min_observations,
                 max_bar_participation, max_adv_participation,
                 impact_coefficient_bps, impact_exponent
[leverage_budget] max_gross_exposure, max_net_exposure
[envelope] operator_frozen
[causality_policy] allow_unverified_scoring
[output] results_dir, quick_checks (bool), artifact_profile, diagnostic_sample_trades (int),
         causality_check, micro_probe_limit, micro_timeout_seconds,
         focused_probe_limit, focused_timeout_seconds, strict_probe_limit,
         foundation_subwindows, foundation_cost_stress_multiplier,
         foundation_fill_stress_fraction
```

`foundation_subwindows` is bounded to 1-64.
The portfolio **leverage budget (gross and net) lives in the operator-frozen
`[leverage_budget]` section** (above), not an agent-editable `[output]` key — there
is no `foundation_max_gross_exposure` field.
Intended exposure beyond the budget is non-scoreable via the feasibility verdict
(`leverage_budget_breach`), never clamped to fit.

`artifact_profile`: `full` (replayable — writes input rows, decision records,
engine request, evidence), `diagnostic` (compact + `diagnostics.json`), `summary`
(compact). Only `full` is replayable from artifacts. `strategy_path` is
resolved relative to the TOML file so candidate-local configs can use
`strategy_path = "strategy.py"`. `output.results_dir` remains repo-root-relative
and must live under ignored `results/`.

**Causality scoreability gate.** A `causality_check` of `"off"` runs no look-ahead
replay, so by default its NAV path is **non-scoreable** — the run fails closed with
`failure_stage="causality"` rather than scoring on unverified look-ahead. Every mode that
runs some replay (`micro`/`emitted`/`focused`/`strict`) remains scoreable. The override
lives in the operator-frozen **`[causality_policy]`** section: `allow_unverified_scoring`
(bool, default `false`) re-admits `off` to scoring for deliberate profiling/debugging. It
is **not** an agent-editable `[output]` key, so a climbing agent cannot relax the gate.

`causality_check` defaults to `"micro"`: it runs a tiny bounded replay sample,
records probe/timeout evidence, and never blocks quick-run scoring. Micro evidence
is diagnostic and does not by itself make a quick run retainable; read
`RunResult.retainable` before advancing evidence.
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
[params], [fill_model], [cost_model], [capacity_model], [leverage_budget]
[readiness] min_observations_per_decision (int), required_observation_fields (list[str])
[causality_replay]? scope = "complete" | "bounded", probe_limit, timeout_seconds
[output] results_dir
[search_pressure] prior_search                # e.g. "none"
[mechanical_thresholds]?                       # optional
```

`verdict_source` accepts only `"engine"` (the netted-book spine).

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
[params], [fill_model], [cost_model], [capacity_model], [leverage_budget]
[metrics] annualization_periods_per_year (int), min_annualized_samples (int, default 20)
[causality_replay]? scope = "complete" | "bounded", probe_limit, timeout_seconds
[readiness]?                                    # optional; defaults to >=1 obs + >=1 symbol per decision
[benchmark]?  symbol                            # must also be in data.symbols; passive evidence only
[[scenarios]]?  id, labels, required (bool), scoreability_bearing (bool),
                 [scenarios.cost_model]?, [scenarios.fill_model]?
[output] results_dir
```

Evaluation defaults to complete replay. Use `[causality_replay] scope = "bounded"`
only when the run should produce portfolio evidence with bounded replay
provenance. In bounded replay, `probe_limit` caps representative row-anchor
probes; emitted-decision replay is still included.

No `[[scenarios]]` ⇒ default fixed six-scenario cost/fill matrix per window.
Default zero-cost scenarios are diagnostic (`scoreability_bearing=false`);
realistic, stressed-cost, and fill-lag scenarios are scoreability-bearing.
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
| `economics` | `RunEconomics \| None` | per-trade attribution ledger **derived from the book walk**, populated on completed engine runs even under compact artifact profiles |
| `foundation` | `RunPortfolioFoundation \| None` | the **authoritative scored portfolio book** (NAV path + scenario metrics); the book is mandatory, so this is populated on every completed, feasible run and is `None` only when the run failed before/at the book (e.g. a feasibility breach) |
| `feasibility` | `FeasibilityVerdict \| None` | typed fail-closed verdict; `None` when the run failed before the book was built; on a breach carries `reason` + observed exposure and maps to a `feasibility` `failure_stage` |
| `succeeded` | `bool` (property) | `outcome.completed and outcome.failure_stage is None` — i.e. **feasible and completed**; a feasibility breach sets `failure_stage="feasibility"` |
| `retainability` | `RunRetainability` | typed quick-run retention verdict: `retainable`, `reason`, and `detail` |
| `retainable` | `bool` (property) | true only when the quick-run evidence may advance to validation/evaluation |

**`RunOutcome`**: `completed` (bool), `failure_stage` (str|None), `assessment_status`
(str; diagnostic, e.g. `runner_failed` on failure), `promotion_eligible` (bool;
always `False`), `param_contract` (`validated` / `unvalidated_passthrough` /
`unknown`).

**`FeasibilityVerdict`**: `feasible` (bool), `reason` (str|None — one of
`leverage_budget_breach`, `zero_cost`, `unfinanced_leverage`,
`unpriced_short_financing`,
`capacity_unpriced`, `capacity_unsupported_volume_semantics`,
`capacity_missing_volume`, `capacity_insufficient_adv_history`,
`capacity_limit_breach`, `insufficient_samples`), `observed_gross` (float|None),
`observed_net` (float|None), `detail` (str|None). `.payload()` returns the
JSON-safe dict. The book is never clamped, normalized, resized, split, or collapsed
into an untyped `None` on a breach.

**`RunEvidence`**: `replayable_from_artifacts` (bool|None), `data_availability_status`
(str|None), `availability_coverage` (dict|None), `row_contract` (dict|None),
`causality` (`RunCausalityEvidence`), `focused_causality`
(`RunFocusedCausalityEvidence`), `causality_admissible` (bool; reads the causality
evidence dimension — `off` is gated to non-scoreable unless `[causality_policy]
allow_unverified_scoring` is set), `warnings` (tuple[str, …]).
**`RunCausalityEvidence`**: `causality_check` (`off` / `emitted` / `strict` / `focused` / `micro`),
`verified`, `deterministic_replay_verified`, `emitted_replay_verified`,
`strict_no_emission_verified`, `strict_replay_capped`, `strict_probe_count`,
`strict_probe_limit`, `skipped_probe_count`, `skipped_probe_reasons`,
`replay_scope`, `candidate_probe_count`, `selected_probe_count`,
`elapsed_seconds` (nullable; micro quick-run artifacts leave wall-clock duration
null to stay byte-deterministic), `timeout_seconds`, `timed_out`, and
`replay_warning`.
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

`RunEconomics` is the in-process quick-run per-trade ledger accessor. It is a
**derived attribution view** of the single portfolio book walk (each record is a
completed netted-book round-trip), populated after completed engine evaluation,
independent of `artifact_profile`, and mirrors the same sample written to
`summary.json` / `diagnostics.json`. It is **not** an independent scored number —
the foundation NAV path is the scored object; this ledger is for alpha attribution /
information-coefficient analysis. It does not expose a per-period return series, NAV
path, or significance statistics.

| Field | Type | Notes |
|---|---|---|
| `schema_version` / `basis` | `str` | Same schema/basis markers as `summary.json["economic_metrics"]`; `basis` is `portfolio_book_round_trip_attribution` |
| `trades` | `tuple[RunTrade, ...]` | Per-trade attribution ledger (one record per netted-book round-trip) |
| `trade_count`, win/loss/flat counts | `int` | Summary scalar counts |
| `hit_rate`, `average_trade_net`, `average_win_net`, `average_loss_net`, `profit_factor` | `float \| None` | Undeflated per-trade scalars |
| `cost_share_of_abs_gross`, `funding_share_of_abs_gross`, `impact_share_of_abs_gross` | `float \| None` | Cost/funding/impact shares of absolute gross attribution |
| `sum_gross_return`, `sum_funding_return`, `sum_cost_return`, `sum_impact_return`, `sum_net_return` | `float` | Ledger totals; impact is included in `sum_cost_return`; totals reconcile with the NAV path's realized PnL |
| `by_symbol`, `by_direction`, `by_exit_reason` | `dict[str, dict]` | Economic slice groupings |
| `win_loss_distribution` | `dict[str, object]` | Largest/median/sum win-loss slice payload |
| `summary_payload()` | `dict[str, object]` | Dict equal to `summary.json["economic_metrics"]` |
| `slices_payload()` | `dict[str, object]` | Dict equal to diagnostic `economic_slices` |

`RunTrade` fields: `symbol`, `side`, `weight`, tz-aware `decision_time` /
`entry_time` / `exit_time`, `entry_price`, `exit_price`, `exit_reason`,
`gross_return`, `funding_return`, `cost_return`, `impact_return`, `net_return`, and
`decision_id`.
Each is the realized after-cost attribution of one round-trip on the netted single
account, so `net_return = gross_return + funding_return - cost_return`;
`impact_return` is a component of `cost_return`, not a second subtraction, and the
ledger reconciles with the NAV path — one model of money, not two.

#### `RunPortfolioFoundation`

`RunPortfolioFoundation` is the in-process **authoritative scored portfolio book**.
Its NAV path is the single object Train scoring statistics derive from; it is not a
diagnostic side-channel. The book is mandatory, so it is populated on every completed,
**feasible** run. It carries compact full-Train and per-subwindow metrics (over
**at-risk bars**) plus the book walk (`ledger`) the derived per-trade attribution is
reconstructed from. The default scenarios are `realistic_costs`, `cost_stress`, and
`fill_stress` (the last applies adverse slippage to `RiskRule` barrier exits; it is a
diagnostic — the loop climbs `realistic_costs` — and is dropped when
`foundation_fill_stress_fraction = 0.0`). Full per-period return traces are not included
in default artifacts.

Top-level payload fields are `schema_version`
(`quant_strategies.quick_run.portfolio_foundation/v2`), `basis`
(`quick_run_netted_portfolio_book`), `evidence_class`, and `scenarios`. Each scenario
reports a typed `feasibility` payload, compact `capacity` diagnostics, a compact
`full_train` metric record, and subwindow metrics such as `return_sample_count`,
`mean_return`, `return_volatility`, `effective_sample_size`, `sharpe`,
`sharpe_standard_error`, `skew`, `kurtosis`, `total_return`,
`max_drawdown`, `closed_trade_count`, `max_symbol_concentration`, and the live
`max/mean_gross_utilization` / `max/mean_net_utilization` exposure series.

Scenario payload fields:

| Field | Type | Notes |
|---|---|---|
| `scenario_id` | `str` | `realistic_costs`, `cost_stress`, or `fill_stress` |
| `cost_multiplier` | `float` | multiplier applied to configured fee + slippage bps |
| `feasibility` | `dict` | typed verdict payload: `feasible`, `reason`, `observed_gross`, `observed_net`, `detail` |
| `capacity` | `dict` | execution event count, normalized/real turnover, impact cost, and max/mean bar and ADV participation |
| `full_train` | `dict` | compact metric record for the full Train scoring path |
| `subwindow_count` | `int` | configured `foundation_subwindows` |
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
| `closed_trade_count` | `int` | netted-book round trips (a net position returning to flat), counted by exit time |
| `max_symbol_concentration` | `float` | max symbol concentration on the netted, marked book |
| `max_gross_utilization` / `mean_gross_utilization` | `float` | live mark-to-market gross-exposure series (reported risk signal, not the fail-closed check) |
| `max_net_utilization` / `mean_net_utilization` | `float` | live mark-to-market net-exposure series |
| `return_sample_count` | `int` | finite period returns over **at-risk** (capital-deployed) bars, not a zero-padded calendar |
| `mean_return` | `float \| None` | arithmetic mean of the period-return sample |
| `return_volatility` | `float \| None` | sample standard deviation of period returns |
| `effective_sample_size` | `float \| None` | lag-one autocorrelation adjustment, capped to `[1, sample_count]` |
| `sharpe` | `float \| None` | sample Sharpe = `mean_return / return_volatility`; not annualized |
| `sharpe_standard_error` | `float \| None` | skew/kurtosis-adjusted Sharpe SE using effective sample size |
| `skew` / `kurtosis` | `float \| None` | central-moment shape inputs for Sharpe SE |
| `warnings` | `list[str]` | statistic warnings such as `insufficient_return_sample` |

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
  "schema_version": "quant_strategies.quick_run.portfolio_foundation/v2",
  "basis": "quick_run_netted_portfolio_book",
  "evidence_class": "quick_run_portfolio_foundation_diagnostic",
  "scenarios": {
    "realistic_costs": {
      "scenario_id": "realistic_costs",
      "cost_multiplier": 1.0,
      "feasibility": {
        "feasible": true,
        "reason": null,
        "observed_gross": 0.25,
        "observed_net": 0.25,
        "detail": null
      },
      "capacity": {
        "execution_event_count": 2,
        "total_normalized_turnover": 50.0,
        "total_real_turnover": 500000.0,
        "total_impact_cost": 0.0025,
        "max_bar_participation": 0.005,
        "mean_bar_participation": 0.005,
        "max_adv_participation": 0.005,
        "mean_adv_participation": 0.005
      },
      "full_train": {
        "window_id": "full_train",
        "start_time": "2024-01-01T00:00:00Z",
        "end_time": "2024-01-07T23:59:59.999999Z",
        "total_return": 0.03,
        "max_drawdown": -0.01,
        "closed_trade_count": 12,
        "max_symbol_concentration": 1.0,
        "max_gross_utilization": 0.27,
        "mean_gross_utilization": 0.21,
        "max_net_utilization": 0.27,
        "mean_net_utilization": 0.21,
        "return_sample_count": 1440,
        "mean_return": 0.00002,
        "return_volatility": 0.001,
        "effective_sample_size": 900.0,
        "sharpe": 0.25,
        "sharpe_standard_error": 0.08,
        "skew": -0.1,
        "kurtosis": 3.2,
        "warnings": []
      },
      "subwindow_count": 6,
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
  "schema_version": "quant_strategies.quick_run.portfolio_foundation/v2",
  "basis": "quick_run_netted_portfolio_book",
  "evidence_class": "quick_run_portfolio_foundation_diagnostic",
  "scenarios": {
    "realistic_costs": {
      "scenario_id": "realistic_costs",
      "cost_multiplier": 1.0,
      "feasibility": {
        "feasible": true,
        "reason": null,
        "observed_gross": 0.25,
        "observed_net": 0.25,
        "detail": null
      },
      "capacity": {
        "...": "same capacity shape as summary"
      },
      "full_train": {
        "...": "same metric shape as summary"
      },
      "subwindow_count": 6,
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
          "max_gross_utilization": 0.27,
          "mean_gross_utilization": 0.21,
          "max_net_utilization": 0.27,
          "mean_net_utilization": 0.21,
          "return_sample_count": 240,
          "mean_return": 0.00002,
          "return_volatility": 0.001,
          "effective_sample_size": 180.0,
          "sharpe": 0.25,
          "sharpe_standard_error": 0.08,
          "skew": -0.1,
          "kurtosis": 3.2,
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

The per-fold accessors let an in-process consumer read each fold's OOS return
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
| `per_symbol` | `Mapping[str, FoldReturnSeries] \| None` | `None`: the single shared book is one cash-shared account (no independent per-symbol return path is computed) |

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
| `scoreability_bearing` | `bool` | whether the scenario counts as scoreable filter evidence |
| `feasibility` | `FeasibilityVerdict` | shared-book scoreability verdict for the scenario |
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
`causality`, `request_build`, `engine_evaluation`, `feasibility` (a fail-closed
envelope breach; read `RunResult.feasibility`), `artifact_write`.

---

## Artifacts (summary)

Artifacts are evidence to inspect, not truth by construction. Generated roots
(`results/`, `validation_results/`, `evaluation_results/`) are git-ignored.

| Surface | Always written | Notable extras |
|---|---|---|
| Quick run | `config.toml`, `strategy_snapshot.py`, `run_manifest.json`, `summary.json` (with `economic_metrics` and optional compact `portfolio_foundation`), `notes.md`, `environment.json`, `data_manifest.json` (when data loads) | `diagnostics.json` (`diagnostic`, includes `economic_slices` and portfolio-foundation matrix); decision records + evidence + engine request + strategy input rows (`full`) |
| Validation | `validation_config.toml`, `strategy_snapshot.py`, `decision_records.jsonl`, `data_audit.json`, `backend_runs/summary.json`, trade-ledger JSONL, `cost_fill_sensitivity.json`, `validation_decision.json`, `validation_manifest.json`, `environment.json`, `validation_report.md` | one verdict backend (the netted-book spine); backend scenario payloads include `scoreability_bearing` and `feasibility` |
| Evaluation | `evaluation_config.toml`, `strategy_snapshot.py`, `data_manifest.json`, `evaluation_metrics.json`, `scenario_summary.json`, `evaluation_manifest.json`, `environment.json`, `notes.md` | Parquet traces under `tables/` (requires `pyarrow`); `audit/` input rows + decision records; per-scenario payloads include `required`, `scoreability_bearing`, and `feasibility`; `evaluation_failure.json` on failure |

The exhaustive artifact inventory (per-window/per-scenario tables and their
schemas) lives in [`docs/foundation-surfaces.md`](../foundation-surfaces.md).
