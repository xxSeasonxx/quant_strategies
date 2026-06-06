## 1. Typed value objects (`evaluation/fold_returns.py`)

- [x] 1.1 Add a frozen `FoldReturnSeries` dataclass: `window_id: str`, `scenario_id: str`, `timestamps: np.ndarray` (datetime64[ns]), `values: np.ndarray` (float64), `periods_per_year: float`, `per_symbol: Mapping[str, FoldReturnSeries] | None = None`.
- [x] 1.2 Add a frozen `FoldScenarioMetrics` dataclass: `window_id`, `scenario_id`, `sharpe`/`sortino`/`calmar`/`max_drawdown`/`worst_period_return: float | None`, `trade_count: int | None`, `return_sample_count: int | None`, `causal_ok: bool`, `provenance: Mapping[str, str]`.
- [x] 1.3 Add `fold_series_from_portfolio_path(window_id, scenario_id, frame, *, periods_per_year)` that derives `(timestamps, values)` from a `portfolio_path` frame's `timestamp` + `period_return`, reusing the existing observed-return semantics (drop synthetic first return; exclude non-finite) so the series matches the summary metrics and the Parquet trace.
- [x] 1.4 Add `fold_metrics_from_scenario(window_id, scenario_id, metrics_map, *, provenance, causal_ok)` mapping the backend metric dict to `FoldScenarioMetrics`.

## 2. Additive result fields + helpers (`evaluation/results.py`)

- [x] 2.1 Add to `EvaluationRunResult` (all defaulted, non-breaking): `fold_returns: tuple[FoldReturnSeries, ...] = ()`, `scenario_metrics: tuple[FoldScenarioMetrics, ...] = ()`, `causal_replay_passed: bool | None = None`, `provenance: Mapping[str, str] = field(default_factory=dict)`.
- [x] 2.2 Add typed lookup helpers: `returns_for(window_id, scenario_id) -> FoldReturnSeries | None`, `metrics_for(window_id, scenario_id) -> FoldScenarioMetrics | None`, `window_ids -> tuple[str, ...]`, `scenario_ids_for(window_id) -> tuple[str, ...]`.
- [x] 2.3 Keep `succeeded` and all existing fields unchanged.

## 3. Pipeline population (`evaluation/_pipeline.py`)

- [x] 3.1 Build a provenance mapping (snapshot/normalized-rows identity from the data windows, foundation + backend versions) once per run.
- [x] 3.2 On the completion path, iterate `state.trace_results`, splitting any combined `portfolio_path` frame by `scenario_id`, and build one `FoldReturnSeries` + one `FoldScenarioMetrics` per `(window_id, scenario_id)`; thread the window id from the trace result's scenario id (`"{window_id}/..."`).
- [x] 3.3 Pass `metrics.annualization_periods_per_year` as `periods_per_year` and the run provenance into the builders; set `causal_ok=True` for completed scenarios.
- [x] 3.4 Populate the new `EvaluationRunResult` fields on the success return; set `causal_replay_passed=True`.
- [x] 3.5 In `_failure_result`, set `causal_replay_passed=False` for causal/audit failure stages (`data_audit`, `preflight`) and leave it `None` otherwise; thread provenance where available.

## 4. Exports (`evaluation/__init__.py`)

- [x] 4.1 Export `FoldReturnSeries` and `FoldScenarioMetrics` from `quant_strategies.evaluation`.

## 5. Tests (`tests/test_evaluation_fold_returns.py`) — AC-10 first

- [x] 5.1 Per-fold OOS returns obtained via the typed API on a completed run (FakeBackend injection): `fold_returns` non-empty, numpy arrays, `periods_per_year` set, lookup helpers resolve.
- [x] 5.2 Parity: the typed series `values`/`timestamps` for each scenario equal the on-disk `tables/portfolio_path.parquet` rows after dropping the synthetic first return and excluding non-finite.
- [x] 5.3 One-evaluate-per-fold: a single-window config yields series carrying only that window's id; a two-window config keys series by the correct window.
- [x] 5.4 Per-fold causal/contract integrity observable: completed run ⇒ `causal_replay_passed is True` and each `FoldScenarioMetrics.causal_ok is True`; a data-audit failure ⇒ `causal_replay_passed is False`.
- [x] 5.5 Cadence guard: under an insufficient/mismatched cadence the annualized scalars are `None` while `values` stay populated.
- [x] 5.6 Additive/non-breaking: a default-constructed `EvaluationRunResult` keeps `fold_returns == ()`, `causal_replay_passed is None`, and `succeeded` behavior.
- [x] 5.7 Optional: a real VectorBT Pro fold-returns assertion guarded by `RUN_VECTORBTPRO_SMOKE` (skipped when unset) proving the series populates on the real backend.

## 6. Docs

- [x] 6.1 `docs/consumer/reference.md`: add the new `EvaluationRunResult` fields + `FoldReturnSeries`/`FoldScenarioMetrics` schema and the lookup helpers; export rows in the public API table.
- [x] 6.2 `docs/consumer/usage-guide.md`: add a short recipe for reading per-fold returns in-process (no Parquet).
- [x] 6.3 `FOUNDATION_LOCK.md`: record the additive in-process per-fold return-series accessor on the evaluation surface (no PSR/DSR/PBO; significance stays in the consumer).

## 7. Verify

- [x] 7.1 `conda run -n quant python -m pytest` green (full suite).
- [x] 7.2 `conda run -n quant ruff format --check . && conda run -n quant ruff check .` clean (repo-wide). `mypy` has pre-existing repo-wide debt and is not in the blocking `make check` gate; this change adds only one more instance of the repo's existing untyped-`pandas`-import pattern (102 → 103 `mypy src` errors), no new genuine type defect.
- [x] 7.3 Run the VectorBT Pro evaluation smoke (`make check-vectorbtpro-smoke`) since VBT Pro is installed; report result.
