# Foundation Handoff TODOs

Compact active handoff for remaining foundation work.

Read first:

- `PRD.md`
- `FOUNDATION_LOCK.md`
- `docs/reviews/README.md`

## 1. Current State

Implemented public surfaces:

```text
S1 quick run                      -> diagnose one strategy version with engine-derived evidence
S2 mechanical evidence validation -> audit retained-candidate evidence integrity
S3 research evaluation            -> stateless frozen-candidate portfolio/economic/path evidence
```

Foundation contract: the strategy declares a **target book**
(`generate_decisions -> Sequence[TargetDecision]`: standing, signed weight-of-NAV
targets, idempotent, optional declared `RiskRule`). The engine folds it into **one
causal single-account netted portfolio book** on every surface
(`netted_portfolio_book_v1`); the **NAV path is the single scored object**; an
envelope breach is a typed **fail-closed** `FeasibilityVerdict` (`succeeded` = feasible
and completed). The per-trade ledger is a derived attribution view.

Current quick-run state:

- **S4** `quant-strategies run config.toml` and `quant_strategies.runner.run_config`
  return `RunResult`.
- **S5** Completed, feasible quick runs expose `RunResult.foundation` (authoritative
  scored NAV book) and the derived `RunResult.economics` attribution ledger; a
  fail-closed breach is on `RunResult.feasibility` with `failure_stage="feasibility"`.
- **S6** Quick-run configs support explicit causality policy:
  `off`, `emitted`, `strict`, `focused`, or `micro`.
- **S7** Committed candidate quick-run configs declare an explicit causality policy;
  Train / iteration diagnostics use `micro`. `causality_check="off"` runs no replay and is
  **non-scoreable by default** (typed `failure_stage="causality"`, review No. 6); the
  operator-frozen `[causality_policy] allow_unverified_scoring=true` re-admits `off` for
  profiling/debugging and is not an agent-editable `[output]` key.
- **S8** `micro` evidence is a Train/autoresearch replay annotation, not validation,
  evaluation, promotion, paper-trading, or live-trading evidence; focused evidence
  remains an advanced source-oriented quick-run mode.

Current validation/evaluation state:

- **S9** Validation and evaluation remain the stronger survivor/audit gates.
- **S10** Validation/evaluation require `validate_params`.
- **S11** Validation/evaluation default to complete causality replay and can be
  explicitly configured for bounded replay on large panels.
- **S12** Evaluation returns `EvaluationRunResult` and writes detailed Parquet traces
  through `pyarrow`.
- **S13** benchmark-relative metrics and user-defined scenario matrices are implemented;
  annualized/risk metrics remain guarded by annualization cadence and the minimum return-sample floor.

Standard verification:

```bash
make check
git diff --check
```

Run `conda run -n quant pytest -q` for final confidence when source, tests, or
public APIs changed.

## 2. Current Open Work

### 2.1 Causality Replay Downstream Follow-Up

Downstream `quant_autoresearch` full-baseline runs were blocked by focused
causality cost on large panels. The current direction is to use micro causality
for quick-run iteration so scoring is not blocked by replay timeout, while
validation/evaluation own complete or explicitly bounded replay evidence.

Observed failures:

- **O1** Full 2024-01-01 to 2025-12-31 baseline with `causality_check = "focused"`,
  `focused_probe_limit = 100`, and `focused_timeout_seconds = 60.0` crashed at
  the causality stage before engine scoring.
- **O2** That run reported `focused_causality_timeout`, `candidate_probe_count =
  5,265,156`, `selected_probe_count = 100`, and about 584.9 seconds elapsed
  before failure.
- **O3** A second full-baseline run with `focused_probe_limit = 10` and
  `focused_timeout_seconds = 180.0` also crashed at the causality stage before
  engine scoring.
- **O4** That run reported `focused_causality_timeout`, `candidate_probe_count =
  5,265,156`, `selected_probe_count = 10`, and about 699.7 seconds elapsed
  before failure.
- **O5** In both runs, no score or trades were logged because failure happened before
  engine scoring.

Issue summary:

- **O6** Probe count alone is not controlling runtime on full-panel runs.
- **O7** Each selected focused probe can still replay strategy generation on a large
  row prefix.
- **O8** Strategies that rebuild large per-symbol indexes per replay can make a small
  selected-probe count too expensive.
- **O9** Focused causality cost is still coupled to full scoring-panel size in this
  downstream path.
- **O10** The research loop should receive scored baseline evidence under micro
  replay even when replay times out or records unverified causality.

### 2.2 Evaluation Follow-Ups

The evaluation surface is implemented. Remaining follow-up work is limited to
backend limitations found during use.

Keep these facts current:

- **O11** Annualized/risk metrics are emitted only when
  `annualization_cadence.status == "ok"` and `return_sample_count` meets
  `[metrics].min_annualized_samples`.
