## REMOVED Requirements

### Requirement: The Train path stays trade-unit and dependency-light

**Reason**: The scored unit is no longer the per-trade ledger. The single
authoritative scored object is the portfolio NAV book (see
`quick-run-portfolio-foundation`), and the per-trade ledger becomes a derived
attribution view of that one book walk. The dependency-light import-wall guarantee
is retained by the ADDED requirement "The per-trade ledger is a derived attribution
view on the dependency-light path".

**Migration**: Consumers that ranked or scored Train runs on the per-trade
economics sum SHALL instead read the NAV-derived foundation statistics; the
per-trade ledger remains available for alpha attribution / information-coefficient
analysis only.

## ADDED Requirements

### Requirement: The per-trade ledger is a derived attribution view on the dependency-light path

The per-trade ledger SHALL be derived from the single causal portfolio book walk,
not computed as an independent scored quantity. It SHALL remain first-class for
alpha attribution and information-coefficient analysis, and SHALL expose no
independent scored "trade-unit" return. The portfolio NAV book SHALL be the
authoritative scored object. The quick-run code path MUST NOT introduce a runtime
dependency on `vectorbtpro`, `pandas`, `numpy`, or `quant_strategies.evaluation`.

#### Scenario: Ledger is derived from the one book
- **WHEN** a completed quick run exposes the per-trade ledger
- **THEN** its records are attributions of the same book walk that produced the NAV path
- **AND** there is no separate per-trade summation that can disagree with the NAV path

#### Scenario: NAV is the scored unit, ledger is attribution
- **WHEN** Train scoring reads a completed quick run
- **THEN** the scored statistics come from the foundation NAV path
- **AND** the per-trade ledger is available for attribution but is not an independent scored number

#### Scenario: Quick-run path imports no heavyweight backend dependency
- **WHEN** the quick-run path (`runner`, `engine`, `core`) is imported and exercised
- **THEN** it does not import `vectorbtpro`, `pandas`, `numpy`, or `quant_strategies.evaluation`

## MODIFIED Requirements

### Requirement: Quick-run per-trade economics are exposed typed and in-process

`run_config` SHALL expose, on its returned `RunResult`, the after-cost per-trade
ledger of a completed run as a typed, frozen in-process value object **derived from
the single portfolio book walk**. Each record SHALL attribute one completed
round-trip reconstructed from the netted book and SHALL carry the fields needed to
slice the sample by time and by symbol: `symbol`, `side`, `weight`,
`decision_time`, `entry_time`, `exit_time` (tz-aware datetimes), `entry_price`,
`exit_price`, `exit_reason`, `gross_return`, `funding_return`, `cost_return`,
`net_return`, and `decision_id`. A consumer MUST be able to obtain the ledger from
the result object alone, without reading `summary.json` or any other artifact under
`result_dir`.

The exposed `net_return` SHALL be the book walk's realized after-cost attribution
for that round-trip (`gross_return + funding_return - cost_return`), computed on the
netted single account so that the ledger and the NAV path describe one model of
money rather than two.

#### Scenario: Per-trade ledger available without artifacts
- **WHEN** a quick run completes its engine evaluation
- **THEN** `RunResult` carries a typed economics object whose per-trade ledger has one record per completed book round-trip
- **AND** each record exposes `symbol`, `side`, `weight`, tz-aware `decision_time`/`entry_time`/`exit_time`, `entry_price`/`exit_price`, `exit_reason`, and `gross_return`/`funding_return`/`cost_return`/`net_return`
- **AND** the consumer obtains the ledger without reading any file under `result_dir`

#### Scenario: Ledger round-trips match the netted book
- **WHEN** a quick run completes with N completed round-trips on the netted book
- **THEN** the in-process per-trade ledger contains exactly N records
- **AND** their attributions reconcile with the NAV path's realized PnL
