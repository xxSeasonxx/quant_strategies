# Foundation Handoff TODOs

This file is the compact active handoff for remaining foundation work.
Do not restart a broad foundation review before reading:

- `PRD.md`
- `FOUNDATION_LOCK.md`
- `docs/reviews/README.md`

Current foundation surfaces:

```text
quick run                  -> diagnose one strategy version with engine-derived evidence
mechanical evidence validation -> audit retained-candidate evidence integrity
research evaluation        -> stateless frozen-candidate portfolio/economic/path evidence
```

Use `make check` for the standard local foundation check. Use
`make check-vectorbtpro-smoke` only when the real VectorBT Pro backend matters.

## Status

There are no open foundation-finalization PRs in this file. `FOUNDATION_LOCK.md`
is the disposition anchor for locked contracts, accepted debt, deferred triggers,
and review protocol.

## Current Open Work

### Evaluation follow-ups

The stateless evaluation surface is implemented through
`quant-strategies evaluate candidate/evaluation.toml` and
`quant_strategies.evaluation.run_evaluation`. It returns `EvaluationRunResult`
for frozen-candidate portfolio/economic/path evidence, remains separate from
validation, and does not authorize promotion, paper trading, or live trading.
Detailed trace artifacts are Parquet through `pyarrow`.

Benchmark-relative metrics and user-defined scenario matrices are implemented
as evaluation evidence surfaces. Remaining follow-up work is limited to
residual backend limitations found during use.

## Locked Direction

Use `FOUNDATION_LOCK.md` as the source of truth for what should not be reopened
as a fresh P1 without a regression or documented trigger. In short:

- quick run, validation run, and evaluation run are the implemented public
  surfaces;
- benchmark-relative metrics and user-defined scenario matrices are implemented
  as evidence-only evaluation features;
- strategies are flat pure files;
- validation and evaluation require `validate_params`;
- engine metrics are linear signed per-trade results, not NAV;
- validation is mechanical evidence validation, advisory, and never promotion authority;
- `quant_autoresearch` owns generation, search memory, variant ranking, stopping
  rules, and iteration decisions;
- `quant_data` owns data acquisition and materialization;
- generated artifacts are evidence, not truth.

## Deferred Residuals

- **Mid-pipeline artifact I/O residual (low priority):** some success-path
  writes still raise raw `OSError` to direct API callers before the final
  artifact-write guard: runner `data_manifest.json`, validation per-window row
  JSONL, validation per-scenario decision JSONL, and validation per-scenario
  trade-ledger JSONL. The CLI backstops escaped filesystem errors as clean exit
  `1`. Result-directory/static artifact creation, final artifact writes, and
  `_failure_result` paths are routed to structured `failure_stage` results.
  Closing the residual means wrapping those mid-pipeline writes or adding an
  outer guard; deferred as low-frequency disk-full handling.
- **VectorBT Pro agreement residual (low priority):** the optional agreement
  check is single-trade only. It should not be treated as multi-trade validation
  confidence unless rebuilt around trade-ledger or path-level comparison.
- **Candidate-local output residual (low priority):** validation and evaluation
  configs still anchor `output.results_dir` beside the config so
  candidate-local workspaces keep working. Revisit rejecting outputs under
  source directories only if config path ownership is redesigned.

Strict suppression-lookahead replay is the default for quick runs, validation
runs, and evaluation preflight; see `causality.check_hidden_lookahead` and the
`hidden_lookahead_suppression_detected` regression tests.

## Verification

Suggested checks:

```bash
make check
rg -n "FOUNDATION_LOCK|accepted_debt|deferred_until_trigger|broad blind|delta reviews|quick run|validation run" FOUNDATION_LOCK.md docs/reviews/README.md TODOS.md
git diff --check
```

Also run a stale-reference grep across active docs for removed dated review
anchors and stale process/guide wording; it should return no matches.

Run `conda run -n quant pytest -q` for final confidence when source, tests, or
public APIs changed.
