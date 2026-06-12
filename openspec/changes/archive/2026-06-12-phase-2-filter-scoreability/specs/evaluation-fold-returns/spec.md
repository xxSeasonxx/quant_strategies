## ADDED Requirements

### Requirement: Evaluation scenario outputs include scoreability metadata

`run_evaluation` SHALL expose, for each scenario result, whether the scenario is
scoreability-bearing and the shared-book feasibility verdict that governed its
scoreability. Completed diagnostic scenarios MAY have return series and summary
metrics while carrying `feasibility.feasible = false`; scoreability-bearing
scenarios with infeasible verdicts SHALL NOT appear as successful fold evidence.

#### Scenario: Fold metrics include scenario scoreability
- **WHEN** an evaluation run completes with a diagnostic zero-cost scenario
- **THEN** the scenario's typed metrics expose `scoreability_bearing = false`
- **AND** the scenario's typed metrics expose the shared-book feasibility verdict

#### Scenario: Required scoreability-bearing failures are absent from fold accessors
- **WHEN** a required scoreability-bearing scenario receives an infeasible verdict
- **THEN** `run_evaluation` fails closed
- **AND** `EvaluationRunResult.fold_returns` does not expose that scenario as
  successful fold evidence

#### Scenario: Metrics artifacts include scoreability metadata
- **WHEN** evaluation writes `evaluation_metrics.json`
- **THEN** each scenario entry includes `required`, `scoreability_bearing`, and
  `feasibility`
