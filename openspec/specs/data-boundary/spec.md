# data-boundary Specification

## Purpose
Define the data-loading and row-contract boundary between `quant_strategies`
and upstream `quant_data`. This spec keeps strategy-visible rows, execution
buffer rows, availability timestamps, row ordering, and upstream feedback
semantics explicit and auditable.
## Requirements
### Requirement: Strategy bars are loaded through the upstream contract layer

`quant_strategies` SHALL load `bars`-kind data exclusively through the `quant_data`
strategy contract layer (`quant_data.contract_loaders`): `load_strategy_bars` for a
single symbol and `load_strategy_universe_bars` for multiple symbols. It MUST NOT load
`bars` through the raw exploratory layer (`quant_data.loader.load_bars` /
`load_universe_bars`), because the raw layer does not stamp `available_at` and does not
guarantee row order.

#### Scenario: Single-symbol bars load
- **WHEN** a config has `data.kind = "bars"` with one symbol
- **THEN** `load_data` calls `contract_loaders.load_strategy_bars(engine, symbol, dataset, start, end, strict=True)`
- **AND** every returned row carries a timezone-aware `available_at`

#### Scenario: Multi-symbol universe bars load
- **WHEN** a config has `data.kind = "bars"` with more than one symbol
- **THEN** `load_data` calls `contract_loaders.load_strategy_universe_bars(...)` and consumes the single returned frame
- **AND** the rows are in the upstream `(timestamp, symbol)` order without any local reordering

#### Scenario: Missing universe member fails loudly
- **WHEN** a requested universe symbol has no rows in the window under strict load
- **THEN** the load raises rather than silently dropping the symbol

### Requirement: FX and crypto kinds use the derived-join loaders strictly

`quant_strategies` SHALL load `forex_with_quotes` via
`quant_data.loader.load_fx_bars_with_quotes` and `crypto_perp_funding` via
`quant_data.loader.load_crypto_perp_bars_with_funding`, always with `strict=True`. These
precomputed-join loaders are the correct source because they return bars combined with
quotes/funding and already carry `available_at`; no contract loader returns the combined
frame.

#### Scenario: FX quote-fill load requires quotes
- **WHEN** a `forex_with_quotes` config uses a quote fill model
- **THEN** `load_fx_bars_with_quotes` is called with `strict=True` and `require_quotes=True`

#### Scenario: Crypto perp funding load is strict
- **WHEN** a `crypto_perp_funding` config loads each symbol
- **THEN** `load_crypto_perp_bars_with_funding` is called with `strict=True`
- **AND** each returned row carries `available_at`, `funding_timestamp`, `funding_rate`, and `has_funding_event`

### Requirement: Strategy-evidence loads are always strict

`quant_strategies` SHALL always load strategy-evidence data in strict mode. There MUST be
no configuration toggle that relaxes loading to the exploratory/lenient contract; the
`data.strict` field is removed and an unknown `strict` key in a `[data]` table is rejected.

#### Scenario: Legacy strict toggle is rejected
- **WHEN** a config `[data]` table contains a `strict` key
- **THEN** config loading fails with an unknown-field error

### Requirement: Upstream owns row order and the boundary preserves it

`quant_data` owns deterministic row ordering. `quant_strategies` SHALL preserve the
supplied row order for hashing, execution inputs, and audit artifacts, and MUST NOT sort,
re-order, de-duplicate, join, or repair rows at the data boundary.

#### Scenario: No local reordering of supplied rows
- **WHEN** rows are returned by the loader
- **THEN** `load_data` preserves their order into `NormalizedRows` and the projection rows
- **AND** no `(symbol, timestamp)` or other local sort is applied

### Requirement: Causal `available_at` is mandatory with no fallback

Every supplied row SHALL carry a valid timezone-aware `available_at`. The row contract MUST
treat a missing or invalid `available_at` as an error in all run surfaces (quick run,
validation, evaluation), and the run MUST fail with that row-contract error rather than
emit evidence from rows of unknown observability. Causality replay MUST decide visibility
of a valid row strictly on `available_at <= decision_time`; because `available_at` is
mandatory, a provenance defect is surfaced as a row-contract failure and never as a
hidden-lookahead accusation.

#### Scenario: Missing available_at fails the row contract
- **WHEN** a supplied row lacks `available_at` (or it is not a timezone-aware datetime)
- **THEN** the row contract records it as an error and the run fails — there is no warning-only path

#### Scenario: Provenance defects fail at the row contract, not as lookahead
- **WHEN** a row is missing or has an invalid `available_at`
- **THEN** the run fails with a row-contract error (a data-quality failure)
- **AND** causality replay does not report the provenance defect as a hidden-lookahead failure
- **AND** a valid row is visible at a boundary only if its `available_at <= decision_time`

### Requirement: Consumer-side row-contract validation and upstream feedback

`quant_strategies` SHALL validate supplied rows against its row contract (required fields,
timezone-aware timestamps and `available_at`, numeric validity, OHLC ordering, duplicate
`(symbol, timestamp)` keys, quote and funding-event semantics) and surface structured
feedback for upstream `quant_data` repair. It MUST NOT repair, backfill, or silently
reinterpret upstream data locally.

#### Scenario: Row-contract issues are reported, not repaired
- **WHEN** supplied rows violate the row contract
- **THEN** the issues are recorded as structured contract feedback
- **AND** the boundary does not mutate the rows to make them pass

