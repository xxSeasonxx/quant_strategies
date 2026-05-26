# Validation Depth Phase 6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add Phase 6 validation depth with typed `StrategyDecision` observation dependencies, synthetic future-poison causality tests, conservative VectorBT PRO portfolio target-weight support, and backend capability artifacts.

**Architecture:** `StrategyDecision` remains the only strategy contract. Observation dependencies become first-class typed fields on that model, so strategies still return `list[StrategyDecision]` and validation audits the declared observations against the same data rows used for as-of checks. Backend capability artifacts are written only after the backend behavior exists, so artifacts never claim support for semantics the code still rejects.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, pandas, optional VectorBT PRO, existing `quant_strategies.decisions` and `quant_strategies.validation` modules.

---

## Engineering Review Decisions

- Use a typed field now: add `ObservationRef` and `StrategyDecision.observations`, defaulting to an empty tuple for backward compatibility.
- Do not use `StrategyDecision.metadata["observations"]`; `metadata` remains available for non-contract strategy extras.
- Execute in this order: Task 1, Task 2, Task 3, Task 4, Task 5.
- Task 3 must land before Task 4 so capability artifacts describe implemented backend behavior, not planned behavior.
- New tests must use synthetic strategies and canonical `StrategyDecision` objects only. Do not import `researched/`, `tested/`, `untested/`, `rank_03`, or legacy signal-only modules.

## What Already Exists

- `StrategyDecision`, `InstrumentRef`, `PositionTarget`, and `ExitPolicy` already define the canonical strategy contract in `src/quant_strategies/decisions/models.py`.
- `audit_decision_rows(...)` already builds a `(symbol, timestamp)` row index and checks as-of row availability in `src/quant_strategies/validation/data_audit.py`; reuse that index for observation dependency audits.
- `VectorBTProBackend` already builds close frames, entry/exit signal matrices, target-weight size matrices, and fail-closed unsupported semantics in `src/quant_strategies/validation/vectorbtpro_backend.py`.
- Validation already writes manifests and per-scenario backend summaries; extend those artifacts instead of adding a parallel manifest path.

## NOT In Scope

- No full portfolio optimizer, margin, borrow, market impact, or capacity model.
- No compatibility layer for legacy signal-only strategies.
- No promotion to paper/live eligibility; validation remains advisory.
- No researched package migration in this phase.
- No new data loading or materialization behavior; `quant_data` remains upstream.

## Data Flow

```text
strategy.generate_decisions(rows, params)
  -> list[StrategyDecision(observations=(ObservationRef(...), ...))]
  -> validate_decision_output(...)
  -> audit_decision_rows(rows, decisions)
       ├── as-of row availability check
       └── observation dependency availability check
  -> validation matrix scenarios
  -> VectorBTProBackend.run(...)
       ├── reject unsupported semantics
       ├── validate per-symbol windows
       ├── validate gross active target weight <= 1.0
       └── simulate one cash-sharing portfolio group
  -> backend_capability_matrix.json
  -> validation_manifest.json embeds capability matrix + artifact hashes
```

## Task 1: Add Typed Observation Dependencies To StrategyDecision

**Files:**
- Modify: `src/quant_strategies/decisions/models.py`
- Modify: `src/quant_strategies/decisions/__init__.py`
- Modify: `tests/test_decision_models.py`

- [x] Add `ObservationRef(DecisionModel)` with fields:

```python
class ObservationRef(DecisionModel):
    symbol: str
    timestamp: datetime
    field: str | None = None
    source: str | None = None

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return _stripped_non_empty(value, "symbol")

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return _timezone_aware(value, "timestamp")

    @field_validator("field", "source")
    @classmethod
    def validate_optional_text(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _stripped_non_empty(value, info.field_name)
```

- [x] Add `observations: tuple[ObservationRef, ...] = ()` to `StrategyDecision`.
- [x] Export `ObservationRef` from `src/quant_strategies/decisions/__init__.py`.
- [x] Add model tests:
  - accepts multiple typed observations for cross-sectional decisions;
  - defaults `observations` to `()`;
  - rejects naive observation timestamps;
  - rejects empty observation symbols;
  - serializes observations into `model_dump(mode="json")`.
- [x] Run:

```bash
conda run -n quant pytest tests/test_decision_models.py -q
```

- [x] Commit:

```bash
git add src/quant_strategies/decisions/models.py src/quant_strategies/decisions/__init__.py tests/test_decision_models.py
git commit -m "feat: add typed decision observations"
```

## Task 2: Audit Observation Dependencies And Future Poison

**Files:**
- Create: `src/quant_strategies/validation/datetime_utils.py`
- Create: `src/quant_strategies/validation/dependencies.py`
- Modify: `src/quant_strategies/validation/data_audit.py`
- Create: `tests/test_validation_dependencies.py`
- Create: `tests/test_validation_future_poison.py`

