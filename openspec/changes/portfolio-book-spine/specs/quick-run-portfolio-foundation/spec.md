## REMOVED Requirements

### Requirement: Quick run exposes diagnostic portfolio foundation metrics

**Reason**: The portfolio book is no longer an optional, additive, fail-open
*diagnostic* layered on top of an authoritative per-trade ledger. It becomes the
single authoritative scored object, and its unavailability on a risk breach is a
fail-closed verdict rather than a swallowed `None`. The replacement behavior is
defined by the ADDED requirements "Quick run exposes the authoritative scored
portfolio book" and "A leverage-budget breach is a fail-closed feasibility
verdict".

**Migration**: Consumers SHALL read `RunResult.foundation` as the authoritative
scored book and SHALL treat a typed infeasible verdict as a run failure. Code that
relied on a completed run with `foundation = None` plus a soft warning must instead
handle the typed feasibility verdict.

## ADDED Requirements

### Requirement: Quick run exposes the authoritative scored portfolio book

A completed, feasible quick run SHALL expose a populated portfolio book on
`RunResult.foundation`, and that book's NAV path SHALL be the single object from
which Train scoring statistics are derived. The book SHALL be produced by one
causal, single-account, stateful walk over the execution rows. The foundation
SHALL NOT be an optional diagnostic layered on an independent scored per-trade
sum.

#### Scenario: Feasible completed run returns the scored book
- **WHEN** `run_config` completes engine evaluation and the book is feasible
- **THEN** `RunResult.foundation` is populated with the NAV path and its scenario metrics
- **AND** the scored return statistics are derived from that NAV path

#### Scenario: Failed quick run omits the book
- **WHEN** a quick run fails before completed engine evaluation
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

The quick run SHALL carry a typed feasibility verdict. When the strategy's
intended **gross or net** exposure at a decision exceeds the operator-frozen
leverage budget, the run SHALL be marked **infeasible** with an actionable typed
reason (for example `leverage_budget_breach`) and the observed exposure, and
`RunResult.succeeded` SHALL be false. The engine SHALL NOT clamp, normalize, or
scale the book to fit the budget, and SHALL NOT collapse the breach into an untyped
`None`. A zero-cost scoreable run and a statistically degenerate sample SHALL
likewise produce typed infeasible verdicts. For an asset class whose financing is
not yet modeled, a net exposure greater than 1.0 SHALL produce a typed
`unfinanced_leverage` infeasible verdict rather than be scored with free leverage;
an asset class whose financing is modeled (for example crypto-perp funding) is not
subject to that verdict.

#### Scenario: Intended over-leverage fails closed
- **WHEN** a decision's intended gross or net exposure exceeds the frozen leverage budget
- **THEN** the run is marked infeasible with reason `leverage_budget_breach` and the observed exposure
- **AND** `RunResult.succeeded` is false
- **AND** the book is not rescaled to fit the budget

#### Scenario: Zero-cost run is non-scoreable
- **WHEN** a scoreable quick run is configured with zero costs below the operator cost floor
- **THEN** the run is marked infeasible with a typed zero-cost reason
- **AND** `RunResult.succeeded` is false

#### Scenario: Unpriced leverage is non-scoreable
- **WHEN** an asset class without a modeled financing term holds net exposure greater than 1.0
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

## MODIFIED Requirements

### Requirement: Foundation computes scenario portfolio paths once

The foundation SHALL build one causal after-cost portfolio path per configured
foundation scenario and SHALL slice that path into Train subwindows. It MUST NOT
replay strategy generation or rebuild the portfolio path independently for every
subwindow. The leverage budget SHALL cover both **gross and net** exposure and
SHALL be operator-frozen — owned by the protocol alongside costs and fills, and
removed from the runner/agent-editable output configuration. Exceeding it SHALL
yield the fail-closed feasibility verdict rather than permitting exposure up to a
limit or raising into a swallowed failure.

#### Scenario: Default scenarios include realistic and cost stress
- **WHEN** a quick run completes with default foundation settings
- **THEN** the foundation includes a realistic-cost scenario
- **AND** the foundation includes a cost-stressed scenario

#### Scenario: Subwindows are derived from the path
- **WHEN** a quick run configures N foundation subwindows within the supported
  1-64 range
- **THEN** each foundation scenario reports N subwindow metric records
- **AND** those records are computed by slicing the scenario's full Train path

#### Scenario: Excessive subwindow count is rejected
- **WHEN** a quick-run config sets `foundation_subwindows` above 64
- **THEN** config loading fails

#### Scenario: Leverage budget is operator-frozen and breach fails closed
- **WHEN** the strategy's intended exposure exceeds the operator-frozen leverage budget
- **THEN** the run yields the fail-closed feasibility verdict
- **AND** the budget is owned by the protocol, not the runner/agent-editable output block
- **AND** it is not a permit that silently allows exposure up to a limit

### Requirement: Foundation reports subwindow metric inputs

Each foundation subwindow metric record SHALL report the foundation inputs needed
by downstream Train scoring: return sample count, mean return, return volatility,
effective sample size, Sharpe, Sharpe uncertainty inputs, skew, kurtosis, DSR
inputs, DSR value when computable, total return, max drawdown, closed-trade count,
and max symbol concentration. These SHALL be computed from the single netted-book
NAV path over at-risk bars; `closed_trade_count` SHALL count netted-book round
trips (a net position returning to flat), not independent trade windows.

#### Scenario: Subwindow metrics include statistical inputs
- **WHEN** a subwindow has finite observed at-risk portfolio returns
- **THEN** its metric record includes `return_sample_count`,
  `mean_return`, `return_volatility`, `effective_sample_size`, `sharpe`,
  `sharpe_standard_error`, `skew`, `kurtosis`, `dsr_inputs`, and `dsr`

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
