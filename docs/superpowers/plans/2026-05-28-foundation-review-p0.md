# Foundation Review P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the P0 semantic blockers from `review-codex.md` and `review-claude.md`.

**Architecture:** Move hidden-lookahead replay into a neutral top-level module, let runner and validation consume it, and keep public runner/validation entry points stable. Rename misleading labels and metric fields directly because old artifacts are disposable under the PRD.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, conda environment `quant`.

---

### Task 1: Runner Causality Enforcement

**Files:**
- Create: `src/quant_strategies/causality.py`
- Modify: `src/quant_strategies/validation/lookahead.py`
- Modify: `src/quant_strategies/runner/__init__.py`
- Modify: `src/quant_strategies/runner/artifacts.py`
- Test: `tests/test_runner_api_cli.py`

- [ ] **Step 1: Write a runner regression test**

Add a test strategy that sizes from a future row while claiming `as_of_time` on the current row. Run `run_config` with rows that have complete `available_at` coverage. Expected: `RunResult.success is False`, summary `stage == "causality"`, `assessment_status == "runner_failed"`, and message includes `hidden_lookahead_detected`.

- [ ] **Step 2: Extract causality replay**

Move the current contents of `validation/lookahead.py` into `src/quant_strategies/causality.py`. Replace `validation/lookahead.py` with a re-export so existing imports still resolve during this phase.

- [ ] **Step 3: Enforce replay in runner**

Import `check_hidden_lookahead` from `quant_strategies.causality`. After `execute_strategy_run`, run replay before engine request construction. Failure returns `_failure_result(..., stage="causality", assessment_status="runner_failed")`.

- [ ] **Step 4: Make evidence quality causality-aware**

Change `artifacts.evidence_quality` and `write_data_manifest` so the runner can pass a computed evidence-quality payload. Remove `runner_causality_not_verified` when replay passes and all rows have parseable aware `available_at`; keep it when availability is partial, missing, or invalid.

- [ ] **Step 5: Verify**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py tests/test_validation_lookahead.py -q
```

Expected: all selected tests pass.

### Task 2: Validation Decision Label Rename

**Files:**
- Modify: `src/quant_strategies/validation/policy.py`
- Modify: `src/quant_strategies/validation/__init__.py`
- Modify: `tests/test_validation_backends_and_policy.py`
- Modify: `tests/test_validation_runner.py`
- Modify: `tests/test_validation_cli.py`
- Modify: `README.md`

- [ ] **Step 1: Rename the policy literal**

Replace `paper_candidate` with `mechanical_review_candidate` in validation decisions and success classification. Do not add aliases.

- [ ] **Step 2: Update policy and artifact tests**

Update expected decision payloads, report strings, and CLI parametrization.

- [ ] **Step 3: Verify**

Run:

```bash
conda run -n quant pytest tests/test_validation_backends_and_policy.py tests/test_validation_runner.py tests/test_validation_cli.py -q
```

Expected: all selected tests pass.

### Task 3: Smoke Activity Metric Rename

**Files:**
- Modify: `src/quant_strategies/engine/models.py`
- Modify: `src/quant_strategies/engine/evaluation.py`
- Modify: `src/quant_strategies/evidence_semantics.py`
- Modify: `src/quant_strategies/runner/__init__.py`
- Modify: runner and engine tests
- Modify: `README.md`
- Modify: `docs/quant-autoresearch-consumer.md`

- [ ] **Step 1: Rename fields**

Replace:

```text
sum_weighted_trade_gross_return -> sum_signed_trade_activity_gross
sum_weighted_trade_funding_return -> sum_signed_trade_activity_funding
sum_weighted_trade_cost_return -> sum_signed_trade_activity_cost
sum_weighted_trade_net_return -> sum_signed_trade_activity_net
```

- [ ] **Step 2: Update evidence semantics**

Set `return_model` to `smoke_score.sum_signed_trade_activity_net`.

- [ ] **Step 3: Update docs and tests**

Update assertions and docs to describe activity sums, not portfolio returns.

- [ ] **Step 4: Verify**

Run:

```bash
conda run -n quant pytest tests/test_engine_screen.py tests/test_runner_api_cli.py tests/test_runner_artifact_profiles.py tests/test_readme_contract.py -q
```

Expected: all selected tests pass.

### Task 4: Final Verification And Review

**Files:**
- Modify: `progress.md`

- [ ] **Step 1: Run focused checks**

Run all commands from Tasks 1-3.

- [ ] **Step 2: Run full suite**

Run:

```bash
conda run -n quant pytest -q
```

Expected: full suite passes.

- [ ] **Step 3: Request code review**

Use a code-review subagent on the diff against the starting commit. Fix Critical and Important findings before committing.

- [ ] **Step 4: Commit**

Commit the Phase 1 work as one coherent root-cause change after review is clean.

## GSTACK REVIEW REPORT

### Scope Challenge

This phase touches more than eight files because it intentionally changes public artifact names and tests. That is acceptable here because the source blast radius is small: one new causality module, runner evidence wiring, validation label string, smoke score field names, tests, and docs. Reducing scope would leave the PRD's most visible semantic lies in place.

### Architecture Review

The key architecture risk is importing `quant_strategies.validation.lookahead` from runner, which would create a package import cycle because `validation/__init__.py` already imports runner execution. The plan avoids that by extracting causality replay to `quant_strategies.causality`. This is a focused neutral kernel extraction, not a new subsystem.

No compatibility aliases are planned. The PRD explicitly says no legacy compatibility shims and existing results can be regenerated.

### Data Flow

```text
run_config
  -> execute_strategy_run
  -> check_hidden_lookahead
       -> fail: summary stage causality, assessment_status runner_failed
       -> pass + complete available_at: causality_verified true
       -> pass + missing/partial available_at: smoke_unverified
  -> decision rows ready
  -> engine request
  -> engine evaluation
  -> artifacts
```

### Edge Cases

- Empty decisions still reach request building and fail as today's request-build behavior unless addressed in a later phase.
- Missing or partial `available_at` does not block smoke search, but it cannot produce `smoke_passed`.
- Hidden-lookahead replay exceptions become runner failures with the replay error surfaced.
- Validation keeps importing `validation.lookahead` successfully through a re-export wrapper.

### Test Coverage

The plan adds or updates focused tests for:

- runner hidden-lookahead failure,
- complete availability producing `causality_verified = true`,
- missing/partial availability producing unverified evidence,
- validation decision label rename,
- smoke activity field rename,
- docs contract strings.

### Performance

Runner causality replay adds work proportional to decision count. Correctness is first here. The review already identifies replay optimization as a later phase; do not weaken replay in P0 for speed.