- [x] Move aware datetime parsing into `validation/datetime_utils.py`:

```python
def parse_aware_datetime(value: Any) -> tuple[datetime | None, str | None]:
    ...
```

Use the existing behavior from `data_audit.py`: accept aware `datetime`, accept ISO strings including `Z`, reject naive/invalid/non-datetime values with the same reason strings.

- [x] Add `audit_observation_dependencies(row_index, decisions)` in `validation/dependencies.py`.
  - Input `row_index` is the existing `dict[tuple[str, datetime], list[Mapping[str, Any]]]` built by `audit_decision_rows`.
  - For each `decision.observations`, fail if observation timestamp is after `decision.as_of_time`.
  - Fail if the observation row is missing.
  - Fail if the observation row has missing/invalid `available_at`.
  - Fail if `available_at > decision.decision_time`.
  - Do not rebuild the full row index inside this helper.
- [x] Update `audit_decision_rows(...)` to call `audit_observation_dependencies(row_index, decisions)` before returning.
- [x] Add dependency tests:
  - no observations remains valid;
  - declared cross-section observations pass;
  - future observation timestamp fails;
  - missing observation row fails;
  - missing/invalid/late `available_at` fails.
- [x] Add synthetic future-poison tests:
  - cross-sectional synthetic generator uses only `AS_OF` rows and typed observations;
  - FX triangle synthetic generator uses only `AS_OF` rows and typed observations;
  - poisoning future rows does not change generated decision fingerprints;
  - a declared future FX observation is caught by the audit.
- [x] Run:

```bash
conda run -n quant pytest tests/test_validation_dependencies.py tests/test_validation_future_poison.py -q
```

- [x] Commit:

```bash
git add src/quant_strategies/validation/datetime_utils.py src/quant_strategies/validation/dependencies.py src/quant_strategies/validation/data_audit.py tests/test_validation_dependencies.py tests/test_validation_future_poison.py
git commit -m "feat: audit decision observation dependencies"
```

## Task 3: Support Conservative Portfolio Target Weights In VectorBT PRO

**Files:**
- Modify: `src/quant_strategies/validation/vectorbtpro_backend.py`
- Modify: `tests/test_vectorbtpro_backend.py`

- [x] Replace the old `multi_asset_target_weight` unsupported test with a passing test for two symbols sized `0.6` and `0.4`.
- [x] In that test, monkeypatch `vectorbtpro.Portfolio.from_signals` and assert:
  - `status == "completed"`;
  - `unsupported_semantics == ()`;
  - `size_type == "valuepercent"`;
  - `cash_sharing is True`;
  - `group_by is True`;
  - both symbol sizes are passed at the expected entry timestamp;
  - metrics include `portfolio_target_weight_model == "vectorbtpro_valuepercent_cash_sharing"` and `max_gross_target_weight == 1.0`.
- [x] Add fail-closed tests:
  - simultaneous `0.7 + 0.4` target weights fail with `portfolio_target_weight_exceeds_one`;
  - staggered cross-symbol windows fail when active gross weight exceeds `1.0`;
  - per-decision weight above `1.0` still reports `leveraged_target_weight`;
  - threshold exits, non-close fills, non-target-weight sizing, flat targets, and same-symbol overlapping windows still fail closed.
- [x] Implement `_validate_portfolio_target_weights(windows)`:
  - compute gross active target weight at each entry timestamp;
  - use positive size as absolute exposure for long and short;
  - raise `ValueError("portfolio_target_weight_exceeds_one:<timestamp>:<gross>")` above `1.0 + 1e-12`;
  - return the maximum gross target weight.
- [x] Remove only the blanket multi-symbol rejection block from `_unsupported_semantics(...)`.
- [x] Add `cash_sharing=True` and `group_by=True` to `vbt.Portfolio.from_signals(...)`.
- [x] Add portfolio metrics after funding adjustment:

```python
metrics = {
    **metrics,
    "portfolio_target_weight_model": "vectorbtpro_valuepercent_cash_sharing",
    "max_gross_target_weight": max_gross_target_weight,
}
```

- [x] Run:

```bash
conda run -n quant pytest tests/test_vectorbtpro_backend.py -q
```

- [x] Commit:

```bash
git add src/quant_strategies/validation/vectorbtpro_backend.py tests/test_vectorbtpro_backend.py
git commit -m "feat: support validation portfolio target weights"
```

## Task 4: Add Backend Capability Matrix Artifacts

**Files:**
- Create: `src/quant_strategies/validation/capabilities.py`
- Modify: `src/quant_strategies/validation/__init__.py`
- Modify: `src/quant_strategies/validation/manifest.py`
- Create: `tests/test_validation_capabilities.py`
- Modify: `tests/test_validation_runner.py`

