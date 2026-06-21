# Foundation Lock

This file records the locked foundation contracts for `quant_strategies`. Use it
as the disposition anchor for future reviews: raise regressions and new issues,
but do not reopen accepted tradeoffs unless a documented trigger occurs.

## Foundation Contract (north star)

The unit of simulation is **one causal, single-account portfolio**, not an
isolated trade. A strategy declares a **target book** — standing, signed base
target shapes per instrument (`0` = flat/close), idempotent so same-symbol
exposure nets and cannot stack, with optional declared price-path `RiskRule`s.
The foundation normalizes that shape, applies the operator `[risk_budget]`, and
the engine folds the final executable weights into **one netted, financed, marked
book** on every surface (`netted_portfolio_book_v1`) and scores its **NAV path**:
the netted single-account portfolio NAV path is the single authoritative scored
unit, and the per-trade ledger is a derived attribution view of the same walk. An
envelope breach (over the operator-frozen risk budget or leverage budget,
unpriced, unsupported, or missing capacity evidence, a capacity participation-limit
breach, zero-cost or zero-slippage on a scoreable run, unfinanced leverage, or a
degenerate sample) is a typed
**fail-closed** feasibility verdict that makes `succeeded=False` — never clamped,
never a silent `None`. See `PRD.md` G8 and `AGENTS.md`.

## Locked Contracts

