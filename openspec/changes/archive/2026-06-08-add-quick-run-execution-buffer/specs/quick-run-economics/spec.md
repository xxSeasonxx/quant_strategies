## ADDED Requirements

### Requirement: Quick-run supports an execution buffer separate from the decision window
The public quick-run config SHALL allow callers to provide an execution/load
window that covers the existing decision window. The existing `data.start` and
`data.end` fields SHALL remain the decision window used for strategy visibility,
causality replay, and Train scoring. When execution-buffer fields are omitted,
quick-run behavior SHALL remain unchanged.

#### Scenario: Existing config keeps single-window behavior
- **WHEN** a quick-run config omits execution-buffer fields
- **THEN** the runner loads the same window it uses for strategy generation and engine execution

#### Scenario: Load window can extend past decision end
- **WHEN** a quick-run config sets `data.load_end` later than `data.end`
- **THEN** the runner may use rows through `load_end` for engine fill and exit coverage
- **AND** `data.end` remains the final strategy-visible decision-window date

#### Scenario: Invalid load window is rejected
- **WHEN** a quick-run config sets a load window that does not cover `data.start` through `data.end`
- **THEN** config loading fails before strategy execution

### Requirement: Strategy generation and causality replay use only decision-window rows
Quick-run strategy generation, deterministic replay, emitted replay, and strict
replay SHALL receive only rows inside the decision window. Execution-buffer rows
SHALL NOT be visible to strategy code or causality replay.

#### Scenario: Strategy cannot see post-window buffer rows
- **WHEN** a quick run loads rows after `data.end` through `data.load_end`
- **THEN** `generate_decisions` receives no post-window buffer rows
- **AND** hidden-lookahead replay derives visible prefixes only from decision-window rows

#### Scenario: Buffer rows cannot repair strategy causality
- **WHEN** a strategy attempts to emit a decision that depends on rows after `data.end`
- **THEN** emitted replay fails rather than treating execution-buffer rows as strategy-visible evidence

### Requirement: Engine execution can use buffer rows for decision-window exits
Quick-run engine request construction SHALL use execution/load rows for fill and
exit coverage while evaluating only decisions eligible for the decision window.
Entries near the end of the decision window MAY resolve exits using buffer rows.

#### Scenario: Late decision exits inside buffer
- **WHEN** a decision-window decision requires exit bars after `data.end`
- **AND** those bars are present through `data.load_end`
- **THEN** request building succeeds and engine evaluation can complete

#### Scenario: Missing buffer still fails loudly
- **WHEN** a decision-window decision requires exit bars after the loaded execution window
- **THEN** request building fails with the existing fillability error

### Requirement: Quick-run economics exclude buffer-only entries
Quick-run economics SHALL report trades for decisions whose `decision_time` is
inside the decision window. Execution-buffer rows SHALL support fills and exits
only; they SHALL NOT introduce scored buffer-only entries.

#### Scenario: Decision-window trade is scored
- **WHEN** a decision has `decision_time` inside `data.start` through `data.end`
- **THEN** its completed engine trade can appear in `RunResult.economics`

#### Scenario: Buffer-only decision is excluded
- **WHEN** a decision has `decision_time` after the decision window
- **THEN** quick-run excludes it from engine evaluation and economics

### Requirement: Quick-run artifacts distinguish decision and execution rows
Quick-run artifacts SHALL distinguish strategy-visible decision-window rows from
execution/load rows when the load window differs from the decision window.
Artifacts MUST NOT silently relabel execution-buffer rows as strategy input
evidence.

#### Scenario: Manifest records both row windows
- **WHEN** a quick run uses an execution buffer
- **THEN** artifacts expose the decision window and the execution/load window
- **AND** row counts or hashes are labeled so strategy-visible evidence is distinguishable from execution support

#### Scenario: Replayability semantics remain honest
- **WHEN** a quick run writes replayable strategy-input artifacts
- **THEN** those artifacts correspond to strategy-visible rows, not execution-buffer rows
