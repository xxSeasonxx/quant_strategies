## Why

The current single-account book prices configured fees, slippage, and crypto-perp
funding, but it does not account for whether the executed deltas are realistically
tradable at the strategy's assumed capital scale. That leaves quick-run,
validation, and evaluation scores capacity-blind even though `volume`, `vwap`,
and `num_trades` already reach the engine rows for supported bar datasets.

## What Changes

- Add an operator-frozen capacity/market-impact model alongside the existing
  cost, fill, and leverage envelopes.
- **BREAKING:** quick-run, validation, and evaluation configs must declare the
  capacity model explicitly; committed candidate configs are cut over rather than
  relying on a silent default.
- Extend the shared netted portfolio book so every executed delta records
  turnover, bar participation, ADV participation, and impact cost from the same
  fill event that updates cash and NAV.
- Charge a simple size-aware market-impact cash term inside the book walk; do
  not add partial fills, order slicing, venue routing, or a second money model.
- Surface compact capacity diagnostics in quick-run foundation metrics and typed
  quick-run economics.
- Surface detailed capacity/impact execution traces in evaluation artifacts.
- Treat FX capacity as unsupported until calibrated, because this repo's FX
  `volume` is tick count/activity, not traded notional volume.

## Capabilities

### New Capabilities

- `capacity-adv-market-impact`: operator-frozen capacity modeling, market-impact
  charging, capacity diagnostics, and unsupported-data semantics across the shared
  book.

### Modified Capabilities

- `data-boundary`: row-contract behavior changes when capacity modeling requires
  volume/ADV inputs, including unsupported FX tick-count semantics.
- `quick-run-portfolio-foundation`: the authoritative quick-run book now includes
  capacity-aware impact costs and compact capacity diagnostics.
- `quick-run-economics`: the typed per-round-trip economics now attribute
  impact costs from the same book walk.

## Impact

- Affected config models: shared core config, quick-run, validation, and
  evaluation config schemas.
- Affected execution code: `core/portfolio_foundation.py` and the shared
  validation/evaluation wrappers that pass operator envelopes into the book.
- Affected result/artifact code: quick-run summary/diagnostics, typed economics,
  validation backend metrics, and evaluation trace tables.
- Affected data contract: capacity-enabled runs require valid notional volume
  inputs for supported data kinds and fail/mark unsupported where volume is not a
  calibrated notional capacity measure.
- Dependencies: no new runtime dependency; the quick-run import wall remains
  intact.
