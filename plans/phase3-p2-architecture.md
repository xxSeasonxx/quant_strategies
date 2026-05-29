# Phase 3 — P2 Architecture & Subtraction (F8/F9/F10/F11/F12) Plan

**Goal:** Subtract duplication and trim the over-built `data_contract`, per the
review's "subtract, don't add" theme. Behavior-preserving; suite green throughout.

**Re-audit (post Phase 1-2):**
- **F8** funding twice → **already resolved** (single `funding.funding_return_over_window`; `engine._funding_return` delegates; `tests/test_funding.py` pins both). No work.
- **F12** seam dup → `runner/events.py` ≡ `validation/events.py` (modulo names + event string); `json_safe_value` defined 2× (`data_contract.py`, `runner/artifact_profiles.py`). (`_causality_evidence` already deduped in Phase 1.)
- **F11** `data_contract` over-build → `freshness_status="not_evaluated"` (dead, no consumers); `metadata_field_coverage` 5-field freshness scaffolding (out-of-scope per NG2; only an internal manifest field + 2 tests, not in consumer docs); `RETAINED` enum value now **identical to VALIDATION** (its only differentiator, `strict_replay`, was removed in Phase 1).
- **F9** validation imports `runner.config`/`runner.execution`/`runner.engine_runner`/`runner.errors` for execution.
- **F10** god-modules: `validation/__init__.py` 987L, `runner/__init__.py` 735L, `data_contract.py` 944L mix orchestration + serialization.

## Sub-steps (each green; one commit after code review)

### 3a — F12 dedup the seam
- Extract one `StageEmitter` (+ `_ActiveStage`, `jsonl_event_sink`, `StageEvent`/`StageEventSink`) into `core/events.py`, parameterized by an `event_type` ClassVar. `runner/events.py` and `validation/events.py` become thin subclasses (`RunnerStageEmitter`/`ValidationStageEmitter` set `event_type`) + re-exports, so usage sites and type names are unchanged.
- One `json_safe_value`: keep `data_contract.json_safe_value`; `runner/artifact_profiles.py` imports it; delete its copy.

### 3b — F11 trim data_contract (safe subtractions)
- Remove the dead `freshness_status="not_evaluated"` field from `row_contract_summary`.
- Remove the `metadata_field_coverage` freshness scaffolding (`_METADATA_COVERAGE_FIELDS`, `metadata_present` tracking, the property, the manifest field in `runner/artifacts.py`); `available_at` coverage already lives in `availability_coverage`. Update the 2 test assertions.
- Remove the `RETAINED` enum value; collapse `RowContractMode` to `search|validation`. Simplify `_validation_row_contract_mode` (paper_readiness no longer changes row-contract mode). Update the `mode="retained"` test.
- **Defer (documented):** the bespoke issue sampler (`_IssueAccumulator`, working, low value) and deferring OHLC/quote structural validation to `engine.Bar` (correctness-adjacent; risky). Note as recommendations.

### 3c — F9 neutral execution spec (assess + attempt)
- Goal: validation no longer imports `runner.config`/`runner.execution` for execution. Extract a neutral `StrategyExecutionSpec` (strategy path/id, data, params, fill, cost — no output policy) that both runner and validation adapt into. Add a test asserting validation does not import `runner.config` for execution.
- Risk: architectural; attempt only with the suite green at each step.

### 3d — F10 god-module serialization split (assess + attempt)
- Mechanically relocate artifact/JSON dict-building out of the `validation/__init__.py` and `runner/__init__.py` orchestrators into the existing `artifacts` modules (orchestrators call writers). No new abstractions; pure relocation.

## Discipline
- `conda run -n quant pytest -q` green after each sub-step; ruff clean.
- F9/F10 are large refactors — do as much as can be done cleanly; document any deferred remainder rather than ship a risky half-refactor.
- `/code-review` on the phase diff; report line counts (expect net negative source).
