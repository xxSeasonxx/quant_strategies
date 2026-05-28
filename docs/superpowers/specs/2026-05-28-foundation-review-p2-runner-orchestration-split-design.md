# Phase 34 Design: Runner Orchestration Split

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` flags `runner.__init__.run_config()` as mildly overbuilt and
still too concentrated. Earlier phases added causality, stage events,
evidence-quality fields, artifact profiles, and failure handling to the public
runner. The function now directly owns config loading, artifact initialization,
strategy execution failure handling, causality, data manifest writing,
request-support checks, data readiness, request build, engine evaluation, and
completion artifact writing.

Validation orchestration has already been split into focused private helpers.
Runner should match that direction without changing its public API.

## Assignment

Extract focused private helpers around existing runner stages so
`run_config()` becomes a readable coordinator. Preserve behavior, artifacts,
events, stage names, failure summaries, and `RunResult` fields exactly.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed
for Phase 34:

- Keep `quant_strategies.runner.run_config` and `RunResult` unchanged.
- Do not introduce a class-based runner object.
- Do not change stage names, event payload names, summary fields, artifact
  names, or failure statuses.
- Prefer private dataclasses only where they reduce parameter threading.
- Use existing runner tests as the behavior-preservation guardrail.

## Scope

- Add progress triage for the runner orchestration finding.
- Extract helper functions for loaded-row/data-manifest artifact writing,
  strategy execution failure handling, causality/evidence preparation, request
  preparation, engine evaluation, and completion artifact writing.
- Keep existing helper functions such as `_failure_result()` and
  `_summary_payload()`.
- Update `progress.md`.

## Not In Scope

- Changing validation orchestration.
- Moving config models to a new `core` package.
- Changing engine request/validation semantics.
- Adding new event stages.

## Success Criteria

- Existing runner API and CLI tests pass.
- Existing request-build, data-readiness, causality, strategy-generation, and
  engine-failure artifact preservation tests pass.
- Full suite passes.
- Code review finds no behavior regression.
