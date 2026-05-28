# Phase 24 Design: Separate Linear Funding Adjustment Semantics

Date: 2026-05-28
Mode: Builder
Source review: `review-codex.md`

## Problem

`review-codex.md` Finding 13 flags that the VectorBT Pro validation backend
adds crypto-perp funding as a linear cashflow approximation to the backend's
portfolio return, then reports the sum as generic `net_return`. Current code
does declare `funding_model = "linear_additive_adjustment"`, but policy gates
still consume the overwritten `net_return`, so a NAV-path portfolio metric and
a linear add-on are mixed under one required metric name.

## Assignment

Keep the validation backend's required `net_return` metric scoped to the
backend portfolio price/cost return path. When funding rows are present, expose
the funding approximation as explicit optional metrics:

- `funding_return`
- `linear_funding_adjusted_return`
- `funding_model = "linear_additive_adjustment"`

Policy gates should continue reading the required typed `net_return`, which
means they do not silently gate on the linear funding adjustment.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed
for Phase 24:

- Do not implement a full NAV-path funding cashflow model in this phase.
- Preserve the flat backend `metrics` payload for artifact readability.
- Add semantics records for optional funding metrics even when a fake backend
  does not emit them.
- Keep the policy metric schema small; optional funding metrics stay in
  `BackendMetrics.extras`.
- Treat this as a semantic correction, not a validation-policy redesign.

## Scope

- Update VectorBT Pro funding metric construction so `net_return` is no longer
  overwritten by linear funding.
- Add metric semantics for funding-related optional metrics.
- Add regression tests for backend metrics and policy gate behavior.
- Update docs and `progress.md`.

## Not In Scope

- Full compounding funding/NAV integration.
- Changing smoke-engine trade-return math.
- Changing validation paper-readiness thresholds.
- Reworking backend artifact reconstructability.
- Backward compatibility for old validation artifacts.

## Success Criteria

- Crypto-perp funding rows produce `linear_funding_adjusted_return` and
  `funding_return` while preserving `net_return` as the backend price/cost
  return.
- Policy gates do not pass because only `linear_funding_adjusted_return` is
  positive.
- Backend metric semantics describe `net_return`, `trade_count`, and the
  funding-specific optional metrics.
- Focused tests, full suite, diff check, compile check, and code review pass.
