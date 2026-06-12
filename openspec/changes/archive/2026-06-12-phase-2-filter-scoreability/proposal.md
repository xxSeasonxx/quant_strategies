## Why

Validation and evaluation both use the shared target-book spine, but required
filter scenarios do not consistently carry or gate on the spine's typed
scoreability verdicts. That lets zero-cost or insufficient-sample evidence look
completed on later filters even though quick run treats the same book as
non-scoreable, and validation still has a separate hard gross-exposure preflight
beside the book's configured leverage budget.

## What Changes

- Add a filter scoreability contract for validation/evaluation scenarios.
- Carry the portfolio book's `FeasibilityVerdict` on validation backend results
  and evaluation scenario results.
- Fail required scoreability-bearing validation/evaluation scenarios when their
  feasibility verdict is non-scoreable.
- Treat zero-cost/reference scenarios as diagnostic evidence, not scoreability
  gates.
- Remove validation's hard-coded gross `> 1.0` exposure preflight so the shared
  portfolio book is the single leverage-budget verdict owner.

## Capabilities

### New Capabilities

- `filter-scoreability`: Validation and evaluation scenario results expose and
  gate on shared-book feasibility verdicts while diagnostic reference scenarios
  remain non-scoreability-bearing.

### Modified Capabilities

- `evaluation-fold-returns`: Evaluation fold/scenario result accessors and
  artifacts carry scoreability verdict metadata for completed and failed
  scenarios.

## Impact

- Affected code:
  - `src/quant_strategies/validation/backends.py`
  - `src/quant_strategies/validation/engine_backend.py`
  - `src/quant_strategies/validation/matrix.py`
  - `src/quant_strategies/validation/policy.py`
  - `src/quant_strategies/validation/_pipeline.py`
  - `src/quant_strategies/evaluation/results.py`
  - `src/quant_strategies/evaluation/scenarios.py`
  - `src/quant_strategies/evaluation/spine_backend.py`
  - `src/quant_strategies/evaluation/_pipeline.py`
- `src/quant_strategies/core/exposure.py` becomes removable unless another
  caller remains.
- Tests covering validation policy, validation runner exposure handling,
  validation/evaluation backend scoreability, evaluation default scenarios, and
  artifacts need updates.
