## MODIFIED Requirements

### Requirement: The Train path stays trade-unit and dependency-light

This capability SHALL preserve the existing trade-level quick-run economics
contract: `RunEconomics` exposes only the trade-level (point-to-point,
per-trade) economics the engine computes. A separate diagnostic portfolio
foundation MAY expose portfolio-path-derived foundation metrics for Train
scoring, but it MUST remain outside `RunEconomics`. The quick-run code path
MUST NOT introduce a runtime dependency on `vectorbtpro`, `pandas`, `numpy`, or
`quant_strategies.evaluation`.

#### Scenario: Trade economics remain trade-unit
- **WHEN** the quick-run economics object is read
- **THEN** it exposes per-trade records and undeflated summary scalars/slices only
- **AND** it exposes no per-period return series, no portfolio NAV path, and no PSR/DSR/PBO field

#### Scenario: Portfolio foundation is separate from trade economics
- **WHEN** a completed quick run exposes diagnostic portfolio foundation metrics
- **THEN** those metrics are available from a separate `RunResult` field
- **AND** `RunResult.economics` remains the engine trade-ledger object

#### Scenario: Quick-run path imports no heavyweight backend dependency
- **WHEN** the quick-run path (`runner`, `engine`, `core`) is imported and exercised
- **THEN** it does not import `vectorbtpro`, `pandas`, `numpy`, or `quant_strategies.evaluation`
