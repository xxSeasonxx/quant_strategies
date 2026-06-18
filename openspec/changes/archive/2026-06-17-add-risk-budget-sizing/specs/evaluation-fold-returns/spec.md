## MODIFIED Requirements

### Requirement: Evaluation consumes the target-book contract and one shared accounting model
The evaluation surface SHALL execute strategies through the same target-book
decision contract, risk-budget sizing policy, and single causal portfolio book as
quick run, with no open-ticket translation layer that rejects flat or leveraged
shape targets as unsupported semantics. Evaluation SHALL apply
`[risk_budget].mode = "fixed_scale"` for retained-candidate fold evidence and
SHALL NOT recalibrate `book_scale` from the realized returns, volatility, drawdown,
or capacity headroom of the same evaluation fold. Evaluation SHALL report a single
shared accounting/funding model identity; the per-asset-class hand-rolled
perp-ledger model name SHALL be retired from the public metric contract, and any
validation gate that enumerates acceptable completed funding models SHALL reflect
the single shared model rather than requiring the removed perp-ledger model. A
second backend MAY exist only as an independent cross-check that must agree with
the shared book, never as a divergent money model the surface routes to by data
kind.

#### Scenario: Evaluation accepts the target-book contract
- **WHEN** an evaluation run executes a strategy that emits flat (`0`) or net-or-gross-leveraged shape targets
- **THEN** the run accepts them through the shared sizing policy and book rather than rejecting them as unsupported decision semantics
- **AND** final executable exposure beyond the leverage budget is handled by the feasibility verdict

#### Scenario: Evaluation does not recalibrate OOS folds
- **WHEN** evaluation runs retained-candidate fold evidence
- **THEN** each fold uses `[risk_budget].mode = "fixed_scale"`
- **AND** no fold computes a new `book_scale` from that fold's realized return or volatility path

#### Scenario: The retired perp-ledger model name is absent from the metric contract
- **WHEN** an evaluation run completes for a crypto-perp data kind
- **THEN** its metric payload identifies the single shared accounting model
- **AND** no field reports the removed `project_perp_ledger_v1` model name

#### Scenario: The completed-funding-model gate reflects the single model
- **WHEN** validation checks the completed funding/accounting model of an evaluation run
- **THEN** the gate accepts the single shared model
- **AND** it does not require the removed perp-ledger model identifier

### Requirement: Evaluation scenario outputs include scoreability metadata
`run_evaluation` SHALL expose, for each scenario result, whether the scenario is
scoreability-bearing, the shared-book feasibility verdict that governed its
scoreability, and the sizing report used to construct the final executable book.
Completed diagnostic scenarios MAY have return series and summary metrics while
carrying `feasibility.feasible = false`; scoreability-bearing scenarios with
infeasible verdicts SHALL NOT appear as successful fold evidence.

#### Scenario: Fold metrics include scenario scoreability
- **WHEN** an evaluation run completes with a diagnostic zero-cost scenario
- **THEN** the scenario's typed metrics expose `scoreability_bearing = false`
- **AND** the scenario's typed metrics expose the shared-book feasibility verdict

#### Scenario: Fold metrics include sizing report
- **WHEN** an evaluation scenario completes
- **THEN** the scenario's typed metrics expose the sizing report
- **AND** the fold return series values are from the final sized book described by that report

#### Scenario: Required scoreability-bearing failures are absent from fold accessors
- **WHEN** a required scoreability-bearing scenario receives an infeasible verdict
- **THEN** `run_evaluation` fails closed
- **AND** `EvaluationRunResult.fold_returns` does not expose that scenario as successful fold evidence

#### Scenario: Metrics artifacts include scoreability metadata
- **WHEN** evaluation writes `evaluation_metrics.json`
- **THEN** each scenario entry includes `required`, `scoreability_bearing`, `feasibility`, and `sizing_report`
