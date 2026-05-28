# Phase 8 Design: Lazy `quant_data` Imports

Date: 2026-05-28
Mode: Builder
Source reviews: `review-claude.md`, `review-codex.md`

## Problem

`runner.data_loader` imports `quant_data.config`, `quant_data.db`, and
`quant_data.loader` at module import time. `review-claude.md` measured this as
a major cold-import cost because `quant_data` brings data SDK dependencies into
plain `quant_strategies.runner` imports, even when tests or consumers inject
rows and never call the real data loader.

## Assignment

Move `quant_data` imports behind helper functions used only when the runner
actually loads rows or builds a default database engine.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 8:

- Preserve the public `load_data(config, engine=None)` behavior.
- Preserve existing test monkeypatch affordances for `data_loader.loader`,
  `data_loader.DataConfig`, and `data_loader.get_engine`.
- Do not change hidden `.env` discovery semantics in this phase. The review
  also flags that coupling, but it is a separate reproducibility decision.
- Do not add a DB engine cache in this phase.

## Scope

- Remove top-level `quant_data` imports from `runner.data_loader`.
- Add small lazy import helpers.
- Add/adjust focused tests proving lazy imports and existing adapter behavior.
- Update progress tracking.

## Not In Scope

- Replacing `quant_data` `.env` discovery.
- Caching `get_engine()`.
- Changing loader APIs or row schemas.
- Data manifest source identity fields.

## Success Criteria

- `import quant_strategies.runner.data_loader` does not require/import
  `quant_data`.
- Existing data adapter tests still pass.
- Full test suite, diff check, and compile check pass.
