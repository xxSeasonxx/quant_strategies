# Phase 39 Design: StrategyGenerator Protocol Finding Rejection

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` recommends adding a public `Protocol` for
`generate_decisions`. Current source already has this contract:

- `quant_strategies.decisions.strategy_loader.StrategyGenerator`
- `quant_strategies.decisions.DecisionStrategyCallable`
- `quant_strategies.decisions.__all__` exports `StrategyGenerator`
- `tests/test_decision_models.py::test_strategy_generator_protocol_is_publicly_importable`
- `docs/quant-autoresearch-consumer.md` documents the public strategy callable
  type as `StrategyGenerator`

## Assignment

Reject the finding as already resolved; do not add a duplicate Protocol or
rename the existing one.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed
for Phase 39:

- Treat the existing public `StrategyGenerator` export and test as sufficient.
- Record the finding as resolved/false-positive in `progress.md`.
- Do not modify runtime source.

## Scope

- Add design/plan/progress records for the rejection.
- Run the existing focused public import test.
- Request review before commit.

## Not In Scope

- Changing the Protocol signature.
- Adding another strategy callable type.
- Changing strategy loader behavior.

## Success Criteria

- Progress triage records the review item as already resolved.
- Existing focused Protocol test passes.
- Full suite, `git diff --check`, and compileall pass.