- [x] Add `backend_capability_matrix(backend_name, backend_results)` returning:
  - `backend`;
  - sorted `observed_unsupported_semantics`;
  - `semantics`, a list of records with `semantic`, `status`, `details`, and `observed_unsupported`.
- [x] For `vectorbtpro`, record:
  - supported: close fills, target-weight sizing;
  - conditional: portfolio target weights under close-fill, no threshold exits, no same-symbol overlap, no leverage, gross active target weight <= `1.0`;
  - unsupported: non-close fills, threshold exits, non-target-weight sizing, flat targets, leveraged weights, same-symbol overlap;
  - conditional: crypto perp funding linear additive adjustment.
- [x] For `fake`, record a single `test_double` supported semantic so tests have deterministic output.
- [x] Write `backend_capability_matrix.json` in `_write_validation_artifacts(...)` for all validation outcomes, including hard-no paths.
- [x] Embed the same matrix under `manifest["backend"]["capability_matrix"]`.
- [x] Include `backend_capability_matrix.json` in manifest `core_hashes`.
- [x] Add tests:
  - static VectorBT matrix marks portfolio target weight conditional;
  - observed unsupported semantic codes set `observed_unsupported=True`;
  - clear-yes validation writes capability artifact, embeds it in manifest, and hashes it;
  - hard-no data-audit failure still writes capability artifact, embeds it in manifest, and hashes it.
- [x] Run:

```bash
conda run -n quant pytest tests/test_validation_capabilities.py tests/test_validation_runner.py::test_run_validation_writes_clear_yes_artifacts tests/test_validation_runner.py::test_run_validation_records_data_audit_failure -q
```

- [x] Commit:

```bash
git add src/quant_strategies/validation/capabilities.py src/quant_strategies/validation/__init__.py src/quant_strategies/validation/manifest.py tests/test_validation_capabilities.py tests/test_validation_runner.py
git commit -m "feat: record validation backend capability matrix"
```

## Task 5: Documentation And Final Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-05-26-foundation-repair-design.md`

- [x] Update README validation docs:
  - `StrategyDecision.observations` is the typed dependency contract;
  - validation audits observation rows against `as_of_time`, `decision_time`, and `available_at`;
  - `backend_capability_matrix.json` is written and embedded in the manifest;
  - VectorBT PRO portfolio target weights are conditional, not general portfolio validation;
  - capability support is not paper/live eligibility.
- [x] Update the rollout spec Phase 6 note to point at this plan and record that Season chose typed observations now.
- [x] Run focused tests:

```bash
conda run -n quant pytest tests/test_decision_models.py tests/test_validation_dependencies.py tests/test_validation_future_poison.py tests/test_vectorbtpro_backend.py tests/test_validation_capabilities.py tests/test_validation_runner.py -q
```

- [x] Run full suite:

```bash
conda run -n quant pytest -q
```

- [x] Report changed-line counts:

```bash
git diff --stat
git diff --shortstat
```

- [x] Commit:

```bash
git add README.md docs/superpowers/specs/2026-05-26-foundation-repair-design.md
git commit -m "docs: describe validation depth semantics"
```

## Test Coverage Diagram

```text
CODE PATHS                                             TESTS
[+] StrategyDecision observations                       tests/test_decision_models.py
  ├── default empty tuple                                [★★★] default test
  ├── multiple typed observations                        [★★★] cross-section test
  ├── naive timestamp                                    [★★★] validation error
  ├── empty symbol/source/field                          [★★★] validation error
  └── JSON serialization                                 [★★★] model_dump test

[+] audit_decision_rows + dependencies                   tests/test_validation_dependencies.py
  ├── no observations                                    [★★★] no-op pass
  ├── valid cross-section observations                   [★★★] pass
  ├── future observation timestamp                       [★★★] fail
  ├── missing observation row                            [★★★] fail
  ├── missing/invalid/late available_at                  [★★★] fail
  └── reuses existing row_index                          [★★★] implementation check via plan

[+] Future poison synthetic strategies                   tests/test_validation_future_poison.py
  ├── cross-section future row poison                    [★★★] unchanged fingerprint
  ├── FX triangle future row poison                      [★★★] unchanged fingerprint
  └── declared future FX observation                     [★★★] audit failure

[+] VectorBT PRO backend portfolio weights               tests/test_vectorbtpro_backend.py
  ├── supported 0.6 + 0.4 multi-symbol weights           [★★★] completed
  ├── simultaneous gross > 1.0                           [★★★] fail closed
  ├── staggered active gross > 1.0                       [★★★] fail closed
  ├── existing unsupported semantics                     [★★★] regression coverage
  └── funding metrics still compose                      [★★★] existing tests

[+] Capability artifacts                                 tests/test_validation_capabilities.py + runner tests
  ├── static matrix shape                                [★★★] unit
  ├── observed unsupported semantics                     [★★★] unit
  ├── clear-yes manifest/artifact/hash                   [★★★] integration
  └── hard-no manifest/artifact/hash                     [★★★] integration

COVERAGE: planned 100% for new behavior
Legend: ★★★ behavior + edge + error coverage
```

