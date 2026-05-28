# Phase 36 Design: Shared Config Primitives

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` flags that `validation/config.py` imports
`DataConfig`, `FillModelConfig`, and `CostModelConfig` from
`runner/config.py`. Those models are shared experiment primitives, not runner
orchestration concepts. Keeping them in `runner.config` makes validation depend
on the runner as the canonical owner for data and engine execution settings.

## Assignment

Move the shared config primitives to a neutral module:

- `DataConfig`
- `FillModelConfig`
- `CostModelConfig`

Keep `RunConfig` and `OutputConfig` in `runner.config`, because they own runner
path resolution, output mode, and artifact profile semantics. Preserve existing
`quant_strategies.runner.config` imports for compatibility, but make validation
consume the neutral definitions directly.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed
for Phase 36:

- Use `quant_strategies.core.config` as the neutral owner.
- Re-export shared config classes from `runner.config` to avoid breaking
  existing strategy tests and consumers.
- Do not move path resolution helpers or TOML loading into the neutral module.
- Do not collapse engine `FillModel`/`CostModel` in this phase.

## Scope

- Add a focused regression that proves the shared primitives are owned by the
  neutral module and remain importable from `runner.config`.
- Add `quant_strategies.core.config`.
- Update `runner.config` and `validation.config` imports.
- Update progress tracking.

## Not In Scope

- Moving `RunConfig`, `OutputConfig`, or `load_config`.
- Renaming config fields or changing validation behavior.
- Changing TOML schemas.
- Collapsing engine model classes.

## Success Criteria

- Shared primitive classes report `quant_strategies.core.config` as their owner.
- `validation.config` imports shared primitives from `quant_strategies.core`.
- Existing runner imports remain valid.
- Validation config conversion still produces a `RunConfig`.
- Focused config tests plus the full suite pass.
