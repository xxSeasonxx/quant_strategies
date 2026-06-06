## Why

`quant_autoresearch` (the auto-research harness) orchestrates walk-forward folds and
needs each fold's **out-of-sample per-period return series** in-process to compute
significance (PSR/DSR/PBO) on its own side. Today `run_evaluation` returns only
`EvaluationRunResult` (a thin status object: `result_dir`, `message`, `run_completed`,
`failure_stage`, `assessment_status`, `evidence_quality_warnings`). The actual return
series — the `period_return` column of the per-scenario `portfolio_path` — is computed
in-process (`_EvaluationState.trace_results`), then **stripped from the result and
written only to `tables/portfolio_path.parquet`**. The only way for the consumer to read
returns today is to scrape that Parquet across the repo boundary, which is brittle,
couples the consumer to an artifact-layout detail, and is exactly the cross-repo seam the
harness PRD (FR-J2, AC-10) requires us to remove.

This change surfaces the **already-computed** per-fold OOS return series **typed and
in-process** on the evaluate result, so the consumer's foundation adapter can populate its
own `FoldReturns`/`FoldEvalResult` without any Parquet read. It is purely additive — it
exposes data the pipeline already produces; it does not recompute engine math, change
existing fields, or add significance statistics (PSR/DSR/PBO stay in the harness).

## What Changes

- Add a typed, frozen per-`(window, scenario)` OOS return-series value object
  `FoldReturnSeries` (numpy `timestamps` + `values`, `periods_per_year`, optional
  `per_symbol`) and a per-`(window, scenario)` summary `FoldScenarioMetrics` (sharpe,
  sortino, calmar, max_drawdown, trade_count, worst_period_return, return_sample_count,
  causal_ok, provenance) in a new module `evaluation/fold_returns.py`.
- Extend `EvaluationRunResult` with **new fields that default to empty/None** (non-breaking):
  `fold_returns: tuple[FoldReturnSeries, ...]`, `scenario_metrics: tuple[FoldScenarioMetrics, ...]`,
  `causal_replay_passed: bool | None`, and `provenance: Mapping[str, str]`. Existing fields
  and the `succeeded` property are unchanged.
- Add typed lookup helpers on `EvaluationRunResult`: `returns_for(window_id, scenario_id)`,
  `metrics_for(window_id, scenario_id)`, and `window_ids` / `scenario_ids_for(window_id)`.
- Populate these fields in the pipeline from the **existing** `trace_results`
  `portfolio_path` frames, reusing the existing `return_coverage` observed-returns
  semantics (drop the synthetic first return, exclude non-finite) so the typed series is
  identical to what feeds the summary metrics and the Parquet trace. The series carries the
  configured `metrics.annualization_periods_per_year` as `periods_per_year`.
- Set `causal_replay_passed = True` on a completed run (the hidden-lookahead replay +
  decision-row/observation-dependency audit + readiness checks are mandatory preflight that
  must pass for completion) and `causal_replay_passed = False` when the run fails at a
  causal/audit stage (`data_audit`, `preflight`), so the consumer can observe per-fold
  Tier-0 integrity from the result without reading artifacts.
- `per_symbol` is `None` for the current backends: evaluation runs a single cash-shared,
  grouped portfolio, so the engine produces one grouped return series, not per-symbol
  return paths. The field is reserved for a future per-symbol-return backend rather than
  fabricated from decision schedules.

## Capabilities

### New Capabilities
- `evaluation-fold-returns`: a typed, in-process per-fold OOS return-series accessor on the
  evaluate result — return series (timestamps + values) plus summary risk scalars and
  per-fold causal-integrity observability, keyed by `(window_id, scenario_id)` — so
  consumers obtain per-fold returns without scraping `tables/portfolio_path.parquet`.

### Modified Capabilities
<!-- None: openspec/specs/ has no existing evaluation-result baseline spec to amend. -->

## Impact

- **Source**: new `evaluation/fold_returns.py` (value types + extraction from
  `portfolio_path`); `evaluation/results.py` (additive fields + lookup helpers on
  `EvaluationRunResult`); `evaluation/_pipeline.py` (build the typed series/metrics from
  `state.trace_results` on the completion path and set `causal_replay_passed` on the
  causal/audit failure paths); `evaluation/__init__.py` (export the new types).
- **Public contract**: additive only — no existing field, signature, or semantic changes;
  `EvaluationRunResult.succeeded` is unchanged; `FOUNDATION_LOCK.md` boundaries preserved
  (no PSR/DSR/PBO; significance stays in the consumer). The annualized-metric trust
  boundary is unaffected: scalar `sharpe`/`sortino`/`calmar` are still nulled by cadence
  guards, while the raw `values` series mirrors the trace `period_return`.
- **Determinism**: identical (config, data snapshot, versions) → identical series; the
  arrays are derived from the same in-process frames that produce the Parquet, with no
  clock or RNG.
- **Docs**: `docs/consumer/reference.md` (EvaluationRunResult field table + new types),
  `docs/consumer/usage-guide.md` (recipe for reading per-fold returns in-process),
  `FOUNDATION_LOCK.md` (note the additive in-process return-series accessor on the
  evaluation surface).
- **Tests**: new `tests/test_evaluation_fold_returns.py` (AC-10 coverage via the existing
  `FakeBackend` injection pattern, plus a parity check against the on-disk Parquet);
  no existing test expectations changed.
- **Not affected**: NAV/portfolio math, scenario fanout, artifact layout, validation and
  quick-run surfaces, data boundary.
