# Phase 30 Design: Failure Smoke Score Artifacts

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` notes that failure summaries include
`engine.smoke_score` with every field set to `null`. That makes consumers infer
whether smoke was not computed by inspecting nulls instead of the artifact shape.
For failure stages before engine evaluation, no smoke score exists.

## Assignment

Omit `engine.smoke_score` when smoke was not computed. Preserve real smoke-score
payloads, including zero-valued scores from completed no-trade runs.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed
for Phase 30:

- Scope this to summary artifact shape only; do not change `RunResult` status or
  engine math.
- Failure summaries that stop before engine evaluation should omit
  `engine.smoke_score`.
- Completed engine runs should continue to include `engine.smoke_score`.
- Keep `metric_semantics` in summaries; it documents possible smoke metrics even
  when a particular failed run did not compute them.

## Scope

- Add focused runner artifact regressions for failure summaries and completed
  zero-trade summaries.
- Remove the default null smoke-score insertion from `_summary_payload()`.
- Update `progress.md`.

## Not In Scope

- Changing engine result models.
- Changing status names or assessment logic.
- Changing summary success payloads.
- Changing `summary.json` top-level keys.

## Success Criteria

- Data-load, import, param-validation, and decision-generation failure summaries
  do not contain `engine.smoke_score`.
- Completed zero-decision runs still include a smoke score with numeric zeros.
- Existing runner artifact/profile tests continue to pass.
