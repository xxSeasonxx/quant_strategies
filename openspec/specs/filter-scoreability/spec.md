# filter-scoreability Specification

## Purpose
Define how validation and evaluation filters preserve the shared portfolio book's
typed scoreability verdicts, distinguish required coverage from scoreable
evidence, and keep leverage feasibility owned by the book.
## Requirements
### Requirement: Filter scenarios carry shared-book feasibility verdicts

Validation and evaluation scenario results SHALL carry the shared portfolio
book's `FeasibilityVerdict`. A feasible scenario result SHALL expose a feasible
verdict. A non-scoreable scenario result SHALL expose the typed reason and detail
from the book verdict rather than requiring consumers to parse warning strings.

#### Scenario: Validation scenario exposes the book verdict
- **WHEN** validation runs a scenario through the shared portfolio book
- **THEN** the backend scenario result includes a `feasibility` payload
- **AND** the payload includes `feasible`, `reason`, observed exposure fields, and
  detail when present

#### Scenario: Evaluation scenario exposes the book verdict
- **WHEN** evaluation runs a scenario through the shared portfolio book
- **THEN** the scenario result includes a `feasibility` payload
- **AND** the same payload is available in evaluation metrics artifacts

#### Scenario: Typed verdict does not collapse into warnings only
- **WHEN** the book reports a non-scoreable reason such as `zero_cost`,
  `insufficient_samples`, or `leverage_budget_breach`
- **THEN** the scenario result exposes that reason in its `feasibility` payload
- **AND** warnings remain supplementary diagnostics only

### Requirement: Scoreability-bearing scenarios fail closed on infeasible verdicts

Validation and evaluation SHALL distinguish diagnostic/reference scenarios from
scoreability-bearing scenarios. A required scoreability-bearing scenario SHALL
fail the filter when its `FeasibilityVerdict.feasible` value is false. A
non-scoreability-bearing scenario MAY complete and emit diagnostics with an
infeasible verdict, but it MUST NOT satisfy required scoreability gates.

#### Scenario: Required validation scenario fails on non-scoreable verdict
- **WHEN** a required validation scenario is scoreability-bearing
- **AND** its backend result carries `feasibility.feasible = false`
- **THEN** validation returns a mechanical failure
- **AND** the failure identifies the typed feasibility reason

#### Scenario: Required evaluation scenario fails on non-scoreable verdict
- **WHEN** a required evaluation scenario is scoreability-bearing
- **AND** its scenario result carries `feasibility.feasible = false`
- **THEN** evaluation fails closed for that scenario
- **AND** the failure identifies the typed feasibility reason

#### Scenario: Reference scenarios remain diagnostic
- **WHEN** a zero-cost or reference scenario is marked
  `scoreability_bearing = false`
- **AND** its scenario result carries a non-scoreable verdict
- **THEN** validation or evaluation may keep the scenario diagnostics
- **AND** the scenario does not count as successful scoreability evidence

### Requirement: Validation leverage feasibility is owned by the book

Validation SHALL NOT reject target books with a fixed gross-exposure ceiling
before backend execution. Intended gross and net exposure SHALL be checked by
the shared portfolio book against the configured `LeverageBudgetConfig`, and any
breach SHALL surface as the book's typed `leverage_budget_breach` verdict.

#### Scenario: Leveraged book within budget reaches the spine
- **WHEN** validation runs a target book with gross exposure greater than `1.0`
- **AND** the configured leverage budget admits that gross and net exposure
- **THEN** validation executes the backend scenario
- **AND** no preflight `exposure_admissibility` failure is emitted

#### Scenario: Leveraged book above budget fails with typed verdict
- **WHEN** validation runs a target book whose intended exposure breaches the
  configured leverage budget
- **THEN** the shared portfolio book emits `leverage_budget_breach`
- **AND** validation reports that typed feasibility reason rather than a fixed
  gross `> 1.0` preflight reason
