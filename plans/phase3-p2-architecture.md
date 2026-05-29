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

### 3c — F10 god-module serialization split — DONE (validation payload builders)
Extracted the two inline artifact payload builders the review specifically cited
("hand-builds four artifact payloads inline at :863-968") out of the
`validation/__init__.py` orchestrator into `validation/artifacts.py`:
`backend_runs_payload`, `robustness_matrix_payload`, plus the `agreement_payload`
and `scenario_classification_reasons` shapers. The orchestrator now calls these
builders; output is byte-identical (test-guarded, 619 green; no import cycle —
`artifacts.py` imports only the lower-level `backends`/`policy` types).

**Deferred remainder (documented recommendation):** the same pattern applies to
`runner/__init__.py` (its `_summary_payload`/notes builders → `runner/artifacts.py`)
and to splitting `data_contract.py`'s normalization vs serialization. These are
further mechanical relocations; left as a follow-up to keep this change bounded
and individually reviewable.

### 3d — F9 neutral execution spec — DONE in Phase 4b (was deferred, then completed)

**UPDATE:** completed in Phase 4b (neutral `StrategyExecutionSpec` in core; validation
no longer imports `runner.config`; AST test enforces it). The F10 remainder
(runner/__init__ split, data_contract `json_safe_value` extraction) completed in
Phase 4c. The deferral rationale below is kept for history.

**Not executed overnight.** Validation threads `run_config` (a runner `RunConfig`)
and `StrategyExecutionResult` through ~10 functions and calls the shared
`execute_strategy_run`; the clean fix (a neutral `StrategyExecutionSpec` both
sides adapt into) changes that **shared function's signature on the
verdict-producing path** and rewires the whole validation execution flow. That is
a deep refactor of trust-critical code whose benefit is maintainability (a
boundary smell), not correctness — best done with real-run validation and Season's
architectural review, not forced unattended.

**Ready-to-run recommendation:** define `StrategyExecutionSpec(strategy_path,
strategy_id, data, params, fill_model, cost_model)` in a neutral module (e.g.
`core/`); give `execute_strategy_run` a spec-based entry; have `RunConfig` and the
validation config each expose `to_execution_spec()`; replace validation's
`to_run_config()` usage and the `run_config.*` field reads with the spec; add a
test asserting `quant_strategies.validation` does not import `runner.config` for
execution. Keep the public `run_config`/`run_validation` APIs stable.

## Discipline
- `conda run -n quant pytest -q` green after each sub-step; ruff clean.
- F9/F10 are large refactors — do as much as can be done cleanly; document any deferred remainder rather than ship a risky half-refactor.
- `/code-review` on the phase diff; report line counts (expect net negative source).
