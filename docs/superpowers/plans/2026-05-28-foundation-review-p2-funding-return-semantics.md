# Funding Return Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development where practical. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Goal:** Stop reporting a linear crypto-perp funding adjustment as generic
backend `net_return` in validation artifacts and policy gates.

**Architecture:** Keep `BackendMetrics.net_return` as the required policy metric
for backend price/cost return. Store funding-specific numbers as explicit flat
extras with metric semantics, leaving policy gates off the linear add-on unless
a future phase promotes it deliberately.

**Tech Stack:** Python 3.12, Pydantic, pytest via `conda run -n quant`.

---

## File Structure

- Modify `src/quant_strategies/validation/vectorbtpro_backend.py`: preserve
  backend `net_return` and add `linear_funding_adjusted_return`.
- Modify `src/quant_strategies/validation/backends.py`: add funding metric
  semantics.
- Modify `tests/test_vectorbtpro_backend.py`: backend funding regressions.
- Modify `tests/test_validation_backends_and_policy.py`: policy gate
  regression and metric semantics expectations.
- Modify `tests/test_validation_runner.py`: backend summary semantics
  expectations.
- Modify `README.md`, `docs/quant-autoresearch-consumer.md`, and
  `progress.md`.

## Implementation Steps

- [x] **Step 1: Add failing regressions**

  Add tests that prove:

  - VectorBT Pro funding rows keep `net_return` equal to the backend
    price/cost return and expose `linear_funding_adjusted_return` separately.
  - Backend metric semantics include `funding_return` and
    `linear_funding_adjusted_return`.
  - Policy still fails aggregate positive net evidence when `net_return` is
    negative even if `linear_funding_adjusted_return` is positive.

  Verify the backend funding test fails before implementation:

  ```bash
  conda run -n quant pytest tests/test_vectorbtpro_backend.py::test_vectorbtpro_backend_adds_funding_return_for_crypto_perp_rows -q
  ```

- [x] **Step 2: Implement semantic separation**

  Change `_funding_adjusted_metrics()` to return `funding_return`,
  `linear_funding_adjusted_return`, and `funding_model` without overwriting
  `net_return`. Add backend metric semantics for the funding extras.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_vectorbtpro_backend.py tests/test_validation_backends_and_policy.py tests/test_validation_runner.py -q
  ```

- [x] **Step 3: Docs, full verification, and review**

  Update docs and progress, then run:

  ```bash
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused
  checks plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

The review recommendation offers two fixes: model funding inside the NAV path or
label the linear adjustment explicitly. Phase 24 chooses the explicit-label
path because it is smaller, auditable, and avoids pretending the current
funding approximation is a real backend NAV cashflow.

### Architecture Review

Target metric split:

```text
portfolio.get_total_return() -> net_return
funding rows              -> funding_return
net_return + funding      -> linear_funding_adjusted_return
policy gates              -> BackendMetrics.net_return
```

The flat artifact payload remains easy to inspect, while typed policy metrics
keep required gates on the non-ambiguous required metric.

### Edge Cases

- No funding rows: metrics remain unchanged.
- Funding rows with zero funding: explicit funding metrics may still appear for
  crypto-perp runs, documenting the model used.
- Positive funding should not rescue a negative backend `net_return` in policy.
- Optional metrics are not required from fake/custom backends.

### Test Review

Tests should cover backend payload semantics, metric semantics artifacts, and
policy gate behavior. Full suite verifies no existing validation expectations
depend on funding being folded into `net_return`.
