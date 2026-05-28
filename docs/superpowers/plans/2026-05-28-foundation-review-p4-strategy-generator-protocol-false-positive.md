# StrategyGenerator Protocol Finding Rejection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development for implementation when practical. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record that the public `StrategyGenerator` Protocol review item is already satisfied and avoid duplicate abstractions.

**Architecture:** No runtime changes. The canonical public strategy callable type remains `quant_strategies.decisions.StrategyGenerator`, defined in `decisions.strategy_loader` and re-exported from `decisions.__init__`.

**Tech Stack:** Python 3.12, pytest via `conda run -n quant`.

---

## File Structure

- Modify `progress.md`: record the triage decision and verification.

## Implementation Steps

- [x] **Step 1: Verify existing Protocol contract**

  Run the existing focused test:

  ```bash
  conda run -n quant pytest tests/test_decision_models.py::test_strategy_generator_protocol_is_publicly_importable -q
  ```

- [x] **Step 2: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused
  checks plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

Adding another Protocol would create duplicate terminology for the same
strategy callable shape. The smallest correct action is to record that this
review item is already resolved and verify the existing public contract.

### Architecture Review

Current contract:

```text
quant_strategies.decisions.StrategyGenerator
  -> Protocol __call__(rows, params) -> Sequence[StrategyDecision]
  -> DecisionStrategyCallable alias for loader return type
```

This is the right owner because `decisions` defines the strategy output
contract and remains independent of runner, engine, and validation.

### Edge Cases

- Runtime source stays unchanged.
- `DecisionStrategyCallable` remains an alias for compatibility and internal
  clarity.
- Consumer docs already point generated strategy authors at `StrategyGenerator`.

### Test Review

The focused test proves the Protocol is publicly importable and assignable to a
plain `generate_decisions(rows, params)` callable.
