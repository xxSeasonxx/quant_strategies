# Phase 6 Design: Engine Strategy Ontology Collapse

Date: 2026-05-28
Mode: Builder
Source reviews: `review-claude.md`, `review-codex.md`

## Problem

The runner currently translates `StrategyDecision` into signal-row dictionaries,
then the engine translates those rows into `engine.Signal`. That creates three
strategy-output shapes in the smoke path and violates PRD G3: the engine must
consume the single strategy ontology directly.

## Assignment

Make `StrategyDecision` the engine request contract. Remove the engine-layer
`Signal` model and stop writing signal-row artifacts. The smoke engine may still
reject unsupported decision semantics, but those rejections must be derived from
the canonical decision object, not a runner adapter.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 6:

- Keep `Bar` as the engine's normalized market-row model. It is row validation,
  not a parallel strategy-output ontology.
- Keep fill/cost config names in this phase unless removing them is required by
  the `Signal` collapse. They are execution assumptions, not strategy output.
- Remove `signals.csv` and signal summaries from runner artifacts. Full-profile
  audit runs already write `decision_records.jsonl` and `engine_request.json`.
- Preserve runner output mode `"validate"` in this phase. Engine gating API
  renames can follow separately without blocking the strategy ontology fix.
- Keep unsupported smoke semantics as fail-fast runner request-build errors and
  engine evaluation errors.

## Scope

- Replace `StrategySpec.signals` with `StrategySpec.decisions`.
- Delete the engine `Signal` model and runner `decision_adapter`.
- Make `engine.screen` derive symbol, side, size, exit policy, and metadata from
  `StrategyDecision`.
- Make `runner.engine_runner.build_request` accept decisions directly.
- Make data readiness check decisions directly.
- Remove signal-row artifacts from full and summary profiles.
- Update tests, README, and progress tracking.

## Not In Scope

- Full futures/options/multi-leg PnL support.
- Renaming runner output mode `"validate"`.
- Validation backend artifact expansion.
- Shared runner/validation causality kernel beyond the existing runner replay.
- Freezing-performance cleanup.

## Success Criteria

- No production code imports or constructs `engine.Signal`.
- No runner path creates signal-row dictionaries before engine execution.
- `engine_request.json` serializes canonical decisions under
  `spec.decisions`.
- Full-profile runner artifacts contain decisions and engine request artifacts,
  but not `signals.csv`.
- Existing supported smoke strategies produce the same trade count, fill timing,
  and smoke score semantics.
