# internal-evaluation-engine Specification

## Purpose

Define the deterministic internal evaluator owned by `quant_strategies`:
request/result models, fill and cost accounting, funding-aware trade returns,
screen/validation behavior, evidence serialization, and the boundary that
keeps strategy files and runner artifact orchestration separate from evaluator
logic.

## Requirements
### Requirement: Internal Evaluator Package Boundary

`quant_strategies` SHALL own a deterministic internal evaluator package for
screening, validation, fill/cost accounting, and evidence serialization. The
internal evaluator SHALL be separate from strategy modules and runner artifact
orchestration.

#### Scenario: Runner imports internal evaluator

- **WHEN** the strategy runner builds and evaluates a request
- **THEN** it imports evaluator models and functions from the internal
  `quant_strategies` package
- **AND** it does not import the external `quant_engine` package

#### Scenario: Strategy files remain pure

- **WHEN** a strategy module under `tested/` or `untested/` generates signals
- **THEN** it does not call the internal evaluator, load data, or write run
  artifacts

### Requirement: Deterministic Evaluation Contracts

The internal evaluator SHALL expose explicit request/result contracts for bars,
signals, fill models, cost models, trades, screening results, validation
reports, and evidence packets.

#### Scenario: Evaluation request validates inputs

- **WHEN** a caller constructs an evaluator request with invalid timestamps,
  invalid prices, missing quote fields for quote fills, or incomplete funding
  events
- **THEN** the evaluator rejects the request or evaluation fail-closed path
  deterministically

#### Scenario: Evidence serialization is deterministic

- **WHEN** the same evaluator request and result are serialized multiple times
- **THEN** evidence JSON bytes are stable for the same interpreter and package
  state

### Requirement: Funding-Aware Accounting Remains Explicit

The internal evaluator SHALL account for supplied crypto perpetual funding
events only when request bars explicitly include funding event fields.

#### Scenario: Funding event inside held interval

- **WHEN** a trade is held across a funding event where
  `entry_time < funding_timestamp <= exit_time`
- **THEN** the trade includes `funding_return`
- **AND** `net_return` includes price return plus funding return minus costs

#### Scenario: No supplied funding events

- **WHEN** request bars do not include funding events inside the held interval
- **THEN** `funding_return` is zero
- **AND** price-return and cost behavior remain unchanged

### Requirement: Standalone Engine Surface Is Removed

The repository SHALL NOT provide `quant_engine` as a public import path or
`quant-engine` as a console script after the cutover.

#### Scenario: Package metadata has no quant-engine dependency

- **WHEN** project dependencies and scripts are inspected
- **THEN** `quant-engine` is not listed as a dependency
- **AND** no `quant-engine` console script is provided by this project

#### Scenario: First-party code avoids old engine surface

- **WHEN** first-party source, tests, and docs are searched
- **THEN** active code does not import `quant_engine`
- **AND** active workflows do not shell `quant-engine`
