## ADDED Requirements

### Requirement: Quick-run foundation applies risk-budget sizing before scoring
The quick-run portfolio foundation SHALL transform the emitted base target-book
shape into final executable target weights using the configured risk-budget sizing
policy before building scenario portfolio paths. Train scoring statistics,
capacity diagnostics, per-trade economics, and artifacts SHALL derive from the
final sized NAV path, not from raw emitted shape weights.

#### Scenario: Quick run scores final sized book
- **WHEN** a quick run completes with `[risk_budget].mode = "calibrate_vol"`
- **THEN** `RunResult.foundation.ledger` is the realistic-cost walk of the final sized book
- **AND** all foundation metrics derive from that sized NAV path

#### Scenario: Raw shape scale cannot improve score
- **WHEN** two emitted decision streams differ only by multiplying every non-zero raw target by the same positive constant
- **THEN** their quick-run final sized target weights and foundation metrics are equal within numeric tolerance

### Requirement: Capacity-bound calibration remains scoreable and explicit
The quick-run foundation SHALL treat capacity-bound `calibrate_vol` runs as
scoreable when the final frontier-sized book is feasible. When `calibrate_vol`
reaches the feasible capacity or leverage frontier before the requested
annualized volatility, the quick-run foundation SHALL score the frontier-sized
final book and report `capacity_bound = true` with `max_feasible_volatility`.
This condition SHALL NOT be encoded as an infeasible verdict because the final
sized book is feasible.

#### Scenario: Target volatility exceeds frontier
- **WHEN** the requested annualized volatility exceeds the maximum feasible volatility for the normalized shape
- **THEN** the quick-run foundation walks and scores the maximum feasible sized book
- **AND** the sizing report sets `capacity_bound = true`
- **AND** the feasibility verdict remains feasible when no final-book breach exists

#### Scenario: Genuine infeasibility still fails closed
- **WHEN** capacity is unpriced, capacity volume semantics are unsupported, required volume or ADV history is missing, cost floors are invalid, financing is unpriced, or the final sized book breaches the envelope
- **THEN** the quick run returns the existing typed fail-closed feasibility verdict
- **AND** no successful scored book is emitted from an untradeable final book

## MODIFIED Requirements

### Requirement: Foundation computes scenario portfolio paths once
The foundation SHALL build one causal after-cost portfolio path per configured
foundation scenario from the final risk-budget-sized executable book and SHALL
slice that path into Train subwindows. It MUST NOT replay strategy generation or
rebuild the portfolio path independently for every subwindow. The leverage budget
SHALL cover both **gross and net** final executable exposure and SHALL be
operator-frozen, owned by the protocol alongside costs, fills, capacity, and risk
budget. Exceeding it after fixed sizing SHALL yield the fail-closed feasibility
verdict rather than clamping or swallowing failure. In `calibrate_vol`, a requested
risk budget above the feasible frontier SHALL be reported as capacity-bound sizing
and SHALL NOT weaken final-book feasibility.

#### Scenario: Default scenarios include realistic, cost stress, and fill stress
- **WHEN** a quick run completes with default foundation settings
- **THEN** the foundation includes a realistic-cost scenario
- **AND** the foundation includes a cost-stressed scenario
- **AND** the foundation includes a fill-stress scenario applying adverse slippage to `RiskRule` barrier exits
- **AND** the fill-stress scenario is omitted when `foundation_fill_stress_fraction` is `0.0`

#### Scenario: Fill stress is a diagnostic, not the climbed path
- **WHEN** a quick run sets a non-zero `foundation_fill_stress_fraction`
- **THEN** the fill-stress scenario's barrier exits fill more adversely than the realistic scenario
- **AND** the `realistic_costs` scenario the loop climbs is unchanged by the knob

#### Scenario: Subwindows are derived from the path
- **WHEN** a quick run configures N foundation subwindows within the supported 1-64 range
- **THEN** each foundation scenario reports N subwindow metric records
- **AND** those records are computed by slicing the scenario's full Train path

#### Scenario: Excessive subwindow count is rejected
- **WHEN** a quick-run config sets `foundation_subwindows` above 64
- **THEN** config loading fails

#### Scenario: Leverage budget is operator-frozen and final-book breach fails closed
- **WHEN** the final executable book's intended exposure exceeds the operator-frozen leverage budget
- **THEN** the run yields the fail-closed feasibility verdict
- **AND** the budget is owned by the protocol, not the runner/agent-editable output block
- **AND** the final book is not silently clamped to fit

### Requirement: Quick run exposes the authoritative scored portfolio book
A completed, feasible quick run SHALL expose a populated portfolio book on
`RunResult.foundation`, and that book's NAV path SHALL be the single object from
which Train scoring statistics are derived. The book SHALL be produced by one
causal, single-account, stateful walk over the execution rows after risk-budget
sizing has produced final executable target weights. The foundation SHALL NOT be
an optional diagnostic layered on an independent scored per-trade sum.

