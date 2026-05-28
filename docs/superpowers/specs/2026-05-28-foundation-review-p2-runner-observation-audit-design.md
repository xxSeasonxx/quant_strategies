# Phase 40 Design: Runner Observation Dependency Audit

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` notes a causality replay limitation: replay catches output
mismatches, but declared `ObservationRef` lineage is only audited in validation.
PRD glossary also describes observation audit as part of the shared kernel. The
runner currently validates the decision's `as_of_time` row and hidden-lookahead
replay, but it does not reject a decision that explicitly declares a future,
missing, or late-available observation.

## Assignment

Share the declared observation dependency audit between validation and runner:

- Move the existing observation audit helper to a neutral module.
- Keep validation data audit behavior unchanged.
- Add a runner `observation_audit` stage after strategy execution and before
  causality replay or engine request construction.
- Fail the runner with `assessment_status = "runner_failed"` when declared
  observations are non-causal or missing.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed
for Phase 40:

- Do not make observations globally mandatory for runner smoke runs. Validation
  configs already enforce minimum observations through readiness settings.
- Do not import `validation` from `runner`; preserve dependency direction by
  moving the helper to `quant_strategies.observation_dependencies`.
- Preserve existing validation violation strings.
- Use the existing failure artifact path so manifests and summaries remain
  consistent.

## Scope

- Add a runner regression for a declared future observation.
- Add neutral `quant_strategies.observation_dependencies`.
- Update validation data audit to import the neutral helper.
- Update runner to call the neutral helper in a dedicated stage.
- Update structured stage event expectations.
- Update `progress.md`.

## Not In Scope

- Requiring non-empty observations in `StrategyDecision`.
- Changing validation readiness config semantics.
- Changing hidden-lookahead replay fingerprints.
- Changing strategy files.

## Success Criteria

- Runner fails before causality replay or request build when declared
  observations reference future rows, missing rows/fields, missing/invalid
  `available_at`, or late availability.
- Validation dependency tests still pass with the same violation messages.
- Runner stage events include `observation_audit` on successful runs.
- Focused runner/validation tests plus full suite pass.
