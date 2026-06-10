## 1. Contract Tests

- [x] 1.1 Add focused portfolio-foundation tests for `full_train` records in summary and matrix payloads.
- [x] 1.2 Add focused statistics tests for `mean_return` and `return_volatility` in return-statistic payloads.

## 2. Core Implementation

- [x] 2.1 Refactor the foundation metric record so full-Train and subwindow metrics share one payload shape.
- [x] 2.2 Compute and attach `full_train` metrics for each scenario from the scenario's scoring path.
- [x] 2.3 Add `mean_return`, `return_volatility`, and `total_return` fields without emitting raw NAV or period-return traces.

## 3. Documentation And Spec Alignment

- [x] 3.1 Update quick-run foundation consumer docs and foundation-surface docs for the additive `full_train` record.
- [x] 3.2 Update OpenSpec tasks and run OpenSpec validation for the change.

## 4. Verification

- [x] 4.1 Run focused tests covering portfolio foundation and quick-run artifact payloads.
- [x] 4.2 Run import-wall verification to confirm quick-run foundation still avoids heavy evaluation dependencies.
