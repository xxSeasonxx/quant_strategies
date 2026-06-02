# Foundation Closeout TODOs

This file is the compact closeout record for the foundation-finalization work.
Do not restart a broad foundation review before reading:

- `PRD.md`
- `FOUNDATION_LOCK.md`
- `docs/reviews/README.md`

The closeout goal was not to make `quant_strategies` perfect. The goal was to
make the foundation surfaces simple enough to use and honest enough to trust:

```text
quick run                  -> diagnose one strategy version and decide whether to keep iterating
mechanical evidence validation -> audit retained-candidate evidence integrity
research evaluation        -> stateless frozen-candidate portfolio/economic/path evidence
```

## Status

Foundation finalization is complete as of 2026-06-01. There are no open
foundation-finalization PRs in this file. `FOUNDATION_LOCK.md` is the disposition
anchor for locked contracts, accepted debt, deferred triggers, and review
protocol.

## Current Open Work

### C. Evaluation follow-ups

The stateless evaluation surface is implemented through
`quant-strategies evaluate candidate/evaluation.toml` and
`quant_strategies.evaluation.run_evaluation`. It returns `EvaluationRunResult`
for frozen-candidate portfolio/economic/path evidence, remains separate from
validation, and does not authorize promotion, paper trading, or live trading.
Detailed trace artifacts are Parquet through `pyarrow`.

Remaining follow-up work is limited to benchmark-relative metrics,
user-defined scenario matrices, and any residual backend limitations found
during implementation.

### B. Quick-run economic diagnostics improvement

Improve quick-run keep/kill diagnostics using the existing engine trade ledger
after the evaluation follow-ups that matter to the diagnostic design are settled.

Candidate diagnostics:

- hit rate;
- average trade net;
- win/loss distribution;
- cost and funding share;
- active exposure or concentration summaries.

Constraints:

- keep quick run on the internal causality-controlled engine;
- do not import VectorBT Pro on the quick-run hot path;
- do not relabel engine trade-activity sums as NAV/path returns;
- do not turn quick run into research evaluation.

## Locked Direction

Use `FOUNDATION_LOCK.md` as the source of truth for what should not be reopened
as a fresh P1 without a regression or documented trigger. In short:

- quick run, validation run, and evaluation run are the implemented public
  surfaces;
- Benchmark-relative metrics are deferred for evaluation;
- strategies are flat pure files;
- validation requires `validate_params`;
- engine metrics are linear signed per-trade results, not NAV;
- validation is mechanical evidence validation, advisory, and never promotion authority;
- `quant_data` owns data acquisition and materialization;
- generated artifacts are evidence, not truth.

## Deferred Residuals

- **F19 residual (low priority):** artifact I/O failures on the *mid-pipeline
  success-path* writes — per-window rows, per-scenario decision/trade-ledger
  records, and data manifests written while a run is progressing — still raise to
  a direct API caller. The CLI backstops them as a clean exit `1`. Result-directory
  creation, final artifact writes, and all `_failure_result` paths are routed to
  structured `failure_stage` results. Closing the residual means wrapping those
  loop writes or adding an outer guard; deferred as low-frequency disk-full
  handling.
- **VectorBT Pro agreement residual (low priority):** the optional agreement
  check is single-trade only. It should not be treated as multi-trade validation
  confidence unless rebuilt around trade-ledger or path-level comparison.
- **Validation source output residual (low priority):** validation configs still
  anchor `output.results_dir` beside the config so candidate-local workspaces
  keep working. Revisit rejecting outputs under source directories only if
  validation config paths are redesigned.

Strict suppression-lookahead replay is the default for both quick runs and
validation runs; see `causality.check_hidden_lookahead` and the
`hidden_lookahead_suppression_detected` regression tests.

## Verification

The closeout was docs-only. Suggested checks:

```bash
rg -n "FOUNDATION_LOCK|accepted_debt|deferred_until_trigger|broad blind|delta reviews|quick run|validation run" FOUNDATION_LOCK.md docs/reviews/README.md TODOS.md
git diff --check
```

Also run a stale-reference grep across active docs for removed dated review
anchors and stale process/guide wording; it should return no matches.

Run `conda run -n quant pytest -q` only if a final full-suite confidence check
is needed; the closeout itself does not change source, tests, public APIs,
schemas, artifacts, or verdict labels.
