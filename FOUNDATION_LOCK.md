# Foundation Lock

This file records the locked foundation contracts for `quant_strategies`. Use it
as the disposition anchor for future reviews: raise regressions and new issues,
but do not reopen accepted tradeoffs unless a documented trigger occurs.

## Foundation Contract (north star)

The unit of simulation is **one causal, single-account portfolio**, not an
isolated trade. A strategy declares a **target book** — standing, signed
weight-of-NAV `TargetDecision`s per instrument (`0` = flat/close), idempotent so
same-symbol exposure nets and cannot stack, with optional declared price-path
`RiskRule`s. The engine folds that book into **one netted, financed, marked book**
on every surface (`netted_portfolio_book_v1`) and scores its **NAV path**: the
netted single-account portfolio NAV path is the single authoritative scored unit,
and the per-trade ledger is a derived attribution view of the same walk. An
envelope breach (over the operator-frozen leverage budget, zero-cost on a
scoreable run, unfinanced leverage, or a degenerate sample) is a typed
**fail-closed** feasibility verdict that makes `succeeded=False` — never clamped,
never a silent `None`. See `PRD.md` G8 and `AGENTS.md`.

## Locked Contracts

- **Implemented public surfaces:** the project currently exposes quick run,
validation run, and evaluation run. Quick run is diagnostic; validation run is
mechanical evidence validation; evaluation run is stateless frozen-candidate
portfolio, path, and economic evidence.
- **Target-book decision contract:** strategies emit `TargetDecision`s — per
instrument and as of a causal time, a standing **signed weight of NAV** (`0` =
flat/close) that holds until the next decision for that symbol changes it.
Targets are **idempotent** (re-emitting the current target trades nothing), so
signal-stacking is structurally inexpressible. Data/time-derivable exits are
explicit `target=0` decisions; price-path exits are a declared `RiskRule`
(stop-loss / take-profit / trailing) enforced by the engine on the net position,
which latches the instrument flat until the strategy emits a new (different)
target.
- **One netted-book accounting spine:** all three surfaces use one shared
decision/spec kernel **and one shared causal netted portfolio book**
(`netted_portfolio_book_v1`). A single bar-by-bar walk nets same-symbol exposure
to a running per-symbol quantity, trades only the delta against one shared
cash/margin account through a market model (costs/fills/funding), and marks to
market to produce one NAV path. There is no separate price-evidence fork by
surface or data kind; evaluation adds only Parquet trace serialization around the
same pure book.
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
only); there is no alternate validation backend and no opt-in agreement
oracle.
- **Evaluation run:** evaluation uses
`quant-strategies evaluate candidates/<candidate_id>/evaluation.toml` or
`quant_strategies.evaluation.run_evaluation` and returns
`EvaluationRunResult`. It writes detailed trace artifacts as Parquet through
`pyarrow`.
- **Per-fold return-series accessor (additive):** `EvaluationRunResult` also
exposes the per-`(window, scenario)` out-of-sample return series typed and
in-process — `fold_returns` (`FoldReturnSeries`: numpy `timestamps`/`values`,
`periods_per_year`, `per_symbol`), `scenario_metrics` (`FoldScenarioMetrics`:
undeflated `sharpe`/`sortino`/`calmar`/`max_drawdown`/`worst_period_return`/
`trade_count`/`return_sample_count` + `causal_ok` + `provenance`),
`causal_replay_passed`, `provenance`, and the `returns_for`/`metrics_for`/
`window_ids`/`scenario_ids_for` helpers. This lets consumers read per-fold OOS
returns without scraping `tables/portfolio_path.parquet`; the `values` reuse the
existing observed-return semantics (drop synthetic first return, exclude
non-finite) and honor the annualized-metric trust boundary. The evaluation
accessor adds no significance statistics (PSR/DSR/PBO) — evaluation significance
stays with the consumer (`quant_autoresearch`). Quick run may emit diagnostic
Train portfolio-foundation DSR inputs/values, but they are not survivor-grade
evaluation or promotion evidence. The fields are additive and default empty/None;
`succeeded` is unchanged.
- **Decision/spec kernel and shared accounting:** the public surfaces use one
shared decision/spec kernel and one shared accounting book — the single causal
netted portfolio book (`netted_portfolio_book_v1`) on quick run, validation, and
evaluation. There are no separate per-surface price-evidence paths.
- **Scored unit:** the netted single-account portfolio NAV path is the single
authoritative scored unit; the per-trade ledger is a derived attribution view of
the same book walk, kept first-class for alpha / information-coefficient research
but never an independent scored number. (This reverses the prior lock that engine
metrics were linear signed per-trade results scored independently of NAV.)
- **Feasibility verdict:** an envelope breach is a typed, **fail-closed**
feasibility verdict, not a clamp and not a silent `None`. Intended gross/net over
the operator-frozen leverage budget, a zero-cost scoreable run, unfinanced
leverage on an unmodeled asset class, or a statistically degenerate sample makes
the run infeasible / non-scoreable with an actionable typed reason
(`leverage_budget_breach` + observed gross, `zero_cost`, `unfinanced_leverage`,
`insufficient_samples`); a benign data gap and an internal error remain
distinguishable verdicts. `RunResult.succeeded` is gated on the verdict, and a
breach sets `failure_stage`.
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
portfolio book, as a NAV cashflow on the net held position — there is one funding
implementation across quick run, validation, and evaluation, not a separate
engine vs evaluation basis and no `project_perp_ledger` money-model. Fillable
crypto perp windows with no funding events in the open interval accrue zero
funding; flagged funding rows still fail when malformed, conflicting, or
mark-misaligned.
- **Artifact boundary:** generated artifacts are evidence, not truth. Compact  
quick-run artifacts are intentionally not full replay chains.

