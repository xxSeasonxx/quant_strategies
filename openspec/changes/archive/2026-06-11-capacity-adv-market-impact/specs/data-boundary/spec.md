## ADDED Requirements

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
