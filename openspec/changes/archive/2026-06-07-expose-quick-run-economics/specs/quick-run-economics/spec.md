## ADDED Requirements

### Requirement: Quick-run per-trade economics are exposed typed and in-process

`run_config` SHALL expose, on its returned `RunResult`, the after-cost per-trade ledger of a
completed run as a typed, frozen in-process value object. Each per-trade record SHALL carry
the engine's after-cost economics and the fields needed to slice the sample by time and by
symbol: `symbol`, `side`, `weight`, `decision_time`, `entry_time`, `exit_time` (tz-aware
datetimes), `entry_price`, `exit_price`, `exit_reason`, `gross_return`, `funding_return`,
`cost_return`, `net_return`, and `decision_id`. A consumer MUST be able to obtain the ledger
from the result object alone, without reading `summary.json` or any other artifact under
`result_dir`.

The exposed `net_return` SHALL be the same after-cost value the engine computes for the trade
(`gross_return + funding_return - cost_return`), so the typed ledger is the same sample that
feeds the summary scalars and the on-disk `economic_metrics`.

#### Scenario: Per-trade ledger available without artifacts
- **WHEN** a quick run completes its engine evaluation
- **THEN** `RunResult` carries a typed economics object whose per-trade ledger has one record per completed trade
- **AND** each record exposes `symbol`, `side`, `weight`, tz-aware `decision_time`/`entry_time`/`exit_time`, `entry_price`/`exit_price`, `exit_reason`, and `gross_return`/`funding_return`/`cost_return`/`net_return`
- **AND** the consumer obtains the ledger without reading any file under `result_dir`

#### Scenario: Ledger record count matches the engine trade count
- **WHEN** a quick run completes with N engine trades
- **THEN** the in-process per-trade ledger contains exactly N records
- **AND** their order matches the engine's trade order

### Requirement: Quick-run summary economics scalars and slices are reachable from the result

The typed economics object SHALL also carry the summary scalars and groupings already
produced by the runner's economics layer: `trade_count`, winning/losing/flat counts,
`hit_rate`, `average_trade_net`, `profit_factor`, cost/funding share of absolute gross, and
the by-symbol / by-direction / by-exit-reason slices. These scalars and slices MUST be
reachable from the result object without reading any artifact, and MUST equal the values the
same run writes to `summary.json`'s `economic_metrics` (and the diagnostic `economic_slices`),
because they are produced by a single shared computation.

#### Scenario: Summary scalars and slices present in-process
- **WHEN** a quick run completes
- **THEN** the result's economics object exposes `trade_count`, `hit_rate`, `profit_factor`, and the cost/funding share scalars
- **AND** it exposes by-symbol, by-direction, and by-exit-reason slices

#### Scenario: In-process scalars equal the on-disk economic_metrics
- **WHEN** the same completed run also writes `summary.json`
- **THEN** the result's economics summary scalars equal the `economic_metrics` payload in `summary.json` for that run

### Requirement: The economics accessor is independent of artifact profile

The in-process economics SHALL populate on every completed run regardless of
`artifact_profile` — including `summary` — and reading them MUST NOT require writing any
artifact. The per-trade ledger and the slices MUST be present even under profiles that do not
write per-trade diagnostics to disk.

#### Scenario: Summary profile still yields full economics
- **WHEN** a quick run completes with `artifact_profile = "summary"`
- **THEN** `RunResult` carries the full per-trade ledger and the summary scalars/slices
- **AND** they are identical to those produced under the `diagnostic` and `full` profiles for the same inputs

#### Scenario: Economics do not depend on artifact writes
- **WHEN** the economics object is read from a completed `RunResult`
- **THEN** its contents are derived from the in-memory engine result, not from any file under `result_dir`

### Requirement: The Train path stays trade-unit and dependency-light

This capability SHALL expose only the trade-level (point-to-point, per-trade) economics the
engine computes. It MUST NOT add a per-period / bar-level return series, a portfolio/NAV path,
or any significance statistic (PSR/DSR/PBO) to the quick-run surface. The quick-run code path
MUST NOT introduce a runtime dependency on `vectorbtpro`, `pandas`, `numpy`, or
`quant_strategies.evaluation`.

#### Scenario: No period series or significance statistics are added
- **WHEN** the quick-run economics object is read
- **THEN** it exposes per-trade records and undeflated summary scalars/slices only
- **AND** it exposes no per-period return series, no portfolio NAV path, and no PSR/DSR/PBO field

#### Scenario: Quick-run path imports no heavyweight backend dependency
- **WHEN** the quick-run path (`runner`, `engine`, `core`) is imported and exercised
- **THEN** it does not import `vectorbtpro`, `pandas`, `numpy`, or `quant_strategies.evaluation`

### Requirement: The economics accessor is additive and non-breaking

The new field and value objects SHALL be additive to `RunResult`. The new field MUST default
to `None` so existing programmatic consumers and the `succeeded` property are unaffected, and
the public `run_config` entry-point signature MUST be unchanged. A run that fails before a
completed engine evaluation MAY leave the field `None`; a completed run MUST populate it.

#### Scenario: Existing result contract preserved
- **WHEN** existing code constructs or reads a `RunResult` using only the prior fields
- **THEN** it continues to work unchanged
- **AND** `succeeded` is still `outcome.completed and outcome.failure_stage is None`

#### Scenario: Completed run populates economics; pre-engine failure leaves it None
- **WHEN** a quick run completes its engine evaluation
- **THEN** the economics field is populated
- **WHEN** a quick run fails before engine evaluation (for example `config_load` or `data_load`)
- **THEN** the economics field is `None`