- **Implemented public surfaces:** the project currently exposes quick run,
validation run, and evaluation run. Quick run is diagnostic; validation run is
mechanical evidence validation; evaluation run is stateless frozen-candidate
portfolio, path, and economic evidence.
- **Target-book decision contract:** strategies emit `TargetDecision`s — per
instrument and as of a causal time, a standing **signed base target shape** (`0` =
flat/close) that holds until the next decision for that symbol changes it.
Targets are **idempotent** (re-emitting the current shaped target trades nothing),
so signal-stacking is structurally inexpressible. The foundation normalizes the
shape by maximum intended raw gross exposure and applies `[risk_budget]` to produce
final executable weights. Data/time-derivable exits are explicit `target=0`
decisions; price-path exits are a declared `RiskRule`
(stop-loss / take-profit / trailing) enforced by the engine on the net position,
which latches the instrument flat until the strategy emits a new (different)
target. `RiskRule` barriers are evaluated against the bar's **intrabar range**
(high/low) and fill at the barrier level, worsened to the bar open on a gap-through
(`take_profit` takes no gap-favorable bonus; an adverse barrier wins a same-bar tie).
A diagnostic `fill_stress` scenario applies extra adverse barrier-exit slippage and
never changes the climbed `realistic_costs` path.
- **One netted-book accounting spine:** all three surfaces use one shared
decision/spec kernel **and one shared causal netted portfolio book**
(`netted_portfolio_book_v1`). A single bar-by-bar walk nets same-symbol exposure
to a running per-symbol quantity, trades only the final sized delta against one
shared cash/margin account through a market model (costs/fills/funding), and marks
to market to produce one NAV path. There is no separate price-evidence fork by
surface or data kind; evaluation adds only Parquet trace serialization around the
same pure book.
- **Risk-budget sizing:** quick-run, validation, and evaluation configs require
`[risk_budget]` with explicit `annualization_periods_per_year`. Train quick runs
may use `mode = "calibrate_vol"` with `target_volatility`; retained validation and
evaluation use `mode = "fixed_scale"` with the positive `book_scale` recorded in
the Train `PortfolioSizingReport`. Validation and evaluation reject
`calibrate_vol`. Capacity-bound Train calibration is recorded on the sizing report,
not encoded as a feasibility failure when the final frontier-sized book is
feasible.
- **Book-scale homogeneity invariant:** the book scale `s` multiplies the declared
signed target shape. Intended gross/net exposure is that shape times `s` —
NAV-independent and exactly degree-1 — so the leverage frontier is closed-form (`min`
over gross/net of operator budget / normalized exposure) and needs no walk. Realized
quantities (executed notional, capacity participation, turnover, at-risk-return
volatility) are only **first-order** degree-1 in `s`: positions are sized from live
equity, so a residual from NAV compounding and market-impact cost makes them
approximately, not exactly, linear. They are monotone increasing in `s`. `book_scale` is therefore derived from the
analytic frontier and a linear seed, then refined by a safeguarded bracketed secant
that verifies every candidate with a real walk and returns only a verified-feasible,
verified-within-target scale — never less conservative than a verified point, since
the residual can locally kink participation or volatility. The fail-closed verdicts
are unchanged; scale-independent breaches (unpriced short/financing, missing volume,
capacity off) fail at every positive `s`.
- **Internal engine boundary:** `quant_strategies.engine` is an internal
execution kernel for quick-run and validation internals/tests, not a fourth
public user surface.
- **Strategy shape:** strategies are flat, single-file, pure strategy modules.
- **Strategy rationale:** each strategy module docstring states thesis,
observables, rule, assumptions, provenance, and falsifier.
- **Quick run:** quick run diagnoses one strategy version and returns quick-run
evidence. It is not validation.
- **Validation run:** validation requires `validate_params` and returns advisory
retained-candidate mechanical evidence. It is not quant strategy evaluation.
The verdict backend is the single netted-book spine (`verdict_source = "engine"`
only).
- **Evaluation run:** evaluation uses
`quant-strategies evaluate candidates/<candidate_id>/evaluation.toml` or
`quant_strategies.evaluation.run_evaluation` and returns
`EvaluationRunResult`. It writes detailed trace artifacts as Parquet through
`pyarrow`.
- **Per-fold return-series accessor:** `EvaluationRunResult` exposes the
per-`(window, scenario)` out-of-sample return series typed and in-process —
`fold_returns` (`FoldReturnSeries`: numpy `timestamps`/`values`,
`periods_per_year`, `per_symbol`), `scenario_metrics` (`FoldScenarioMetrics`:
undeflated `sharpe`/`sortino`/`calmar`/`max_drawdown`/`worst_period_return`/
`trade_count`/`return_sample_count` + `causal_ok` + `scoreability_bearing` +
`feasibility` + `sizing_report` + `provenance`),
`causal_replay_passed`, `provenance`, and the `returns_for`/`metrics_for`/
`window_ids`/`scenario_ids_for` helpers. This lets consumers read per-fold OOS
returns without scraping `tables/portfolio_path.parquet`; the `values` reuse the
existing observed-return semantics (drop synthetic first return, exclude
non-finite) and honor the annualized-metric trust boundary. Quick run and
evaluation expose return statistics and score inputs; significance statistics
(PSR/DSR/PBO), search-pressure interpretation, and final score policy stay with
the consumer (`quant_autoresearch`).
- **Decision/spec kernel and shared accounting:** the public surfaces use one
shared decision/spec kernel and one shared accounting book — the single causal
netted portfolio book (`netted_portfolio_book_v1`) on quick run, validation, and
evaluation. There are no separate per-surface price-evidence paths.
- **Scored unit:** the netted single-account portfolio NAV path is the single
authoritative scored unit; the per-trade ledger is a derived attribution view of
the same book walk, kept first-class for alpha / information-coefficient research
but never an independent scored number.
- **Feasibility verdict:** an envelope breach is a typed, **fail-closed**
feasibility verdict, not a clamp and not a silent `None`. Intended gross/net over
the operator-frozen leverage budget, unpriced, unsupported, or missing capacity
evidence, a capacity participation-limit breach, a zero-cost or zero-slippage
scoreable run, unfinanced leverage on an unmodeled asset class, or a statistically
degenerate
sample makes the run infeasible / non-scoreable with an actionable typed reason
(`leverage_budget_breach` + observed gross, `capacity_unpriced`,
`capacity_unsupported_volume_semantics`, `capacity_missing_volume`,
`capacity_insufficient_adv_history`, `capacity_limit_breach`, `zero_cost`,
`zero_slippage`, `unfinanced_leverage`, `insufficient_samples`); a benign data gap
and an internal
error remain distinguishable verdicts. `RunResult.succeeded` is gated on the
verdict, and a breach sets `failure_stage`.
- **Capacity/ADV/market impact:** ADV capacity is enforced for supported bars and
crypto-perp data through the operator-frozen `[capacity_model]` envelope. ADV
impact charges the single NAV cash path and emits compact quick-run diagnostics
plus evaluation `execution_events` traces. `forex_with_quotes` is explicitly
unsupported for ADV impact because FX `volume` is tick-count activity, not
calibrated notional liquidity.
- **At-risk-bar statistics:** foundation return statistics are computed over the
bars on which capital is actually deployed (at-risk bars), not a zero-padded
union-of-timestamps calendar; flat bars do not inflate the effective sample. A
subwindow or full-Train statistic is scoreable only when its at-risk return
sample meets the configured minimum; below it the statistic is reported
non-scoreable with a typed reason rather than emitted as a finite number from
sample count alone.
- **Strategy readiness:** a strategy may be quick-run-only. A strategy is not
validation/evaluation-ready until it has `validate_params`, passes the relevant
row-contract and causality checks, and does not depend on future rows during
signal generation.
- **Result success:** programmatic consumers should prefer `result.succeeded`.
It is derived from `completed` / `run_completed` being true, `failure_stage is
None`, and a feasible book (no fail-closed envelope breach); the underlying
fields remain the audit detail.
- **Promotion boundary:** validation does not authorize paper trading, live
trading, or promotion. Promotion remains outside this foundation.
- **Evaluation boundary:** evaluation is not validation and does not authorize promotion, paper trading, or live trading. Benchmark-relative metrics are evidence only and do not authorize ranking or promotion.
- **Annualized metric trust boundary:** annualized/risk metrics are guarded by
  annualization cadence (`annualization_cadence.status == "ok"`) and the
  minimum return-sample floor `[metrics].min_annualized_samples` (default
  `20`). Any non-ok cadence status or insufficient samples null `annualized_return`,
  `volatility`, `sharpe`, `sortino`, and `calmar` without nulling core
  economics. Sortino uses downside semivariance over the full return sample and
  returns `None`, not infinity, when undefined.