### Requirement: Upstream contract smoke proves the consumed boundary

The repository SHALL provide an opt-in smoke check that exercises the real `quant_data`
contract layer and asserts the boundary `quant_strategies` depends on. It MUST be gated
behind an environment flag (not part of the default unit run) and MUST NOT materialize,
repair, or duplicate upstream data coverage.

#### Scenario: Contract smoke asserts the consumed guarantees
- **WHEN** the contract smoke runs against real `quant_data`
- **THEN** it asserts required fields including `available_at`, timezone-aware `timestamp` and `available_at`, `available_at` strictly after `timestamp` for bars, `(timestamp, symbol)` ordering for a universe load, and absence of duplicate keys

#### Scenario: Contract smoke is opt-in
- **WHEN** the environment flag is not set
- **THEN** the smoke is skipped and the default test run does not require a live database

### Requirement: Quick-run load windows preserve strict upstream loading
`quant_strategies` SHALL load rows through the same strict upstream loader
contracts used for the decision window when quick-run config declares
execution/load window fields. The widened load window SHALL NOT relax strictness, repair
rows locally, or change upstream-owned row ordering.

#### Scenario: Buffered bars load remains strict
- **WHEN** a quick-run `bars` config uses `data.load_start` or `data.load_end`
- **THEN** data loading calls the same strict `quant_data` contract loader with the load window
- **AND** it preserves the upstream row order into normalized execution rows

#### Scenario: Buffered crypto funding load remains strict
- **WHEN** a quick-run `crypto_perp_funding` config uses `data.load_start` or `data.load_end`
- **THEN** data loading calls the same strict crypto perp funding loader with the load window for each symbol
- **AND** each row still satisfies the row contract before engine use

### Requirement: Strategy-visible row projection is bounded by the decision window
The shared execution path SHALL derive a separate strategy-visible row set
bounded by `data.start` and `data.end` when loaded execution rows cover a wider
window than the decision window. Strategy-input hashes and causality
evidence SHALL be based on that strategy-visible row set.

#### Scenario: Post-window rows are execution-only
- **WHEN** loaded rows include timestamps after `data.end`
- **THEN** those rows are available for engine execution
- **AND** they are excluded from strategy-visible rows and causality replay inputs

#### Scenario: Strategy evidence hash excludes buffer rows
- **WHEN** a quick run writes strategy-input hashes or rows
- **THEN** the hash or rows cover only the decision-window strategy input rows

### Requirement: Load window validation protects decision-window coverage
Quick-run config validation SHALL require any explicit load window to cover the
decision window. The runner MUST reject a load window that starts after
`data.start` or ends before `data.end`.

#### Scenario: Load end before decision end fails
- **WHEN** a quick-run config sets `data.load_end` before `data.end`
- **THEN** config loading fails before data loading

#### Scenario: Load start after decision start fails
- **WHEN** a quick-run config sets `data.load_start` after `data.start`
- **THEN** config loading fails before data loading

### Requirement: Capacity-enabled rows expose valid notional volume inputs

The row contract SHALL require every execution row that can be used for fills,
marks, or ADV history to expose a valid non-negative `volume` field when a run
declares ADV/impact capacity pricing for a supported data kind. Executed bars and
ADV-history bars used in capacity calculations SHALL reject missing, non-finite,
negative, or zero notional volume when that value is needed to price or gate an
executed delta. `vwap` MAY be used as the preferred notional-volume price when
present and positive; otherwise the book SHALL use the fill or mark price already
validated for the row.

#### Scenario: Missing capacity volume fails before scoring
- **WHEN** a capacity-enabled supported-data run supplies rows without `volume`
- **THEN** the row contract or capacity preflight records a capacity input error
- **AND** the run fails before emitting scored success

#### Scenario: Positive volume is preserved into execution
- **WHEN** the upstream loader supplies `volume`, `vwap`, and `num_trades`
- **THEN** normalization preserves those fields into execution rows
- **AND** the book can consume them without a local data join or repair step

### Requirement: ADV history is causal

ADV notional volume used for capacity pricing SHALL be computed from prior rows
for the same symbol, excluding the current execution row and all future rows.
If the configured minimum number of prior observations is unavailable for an
executed delta, the run SHALL fail closed with reason
`capacity_insufficient_adv_history`.

#### Scenario: Current bar is excluded from ADV history
- **WHEN** an execution event occurs on timestamp `T`
- **THEN** its ADV notional volume uses only rows for the same symbol with timestamps before `T`
- **AND** the current row's volume is used only for bar participation, not for ADV history

#### Scenario: Insufficient ADV history fails closed
- **WHEN** an execution event has fewer prior volume observations than the configured minimum
- **THEN** the run fails closed with `capacity_insufficient_adv_history`
- **AND** it does not substitute current or future volume to make the trade scoreable

### Requirement: FX tick-count volume is not capacity volume

The data boundary SHALL treat FX `volume` as tick-count activity, not traded
notional volume, until upstream exposes a calibrated notional liquidity contract.
Capacity-enabled FX runs SHALL fail closed instead of using tick count as ADV or
bar notional volume.

#### Scenario: FX tick count cannot price ADV impact
- **WHEN** a `forex_with_quotes` run enables ADV/impact capacity pricing
- **THEN** the run fails with `capacity_unsupported_volume_semantics`
- **AND** no capacity metric labels FX tick count as notional volume
