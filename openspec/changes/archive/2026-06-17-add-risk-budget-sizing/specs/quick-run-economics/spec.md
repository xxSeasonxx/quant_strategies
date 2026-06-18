## MODIFIED Requirements

### Requirement: Quick-run per-trade economics are exposed typed and in-process
`run_config` SHALL expose, on its returned `RunResult`, the after-cost per-trade
ledger of a completed run as a typed, frozen in-process value object **derived from
the single final sized portfolio book walk**. Each record SHALL attribute one
completed round-trip reconstructed from the netted book and SHALL carry the fields
needed to slice the sample by time and by symbol: `symbol`, `side`, executable
`weight`, `decision_time`, `entry_time`, `exit_time` (tz-aware datetimes),
`entry_price`, `exit_price`, `exit_reason`, `gross_return`, `funding_return`,
`cost_return`, `net_return`, and `decision_id`. A consumer MUST be able to obtain
the ledger from the result object alone, without reading `summary.json` or any
other artifact under `result_dir`.

The exposed `weight` SHALL be the final executable sized weight, not the raw shape
target emitted by the strategy. The exposed `net_return` SHALL be the book walk's
realized after-cost attribution for that round-trip (`gross_return +
funding_return - cost_return`), computed on the netted single account so that the
ledger and the NAV path describe one model of money rather than two.

#### Scenario: Per-trade ledger available without artifacts
- **WHEN** a quick run completes its engine evaluation and foundation sizing
- **THEN** `RunResult` carries a typed economics object whose per-trade ledger has one record per completed book round-trip
- **AND** each record exposes `symbol`, `side`, executable `weight`, tz-aware `decision_time`/`entry_time`/`exit_time`, `entry_price`/`exit_price`, `exit_reason`, and `gross_return`/`funding_return`/`cost_return`/`net_return`
- **AND** the consumer obtains the ledger without reading any file under `result_dir`

#### Scenario: Ledger round-trips match the netted sized book
- **WHEN** a quick run completes with N completed round-trips on the final sized netted book
- **THEN** the in-process per-trade ledger contains exactly N records
- **AND** their attributions reconcile with the sized NAV path's realized PnL
