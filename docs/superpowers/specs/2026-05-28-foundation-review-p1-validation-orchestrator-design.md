# Phase 4 Design: Validation Orchestrator Split

Date: 2026-05-28
Mode: Builder
Source reviews: `review-codex.md`, `review-claude.md`

## Problem

`validation.run_validation` still owns config resolution, backend selection,
window execution, execution-failure translation, data audit, hidden-lookahead
replay, readiness checks, scenario expansion, backend execution, classification,
and artifact writing in one long function. The reviews correctly flag this as a
PRD G3 violation: orchestrator god-functions make later metric schemas,
capability handling, and validation artifact expansion risky.

## Assignment

Split the validation orchestrator into focused helpers without changing
validation behavior, artifact shapes, or policy decisions. This phase is a
structural refactor only.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 4:

- Keep the public API as `quant_strategies.validation.run_validation`.
- Keep helpers private inside `validation/__init__.py` for now; do not add a new
  package unless behavior changes later justify it.
- Preserve existing artifact schemas and failure reason strings.
- Do not add typed backend metrics, trust tiers, or engine ontology changes in
  this phase.
- Prefer dataclass state/context objects only if they reduce argument sprawl.

## Scope

- Introduce private validation context/state dataclasses.
- Extract backend selection failure handling.
- Extract per-window execution and `StrategyExecutionError` handling.
- Extract executed-window audit/readiness/lookahead handling.
- Extract per-scenario backend execution and result packaging.
- Keep final classification and artifact writing equivalent.
- Update progress tracking.

## Not In Scope

- Validation backend metric schemas.
- Cross-backend tolerance/agreement policy.
- Validation row/fill/trade/cost/funding artifact expansion.
- Engine ontology collapse.
- Capability matrix redesign.
- Performance changes to freezing or lookahead replay.

## Success Criteria

- `run_validation` becomes a readable top-level pipeline.
- Strategy import, param validation, data load, decision generation, audit,
  lookahead, readiness, scenario backend, and artifact outcomes remain unchanged.
- Existing validation tests and full suite pass.
- The refactor reduces future change risk without introducing compatibility
  adapters or new public APIs.
