# Phase 20 Design: Document Review Archive Directory

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` flags empty documentation scaffolds, including
`docs/reviews/`. The `docs/superpowers/plans` and `docs/superpowers/specs`
directories are now populated by the phase workflow, but `docs/reviews/` remains
empty and unexplained.

## Assignment

Populate `docs/reviews/` with a short README that defines its purpose and keeps
the active root review files in place for the current workflow.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 20:

- Do not move `review-codex.md` or `review-claude.md`; they are active root
  inputs referenced by `progress.md` and the current objective.
- Add `docs/reviews/README.md` to document the archive convention.
- Treat `docs/superpowers/{plans,specs}` as already resolved by existing phase
  artifacts.
- Keep this as a docs-only hygiene phase.

## Scope

- Add `docs/reviews/README.md`.
- Update progress tracking.

## Not In Scope

- Moving active review input files.
- Rewriting review content.
- Changing OpenSpec or Superpowers directory layouts.

## Success Criteria

- `docs/reviews/` is no longer empty.
- The directory purpose and archive naming convention are documented.
- The active root review files remain in place.
- Diff check, focused docs existence check, full suite, and code review pass.