## Failure Modes

- Typed observations reject valid strategy output if the schema is too narrow: covered by model tests and mitigated with optional `field`/`source`.
- Observation rows can be missing or become available after the decision: covered by dependency audit tests with explicit violations.
- Future-poisoned rows can influence strategy logic: covered by synthetic cross-section and FX triangle fingerprint tests.
- VectorBT PRO can over-allocate portfolio target weights: covered by simultaneous and staggered gross exposure fail-closed tests.
- Capability artifacts can be missing on hard-no runs: covered by failure-path runner test.
- Real VectorBT PRO semantics can differ from fake monkeypatch assertions: mitigated by retaining existing optional real-package backend tests where available.

## Parallelization Strategy

| Step | Modules touched | Depends on |
|---|---|---|
| Task 1 typed observations | `decisions/`, `tests/` | — |
| Task 2 dependency audits | `validation/`, `tests/` | Task 1 |
| Task 3 portfolio target weights | `validation/`, `tests/` | — |
| Task 4 capability artifacts | `validation/`, `tests/` | Task 3 |
| Task 5 docs/verifications | `README`, `docs/` | Tasks 1-4 |

Parallel lanes:

- Lane A: Task 1 → Task 2, sequential because the audit reads the typed field.
- Lane B: Task 3, independent of typed observations.
- Lane C: Task 4 → Task 5, waits for Task 3 and should merge after Lane A.

Execution order for same-session subagent-driven development: Task 1, Task 2, Task 3, Task 4, Task 5. Do not dispatch implementation subagents in parallel in this session.

## Implementation Tasks

Synthesized from the engineering review findings. Each task derives from a specific finding above. Run with Claude Code or Codex; checkbox as you ship.

- [x] **T1 (P1, human: ~1h / CC: ~10min)** — plan/order — Keep artifact claims behind implemented backend behavior.
  - Surfaced by: Architecture Review — capability matrix must not claim conditional portfolio support before `VectorBTProBackend` supports it.
  - Files: `docs/superpowers/plans/2026-05-26-validation-depth-phase-6.md`
  - Verify: Task 3 appears before Task 4 in execution order.

- [x] **T2 (P2, human: ~1h / CC: ~10min)** — decisions — Use typed observations on `StrategyDecision`.
  - Surfaced by: User decision — Season chose typed field now over metadata convention.
  - Files: `src/quant_strategies/decisions/models.py`, `src/quant_strategies/decisions/__init__.py`, `tests/test_decision_models.py`
  - Verify: `conda run -n quant pytest tests/test_decision_models.py -q`

- [x] **T3 (P2, human: ~45min / CC: ~8min)** — validation — Reuse data-audit row index for observation audits.
  - Surfaced by: Performance Review — avoid scanning validation rows twice.
  - Files: `src/quant_strategies/validation/data_audit.py`, `src/quant_strategies/validation/dependencies.py`
  - Verify: `conda run -n quant pytest tests/test_validation_dependencies.py -q`

- [x] **T4 (P2, human: ~45min / CC: ~8min)** — tests — Add edge coverage for observation and portfolio failure branches.
  - Surfaced by: Test Review — malformed/missing dependency cases and staggered gross-exposure case need tests.
  - Files: `tests/test_validation_dependencies.py`, `tests/test_vectorbtpro_backend.py`
  - Verify: `conda run -n quant pytest tests/test_validation_dependencies.py tests/test_vectorbtpro_backend.py -q`

## Final Self-Review Checklist

- [x] New tests do not import `researched/`, `tested/`, `untested/`, `rank_03`, or legacy signal-only modules.
- [x] All strategies still use the canonical `StrategyDecision` contract.
- [x] Observation dependencies are typed fields, not metadata conventions.
- [x] Observation dependency audits reuse the existing data-audit row index.
- [x] Capability artifacts are written for successful and hard-no validation outcomes.
- [x] VectorBT PRO supports only constrained cash-sharing portfolio target weights.
- [x] Full suite passes with `conda run -n quant pytest -q`.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 7 | CLEAR | 4 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | CLEAR | score: 10/10 → 10/10, 1 decisions |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

- **UNRESOLVED:** 0
- **VERDICT:** ENG CLEARED — ready to implement when Plan Mode ends.