- **O12** Non-ok cadence or insufficient samples null the annualized/risk metrics
  family without nulling core economics.
- **O13** Evaluation evidence does not authorize promotion, paper trading, or live
  trading.

### 2.3 Market-Model Follow-Ons

The netted book prices crypto-perp funding today. The remaining asset-class frictions
and capacity are **in-repo modeling**: consume the already-public `quant_data` loaders
and the catalog integrity contracts, and add a localized market-model term per
`DataKind` (mirroring `funding.py`). There are **no missing upstream contracts** — every
loader and integrity enum exists (authoritative pass, 2026-06-11). Where an item is
still blocked it is on upstream **data coverage** (a `blocked`/empty dataset), tracked in
§2.4. Read `quant_data.catalog.DATASET_STATUS[dataset]["status"]` at runtime — never
hand-copy.

- **O14** Asset-class frictions beyond crypto-perp funding (review No. 7). In-repo:
  consume the public point-in-time loaders and price the term per `DataKind`. Until a
  class is priced, a net exposure > 1.0 for it stays a fail-closed `unfinanced_leverage`
  verdict (crypto perp is modeled, so it is exempt).
  - **Dividends — in-repo, data ready.** `load_dividends` returns `ticker, ex_date,
    pay_date, declared_date, record_date, cash_amount, dividend_type, frequency`;
    `dividends` is `usable_with_caveats` (2008→2026). ⚠️ Equity OHLCV is
    `split_dividend_adjusted`, so do **not** re-add dividends on adjusted prices
    (double-count); model explicit dividend cashflows only for the short side or
    raw-price use.
  - **Equity short-borrow — modeling ready, data-coverage blocked (§2.4).**
    `load_equity_borrow_rates` returns `borrow_fee_rate, availability_status,
    shares_available, notional_available, source`, but `equity_borrow_rates` is
    `blocked` (no rows).
  - **FX rollover/carry — modeling ready, data-coverage blocked (§2.4).**
    `load_forex_rollover_rates` (`long_base_rate`/`short_base_rate`, roll dates);
    `forex_rollover_rates` is `blocked`.
  - **Margin financing on gross > 1 — modeling ready, data-coverage blocked (§2.4).**
    `load_margin_reference_rates` returns an annualized reference `rate`; the broker
    spread, compounding, and margin policy are this repo's operator-frozen envelope.
    `margin_reference_rates` is `blocked`.
- **O15** Capacity / ADV / market-impact sizing (review No. 3) — **in-repo, data present
  now.** `volume` (plus `vwap`, `num_trades`) ships in the `load_strategy_bars` locked
  schema (`symbol, timestamp, available_at, open, high, low, close, volume, vwap,
  num_trades`) and already reaches the engine rows — the repo's `to_dicts()` load path
  and `NormalizedRows` preserve every column; it simply isn't consumed yet. Add turnover
  + notional/ADV diagnostics and a size-aware impact term in the book walk; optionally
  surface `volume` in the row contract. Caveat: FX `volume` is **tick count, not
  notional** (`forex-volume-is-tick-count`), so FX capacity needs calibration first.
- **O16 (RESOLVED 2026-06-10, review No. 8)** Intrabar OHLC stop fills shipped:
  `RiskRule` stop/TP/trailing trigger on the bar's intrabar high/low and fill at the
  barrier level (worsened to the bar open on a gap-through; adverse barrier wins a
  same-bar tie). A diagnostic `fill_stress` scenario (`foundation_fill_stress_fraction`,
  default 10 bps) applies extra adverse barrier-exit slippage; the climbed
  `realistic_costs` path is unaffected by the knob.
- **O17** Survivorship / corporate-action gate (review No. 11/17) — **in-repo, fields
  present now.** The old "no machine-readable field" framing is resolved:
  `quant_data.catalog.DATASET_CONTRACTS[dataset]` exposes machine-readable
  `adjustment_status`, `survivorship_status`, `corporate_action_event_status`, and
  `caveat_ids`, and `quant_data.readiness.validate_dataset_window` is the gate. In-repo
  work: read these to fail-closed when a strategy needs a stronger contract than the
  dataset provides (equity is `not_survivorship_free`, `events_partial`). The PIT
  `available_at < timestamp` row guard already ships (review No. 11). Delisting/rename
  reconstruction uses `load_ticker_events`, whose `ticker_events` dataset is `blocked`
  (no rows) → that half waits on data coverage (§2.4).

### 2.4 Upstream `quant-data` Data-Coverage Dependencies

