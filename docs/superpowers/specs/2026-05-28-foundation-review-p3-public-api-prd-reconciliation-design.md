# Phase 28 Design: Public API PRD Reconciliation

Date: 2026-05-28
Mode: Builder
Source review: `review-codex.md`, `review-claude.md`

## Problem

`review-codex.md` Finding 4 correctly flags a contract mismatch: `PRD.md` says
the public consumer surface is re-exported, while README, consumer docs, and the
repo-local agent contract intentionally direct downstream automation to
`quant_strategies.runner.run_config`. The package root contains no facade.

## Assignment

Reconcile the source-of-truth PRD to the implemented and documented public API:
`quant_strategies.runner.run_config` and `quant_strategies.runner.RunResult`.
Do not add a top-level re-export just to satisfy stale PRD wording, because that
would broaden the public surface and increase misuse risk.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed
for Phase 28:

- Preserve `from quant_strategies.runner import run_config` as the stable
  downstream API.
- Keep the package root minimal; no top-level facade or compatibility alias.
- Treat the review finding as true PRD/docs drift, not a code bug.
- Add a docs-contract regression so the PRD, README, and consumer docs cannot
  drift back to the top-level re-export claim.

## Scope

- Update PRD G4 to name the runner subpackage public surface explicitly.
- Keep README and `docs/quant-autoresearch-consumer.md` aligned with that PRD.
- Add a focused test that asserts the PRD does not promise package-root
  re-exports and that the package root does not expose `run_config`.
- Update `progress.md`.

## Not In Scope

- Adding top-level `quant_strategies.run_config`.
- Introducing a new facade module.
- Reworking `RunResult` into a Protocol.
- Changing runner execution behavior or artifacts.

## Success Criteria

- PRD G4 explicitly names `quant_strategies.runner.run_config` and
  `quant_strategies.runner.RunResult` as the public consumer surface.
- PRD no longer says the public consumer surface is re-exported at the package
  root.
- README and consumer docs remain aligned with the same import path.
- A test fails on the stale PRD claim and passes after reconciliation.