- **Causality and audit boundary:** usable validation and evaluation evidence
requires a passed row contract, decision-row / observation-dependency audit, and
complete deterministic, emitted, and strict suppression replay proof. Evaluation
must not be weaker than validation on decision lineage before portfolio metrics
are trusted. hidden-lookahead replay proves point-in-time causal replay; it does
not prove out-of-sample validity and it does not prove freedom from in-sample
fitting.
- **Causality scoreability gate:** `causality_check="off"` runs no look-ahead replay
and is **non-scoreable by default** — the run fails closed with
`failure_stage="causality"` rather than scoring on unverified look-ahead. Replay
modes (`micro`/`emitted`/`focused`/`strict`) are scoreable only when replay does
not detect a causality violation. In `micro`, timeout or incomplete probe evidence
may still score but is non-retainable. The override is the operator-frozen
`[causality_policy] allow_unverified_scoring` (default `false`), never an
agent-editable `[output]` key.
- **Archive boundary:** ranked research handoff archives and search-loop records
do not live in this repository. This repo keeps no pointer, symlink,
compatibility path, or archive index for moved research records.
- **Auto-research boundary:** `quant_autoresearch` owns candidate generation,
search memory, variant ranking, stopping rules, and iteration decisions.
`quant_strategies` evaluates supplied strategies and configs.
- **Data boundary:** `quant_data` owns data acquisition, materialization,
refresh, backfill, repair, and source joining. Package metadata bounds the
supported `quant-data` contract as `>=0.1.0,<0.2.0`. `quant_data` owns
deterministic row ordering and the causal `available_at` stamp for supplied
rows; `quant_strategies` consumes the strategy contract loaders (always strict),
preserves the supplied row order for strategy input, hashing, and execution, and
does not sort rows locally before hashing or execution. `available_at` is an
unconditional hard requirement on every row in quick run, validation, and
evaluation; causal replay gates valid rows strictly on `available_at <= decision_time`,
and a missing/invalid `available_at` fails the row contract rather than the
lookahead guard.
- **Funding basis:** funding is computed once, in the single shared netted
portfolio book, as a NAV cashflow on the net held position — one funding
implementation across quick run, validation, and evaluation. Fillable
crypto perp windows with no funding events in the open interval accrue zero
funding; flagged funding rows still fail when malformed, conflicting, or
mark-misaligned.
- **Artifact boundary:** generated artifacts are evidence, not truth. Compact  
quick-run artifacts are intentionally not full replay chains.

## Run Readiness

The active codebase holds these run-readiness contracts:

