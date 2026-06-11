## ADDED Requirements

### Requirement: Quick-run economics attribute market-impact costs

The typed quick-run economics ledger SHALL expose market-impact cost attribution
derived from the same netted book execution events that update NAV. `cost_return`
SHALL remain the total transaction-cost return component, and an additional
impact-cost component SHALL show the portion of total cost caused by capacity
impact. Net round-trip attribution SHALL reconcile as gross plus funding minus
total cost, with impact included in total cost.

#### Scenario: Per-trade ledger includes impact attribution
- **WHEN** a completed round trip includes one or more impacted execution events
- **THEN** the typed economics record exposes a positive impact-cost return component
- **AND** its total `cost_return` includes both base transaction costs and impact costs

#### Scenario: Existing net attribution still reconciles
- **WHEN** a completed round trip reports gross, funding, total cost, impact, and net return
- **THEN** net return equals gross return plus funding return minus total cost return
- **AND** impact return is a component of total cost return, not a second independent subtraction

### Requirement: Economics slices summarize capacity impact

Quick-run economics summary scalars and slices SHALL include total impact cost
and impact share of absolute gross attribution where computable. These values
SHALL be reachable from the in-process `RunResult.economics` object without
reading artifacts.

#### Scenario: Summary exposes impact totals
- **WHEN** a quick run completes with impacted execution events
- **THEN** the economics summary exposes total impact cost and impact share
- **AND** by-symbol and by-exit-reason slices include impact-cost contribution
