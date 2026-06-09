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

Current quick-run state:

- **S4** `quant-strategies run config.toml` and `quant_strategies.runner.run_config`
  return `RunResult`.
- **S5** Completed quick runs expose typed `RunResult.economics` for trade-level
  after-cost evidence.
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

Use `make check-vectorbtpro-smoke` only when the real VectorBT Pro evaluation
smoke is the only needed slice. Run `conda run -n quant pytest -q` for final
confidence when source, tests, or public APIs changed.

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

## 3. Locked Direction

Use `FOUNDATION_LOCK.md` as the source of truth for contracts that should not be
reopened without a regression or documented trigger.

Current locked direction:

- **L1** Public vocabulary stays: quick run, validation run, evaluation run.
- **L2** Strategies are flat pure files.
- **L3** Validation is mechanical evidence validation, advisory, and never promotion
  authority.
- **L4** Evaluation is stateless frozen-candidate portfolio/economic/path evidence.
- **L5** Engine metrics are linear signed per-trade results, not NAV.
- **L6** Generated artifacts are evidence, not truth.
- **L7** `quant_autoresearch` owns generation, search memory, variant ranking,
  stopping rules, and iteration decisions.
- **L8** `quant_data` owns data acquisition and materialization.
- **L9** `quant-data` is bounded as `>=0.1.0,<0.2.0`.

## 4. Contained Residuals

Preserve these contained residuals unless they become active work:

- **R1** `net_return` dual semantics
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
- **D2 VectorBT Pro agreement residual (low priority):** the optional agreement
  check is single-trade only. It should not be treated as multi-trade validation
  confidence unless rebuilt around trade-ledger or path-level comparison.
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