- **Evaluation audit parity:** evaluation runs the same decision-row /
observation-dependency audit as validation before portfolio metrics and
artifacts are trusted.
- **Fillability lives in the engine:** fillability and hold-window feasibility
are enforced in execution/evaluation logic, not in strategy signal generation.
- **Evaluation final-value semantics:** completed evaluation scenarios require
`ending_value` to be the actual final portfolio value; a missing, NaN, or
infinite final value fails the scenario.
- **Candidate readiness:** strategies under `candidates/` are research
candidates and declare the target-book contract; validation and evaluation
require `validate_params`. Candidate folders remain research candidates until
Season explicitly promotes or renames them.
- **Evaluation evidence contract:** evaluation runs the single shared netted
portfolio book, configs may opt into custom `[[scenarios]]`, and optional
`[benchmark]` metrics add passive benchmark and excess return evidence only.
- **Annualized/risk metric guards:** completed evaluation artifacts keep the
annualized/risk metrics family null unless cadence matches and
`return_sample_count` meets the configured minimum return-sample floor,
`[metrics].min_annualized_samples`.
- **Default verification:** `make check` refreshes the editable install, checks
the installed CLI, and runs the full pytest suite. Evaluation needs only
`pandas` and `pyarrow` (the `[evaluation]` extra) for Parquet trace
serialization; the accounting path is the pure-Python spine book.
- **Quick-run failure semantics:** runner-stage failures return
`RunOutcome.completed=False`, set `failure_stage`, and write `summary.json`
with `run_completed=false`.
- **Data dependency boundary:** `quant-data` is version-bounded as
`>=0.1.0,<0.2.0` to guard the upstream data contract.
- **Consumer contract:** `quant_autoresearch` consumes the public
`run_config`, `run_validation`, and `run_evaluation` APIs. Candidate ranking,
comparison, search memory, stopping rules, and promotion remain outside this
repo.

Run with targeted configs and use disposition-aware delta reviews for new
issues; run a broad foundation review only when Season asks for one.

## Accepted Debt

- Large facade modules are not immediate foundation blockers.
- No independent cross-check of the spine's accounting exists today; a
  netted-book agreement oracle (a second implementation that must agree with the
  spine) is a named follow-on. The spine's correctness is guarded by the
  NAV↔ledger reconciliation test and the at-risk-bar / feasibility-verdict test
  suite.
- Asset-class financing realism beyond crypto-perp funding (equity
  short-borrow/dividends, FX rollover/carry, margin financing on gross > 1) and
  richer venue/order-execution modeling beyond the current ADV-impact envelope
  remain follow-ons that plug into the book's localized friction step; an
  `unfinanced_leverage` fail-closed verdict keeps unpriced-leverage books
  non-scoreable until they land.
- Runtime sandboxing is deferred unless strategy code becomes untrusted.

## Approved Next Direction

- Preserve the contract: docs distinguish quick run, mechanical evidence
validation, and research evaluation without renaming current CLI commands,
package paths, or artifact names.
- Keep the quick-run Python result model nested as `RunResult.outcome` and
`RunResult.evidence`; do not add flat compatibility aliases to the result model.
- Keep research evaluation as the term for stateless frozen-candidate evidence;
do not use it to mean the auto-research loop.
- Keep the stateless research evaluation surface separate from validation and  
quick-run hot paths.
- Rerun affected artifacts after foundation contract changes instead of carrying
compatibility shims for old generated outputs.

## Deferred Until Trigger

- **Mid-pipeline artifact I/O failures:** per-window rows, per-scenario
decision/trade-ledger records, and data manifests written while a validation
run is progressing still raise to direct API callers. Revisit if these writes
become a practical reliability issue or if validation artifact durability
requirements tighten.
- **Independent netted-book cross-check:** the spine has no independent
accounting cross-check today. A second, independent netted-book implementation
that must agree with the spine is the bar before any cross-check evidence is
treated as verification. Any such implementation is a cross-check only, never a
divergent money-model routed by data kind.
- **Validation/evaluation source output paths:** validation and evaluation
configs still anchor `output.results_dir` beside the config so candidate-local
workspaces keep working. Revisit source-directory rejection only if config path
ownership is redesigned.

## Review Protocol

Future foundation reviews should be disposition-aware delta reviews by default.
Classify findings as one of:

- `new`
- `regression`
- `fixed`
- `accepted_debt`
- `deferred_until_trigger`
- `false_positive`
- `superseded`

Run a fresh broad blind foundation review only when Season explicitly asks for
one.
