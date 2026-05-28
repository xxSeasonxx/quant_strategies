# Phase 2 Design: Decision Ontology

Date: 2026-05-28
Mode: Builder
Source reviews: `review-codex.md`, `review-claude.md`

## Problem

Phase 1 removed the most visible semantic overclaims, but the strategy-output
contract is still narrower than PRD G1. Strategies cannot explicitly represent
decision identity, action intent, side of book, futures, options, multi-leg
structures, or the requested sizing modes. That forces authors to overload
metadata or encode meaning in symbol strings, which is exactly the adapter
sprawl the reviews warned about.

## Assignment

Make `StrategyDecision` the single expressive ontology at the strategy boundary.
Do not implement full futures, options, multi-leg, or non-weight execution in
the smoke engine during this phase. Instead, make those semantics representable
and have unsupported runner/backend paths reject them with explicit reasons.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 2:

- Add expression first, execution later.
- Preserve simple equity/FX/crypto target-weight smoke runs.
- Retire the ambiguous `notional` sizing literal in favor of
  `target_notional`.
- Generate deterministic `decision_id` values when a strategy omits one, so
  audit joins exist without random UUIDs.
- Keep unsupported semantics non-silent: runner smoke fails with clear
  `RequestBuildError`; validation backends report unsupported semantics.

## Scope

- Add decision identity and export a typed strategy generator Protocol.
- Add intent/action plus optional buy/sell book side.
- Add future, option, and multi-leg instrument types.
- Add target notional, target contracts, and target volatility sizing literals.
- Propagate `decision_id` through signal rows and engine trades.
- Add tests proving unsupported richer semantics are accepted by the decision
  model but rejected by unsupported execution paths.
- Update docs and progress tracking.

## Not In Scope

- Full futures/options/multi-leg PnL.
- Portfolio NAV accounting.
- Margin, contract multiplier PnL, option Greeks, exercise/assignment.
- Collapsing the engine parallel ontology. This phase reduces boundary pressure
  but does not remove `engine.Signal`.
- Validation orchestrator split.

## Success Criteria

- `StrategyDecision` can express all PRD G1 instrument and sizing categories.
- Existing simple target-weight smoke runs still work.
- Unsupported richer decisions fail explicitly before engine math.
- Validation backend capability reporting covers the new unsupported semantics.
- Artifacts and trades carry a stable `decision_id`.
- README and consumer docs teach the new contract without claiming execution
  support that does not exist.