#### Scenario: Feasible completed run returns the scored book
- **WHEN** `run_config` completes engine evaluation, risk-budget sizing, and the book is feasible
- **THEN** `RunResult.foundation` is populated with the final sized NAV path and its scenario metrics
- **AND** the scored return statistics are derived from that NAV path

#### Scenario: Failed quick run omits the book
- **WHEN** a quick run fails before completed engine evaluation or before a feasible final sized book exists
- **THEN** `RunResult.foundation` carries no scored book
- **AND** no foundation metrics are written as successful artifacts

#### Scenario: Foundation remains non-promotion evidence
- **WHEN** a quick run writes foundation artifacts
- **THEN** the artifacts continue to indicate the run is not promotion, paper-trade, or live eligible
- **AND** the book is authoritative for the Train feasibility score only

### Requirement: A leverage-budget breach is a fail-closed feasibility verdict
The quick run SHALL carry a typed feasibility verdict. When the final executable
book's intended **gross or net** exposure at a decision exceeds the
operator-frozen leverage budget, the run SHALL be marked **infeasible** with an
actionable typed reason (for example `leverage_budget_breach`) and the observed
exposure, and `RunResult.succeeded` SHALL be false. The engine SHALL NOT clamp,
normalize, or rescale a final executable book to fit the budget, and SHALL NOT
collapse the breach into an untyped `None`. A zero-cost scoreable run and a
statistically degenerate sample SHALL likewise produce typed infeasible verdicts.
For an asset class whose financing is not yet modeled, a final net exposure
greater than 1.0 SHALL produce a typed `unfinanced_leverage` infeasible verdict
rather than be scored with free leverage; an asset class whose financing is
modeled (for example crypto-perp funding) is not subject to that verdict.

#### Scenario: Intended over-leverage fails closed
- **WHEN** a final executable decision's intended gross or net exposure exceeds the frozen leverage budget
- **THEN** the run is marked infeasible with reason `leverage_budget_breach` and the observed exposure
- **AND** `RunResult.succeeded` is false
- **AND** the book is not rescaled to fit the budget

#### Scenario: Zero-cost run is non-scoreable
- **WHEN** a scoreable quick run is configured with zero costs below the operator cost floor
- **THEN** the run is marked infeasible with a typed zero-cost reason
- **AND** `RunResult.succeeded` is false

#### Scenario: Unpriced leverage is non-scoreable
- **WHEN** an asset class without a modeled financing term holds final net exposure greater than 1.0
- **THEN** the run is marked infeasible with reason `unfinanced_leverage`
- **AND** a crypto-perp book, whose funding is modeled, is not flagged by this verdict

#### Scenario: Breach reason is actionable, not a swallowed None
- **WHEN** any feasibility breach occurs
- **THEN** the verdict names the breached dimension and observed value
- **AND** a benign data gap, an internal error, and a risk breach are distinguishable verdicts

### Requirement: Foundation book includes capacity impact in scored NAV
The quick-run portfolio foundation SHALL charge capacity impact inside the same
single netted-book walk that applies target deltas, fees, slippage, funding,
mark-to-market, and risk-budget-sized final weights. Foundation return statistics
SHALL be derived from the capacity-impacted NAV path. Capacity impact SHALL NOT be
reported as a separate post-score adjustment.

#### Scenario: Capacity impact changes the scored path
- **WHEN** a quick run executes a non-zero final sized delta with positive configured impact
- **THEN** the realistic-cost foundation scenario subtracts impact cost on the execution bar
- **AND** its NAV path and Train statistics reflect that impact

#### Scenario: Cost stress preserves capacity semantics
- **WHEN** the foundation builds its cost-stress scenario
- **THEN** the scenario applies the configured fee/slippage stress and the same final sized target book
- **AND** it does not drop capacity impact from the stressed book walk

### Requirement: Foundation reports compact capacity diagnostics
Each quick-run foundation scenario SHALL report compact capacity diagnostics
derived from the final sized book's execution events: executed turnover, impact
cost, maximum and mean bar participation, maximum and mean ADV participation, and
capacity verdict detail when a run is infeasible. Default summary and diagnostic
artifacts SHALL remain compact and SHALL NOT write full per-event traces unless a
full artifact profile later requires them.

#### Scenario: Completed capacity-priced run reports capacity diagnostics
- **WHEN** a quick run completes with capacity-priced final sized deltas
- **THEN** `RunResult.foundation` and summary diagnostics include turnover, impact cost, and participation aggregates
- **AND** those aggregates are derived from the same execution events that updated NAV

#### Scenario: Capacity infeasibility is distinguishable
- **WHEN** a quick run fails because final-book capacity is unpriced, unsupported, missing, insufficient, or breached
- **THEN** the feasibility verdict names the capacity reason
- **AND** `RunResult.succeeded` is false