## Current Run Readiness

As of 2026-06-04, the public architecture is not a rewrite case. The identified
P0/P1/P2 run-readiness blockers have been fixed in the active codebase:

- **Evaluation audit parity:** evaluation runs the same decision-row /
observation-dependency audit as validation before portfolio metrics and
artifacts are trusted.
- **Future-row strategy logic:** the current active strategy fixes keep
fillability and hold-window feasibility in execution/evaluation logic rather
than strategy signal generation.
- **Evaluation final-value semantics:** completed evaluation scenarios require
`ending_value` to be the actual final portfolio value; a missing, NaN, or
infinite final value fails the scenario.
- **Current strategy readiness:** current candidate strategies under
`candidates/` expose `validate_params` and have targeted validator plus
causality/data-audit tests. Candidate folders remain research candidates until
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
serialization; the accounting path is the pure-Python spine book with no
backtest-library dependency.
- **Quick-run failure semantics:** runner-stage failures return
`RunOutcome.completed=False`, set `failure_stage`, and write `summary.json`
with `run_completed=false`.
- **Data dependency boundary:** `quant-data` is version-bounded as
`>=0.1.0,<0.2.0` to guard the upstream data contract.
- **Consumer contract:** `quant_autoresearch` should consume public
`run_config`, `run_validation`, and `run_evaluation` APIs. Candidate ranking,
comparison, search memory, stopping rules, and promotion remain outside this
repo.

Start running with targeted configs and use delta reviews for new issues. Do
not run another broad blind foundation review unless Season asks for one.

## Accepted Debt

- Large facade modules are not immediate foundation blockers.
- No independent cross-check of the spine's accounting exists today. The
  single-trade agreement oracle is retired (it was single-trade-only
  and gave no multi-trade verification); a netted-book agreement oracle is a named
  follow-on. The spine's correctness is guarded instead by the NAV↔ledger
  reconciliation test and the at-risk-bar / feasibility-verdict test suite.
- Asset-class financing realism beyond crypto-perp funding (equity
  short-borrow/dividends, FX rollover/carry, margin financing on gross > 1),
  capacity/ADV/market-impact, and intrabar OHLC stop-fill realism are named
  follow-ons that plug into the book's localized friction step; an
  `unfinanced_leverage` fail-closed verdict keeps unpriced-leverage books
  non-scoreable until they land.
- Runtime sandboxing is deferred unless strategy code becomes untrusted.

## Approved Next Direction

- Preserve the clarified contract: docs should distinguish quick run,
mechanical evidence validation, and research evaluation without renaming
current CLI commands, package paths, or artifact names.
- Keep the quick-run Python result model nested as `RunResult.outcome` and
`RunResult.evidence`; do not add flat compatibility aliases for retired runner
result fields.
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
accounting cross-check today. Generalize the agreement oracle from single-trade
to the full netted book (a second implementation that must agree with the spine)
before any cross-check evidence is treated as multi-trade verification. Any
reintroduced library could only return in that role, never as a divergent money-model routed by
data kind.
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