**No outstanding upstream contract/field requests.** Every loader and the catalog
integrity enums (`adjustment_status`/`survivorship_status`/
`corporate_action_event_status`) already exist — the prior "field request" framing was
wrong: it judged against this repo's row contract, not the `quant_data` loader surface.
The only remaining upstream dependency is **data coverage** — the loader and schema
exist but the dataset is `blocked` (zero rows), so the corresponding in-repo friction
cannot be priced until upstream **backfills** it. Read `DATASET_STATUS[dataset]["status"]`
at runtime and treat `blocked` as "modeling ready, data pending." Raise backfill priority
with Season as upstream feedback.

| Blocked dataset | Loader | Unblocks (when backfilled) |
|---|---|---|
| `equity_borrow_rates` | `load_equity_borrow_rates` | equity short-borrow pricing (`O14`, No. 7) |
| `forex_rollover_rates` | `load_forex_rollover_rates` | FX carry/rollover pricing (`O14`, No. 7) |
| `margin_reference_rates` | `load_margin_reference_rates` | margin financing on gross > 1 (`O14`, No. 7) |
| `ticker_events` | `load_ticker_events` | delisting/rename → survivorship reconstruction (`O17`, No. 17) |

Everything else the 2026-06-10 review flagged is **in-repo with data available now**:
capacity/`volume` (`O15`), dividends (`O14`), and the survivorship/corporate-action gate
(`O17`).

## 3. Locked Direction

Use `FOUNDATION_LOCK.md` as the source of truth for contracts that should not be
reopened without a regression or documented trigger.

Current locked direction:

- **L1** Public vocabulary stays: quick run, validation run, evaluation run.
- **L2** Strategies are flat pure files.
- **L3** Validation is mechanical evidence validation, advisory, and never promotion
  authority.
- **L4** Evaluation is stateless frozen-candidate portfolio/economic/path evidence.
- **L5** The scored object is the single netted-book **NAV path**; the per-trade
  ledger is a derived attribution view of that one book walk.
- **L6** Generated artifacts are evidence, not truth.
- **L7** `quant_autoresearch` owns generation, search memory, variant ranking,
  stopping rules, and iteration decisions.
- **L8** `quant_data` owns data acquisition and materialization.
- **L9** `quant-data` is bounded as `>=0.1.0,<0.2.0`.

## 4. Contained Residuals

Preserve these contained residuals unless they become active work:

- **R1** `_is_true_flag` coercion
- **R2** `not_evaluated` soft-stop
- **R3** causality's missing-`available_at` fallback
- **R4** Barrier-exit slippage on the climbed path is the uniform `slippage_bps_per_side`;
  the `zero_cost` floor guarantees only `fee+slippage > 0`, not `slippage > 0`, so a
  `fee>0, slippage=0` config is scoreable with stops filling at the level/gap-open and no
  slippage. Stop-specific extra slippage is modeled only in the `fill_stress` diagnostic,
  not the scored number (standard bar-granularity limit; the post-trigger intrabar path is
  unobservable). Optional action-3 tightening: require `slippage_bps > 0` in the cost
  floor (uniform, affects all fills) — Season-owned, not part of the No. 8 contract.

## 5. Deferred Residuals

- **D1 Mid-pipeline artifact I/O residual (low priority):** some success-path
  writes still raise raw `OSError` to direct API callers before the final
  artifact-write guard: runner `data_manifest.json`, validation per-window row
  JSONL, validation per-scenario decision JSONL, and validation per-scenario
  trade-ledger JSONL. The CLI backstops escaped filesystem errors as clean exit
  `1`. Result-directory/static artifact creation, final artifact writes, and
  `_failure_result` paths are routed to structured `failure_stage` results.
- **D2 Independent netted-book cross-check:** the spine has no independent
  accounting cross-check today. A second implementation that must agree with the
  spine — the bar before any cross-check evidence is treated as verification — is a
  named follow-on, not a current surface.
- **D3 Candidate-local output residual (low priority):** validation and evaluation
  configs still anchor `output.results_dir` beside the config so
  candidate-local workspaces keep working. Revisit rejecting outputs under
  source directories only if config path ownership is redesigned.
- **D4 `researched/` archive-boundary test removed (temporary, 2026-06-11):** review
  No. 17's "stale `researched/` artifacts" concern was a `researched/`-must-not-exist
  boundary test; it was removed because Season is actively working in `researched/`.
  The repo no longer enforces the boundary. Restore the test (or relocate the
  artifacts) once that work settles. The other repository-boundary tests
  (loop-memory markers, archive-pointer scan) are unchanged.

## 6. Stale-Reference Checks

Use these when updating foundation docs:

```bash
rg -n "FOUNDATION_LOCK|accepted_debt|deferred_until_trigger|broad blind|delta reviews|quick run|validation run" FOUNDATION_LOCK.md docs/reviews/README.md TODOS.md
```

Also run a stale-reference grep across active docs for removed dated review
anchors and stale process/guide wording; it should return no matches.
