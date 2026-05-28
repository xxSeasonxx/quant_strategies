# Phase 37 Design: Paper Readiness Gate Table

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` flags that
`validation/policy.py::_paper_readiness_decision` is mildly overbuilt because
each paper-readiness gate is hand-coded as a repeated block. Current behavior is
well-tested, but adding or auditing gates requires reading imperative list
mutation rather than a clear policy table.

## Assignment

Refactor paper-readiness gate evaluation into a small declarative table while
preserving behavior:

- Gate names and order stay stable.
- Gate detail strings stay stable.
- Decision outcomes stay stable.
- `mechanical_validation` remains a base gate supplied by the backend execution
  gate.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed
for Phase 37:

- Use a private table in `validation.policy`; do not expose a new public API.
- Add a narrow structural regression for the private table because the review
  finding is implementation structure, not user-visible behavior.
- Keep threshold loading and scenario grouping in `_paper_readiness_decision`.
- Do not change any policy label or eligibility flag.

## Scope

- Add a test proving the expected paper-readiness gates are declared in one
  ordered table.
- Replace repeated gate mutation blocks with a local `gate_results` map and
  iteration over the ordered gate-name table.
- Update `progress.md`.

## Not In Scope

- Changing policy thresholds.
- Changing `mechanical_review_candidate`, `watchlist`, or `mechanical_pass`
  classification.
- Adding statistical deflation logic.
- Changing validation artifact schemas.

## Success Criteria

- `_PAPER_READINESS_GATES` declares the seven paper-readiness gates in the
  existing order.
- Existing policy behavior tests continue to pass.
- Validation runner artifact tests continue to pass.
- Full suite, `git diff --check`, and compileall pass.
