## ADDED Requirements

### Requirement: Position valuation resolves against a dedicated repair-aware mark frame

The portfolio book SHALL value open positions — NAV mark, exposure series, and barrier
*detection* — against a dedicated mark frame that is separate from the execution frame.
Mark-eligible repaired rows SHALL NOT feed fills, capacity/ADV, funding, or signal
projection; those resolve only against observed, tradable signal rows. A walked bar that
has neither an observed signal row nor a mark-eligible mark row for a held symbol SHALL
fail closed with a typed `missing_mark` error. Every repaired mark consumed in the scored
NAV path SHALL be recorded in an `is_repaired` audit trail emitted with the foundation's
repair summary.

#### Scenario: Held position across a repairable gap is marked, not crashed
- **WHEN** a position is open at a bar its symbol did not observe but the walk visits, and a mark-eligible repaired row exists for that bar
- **THEN** the position is valued at the repaired mark and the walk continues without raising `missing_mark`

#### Scenario: Barrier detection reads the mark frame
- **WHEN** a risk-rule position is evaluated at a repaired (flat `open=high=low=close`) bar
- **THEN** no barrier fires on the flat bar and detection resolves on the next observed bar with the existing gap-through fill price

#### Scenario: Repaired rows never reach execution surfaces
- **WHEN** capacity/ADV, a fill, or funding reads a bar for a symbol
- **THEN** it resolves only against an observed tradable signal row and never against a repaired row (`volume=0`, `tradable=False`)

#### Scenario: Missing mark with no repair fails closed
- **WHEN** a held bar has neither a signal row nor a mark-eligible mark row
- **THEN** the run raises a typed `missing_mark` and produces no scored book

#### Scenario: Consumed repaired marks are audited
- **WHEN** the scored NAV path consumes one or more repaired marks
- **THEN** the foundation payload records each consumed `(symbol, timestamp)` with `is_repaired` provenance alongside the upstream repair summary
