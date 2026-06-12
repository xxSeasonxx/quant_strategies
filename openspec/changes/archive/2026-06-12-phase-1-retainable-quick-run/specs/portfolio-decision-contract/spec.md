## ADDED Requirements

### Requirement: Unpriced short financing fails closed

The portfolio book SHALL produce a typed fail-closed feasibility verdict for
intended short exposure in data kinds whose short financing or carry is not
modeled, rather than scoring free borrow/carry. Data kinds with modeled
financing, such as crypto-perp funding, are exempt from this verdict.

#### Scenario: Equity short exposure is unpriced
- **WHEN** a strategy targets a negative weight on an equity or ETF instrument
- **AND** the run has no modeled short-financing term for that data kind
- **THEN** the book fails closed with reason `unpriced_short_financing`
- **AND** no successful score is emitted from free short financing

#### Scenario: FX short exposure is unpriced
- **WHEN** a strategy targets a negative weight on an FX pair
- **AND** the run has no modeled carry or rollover term
- **THEN** the book fails closed with reason `unpriced_short_financing`

#### Scenario: Crypto-perp short exposure remains financed
- **WHEN** a crypto-perp funding run targets a negative weight
- **THEN** the short exposure is not rejected by `unpriced_short_financing`
- **AND** funding remains priced by the shared book
