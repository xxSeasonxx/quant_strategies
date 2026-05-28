# Phase 16 Design: Retire Runner Strategy Loader

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` identifies `runner/strategy_loader.py` as dead weight. The
module is a small pass-through to `decisions.load_decision_strategy()` with one
exception translation from `DecisionStrategyLoadError` to `StrategyLoadError`.
That indirection makes the runner look like it owns a second strategy-loading
API when the canonical strategy contract already lives under `decisions`.

## Assignment

Retire `quant_strategies.runner.strategy_loader` and inline the exception
translation at the runner execution boundary. Preserve the public decisions
loader and preserve runner/validation failure diagnostics that report
`StrategyLoadError`.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 16:

- Keep `quant_strategies.decisions.load_decision_strategy` as the canonical
  strategy loader.
- Delete `src/quant_strategies/runner/strategy_loader.py`.
- Keep `StrategyLoadError` because runner and validation diagnostics use it.
- Inline the translation in `runner.execution`, not in a new helper module.
- Update tests to import the canonical decisions loader.
- Treat `_FrozenDict` as already resolved: no source symbol remains, so it is a
  stale review item rather than Phase 16 work.

## Scope

- Add/keep tests for canonical decisions strategy loading.
- Remove references to `quant_strategies.runner.strategy_loader`.
- Add a private `_load_strategy()` helper in `runner.execution` that wraps
  `DecisionStrategyLoadError` as `StrategyLoadError`.
- Delete the runner strategy-loader module.
- Update progress tracking.

## Not In Scope

- Strategy purity checks for arbitrary candidate files.
- Public API re-export decisions.
- Removing `StrategyLoadError`.
- Changing validation failure-detail semantics.

## Success Criteria

- No source or tests import `quant_strategies.runner.strategy_loader`.
- The runner strategy-loader file is gone.
- Canonical decisions loader tests still cover valid and invalid strategy files.
- `execute_strategy_run()` still maps missing/bad strategy imports to
  `StrategyExecutionError(stage="strategy_import")`.
- Validation strategy-import failure artifacts still report type
  `StrategyLoadError`.
- Focused tests, full suite, diff check, compile check, and code review pass.
