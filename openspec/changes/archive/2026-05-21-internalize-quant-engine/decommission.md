## Standalone Quant Engine Decommission

Date: 2026-05-21

Standalone repository before archive:

- Path: `/Users/Season_Yang/Personal/quant_engine`
- Git commit: `56c307ca6664693c809368123175afefcfa8fc9b`
- State: dirty before migration, with funding-aware evaluator changes already
  present in source, tests, and docs.

Preservation decision:

- Evaluator source and focused tests were migrated into
  `src/quant_strategies/engine/` and `tests/test_engine_*.py`.
- The old standalone README, PRD, and strategy guide are preserved by archiving
  the repository path rather than deleting the dirty checkout.
- Active documentation in `quant_strategies` now points to the internal
  evaluator boundary, not the standalone package or CLI.

Archived path:

- `/Users/Season_Yang/Personal/quant_engine_ARCHIVED_2026-05-21`

