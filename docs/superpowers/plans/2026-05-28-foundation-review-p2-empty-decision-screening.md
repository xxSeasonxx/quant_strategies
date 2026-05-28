# Empty-Decision Screening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Treat an empty decision list as a valid zero-opportunity runner output instead of a runner failure.

**Architecture:** The engine request model will allow `StrategySpec.decisions` to be empty. The existing smoke engine already sums empty trades to zero, so runner and engine behavior can flow through the normal request, evaluation, artifact, summary, and evidence paths.

**Tech Stack:** Python 3.12, Pydantic v2, existing smoke engine and runner tests, pytest via `conda run -n quant`.

---

## File Structure

- Modify `src/quant_strategies/engine/models.py`: allow `StrategySpec.decisions` to be an empty tuple.
- Modify `src/quant_strategies/runner/engine_runner.py`: remove the request-builder guard that rejects zero decisions.
- Modify `tests/test_engine_screen.py`: prove `screen()` reports zero trades and zero scores for empty decisions.
- Modify `tests/test_engine_validate_and_evidence.py`: prove `validate()` treats zero decisions as valid inputs and fails smoke gates, not input validation.
- Modify `tests/test_runner_engine_runner.py`: replace the rejection test with a request/evaluation acceptance test.
- Modify `tests/test_runner_api_cli.py`: prove `run_config()` writes completed zero-decision artifacts and reports `smoke_failed`.
- Modify `README.md` and `docs/quant-autoresearch-consumer.md`: document zero-opportunity interpretation.
- Modify `progress.md`: record Phase 13 status and verification.

## Implementation Steps

- [x] **Step 1: Add engine no-op regressions**

  Add tests that construct `StrategySpec(strategy_id="no_op", decisions=())`.
  Expected behavior:

  - `screen()` returns `trade_count == 0`, `trades == ()`, and all
    `smoke_score.sum_signed_trade_activity_*` values equal `0.0`.
  - `validate()` returns `passed is False`, `valid_inputs` is true,
    `min_trades` is false, `positive_gross` is false, and `positive_net` is
    false.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_engine_screen.py::test_screen_accepts_empty_decision_set_as_zero_trade_result tests/test_engine_validate_and_evidence.py::test_validate_empty_decision_set_fails_smoke_gates_not_inputs -q
  ```

  Expected before implementation: fails because `StrategySpec.decisions` rejects
  an empty tuple.

- [x] **Step 2: Add runner no-op regression**

  Replace `test_build_request_rejects_zero_decisions()` with
  `test_build_request_accepts_zero_decisions_as_no_op()`. Add a runner API test
  with a strategy whose `generate_decisions()` returns `[]`.

  Runner API expected behavior for default validate mode:

  - `result.run_completed is True`
  - `result.success is False`
  - `result.assessment_status == "smoke_failed"`
  - summary `stage == "completed"`
  - summary `status == "failed"`
  - summary engine `trade_count == 0`
  - summary engine smoke scores are all zero
  - `decision_records.jsonl` exists and is empty
  - `engine_request.json` contains `"decisions": []`
  - `evidence.json` contains zero trades

  Verify:

  ```bash
  conda run -n quant pytest tests/test_runner_engine_runner.py::test_build_request_accepts_zero_decisions_as_no_op tests/test_runner_api_cli.py::test_run_config_treats_empty_decisions_as_zero_trade_smoke_result -q
  ```

  Expected before implementation: fails because `build_request()` raises
  `RequestBuildError`.

- [x] **Step 3: Implement the contract fix**

  In `src/quant_strategies/engine/models.py`, change:

  ```python
  decisions: tuple[StrategyDecision, ...] = Field(min_length=1)
  ```

  to:

  ```python
  decisions: tuple[StrategyDecision, ...]
  ```

  In `src/quant_strategies/runner/engine_runner.py`, delete:

  ```python
  if not decisions:
      raise RequestBuildError("strategy generated no decisions")
  ```

  Verify:

  ```bash
  conda run -n quant pytest tests/test_engine_screen.py::test_screen_accepts_empty_decision_set_as_zero_trade_result tests/test_engine_validate_and_evidence.py::test_validate_empty_decision_set_fails_smoke_gates_not_inputs tests/test_runner_engine_runner.py::test_build_request_accepts_zero_decisions_as_no_op tests/test_runner_api_cli.py::test_run_config_treats_empty_decisions_as_zero_trade_smoke_result -q
  ```

- [x] **Step 4: Update docs and progress**

  Update README runner semantics and autoresearch consumer guidance so zero
  trades are a valid search signal, not infrastructure failure. Update
  `progress.md` with Phase 13 current phase, triage row, checklist, and
  verification log.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_readme_contract.py -q
  ```

- [x] **Step 5: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest tests/test_engine_screen.py tests/test_engine_validate_and_evidence.py tests/test_runner_engine_runner.py tests/test_runner_api_cli.py tests/test_readme_contract.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix any valid findings and rerun the
  relevant focused checks plus the full suite.

## GSTACK REVIEW REPORT

### Scope Challenge

The tempting smaller fix is to catch empty decisions in `run_config()` and
synthesize a zero-trade summary. That would create a runner-only behavior and
leave the engine contract incorrectly saying a no-op strategy is invalid. The
root-cause fix is to make the engine request model accept zero decisions.

### Architecture Review

Target flow:

```text
generate_decisions() -> []
        |
        v
StrategySpec(decisions=())
        |
        v
screen(): zero trades, zero smoke score
        |
        v
validate(): valid_inputs true, smoke gates fail
        |
        v
run_config(): completed smoke result, not runner_failed
```

### Edge Cases

- Empty loaded rows remain a data-load failure through the existing loader
  checks.
- Malformed strategy output remains a `decision_generation` failure.
- Unsupported non-empty decisions remain request-build failures.
- Full-profile zero-decision runs still write request/evidence artifacts.
- Summary-profile zero-decision runs keep compact search artifacts only.

### Test Review

Tests cover engine model acceptance, screen output, validate gates, runner
request building, full-profile artifact contents, docs, and existing failure
paths through the focused and full suites.
