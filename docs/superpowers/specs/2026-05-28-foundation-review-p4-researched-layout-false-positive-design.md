# Phase 38 Design: Researched Layout Finding Rejection

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` flags that `researched/` is a folder convention rather than
an enforced runner or validation rule. The concern is true as a code observation
but false as a required fix: the current repo contract intentionally keeps
validation layout-agnostic and treats promotion as a separate human process.

## Assignment

Reject the finding as a false positive for runner/validation enforcement:

- Do not add `researched/` special-casing to runner or validation.
- Keep validation driven by an explicit `validation.toml` candidate workspace.
- Keep promotion from `researched/` to `tested/` outside automated validation.
- Add a docs-contract regression so the intended contract remains explicit.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed
for Phase 38:

- Treat README, `docs/quant-autoresearch-consumer.md`, AGENTS.md, and PRD C-4/C-6
  as the authoritative contract.
- Prefer a test that locks the contract over behavior that would reject valid
  candidate workspaces by path.
- Do not move any strategy files.

## Scope

- Add a focused docs-contract test covering layout-agnostic validation,
  `researched/` non-specialness, and human-only promotion.
- Reconcile stale PRD lifecycle direction wording with AGENTS/README if needed.
- Update `progress.md` with the false-positive triage decision.
- Request review before commit.

## Not In Scope

- Changing runner path validation.
- Changing validation config path rules.
- Enforcing `researched/` package manifests.
- Moving `researched/`, `untested/`, or `tested/` contents.

## Success Criteria

- Progress triage records the finding as rejected false positive.
- Docs-contract test proves validation remains layout-agnostic and promotion is
  human-controlled.
- Focused docs test, full suite, `git diff --check`, and compileall pass.
