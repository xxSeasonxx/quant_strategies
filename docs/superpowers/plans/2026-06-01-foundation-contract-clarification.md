# Foundation Contract Clarification Plan

> **Status:** Implemented by `19d7ee7` (`docs: clarify foundation evaluation contract`).
> This file is a historical summary, not an active implementation checklist.

**Goal:** Clarify the active foundation contract so quick run, mechanical
evidence validation, and the future research evaluation surface are distinct
without changing code, commands, public APIs, or artifact schemas.

**Result:** Completed as docs-only work. The active docs now describe:

- `quick run`: implemented fast causal diagnostics for one strategy version;
- `validation run`: implemented mechanical evidence validation for retained
  candidates;
- `research evaluation`: approved missing stateless surface for frozen-candidate
  portfolio, path, and economic evidence.

## Files Updated

- `PRD.md`: target contract and three-job product model.
- `README.md`: concise current-state guide and command surface.
- `FOUNDATION_LOCK.md`: locked contracts, accepted debt, and next direction.
- `TODOS.md`: current open work for C and B only.
- `docs/validation.md`: validation as mechanical evidence validation.
- `docs/quant-autoresearch-consumer.md`: downstream validation wording and
  `net_return` usage.
- `docs/vectorbtpro.md`: VectorBT Pro boundary and research-evaluation role.

## Deliberate Boundaries

- No source or test files changed.
- No code, CLI, package path, artifact name, or public API rename occurred.
- No speculative implemented-surface I/O reference doc was added for the future
  evaluation surface.
- Existing out-of-scope dirty docs were not staged as part of this work.

## Verification Used

Verification used focused stale-language checks for old surface, readiness, and
ranking terminology; VectorBT quick-run boundary checks; and `git diff --check`.
The stale-language checks returned no active-doc hits. The VectorBT hot-path
check returned only explicit negative constraints. Markdown whitespace checks
passed.

## Next Work

Use a new plan for C: the stateless research evaluation surface MVP. Do not use
this completed A plan as an execution checklist.
