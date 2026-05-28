# Phase 29 Design: Tracked Git Identity

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` flags that repository identity hashes are unstable because
`git_identity()` hashes `git status --untracked-files=all`. Untracked scratch
files that are not part of the run's code, config, or data can change
`status_porcelain_sha256`, so two runs from the same tracked code and same
snapshotted inputs can report different repository identities.

## Assignment

Make repository identity deterministic with respect to tracked code state:
include tracked modifications and staged changes, but ignore untracked
detritus. Strategy and config inputs remain captured separately by snapshots and
hashes, so the repo identity does not need to hash arbitrary untracked files.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed
for Phase 29:

- Change `git_identity()` to use tracked-only status (`--untracked-files=no`).
- Keep `tracked_diff_sha256` unchanged; it already hashes tracked diffs.
- Preserve result-directory path exclusions.
- Update tests to prove tracked dirty files still mark the repo dirty while
  untracked scratch files do not affect repository identity.

## Scope

- Update `src/quant_strategies/provenance.py`.
- Update runner manifest tests that currently expect untracked files to affect
  `status_porcelain_sha256`.
- Update `progress.md`.

## Not In Scope

- Hashing untracked arbitrary source trees.
- Adding a new repository identity schema version.
- Changing strategy/config snapshot hashes.
- Changing artifact content outside repository identity.

## Success Criteria

- A tracked file modification still sets `repository.dirty` and hashes tracked
  status/diff.
- An untracked scratch file alone does not set `repository.dirty` and does not
  produce `status_porcelain_sha256`.
- Result directory exclusion behavior remains intact.
- Focused runner manifest tests and the full suite pass.
