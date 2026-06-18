# quick-run-portfolio-foundation Specification

## Purpose

Provide diagnostic quick-run portfolio-return foundation metrics for Train
scoring without using the heavier evaluation backend.
## Requirements
### Requirement: Foundation path avoids heavy evaluation dependencies

The quick-run portfolio foundation SHALL compute from normalized quick-run rows
and emitted decisions without importing or calling the evaluation backend. The
quick-run path MUST NOT import `quant_strategies.evaluation`,
`pandas`, or `numpy` to build foundation metrics.

#### Scenario: Quick-run foundation import wall is preserved
- **WHEN** the quick-run path imports `runner`, `engine`, `core`, and builds
  quick-run economics plus portfolio foundation metrics
- **THEN** `quant_strategies.evaluation`, `pandas`, and `numpy`
  are absent from imported modules

#### Scenario: Foundation uses quick-run execution rows
- **WHEN** a quick run uses a load window wider than its decision window
- **THEN** foundation metrics are computed from the execution rows needed to fill
  and mark emitted decisions
- **AND** strategy generation remains limited to decision-window rows

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

### Requirement: Foundation reports subwindow metric inputs

Each foundation subwindow metric record SHALL report the foundation inputs needed
by downstream Train scoring: return sample count, mean return, return volatility,
effective sample size, Sharpe, Sharpe uncertainty inputs, skew, kurtosis,
total return, max drawdown, closed-trade count,
and max symbol concentration. These SHALL be computed from the single netted-book
NAV path over at-risk bars; `closed_trade_count` SHALL count netted-book round
trips (a net position returning to flat), not independent trade windows.

#### Scenario: Subwindow metrics include statistical inputs
- **WHEN** a subwindow has finite observed at-risk portfolio returns
- **THEN** its metric record includes `return_sample_count`,
  `mean_return`, `return_volatility`, `effective_sample_size`, `sharpe`,
  `sharpe_standard_error`, `skew`, and `kurtosis`

#### Scenario: Subwindow metrics include gate inputs
- **WHEN** a subwindow contains portfolio path and trade activity
- **THEN** its metric record includes `total_return`, `max_drawdown`,
  `closed_trade_count`, and `max_symbol_concentration`

#### Scenario: Closed round trips are counted by exit time
- **WHEN** a netted-book position is opened before a subwindow and returns to flat inside it
- **THEN** that round trip contributes to that subwindow's `closed_trade_count`
- **AND** it does not contribute to the prior subwindow's closed-trade count

### Requirement: Foundation reports full-Train metric inputs

Each foundation scenario SHALL report a compact `full_train` metric record computed
from the same single netted-book NAV path used to derive subwindow metrics, over
at-risk bars. The `full_train` record SHALL include the return-statistic inputs
needed by downstream PSR scoring and minimal gate inputs that require upstream path
accounting. Downstream systems SHALL NOT need raw period-return traces to calculate
a PSR score from foundation statistics.

#### Scenario: Full-Train metric includes statistical inputs
- **WHEN** a scenario has finite observed at-risk Train portfolio returns
- **THEN** its `full_train` record includes `return_sample_count`,
  `effective_sample_size`, `mean_return`, `return_volatility`, `sharpe`,
  `sharpe_standard_error`, `skew`, `kurtosis`, and `warnings`
- **AND** those statistics are computed from the scenario's full Train NAV path,
  not from subwindow summaries

#### Scenario: Full-Train metric includes gate inputs
- **WHEN** a scenario contains Train portfolio path and trade activity
- **THEN** its `full_train` record includes `total_return`, `max_drawdown`,
  `closed_trade_count`, and `max_symbol_concentration`

### Requirement: Default artifacts stay compact and diagnostic

Quick-run foundation artifacts SHALL be compact by default. Default diagnostic
and summary artifacts SHALL include foundation metric summaries, not full
per-period return traces.

#### Scenario: Diagnostic artifacts include compact foundation metrics
- **WHEN** a completed quick run writes default diagnostic artifacts
- **THEN** `summary.json` includes compact foundation metrics
- **AND** `diagnostics.json` includes the foundation metric matrix
- **AND** neither artifact contains the full per-period return trace by default

#### Scenario: Foundation evidence is not promotion authority
- **WHEN** a quick run writes foundation artifacts
- **THEN** the artifacts continue to indicate the run is not promotion eligible,
  paper-trade eligible, or live eligible

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

### Requirement: The portfolio book nets same-symbol exposure on one account

The portfolio book SHALL track a running signed quantity per instrument on one
shared cash/margin account. At each decision it SHALL trade only the delta between
the target quantity and the current quantity, and SHALL charge costs on the traded
delta and financing/funding on the net held position. Gross and net exposure SHALL
be measured on the netted, marked-to-market book, not as a sum over independent
trade windows. When several instruments are targeted at the same bar, the engine
SHALL size them against one equity snapshot taken before any of that bar's entries,
so the intended gross equals the sum of the absolute target weights exactly and is
independent of same-bar fill order.

#### Scenario: Offsetting same-symbol intent nets before measurement
- **WHEN** the book holds a position and a new target reduces or reverses it
- **THEN** only the delta is traded and costed
- **AND** gross exposure reflects the netted position, not the sum of legs

#### Scenario: Gross exposure is a marked-to-market series
- **WHEN** the book is marked each bar
- **THEN** it reports a live gross-exposure series from net positions and marks
- **AND** per-instrument concentration is derived from the same netted book

#### Scenario: Same-bar sizing is fill-order independent
- **WHEN** a strategy targets multiple instruments at one bar with total intended weight W
- **THEN** the instruments are sized against one pre-entry equity snapshot
- **AND** the measured intended gross equals W regardless of the order the entries are applied

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

### Requirement: Return statistics are computed over at-risk bars with a minimum-sample gate

The foundation return statistics SHALL be computed over the bars on which capital
is actually deployed (at-risk bars), not over a zero-padded union-of-timestamps
calendar. A subwindow or full-Train statistic SHALL be scoreable only when its
at-risk return sample meets a configured minimum; below the minimum the statistic
SHALL be reported as non-scoreable with a typed reason rather than emitted from
sample count alone.

#### Scenario: Statistics use at-risk returns
- **WHEN** a strategy is in cash for part of a window
- **THEN** the window's return statistics are computed from the at-risk return sample
- **AND** flat zero-return bars do not inflate the effective sample size

#### Scenario: Degenerate sample is gated
- **WHEN** a subwindow's at-risk return sample is below the configured minimum
- **THEN** that subwindow's statistic is reported non-scoreable with a typed reason
- **AND** it is not emitted as a finite Sharpe from sample count alone

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

