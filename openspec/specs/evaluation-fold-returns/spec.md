# evaluation-fold-returns Specification

## Purpose
TBD - created by archiving change foundation-perfold-returns. Update Purpose after archive.
## Requirements
### Requirement: Per-fold OOS return series are exposed typed and in-process

`run_evaluation` SHALL expose, on its returned `EvaluationRunResult`, the per-period
out-of-sample return series for every completed `(window, scenario)` as a typed, frozen
value object carrying numpy `timestamps` (datetime64[ns], strictly increasing) and
`values` (float64 per-period returns, net of the scenario's configured costs), plus the
configured annualization cadence as `periods_per_year`. A consumer MUST be able to obtain
a fold's return series from the result object alone, without reading
`tables/portfolio_path.parquet` or any other artifact.

The exposed `values` SHALL use the same observed-return semantics the evaluation already
applies to its summary metrics: the synthetic first period return is dropped and any
non-finite period return is excluded, so the typed series is the same sample that feeds
`return_sample_count`, `sharpe`, and the other return-based metrics.

`per_symbol` SHALL be `None` while the evaluation backends compute a single grouped
(cash-shared) portfolio. The accessor MUST NOT fabricate a per-symbol return series from
target-position schedules; per-symbol return paths are populated only by a backend that
actually computes them.

#### Scenario: Fold return series available without Parquet
- **WHEN** an evaluation run completes
- **THEN** `EvaluationRunResult.fold_returns` contains one typed `FoldReturnSeries` per completed `(window_id, scenario_id)`
- **AND** each series exposes numpy `timestamps`, numpy `values`, and `periods_per_year`
- **AND** the consumer obtains them without reading any file under `result_dir`

#### Scenario: Typed series matches the on-disk trace
- **WHEN** the same completed run also writes `tables/portfolio_path.parquet`
- **THEN** for each `(window_id, scenario_id)` the typed series `values` equal the Parquet `period_return` rows for that scenario after dropping the synthetic first return and excluding non-finite values
- **AND** the typed series `timestamps` equal the corresponding Parquet `timestamp` rows

#### Scenario: Single-window evaluate yields exactly that window's series
- **WHEN** the evaluation config declares a single `[[windows]]` entry
- **THEN** every `FoldReturnSeries` in the result carries that window's `window_id`
- **AND** no series pools rows from any other window

#### Scenario: Per-symbol breakdown is absent for grouped-portfolio backends
- **WHEN** a completed run used a grouped cash-shared portfolio backend
- **THEN** every `FoldReturnSeries.per_symbol` is `None`

### Requirement: Per-fold summary scalars and provenance are reachable from the result

`EvaluationRunResult` SHALL expose, per completed `(window, scenario)`, a typed
`FoldScenarioMetrics` carrying the summary risk scalars already computed by the backend
(`sharpe`, `sortino`, `calmar`, `max_drawdown`, `trade_count`, `worst_period_return`,
`return_sample_count`) and the run provenance sufficient to reproduce the metric (snapshot
identity and foundation/backend versions, FR-I1). These scalars MUST honor the existing
annualized-metric trust boundary: when the annualization cadence is not `ok` or the return
sample is below the configured floor, the annualized/risk scalars are `None`, exactly as in
the artifact metrics. This change MUST NOT add deflated or significance statistics
(PSR, DSR, PBO) to the foundation; those remain the consumer's responsibility.

#### Scenario: Summary scalars and provenance present per fold
- **WHEN** an evaluation run completes
- **THEN** `EvaluationRunResult.scenario_metrics` contains one `FoldScenarioMetrics` per completed `(window_id, scenario_id)`
- **AND** each carries the backend's `sharpe`/`sortino`/`calmar`/`max_drawdown`/`trade_count`/`worst_period_return`/`return_sample_count`
- **AND** each carries `provenance` identifying the data snapshot and the foundation/backend versions

#### Scenario: Annualized scalars stay nulled under a cadence guard
- **WHEN** the run's annualization cadence status is not `ok`
- **THEN** the `FoldScenarioMetrics` annualized/risk scalars (`sharpe`, `sortino`, `calmar`) are `None`
- **AND** the raw `FoldReturnSeries.values` for the same fold are still populated

#### Scenario: No significance statistics are added to the foundation
- **WHEN** the per-fold accessor is read
- **THEN** it exposes only raw returns and undeflated risk scalars
- **AND** it exposes no PSR, DSR, or PBO field

### Requirement: Per-fold causal-replay and decision-contract integrity is observable on the result

The result SHALL expose whether the Tier-0 causal-replay and decision-contract integrity
checks passed for the run via a `causal_replay_passed` flag. Because the hidden-lookahead
replay, the decision-row/observation-dependency audit, and decision-readiness are mandatory
preflight that must pass before portfolio metrics are computed, a completed run MUST report
`causal_replay_passed = True`, and a run that fails at a causal or audit stage MUST report
`causal_replay_passed = False`. A consumer orchestrating one `evaluate` call per fold MUST
be able to read this per-fold Tier-0 outcome from the result object without inspecting
artifacts.

#### Scenario: Completed run reports causal integrity passed
- **WHEN** an evaluation run completes
- **THEN** `EvaluationRunResult.causal_replay_passed` is `True`

#### Scenario: Causal/audit failure reports causal integrity failed
- **WHEN** an evaluation run fails at a causal-replay or decision-audit stage (for example `data_audit` or `preflight`)
- **THEN** `EvaluationRunResult.causal_replay_passed` is `False`

#### Scenario: Pre-causal failure leaves integrity unknown
- **WHEN** an evaluation run fails before the causal/audit stage (for example `config_load`)
- **THEN** `EvaluationRunResult.causal_replay_passed` is `None`

### Requirement: The per-fold accessor is additive and non-breaking

The new fields and helpers SHALL be additive to `EvaluationRunResult`. All new fields MUST
default to empty or `None` so existing programmatic consumers and the `succeeded` property
are unaffected, and the existing public evaluation entry-point signature MUST be unchanged.

#### Scenario: Existing result contract preserved
- **WHEN** existing code constructs or reads an `EvaluationRunResult` using only the prior fields
- **THEN** it continues to work unchanged
- **AND** `succeeded` is still `run_completed and failure_stage is None`

