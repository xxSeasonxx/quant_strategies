## Why

Quick-run Train evidence is the hot path for `quant_autoresearch`, but a completed
quick run is not yet explicit about whether the evidence is safe to retain. The
foundation needs one practical retainability contract that combines causality,
trusted envelope, and priced financing without adding a new engine or search
workflow.

## What Changes

- Add a quick-run retainability result contract distinct from "the run scored".
- Treat micro causality as fast iteration evidence: it may allow scoring, but a
  detected violation or incomplete retention proof makes the result non-retainable.
- Add minimal operator-envelope trust checks for scoreable retained evidence:
  realistic nonzero cost floor, positive impact pricing for ADV capacity, bounded
  participation limits, and explicit provenance that the envelope is operator-owned.
- Add a fail-closed verdict for short exposure in asset classes without modeled
  short financing/carry.
- Keep the implementation root-level and practical: no new backend, no
  compatibility shim, no search-loop ownership.

## Capabilities

### New Capabilities
- `quick-run-retainability`: Public quick-run result semantics for whether scored
  evidence may be retained for validation/evaluation.

### Modified Capabilities
- `causality-replay-policy`: Micro replay evidence affects retainability instead
  of silently making detected replay problems retainable.
- `capacity-adv-market-impact`: Capacity/cost envelope must be trusted and
  realistically priced before evidence is retainable.
- `portfolio-decision-contract`: Short exposure in unpriced asset classes must
  fail closed instead of scoring with free borrow/carry.

## Impact

- Affected code:
  - `src/quant_strategies/runner/__init__.py`
  - `src/quant_strategies/core/config.py`
  - `src/quant_strategies/core/portfolio_foundation.py`
  - quick-run artifacts and result dataclasses
- Affected tests:
  - quick-run causality tests
  - config/envelope validation tests
  - portfolio feasibility verdict tests
  - result success/retainability contract tests
- Affected docs:
  - `README.md`
  - `docs/foundation-surfaces.md`
  - `docs/consumer/*`
  - `foundation-review-2026-06-12.md` status table
