## Context

The auto-research harness (`quant_autoresearch`) depends on a typed Foundation seam
(`harness/foundation.py`): `FoldReturns` (numpy `timestamps`/`values`, `periods_per_year`,
optional `by_symbol`) and `FoldEvalResult` (returns + risk scalars + provenance +
`causal_ok`). Its `RealFoundationGateway.evaluate(experiment, protocol, window)` must
populate those from `quant_strategies.evaluation.run_evaluation` **without scraping
Parquet** (PRD FR-J2, AC-10). Today the evaluate result carries no returns; the
`period_return` series exists only inside `_EvaluationState.trace_results` and on disk in
`tables/portfolio_path.parquet`.

## Goals / Non-Goals

- **Goals:** surface the already-computed per-fold OOS return series typed and in-process;
  make a single-window evaluate yield exactly that fold's series; expose per-fold Tier-0
  causal integrity on the result. Additive and non-breaking.
- **Non-Goals:** no PSR/DSR/PBO (significance is the harness's job); no new engine math; no
  change to NAV/portfolio computation, scenario fanout, artifact layout, or other surfaces;
  no embargo/purge logic (the harness owns walk-forward spacing, FR-B3).

## Key decisions

### Numpy arrays on the foundation accessor (not pandas)
The harness core is numpy (`FoldReturns.timestamps/values` are `np.ndarray`). Returning
numpy from the foundation accessor makes `RealFoundationGateway` a near pass-through
instead of a pandas-scraping adapter, and keeps the value object hashable-friendly and
backend-agnostic. Pandas stays internal to the pipeline (the `portfolio_path` frame is the
source); the public value object is numpy.

### Keyed by `(window_id, scenario_id)`, not just window
One `[[windows]]` entry fans out to N scenarios (default 6 = 3 cost × 2 fill). The OOS
return series differs per scenario (different costs/fills), so the natural key is
`(window_id, scenario_id)`. The harness, orchestrating one fold per evaluate with a single
window, selects the scenario matching its Protocol's costs-on / fixed-exposure objective
(e.g. the `realistic_costs/base_fill` scenario or a single custom `[[scenarios]]`). Exposing
all completed scenarios is strictly more information than the harness needs and keeps the
accessor faithful to what the run computed; `returns_for(window_id, scenario_id)` is the
typed selector.

### Reuse the existing observed-return semantics exactly
The summary metrics define "observed returns" via `_portfolio_common.return_coverage`: drop
the first (synthetic) period return, exclude non-finite. The typed `values` MUST use the
same definition so the series is consistent with `return_sample_count`, `sharpe`, and the
Parquet trace. `timestamps` are the matching `portfolio_path.timestamp` rows for the kept
returns. This is why the parity test compares against the Parquet after applying the same
drop/filter — the typed series is the same sample, just delivered in-process.

### `per_symbol = None` (honest, not fabricated)
`vbt.Portfolio.from_signals(..., cash_sharing=True, group_by=True)` and the project perp
ledger both produce a single grouped NAV/return path; there is no per-symbol return series
to expose. `target_positions`/`target_exposure_summary` are decision schedules, not return
paths, so deriving a per-symbol return from them would be invented evidence. The field is
kept (the harness seam allows `by_symbol=None`) and reserved for a future backend that
genuinely computes per-symbol returns. This is the simplest additive option that satisfies
the seam; it is noted as a deviation from the seam's optional per-symbol capability.

### `causal_replay_passed` derived from the run outcome, not recomputed
The hidden-lookahead replay (`check_hidden_lookahead`), the decision-row/observation
audit (`audit_decision_rows`), and decision-readiness are mandatory preflight: a run cannot
complete unless they pass, and a failure short-circuits with a causal/audit `failure_stage`.
So `causal_replay_passed` is a faithful projection of the existing control flow —
`True` on completion, `False` on a causal/audit failure stage (`data_audit`, `preflight`),
`None` on a pre-causal failure (`config_load`, `artifact_initialization`). No new check is
run; the flag just makes the already-enforced Tier-0 outcome observable per fold, as the
seam's `FoldEvalResult.causal_ok` requires.

### Provenance
`provenance` is a small `Mapping[str, str]` built from data-window identity (the
`normalized_rows_sha256` already captured per window) plus the backend name and the
`quant_strategies` package version, sufficient for the harness's FR-I1 measurement
fingerprint. It deliberately does not duplicate the full `evaluation_manifest.json`; the
manifest remains the exhaustive on-disk record.

## Risks / Trade-offs

- **No per-symbol returns** — the harness's concentration/effective-breadth gates that want
  per-symbol returns cannot be fed from this accessor yet. Mitigation: documented; the
  harness can use `target_exposure_summary`/decision-level breadth, or a future per-symbol
  backend can populate `per_symbol`. This does not block the primary OOS-return seam.
- **Scenario selection is the consumer's** — the foundation exposes all completed scenarios
  and does not pick "the" OOS series; the harness selects per its Protocol. This keeps the
  foundation free of judgment (matches the ownership boundary).
- **Memory** — holding the typed series in-process keeps the per-run return arrays alive in
  the result. They are small (per-period returns for one window) and the harness consumes
  one fold at a time, so this is negligible versus the Parquet write already performed.

## Migration

Additive; no migration. Existing callers see new defaulted fields and are unaffected. The
Parquet trace is still written (other consumers and the audit trail rely on it); this change
adds an in-process path so the harness need not read it.
