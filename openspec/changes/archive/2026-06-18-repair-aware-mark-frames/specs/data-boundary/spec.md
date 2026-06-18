## ADDED Requirements

### Requirement: Valuation mark frame is loaded through the upstream repair-aware contract loader

`load_data` SHALL load a valuation **mark frame** separately from the raw
signal/execution frame, through the upstream repair-aware contract loader
`quant_data.contract_loaders.load_strategy_universe_mark_frame` with `strict=True` and
`return_summary=True`, over the same effective load window (including the execution
buffer) as the signal frame. The mark dataset SHALL be the **base OHLCV dataset**
underlying the signal frame when that dataset supports regular-series repair (the strict
loader's window validation only supports base datasets); otherwise `load_data` SHALL load
no mark frame, and a within-window gap fails closed at valuation. Consuming the upstream
repair-aware loader is distinct from local repair: the consumer still MUST NOT reorder,
de-duplicate, join, or repair the signal rows itself.

#### Scenario: Repair-capable kind loads a repair-aware mark frame
- **WHEN** a `crypto_perp_funding` run loads data
- **THEN** `load_data` calls `load_strategy_universe_mark_frame(engine, symbols, "crypto_perp_1min", load_start, load_end, strict=True, return_summary=True)`
- **AND** carries the returned mark frame and its repair summary separately from the signal frame

#### Scenario: Mark window matches the signal load window
- **WHEN** the run uses an execution buffer (load end beyond the decision-window end)
- **THEN** the mark frame is loaded over the same effective load window so buffered exits have marks

#### Scenario: Unrepairable gap fails closed at the data-load stage
- **WHEN** the upstream mark loader raises an unrepairable-gap error for the window
- **THEN** the run fails at the data-load stage with a typed error and no portfolio book is walked

#### Scenario: No-repair dataset has no mark frame
- **WHEN** the signal dataset has no regular-series repair policy
- **THEN** `load_data` loads no mark frame, and a held bar that the signal frame is missing fails closed with `missing_mark` at valuation

#### Scenario: Local no-repair rule is preserved
- **WHEN** signal rows are returned by the loader
- **THEN** the consumer does not reorder, de-duplicate, join, or repair them locally; the only repair is performed by the upstream mark-frame loader
