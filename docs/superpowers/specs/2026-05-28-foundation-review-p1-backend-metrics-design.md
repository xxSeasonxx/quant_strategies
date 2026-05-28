# Phase 5 Design: Validation Backend Metric Contract

Date: 2026-05-28
Mode: Builder
Source reviews: `review-codex.md`, `review-claude.md`

## Problem

Validation backend results still expose metrics as a raw dictionary, while PRD
G2 requires numeric quantities to carry units, bases, backend semantics,
comparability, and tolerance. The policy also treats unsupported required
backend semantics as a `watchlist`, which is too soft: if a required scenario
cannot execute the strategy semantics, validation did not complete the required
mechanical check.

## Assignment

Add a typed validation backend metrics boundary for policy use and artifact
semantics, while preserving the existing flat metrics artifact shape. Change
unsupported required backend semantics to `hard_no`. Diagnostic-only unsupported
scenarios remain non-blocking because policy gates only required scenarios.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 5:

- Keep backend `metrics` serialized as a flat mapping to avoid artifact churn.
- Add a typed `BackendMetrics` parser/schema used by validation policy.
- Add backend metric semantics with declared tolerance/asymmetry for
  `net_return` and `trade_count`.
- Treat unsupported required backend semantics as `hard_no` with the existing
  `unsupported_semantics` reason.
- Do not implement cross-backend agreement computation in this phase.

## Scope

- Add `BackendMetrics` and metric semantics helpers in validation backend
  contracts.
- Use the typed metrics schema inside validation policy.
- Include metric semantics in backend run summaries.
- Change required unsupported backend semantics from `watchlist` to `hard_no`.
- Update tests, README, and progress tracking.

## Not In Scope

- Replacing flat metric dictionaries in artifacts.
- Computing backend-to-backend agreement.
- Validation row/fill/trade/cost/funding replay artifacts.
- VectorBT Pro execution math changes.
- Engine ontology collapse.

## Success Criteria

- Policy reads `net_return` and `trade_count` through `BackendMetrics`, not
  ad-hoc positional dict parsing.
- Backend summary artifacts declare metric semantics and tolerance/asymmetry.
- Required unsupported backend semantics produce `hard_no`.
- Diagnostic-only unsupported semantics do not block required mechanical gates.
- Existing backend artifacts remain readable with flat `metrics` fields.
