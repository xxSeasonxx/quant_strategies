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

Foundation contract (portfolio-book-spine, 2026-06-10): the strategy declares a
**target book** (`generate_decisions -> Sequence[TargetDecision]`: standing, signed
weight-of-NAV targets, idempotent, optional declared `RiskRule`). The engine folds
it into **one causal single-account netted portfolio book** on every surface
(`netted_portfolio_book_v1`); the **NAV path is the single scored object**; an
envelope breach is a typed **fail-closed** `FeasibilityVerdict` (`succeeded` = feasible
and completed). The per-trade ledger is a derived attribution view. The legacy
alternate backend, `project_perp_ledger`, and the single-trade agreement oracle are
retired.

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

### 2.3 Live Portfolio Feasibility Issues — RESOLVED by portfolio-book-spine

These issues recorded the gap between trade-ticket Train diagnostics and
live-shaped portfolio evidence. The **portfolio-book-spine** change (2026-06-10)
resolves the cluster at the root — the atomic unit is now one causal netted
portfolio book, not an isolated trade:

- **Signal-stacking / implicit leverage (O14, O17, O20, O22)** — RESOLVED. Targets
  are idempotent signed weights of NAV; re-emitting the current target trades
  nothing and same-symbol targets net to the latest value, so additive stacking is
  **structurally inexpressible**. Returns can no longer come from stacked gross.
- **Un-netted / per-ticket exposure (O18)** — RESOLVED. The book keys a running
  signed quantity per symbol on one account; gross/net are measured on the netted,
  marked book, so portfolio-level exposure is bounded by construction, not by
  per-ticket suppression.
- **Two evidence classes / missing portfolio path (O15, O16, O19)** — RESOLVED. The
  NAV book is the single authoritative scored object; there is no separate
  trade-ticket evidence class. A breach is a typed fail-closed verdict
  (`failure_stage="feasibility"`, `succeeded=False`), not a completed run with a
  silently-missing foundation, so a quick run can no longer be misread as
  live-shaped when it is not.
- **Leverage budget fail-open (O15 root) / comparability (O21)** — RESOLVED. The
  gross+net leverage budget is operator-frozen and **fails closed** with an observed
  exposure; the book is never clamped, so a levered intent is non-scoreable rather
  than silently rescaled, and the leverage contract is explicit in the verdict.

Residual (named follow-ons, plug into the spine's market-model interface; tracked
in the change's Impact §, several need `quant-data` upstream work):

- **O23** Asset-class financing realism beyond crypto-perp funding (equity
  short-borrow + dividends, FX rollover/carry, margin financing on gross > 1) is
  still upstream. The spine guards against minting free leverage in the meantime: a
  net exposure > 1.0 for an asset class **without** modeled financing is a
  fail-closed `unfinanced_leverage` verdict (crypto-perp funding is modeled, so it
  is exempt). Capacity/ADV/impact and intrabar OHLC stop fills remain follow-ons.

## 3. Locked Direction

Use `FOUNDATION_LOCK.md` as the source of truth for contracts that should not be
reopened without a regression or documented trigger.

Current locked direction:

- **L1** Public vocabulary stays: quick run, validation run, evaluation run.
- **L2** Strategies are flat pure files.
- **L3** Validation is mechanical evidence validation, advisory, and never promotion
  authority.
- **L4** Evaluation is stateless frozen-candidate portfolio/economic/path evidence.
- **L5** *(superseded by portfolio-book-spine, 2026-06-10)* The scored object is the
  single netted-book **NAV path**, not a linear per-trade sum. The per-trade ledger
  is a derived attribution view of that one book walk.
- **L6** Generated artifacts are evidence, not truth.
- **L7** `quant_autoresearch` owns generation, search memory, variant ranking,
  stopping rules, and iteration decisions.
- **L8** `quant_data` owns data acquisition and materialization.
- **L9** `quant-data` is bounded as `>=0.1.0,<0.2.0`.

## 4. Contained Residuals

Preserve these contained residuals unless they become active work:

- **R1** *(resolved by portfolio-book-spine, 2026-06-10)* `net_return` dual semantics
  — there is now one model of money; the per-trade `net_return` is the book walk's
  realized after-cost attribution (`gross + funding − cost`) and reconciles with the
  NAV path. The retired second accounting basis is gone.
- **R2** `_is_true_flag` coercion
- **R3** `not_evaluated` soft-stop
- **R4** causality's missing-`available_at` fallback

## 5. Deferred Residuals

- **D1 Mid-pipeline artifact I/O residual (low priority):** some success-path
  writes still raise raw `OSError` to direct API callers before the final
  artifact-write guard: runner `data_manifest.json`, validation per-window row
  JSONL, validation per-scenario decision JSONL, and validation per-scenario
  trade-ledger JSONL. The CLI backstops escaped filesystem errors as clean exit
  `1`. Result-directory/static artifact creation, final artifact writes, and
  `_failure_result` paths are routed to structured `failure_stage` results.
- **D2 *(resolved by portfolio-book-spine, 2026-06-10)* agreement-oracle
  residual:** the single-trade agreement oracle and its cross-check are retired;
  the netted-book spine is the single accounting model on every surface. An
  independent cross-check (a second re-implementation that must agree, generalized
  from single-trade to the netted book) is a named follow-on, not a current surface.
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
