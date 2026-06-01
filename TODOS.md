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
research evaluation        -> missing stateless surface for frozen-candidate portfolio/economic evidence
```

## Status

Foundation finalization is complete as of 2026-06-01. There are no open
foundation-finalization PRs in this file. `FOUNDATION_LOCK.md` is the disposition
anchor for locked contracts, accepted debt, deferred triggers, and review
protocol.

## Current Open Work

### C. Research evaluation surface MVP

The next missing product layer is a stateless evaluation surface for frozen
candidates. It should accept strategy/config/data references and explicit
evaluation assumptions, then return economic, path, and portfolio evidence.

Initial design boundaries:

- keep it stateless; no candidate generation, search memory, ranking, stopping
  rules, or promotion policy;
- keep validation as mechanical evidence validation, not a renamed evaluation
  run;
- use VectorBT Pro where portfolio/NAV semantics are the deliverable;
- label all NAV/path/portfolio metrics separately from engine trade-activity
  sums;
- preserve the promotion boundary: evaluation evidence does not authorize paper
  trading, live trading, or autonomous promotion.

Acceptance criteria for the next C design:

- clear input contract for frozen candidate, params, data references or splits,
  and evaluation assumptions;
- clear output contract for NAV/path metrics, drawdown, turnover, exposure,
  concentration, per-asset evidence where supported, and explicit non-claims;
- no quick-run dependency on VectorBT Pro;
- no update to `docs/foundation-surfaces.md` until an implemented evaluation
  surface exists.

### B. Quick-run economic diagnostics improvement

After C is designed, improve quick-run keep/kill diagnostics using the existing
engine trade ledger.

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

- quick run and validation run are the two implemented public surfaces;
- research evaluation is the approved missing next surface;
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

Also run a stale-reference grep across active docs for the removed dated review
anchor, the old surface-doc path, and process/guide wording; it should return no
matches.

Run `conda run -n quant pytest -q` only if a final full-suite confidence check
is needed; the closeout itself does not change source, tests, public APIs,
schemas, artifacts, or verdict labels.
