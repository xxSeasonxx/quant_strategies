# Phase 2 Plan: Decision Ontology

Date: 2026-05-28
Design: `docs/superpowers/specs/2026-05-28-foundation-review-p1-ontology-design.md`

## Goal

Address PRD G1/G4 and the review findings about the too-narrow decision
ontology without overbuilding execution support.

## Implementation Steps

- [ ] **Step 1: Extend decision models**

  Add `DecisionIntent`, `FutureRef`, `OptionRef`, `InstrumentLeg`,
  `MultiLegInstrumentRef`, expanded `SizingKind`, and `StrategyGenerator` to the
  public decision API. Add deterministic `decision_id` generation and duplicate
  `decision_id` validation.

  Verify: `tests/test_decision_models.py` covers valid futures/options/multi-leg
  decisions, invalid expiry/strike/multiplier/leg shapes, sizing literal
  changes, deterministic IDs, and duplicate IDs.

- [ ] **Step 2: Gate unsupported runner smoke semantics**

  Update `decisions_to_signal_rows` to preserve `decision_id` and reject
  unsupported intents, instrument shapes, and sizing modes before building engine
  requests.

  Verify: `tests/test_runner_engine_runner.py` and runner API tests assert clear
  messages for futures/options/multi-leg/non-weight/close-or-roll decisions.

- [ ] **Step 3: Propagate audit identity through engine artifacts**

  Add `decision_id` to `engine.Signal` and `engine.Trade`, pass it through
  evaluation, summary profiles, decision records, and evidence JSON.

  Verify: engine and runner artifact tests assert decision/trade joinability.

- [ ] **Step 4: Update validation backend unsupported semantics**

  Ensure VectorBT Pro backend and capability matrix report richer unsupported
  semantics instead of silently adapting them.

  Verify: vectorbtpro backend/capability tests cover non-target-weight,
  futures/options/multi-leg, and unsupported intent.

- [ ] **Step 5: Docs and progress**

  Update README, autoresearch consumer docs, and `progress.md`.

  Verify: README contract tests and stale-literal scans.

## Verification Commands

```bash
conda run -n quant pytest tests/test_decision_models.py tests/test_runner_engine_runner.py tests/test_runner_api_cli.py tests/test_vectorbtpro_backend.py tests/test_validation_capabilities.py tests/test_engine_screen.py tests/test_engine_validate_and_evidence.py tests/test_readme_contract.py -q
conda run -n quant pytest -q
git diff --check
conda run -n quant python -m compileall -q src tests
```

## GSTACK REVIEW REPORT

### Scope Challenge

This plan touches more than eight files, which is normally a smell. Here the
scope is acceptable because the public decision ontology is intentionally
cross-cutting: strategy models, runner adapter, validation backend, engine audit
identity, tests, and docs all need to agree. Reducing the scope to model-only
would preserve the false appearance that unsupported semantics execute.

### Architecture Review

Current flow:

```text
strategy.py
  -> StrategyDecision
  -> runner.decision_adapter signal rows
  -> engine.Signal
  -> engine.Trade/evidence
```

Phase 2 keeps that flow but makes the first node authoritative and explicit.
The adapter becomes the boundary that rejects unsupported execution semantics.
Engine ontology collapse remains a later phase.

### Data Flow Risks

- Deterministic `decision_id` must not use random UUIDs or wall-clock time.
- Multi-leg decisions must not leak into single-symbol engine math.
- New sizing literals must not be accepted by smoke execution unless the math
  exists.
- `book_side` must not replace `target.direction`; it is order-side metadata,
  not net exposure.

### Test Plan

Coverage must include model validity, unsupported path failures, artifact
identity propagation, validation backend unsupported semantics, docs, and full
suite regression. The decisive regression is a future/option/multi-leg decision
that validates as a `StrategyDecision` but cannot produce smoke-engine PnL.

### Not In Scope

- Contract multiplier PnL.
- Option payoff/exercise.
- Multi-leg spread NAV.
- Engine ontology collapse.
- Validation orchestrator split.
