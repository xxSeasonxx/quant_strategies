# Single Freezing Idiom Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `quant_strategies.boundary` the single immutable input boundary and reuse frozen rows/params across runner and validation.

**Architecture:** `boundary.py` owns recursive freezing and idempotence through a boundary-owned `FrozenMapping` backed by `MappingProxyType`. `execute_strategy_run()` freezes loaded rows and validated params once, stores both on `StrategyExecutionResult`, and passes them to strategy generation. Runner and validation reuse those frozen values when calling causality checks, audits, backend runs, and parameter scenario generation.

**Tech Stack:** Python 3.12, `MappingProxyType`, Pydantic models, pytest via `conda run -n quant`.

---

## File Structure

- Modify `src/quant_strategies/boundary.py`: remove `deepcopy`, add boundary-owned `FrozenMapping`, add idempotent freeze behavior.
- Modify `src/quant_strategies/runner/execution.py`: add frozen rows/params fields and freeze once after data load.
- Modify `src/quant_strategies/runner/__init__.py`: use frozen inputs for causality replay.
- Modify `src/quant_strategies/validation/__init__.py`: reuse frozen execution rows/params.
- Modify `src/quant_strategies/validation/matrix.py`: replace private `_FrozenDict` and `_freeze_value` with `boundary.frozen_params`.
- Add `tests/test_boundary.py`: direct boundary idempotence and isolation tests.
- Modify `tests/test_validation_matrix.py`: keep matrix immutability coverage through the shared boundary helper.
- Modify `progress.md`: record Phase 9 status and verification.

## Implementation Steps

- [x] **Step 1: Add boundary regression tests**

  Add tests proving `frozen_rows()` and `frozen_params()` isolate ordinary nested
  caller data, block mutation, and return the same object when called on already
  frozen boundary objects.

  Verify: `conda run -n quant pytest tests/test_boundary.py -q`.

- [x] **Step 2: Make boundary freezing idempotent**

  Remove `deepcopy`; rely on recursive standard-container freezing to copy nested
  mappings, lists, tuples, and sets. Return boundary-created `FrozenMapping`
  instances and already-frozen row tuples unchanged.

  Verify: `conda run -n quant pytest tests/test_boundary.py -q`.

- [x] **Step 3: Freeze execution inputs once**

  Extend `StrategyExecutionResult` with `frozen_rows` and `frozen_params`, compute
  both once in `execute_strategy_run()`, and use them for initial strategy
  execution. Keep `loaded_rows` and `validated_params` unchanged for artifacts and
  config merging.

  Verify: runner mutation tests still pass.

- [x] **Step 4: Reuse frozen execution inputs**

  Use `execution.frozen_rows` and `execution.frozen_params` in runner causality
  and validation stages that currently call `frozen_rows(execution.loaded_rows)`.
  Keep artifact/data provenance calls on raw `execution.loaded_rows`.

  Verify: focused runner and validation tests pass.

- [x] **Step 5: Collapse validation matrix freezing**

  Remove `_FrozenDict` and local `_freeze_value` from `validation.matrix`; use
  `frozen_params()` for scenario `params`, `cost_model`, and `fill_model`.

  Verify: `conda run -n quant pytest tests/test_validation_matrix.py -q`.

- [x] **Step 6: Docs/progress, verification, review**

  Update `progress.md`; run focused tests, full suite, diff checks, compile
  checks, and code review before commit.

## Verification Commands

```bash
conda run -n quant pytest tests/test_boundary.py tests/test_runner_api_cli.py::test_runner_blocks_strategy_row_mutation tests/test_runner_api_cli.py::test_runner_blocks_strategy_param_mutation tests/test_validation_runner.py::test_run_validation_blocks_strategy_row_mutation tests/test_validation_runner.py::test_run_validation_blocks_strategy_param_mutation tests/test_validation_matrix.py -q
conda run -n quant pytest tests/test_runner_api_cli.py tests/test_validation_runner.py tests/test_validation_matrix.py -q
conda run -n quant pytest -q
git diff --check
conda run -n quant python -m compileall -q src tests
```

## GSTACK REVIEW REPORT

### Scope Challenge

This phase deliberately stops before validation replay indexing. Removing the
redundant deep copy and reusing frozen execution inputs addresses the root
duplication and the high-cost repeat freezing without changing the replay
algorithm.

### Architecture Review

Target flow:

```text
load rows + validate params
        |
        v
boundary.frozen_rows / boundary.frozen_params
        |
        v
StrategyExecutionResult carries raw + frozen inputs
        |
        v
runner and validation reuse frozen inputs at strategy/audit/backend boundaries
```

### Edge Cases

- Caller mutates the original nested row or params after freezing: frozen values
  stay unchanged for standard mappings/lists/tuples/sets.
- Strategy attempts to mutate rows or params: mapping proxies and tuples raise
  `TypeError`.
- Already frozen rows/params are passed back through the boundary: identity is
  preserved.
- Externally-created `MappingProxyType` values are copied into `FrozenMapping`
  before freezing, so later backing-dict mutations do not leak.
- Validation matrix override maps remain immutable after Pydantic validation.

### Test Review

Tests must cover:

- direct boundary idempotence;
- direct boundary caller isolation and mutation failure;
- runner and validation mutation-blocking behavior;
- validation matrix override immutability through the shared boundary helper;
- full regression suite.
