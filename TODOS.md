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
  Train / iteration diagnostics should use `micro` unless a config is intentionally
  marked `off` for profiling/debugging.
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

The netted book prices crypto-perp funding today. These asset-class frictions plug
into the book's localized market-model step and remain open; several need
`quant-data` upstream fields:

- **O14** Asset-class financing realism beyond crypto-perp funding: equity
  short-borrow + dividends, FX rollover/carry, and margin financing on gross > 1
  (upstream fields: §2.4 U2–U5). Until a class is modeled, a net exposure > 1.0
  for it is a fail-closed `unfinanced_leverage` verdict (crypto perp is modeled,
  so it is exempt), so unpriced leverage stays non-scoreable.
- **O15** Capacity / ADV / market-impact sizing: unmodeled, and no `volume` field
  exists to size against liquidity (upstream field: §2.4 U1).
- **O16** Intrabar OHLC stop fills: `RiskRule` thresholds are evaluated on the
  configured end-of-bar fill-price sample, not as intrabar high/low barrier orders.
- **O17** Survivorship / corporate-action certification in the data manifest: the
  row contract now rejects look-ahead stamps (`available_at < timestamp`), but
  survivorship and corporate-action (split/dividend/delisting) integrity is
  `quant-data`-owned and has no field to certify in the manifest today. Adding a
  certification field is an upstream `quant-data` contract addition; this repo would
  consume and surface it once it exists. (Closes the upstream half of review No. 11.)

### 2.4 Upstream `quant-data` Field/Contract Requests

These foundation follow-ons are blocked on data this repo does not own (`L8`):
each is a field or manifest-contract addition `quant-data` must materialize before
the corresponding market-model term can be priced or the gate can certify. Each is
an upstream contract addition that this repo consumes and surfaces once it lands;
revisit the `L9` version bound when consuming it. Raise each with Season as upstream
feedback. (Not all foundation gaps are upstream-blocked — review No. 6 causality
scoreability and No. 8 / `O16` intrabar OHLC stop fills need no new field; build
those in-repo.)

- **U1 `volume` (per-bar traded volume).** Non-negative float at the OHLC cadence.
  Unblocks capacity / ADV / market-impact sizing (`O15`, review No. 3): notional-vs-ADV
  turnover diagnostics and a size-aware impact term. Until it lands, capacity is
  unmodeled and quick runs should stamp the absence explicitly rather than imply safety.
- **U2 Equity short-borrow rate (+ availability).** Per-symbol, point-in-time
  annualized borrow fee, ideally with a locate/availability flag. Unblocks equity
  short-borrow pricing (`O14`, review No. 7); without it a long/short equity book is
  scored as if shorting is free below net 1.0.
- **U3 Dividend events.** Per-symbol ex-date + cash amount (subset of the
  corporate-action feed). Unblocks dividend accrual on held equity positions
  (`O14`, review No. 7).
- **U4 FX rollover / swap points.** Per-pair, point-in-time swap points (or the rate
  differential to derive them). Unblocks overnight FX carry/rollover pricing
  (`O14`, review No. 7); carry can be the entire edge or loss of an FX strategy.
- **U5 Margin-financing rate.** Point-in-time financing rate (benchmark + spread) to
  charge financing on book gross > 1 for non-perp classes (`O14`, review No. 7). Until
  U2–U5 land, a non-financed class above net 1.0 stays a fail-closed
  `unfinanced_leverage` verdict — the gap is fenced, but those strategies are
  non-scoreable rather than honestly priced.
- **U6 Survivorship / corporate-action certification.** A data-manifest field
  certifying the panel is survivorship-bias-free and corporate-action-adjusted
  (splits/dividends/delistings). Same item as `O17` (upstream half of review No. 11);
  the in-repo row contract already rejects `available_at < timestamp` look-ahead.

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

## 6. Stale-Reference Checks

Use these when updating foundation docs:

```bash
rg -n "FOUNDATION_LOCK|accepted_debt|deferred_until_trigger|broad blind|delta reviews|quick run|validation run" FOUNDATION_LOCK.md docs/reviews/README.md TODOS.md
```

Also run a stale-reference grep across active docs for removed dated review
anchors and stale process/guide wording; it should return no matches.
