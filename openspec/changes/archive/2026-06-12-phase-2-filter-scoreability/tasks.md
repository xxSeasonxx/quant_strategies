## 1. Validation Scoreability

- [x] 1.1 Add failing validation backend tests for zero-cost and insufficient-sample verdicts carried on `BackendRunResult`.
- [x] 1.2 Add failing validation policy/runner tests that required scoreability-bearing infeasible verdicts fail and zero-cost/reference diagnostics do not satisfy gates.
- [x] 1.3 Implement validation result `feasibility` and `scoreability_bearing` threading through backend results, matrix scenarios, artifacts, and policy gates.

## 2. Validation Leverage Ownership

- [x] 2.1 Add failing validation runner tests proving gross exposure above `1.0` but within configured leverage budget reaches the spine.
- [x] 2.2 Remove the validation hard gross-exposure preflight and delete unused exposure helper code.

## 3. Evaluation Scoreability

- [x] 3.1 Add failing evaluation scenario/backend tests for `scoreability_bearing` defaults and typed feasibility verdicts.
- [x] 3.2 Add failing evaluation pipeline tests that scoreability-bearing infeasible scenarios fail closed while non-bearing zero-cost diagnostics can complete.
- [x] 3.3 Implement evaluation scenario/result scoreability fields, verdict computation, typed fold metrics, and artifact payloads.

## 4. Verification And Closeout

- [x] 4.1 Run focused validation/evaluation tests and `openspec validate phase-2-filter-scoreability --strict`.
- [x] 4.2 Run `make check` and `git diff --check`.
- [x] 4.3 Update action status in `foundation-review-2026-06-12.md`, archive the OpenSpec change, rerun strict validation, and commit.
