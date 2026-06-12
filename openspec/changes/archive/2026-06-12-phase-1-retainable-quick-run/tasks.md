## 1. Retainability Result Contract

- [x] 1.1 Add failing tests for `RunResult.retainable` and typed retainability reasons.
- [x] 1.2 Implement the quick-run retainability model and summary artifact fields.
- [x] 1.3 Document `succeeded` versus `retainable` in active quick-run docs.

## 2. Micro Causality Retainability

- [x] 2.1 Add failing tests for micro replay violations/timeouts making a completed run non-retainable.
- [x] 2.2 Wire micro replay evidence into retainability without changing diagnostic scoring semantics.

## 3. Envelope Trust And Realism

- [x] 3.1 Add failing tests for missing operator-frozen envelope provenance and unrealistic envelope values.
- [x] 3.2 Add the minimal envelope config contract and retainability checks.
- [x] 3.3 Update checked-in quick-run configs that should remain retainable.

## 4. Unpriced Short Financing

- [x] 4.1 Add failing tests for unpriced equity/FX short exposure and financed crypto-perp shorts.
- [x] 4.2 Add a typed fail-closed short-financing verdict in the portfolio book.

## 5. Review Status And Verification

- [x] 5.1 Update `foundation-review-2026-06-12.md` Phase 1 recommendation status after implementation.
- [x] 5.2 Run focused tests and `git diff --check`.
