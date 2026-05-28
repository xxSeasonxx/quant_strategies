# Phase 5 Plan: Validation Backend Metric Contract

Date: 2026-05-28
Design: `docs/superpowers/specs/2026-05-28-foundation-review-p1-backend-metrics-design.md`

## Goal

Address validation backend metric schema and required unsupported-semantics
findings without changing backend execution math or artifact metric flattening.

## Implementation Steps

- [x] **Step 1: Add typed backend metric contract**

  Add `BackendMetrics` plus metric semantics/tolerance helpers. Preserve flat
  `BackendRunResult.metrics` serialization.

  Verify: backend/policy tests cover valid, invalid, and extra metrics.

- [x] **Step 2: Use typed metrics in policy**

  Replace ad-hoc policy metric parsing with `BackendMetrics.from_mapping`.

  Verify: invalid metric tests still classify `hard_no`.

- [x] **Step 3: Harden unsupported required semantics**

  Change required unsupported backend semantics to `hard_no`. Keep diagnostic
  unsupported scenarios non-blocking.

  Verify: policy and validation-runner tests assert required unsupported
  semantics are `hard_no`.

- [x] **Step 4: Docs/progress, verification, review**

  Update README and `progress.md`; run focused tests, full suite, diff checks,
  and subagent code review before commit.

## Verification Commands

```bash
conda run -n quant pytest tests/test_validation_backends_and_policy.py tests/test_validation_runner.py tests/test_validation_capabilities.py tests/test_vectorbtpro_backend.py tests/test_readme_contract.py -q
conda run -n quant pytest -q
git diff --check
conda run -n quant python -m compileall -q src tests
```

## GSTACK REVIEW REPORT

### Scope Challenge

This phase intentionally stops short of full cross-backend agreement
computation. A typed schema and declared semantics are the smallest durable
step: they make the current policy contract explicit without forcing a new
backend comparison engine.

### Architecture Review

Target flow:

```text
BackendRunResult.metrics (flat artifact payload)
        |
        v
BackendMetrics.from_mapping(...)
        |
        v
validation.policy gates
```

The flat mapping remains the artifact surface. The typed schema becomes the
policy boundary.

### Code Quality Review

- Keep `BackendMetrics` focused on required policy metrics.
- Store non-required backend metrics as extras.
- Do not make invalid completed backend metrics impossible to construct in
  tests; policy still needs to classify invalid backend output.
- Keep unsupported required semantics distinct from backend unavailable and
  backend failed.

### Test Review

Tests must cover:

- valid typed metric parsing with extras;
- invalid metric values still become policy `hard_no`;
- required unsupported semantics become `hard_no`;
- diagnostic unsupported semantics remain non-blocking;
- backend summary artifacts include metric semantics.

### Performance Review

Metric parsing is constant-time per backend result and should not affect
validation runtime meaningfully.

### Not In Scope

- Backend agreement calculations.
- Multi-backend validation orchestration.
- New validation artifact replay files.
