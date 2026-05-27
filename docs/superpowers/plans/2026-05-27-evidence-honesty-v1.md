# Evidence Honesty v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make runner and validation evidence harder to overread by adding validation-only hidden-lookahead checks, runner evidence-quality artifact fields, and structured validation failure details.

**Architecture:** Keep the bundle narrow. Add a small runner evidence-quality helper, a small validation lookahead module, and explicit failure-detail plumbing through existing validation artifact writing. Do not change strategy APIs, researched layout semantics, `paper_candidate` policy, VectorBT Pro setup, or scenario backend typing in this plan.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, existing `quant_strategies.runner` and `quant_strategies.validation` modules.

---

## What Already Exists

- Runner result writing already centralizes artifact JSON in `runner/artifacts.py`; reuse it instead of adding a second artifact writer.
- Runner summaries already flow through `_summary_payload`; add evidence-quality fields there instead of creating a parallel summary format.
- `metadata_field_coverage` already counts row metadata in `data_manifest.json`; keep it and add a focused `available_at` evidence-quality payload beside it.
- Validation already gates decision output through `validate_decision_output`, declared row lineage through `audit_decision_rows`, and readiness through `check_validation_readiness`; insert hidden-lookahead replay between audit and readiness.
- Validation already writes all machine-readable artifacts through `_write_validation_artifacts`; thread `failure_details` through that path instead of writing ad hoc files.
- Validation backend names are type-restricted in `ValidationConfig`; backend-selection failure tests must monkeypatch `quant_strategies.validation.get_backend` rather than use invalid TOML.

## NOT In Scope

- No `researched/` package compatibility, manifests, variant ontology, or market-validation claims.
- No legacy strategy-output accommodation or adapters.
- No VectorBT Pro setup/package refactor.
- No scenario backend typing refactor.
- No change that makes missing runner `available_at` fatal.
- No hidden-lookahead replay for diagnostic parameter scenarios in v1; required backend scenarios reuse base decisions, so base replay covers the decisions that gate validation.
- No new public artifact-reader facade.

## Data Flow

Runner evidence quality:

```text
run_config
  -> load_data(config)
  -> artifacts.evidence_quality(rows)
  -> write_data_manifest(..., rows)  # writes the same quality payload
  -> generate_decisions(frozen_rows, frozen_params)
  -> engine evaluation
  -> write_summary(..., evidence_quality=quality)
```

Validation hidden-lookahead and failure details:

```text
run_validation
  -> load config and create result_dir
  -> get_backend / load_strategy / validate_params
       -> on fatal exception: _failure_detail(stage, exc)
       -> _failure_result(..., failure_details=[...])
  -> per window:
       load rows -> generate baseline decisions -> validate output
       -> audit_decision_rows
       -> check_hidden_lookahead(full rows, baseline decisions)
       -> if audit + replay + readiness pass: run backend scenarios
  -> _write_validation_artifacts(..., failure_details=[])
```

## Failure Modes

| Codepath | Realistic failure | Planned handling | Planned test |
|---|---|---|---|
| Runner evidence quality | Rows have no `available_at` and could be overread as causal evidence | Non-fatal `missing` status, `causality_verified = false`, explicit warnings | `test_run_config_writes_success_artifacts` |
| Runner evidence quality | Rows have mixed `available_at` coverage | Non-fatal `partial` status and warning | `test_run_config_marks_partial_available_at_coverage` |
| Runner failure before data load | No rows exist for quality calculation | Empty-row quality has total `0`, fraction `None`, still says causality is not verified | `test_run_config_writes_data_failure_summary` |
| Validation backend selection | Backend registry raises despite valid config | `backend_selection_failed` plus structured exception detail | `test_run_validation_records_backend_selection_failure_details` |
| Validation strategy import | Strategy file is missing or invalid | `strategy_import_failed` plus structured exception detail | `test_run_validation_records_strategy_import_failure_details` |
| Hidden-lookahead replay | Strategy changes a decision when future rows are removed | `hidden_lookahead_detected`; backend is not called | `test_run_validation_blocks_hidden_lookahead_strategy` |
| Hidden-lookahead replay | Strategy cannot run on truncated rows | `hidden_lookahead_check_failed`; backend is not called | `test_run_validation_records_hidden_lookahead_replay_failure` |

## Test Coverage Diagram

```text
CODE PATHS                                                    TESTS
[+] runner/artifacts.evidence_quality(rows)
  |-- all rows have available_at ---------------------------- [planned] complete coverage test
  |-- some rows have available_at --------------------------- [planned] partial coverage test
  |-- no rows have available_at ----------------------------- [planned] success artifact test
  `-- empty rows -------------------------------------------- [planned] data failure summary test

[+] runner._summary_payload(..., evidence_quality)
  |-- completed summary includes fields --------------------- [planned] success artifact test
  `-- failure summary includes fields ----------------------- [planned] data failure summary test

[+] validation._failure_detail(stage, exc)
  |-- backend selection exception --------------------------- [planned] monkeypatched get_backend test
  |-- strategy import exception ----------------------------- [planned] missing strategy test
  `-- param validation exception ---------------------------- [planned] existing branch plus detail threading

[+] validation.lookahead.check_hidden_lookahead(...)
  |-- replay matches baseline ------------------------------- [planned] as-of-only unit test
  |-- replay fingerprint differs ---------------------------- [planned] future-sensitive unit test
  |-- replay raises ----------------------------------------- [planned] replay exception unit test
  |-- duplicate replay key ---------------------------------- [not planned] defensive branch, covered by implementation simplicity
  `-- missing replay decision ------------------------------- [covered by fingerprint mismatch path]

[+] validation.run_validation integration
  |-- lookahead fails before backend scenarios -------------- [planned] backend calls == 0
  |-- replay error preserves detailed violation ------------- [planned] data_audit assertions
  `-- existing future-poison tests remain unchanged --------- [planned] focused verification command
```

The only uncovered defensive branch is duplicate replay keys. It is a guard
against invalid replay output after `validate_decision_output`; exercising it
would require an artificial duplicate-decision fixture and does not change the
public behavior of this v1 bundle.

## Worktree Parallelization Strategy

| Step | Modules touched | Depends on |
|---|---|---|
| Runner evidence quality | `src/quant_strategies/runner`, `tests` | - |
| Validation failure details | `src/quant_strategies/validation`, `tests` | - |
| Hidden-lookahead replay | `src/quant_strategies/validation`, `tests` | Validation failure details only for final artifact plumbing |
| README update | `README.md` | Runner + validation wording stabilized |

Parallel lanes:

- Lane A: Runner evidence quality.
- Lane B: Validation failure details -> hidden-lookahead replay. Keep these sequential because both touch `validation/__init__.py`.
- Lane C: README update after lanes A and B.

Execution order: launch Lane A and Lane B in parallel agents, merge/review both,
then do Lane C locally.

Conflict flags: Lane B owns `src/quant_strategies/validation/__init__.py` and
`tests/test_validation_runner.py`; no other lane should edit those files.

## Implementation Tasks

- [ ] **T1 (P1, human: ~1h / CC: ~10min)** - Runner evidence quality - add artifact fields without changing runner pass/fail semantics.
  - Surfaced by: foundation review finding on runner evidence overread risk.
  - Files: `src/quant_strategies/runner/artifacts.py`, `src/quant_strategies/runner/__init__.py`, `tests/test_runner_api_cli.py`.
  - Verify: `conda run -n quant pytest tests/test_runner_api_cli.py -q`.
- [ ] **T2 (P1, human: ~45min / CC: ~10min)** - Validation failure details - persist structured exception details for fatal validation setup failures.
  - Surfaced by: foundation review finding on swallowed validation exception context.
  - Files: `src/quant_strategies/validation/__init__.py`, `tests/test_validation_runner.py`.
  - Verify: `conda run -n quant pytest tests/test_validation_runner.py -q`.
- [ ] **T3 (P1, human: ~2h / CC: ~20min)** - Hidden-lookahead replay - add validation-only replay check and block hidden future-row dependence before backend scenarios.
  - Surfaced by: foundation review finding on undeclared future-row dependence.
  - Files: `src/quant_strategies/validation/lookahead.py`, `src/quant_strategies/validation/__init__.py`, `tests/test_validation_lookahead.py`, `tests/test_validation_runner.py`.
  - Verify: `conda run -n quant pytest tests/test_validation_lookahead.py tests/test_validation_runner.py tests/test_validation_future_poison.py -q`.
- [ ] **T4 (P2, human: ~20min / CC: ~5min)** - README evidence wording - document that runner evidence is non-causal smoke and validation replay is advisory gating.
  - Surfaced by: stale-doc risk from new artifact semantics.
  - Files: `README.md`.
  - Verify: `conda run -n quant pytest tests/test_readme_contract.py -q`.

## File Structure

Create:
- `src/quant_strategies/validation/lookahead.py`
- `tests/test_validation_lookahead.py`

Modify:
- `src/quant_strategies/runner/artifacts.py`
  - Own the runner evidence-quality payload helper.
  - Add evidence-quality fields to `data_manifest.json`.
- `src/quant_strategies/runner/__init__.py`
  - Compute runner evidence quality after rows load.
  - Thread it into `summary.json`.
- `src/quant_strategies/validation/__init__.py`
  - Thread structured failure details into validation artifacts.
  - Run hidden-lookahead checks before backend scenarios.
- `tests/test_runner_api_cli.py`
  - Assert new runner summary and data-manifest fields.
- `tests/test_validation_runner.py`
  - Assert hidden-lookahead integration and validation failure details.
- `README.md`
  - Document evidence-quality fields and validation hidden-lookahead replay at a high level.

Read/verify unchanged:
- `tests/test_validation_future_poison.py`
  - Existing future-poison tests must remain green without edit.

Do not modify:
- `src/quant_strategies/validation/research_manifest.py`; it was deleted and must stay gone.
- `src/quant_strategies/validation/vectorbtpro_backend.py`; VectorBT Pro setup clarity is a later finding.
- `src/quant_strategies/validation/backends.py`; typed scenario backend config is a later refactor.

---

### Task 1: Add Runner Evidence-Quality Fields

**Files:**
- Modify: `src/quant_strategies/runner/artifacts.py`
- Modify: `src/quant_strategies/runner/__init__.py`
- Modify: `tests/test_runner_api_cli.py`

- [ ] **Step 1: Write summary-key expectations**

In `tests/test_runner_api_cli.py`, add these keys to `SUMMARY_KEYS`:

```python
    "data_availability_status",
    "availability_coverage",
    "causality_verified",
    "evidence_quality_warnings",
```

- [ ] **Step 2: Add assertions for missing coverage**

In `test_run_config_writes_success_artifacts`, keep the existing row fixture
call without `research_fields`; then add assertions after
`summary = read_summary(result.result_dir)`:

```python
    assert summary["data_availability_status"] == "missing"
    assert summary["availability_coverage"] == {
        "field": "available_at",
        "present": 0,
        "total": 4,
        "fraction": 0.0,
    }
    assert summary["causality_verified"] is False
    assert summary["evidence_quality_warnings"] == [
        "available_at_missing",
        "runner_causality_not_verified",
    ]
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert data_manifest["data_availability_status"] == summary["data_availability_status"]
    assert data_manifest["availability_coverage"] == summary["availability_coverage"]
    assert data_manifest["causality_verified"] is False
    assert data_manifest["evidence_quality_warnings"] == summary["evidence_quality_warnings"]
```

In `test_run_config_writes_data_failure_summary`, add focused assertions for
empty-row quality:

```python
    assert summary["data_availability_status"] == "missing"
    assert summary["availability_coverage"] == {
        "field": "available_at",
        "present": 0,
        "total": 0,
        "fraction": None,
    }
    assert summary["causality_verified"] is False
    assert summary["evidence_quality_warnings"] == [
        "available_at_missing",
        "runner_causality_not_verified",
    ]
```

Add a focused complete-coverage test near the existing data-manifest tests:

```python
def test_run_config_marks_complete_available_at_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        data_loader,
        "load_data",
        lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, research_fields=True)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert summary["data_availability_status"] == "complete"
    assert summary["availability_coverage"] == {
        "field": "available_at",
        "present": 3,
        "total": 3,
        "fraction": 1.0,
    }
    assert summary["causality_verified"] is False
    assert summary["evidence_quality_warnings"] == ["runner_causality_not_verified"]
    assert data_manifest["data_availability_status"] == "complete"
    assert data_manifest["availability_coverage"] == summary["availability_coverage"]
```

Add a partial-coverage test:

```python
def test_run_config_marks_partial_available_at_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    partial_rows = rows(100.0, 101.0, 102.0, research_fields=True)
    partial_rows[1].pop("available_at")
    monkeypatch.setattr(data_loader, "load_data", lambda config: LoadedData(rows=partial_rows))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert summary["data_availability_status"] == "partial"
    coverage = summary["availability_coverage"]
    assert coverage["field"] == "available_at"
    assert coverage["present"] == 2
    assert coverage["total"] == 3
    assert coverage["fraction"] == pytest.approx(2 / 3)
    assert summary["evidence_quality_warnings"] == [
        "available_at_partial",
        "runner_causality_not_verified",
    ]
    assert data_manifest["data_availability_status"] == "partial"
    assert data_manifest["availability_coverage"]["fraction"] == pytest.approx(2 / 3)
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py -q
```

Expected: FAIL because `SUMMARY_KEYS` includes fields that `_summary_payload`
does not write yet, and `data_manifest.json` lacks the evidence-quality keys.

- [ ] **Step 4: Add evidence-quality helper**

In `src/quant_strategies/runner/artifacts.py`, add this helper above
`write_data_manifest`:

```python
def evidence_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    present = sum(1 for row in rows if row.get("available_at") is not None)
    fraction = None if total == 0 else present / total
    if total > 0 and present == total:
        status = "complete"
        warnings = ["runner_causality_not_verified"]
    elif present > 0:
        status = "partial"
        warnings = ["available_at_partial", "runner_causality_not_verified"]
    else:
        status = "missing"
        warnings = ["available_at_missing", "runner_causality_not_verified"]
    return {
        "data_availability_status": status,
        "availability_coverage": {
            "field": "available_at",
            "present": present,
            "total": total,
            "fraction": fraction,
        },
        "causality_verified": False,
        "evidence_quality_warnings": warnings,
    }
```

- [ ] **Step 5: Write evidence quality into data_manifest.json**

In `write_data_manifest`, compute once and merge `quality` into the existing
payload. Keep every current key in the payload unchanged and add `**quality` as
the last entry:

```python
    quality = evidence_quality(rows)
```

The final line inside the existing payload dict should be:

```python
        **quality,
```

- [ ] **Step 6: Thread evidence quality into summary payloads**

In `src/quant_strategies/runner/__init__.py`, after rows load and before
`write_data_manifest`, compute:

```python
        evidence_quality = artifacts.evidence_quality(loaded.rows)
```

Pass it to the completed `_summary_payload` call:

```python
            evidence_quality=evidence_quality,
```

In `_failure_result`, pass empty-row quality:

```python
            evidence_quality=artifacts.evidence_quality([]),
```

Change `_summary_payload` signature:

```python
def _summary_payload(
    config: config_module.RunConfig,
    *,
    success: bool,
    status: str,
    stage: str,
    message: str,
    engine: dict[str, object],
    assessment_status: str,
    evidence_quality: dict[str, object],
) -> dict[str, object]:
```

Merge it into the returned dict:

```python
        **semantics,
        **evidence_quality,
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit runner evidence-quality fields**

```bash
git add src/quant_strategies/runner/artifacts.py src/quant_strategies/runner/__init__.py tests/test_runner_api_cli.py
git commit -m "feat: report runner evidence quality"
```

---

### Task 2: Add Structured Validation Failure Details

**Files:**
- Modify: `src/quant_strategies/validation/__init__.py`
- Modify: `tests/test_validation_runner.py`

- [ ] **Step 1: Assert success artifacts carry empty failure details**

In the existing happy-path validation artifact tests, assert normal artifacts
carry an empty failure-details list:

```python
    assert decision_payload["failure_details"] == []
    assert robustness_matrix["failure_details"] == []
```

- [ ] **Step 2: Add strategy import failure test**

In `tests/test_validation_runner.py`, add:

```python
def test_run_validation_records_strategy_import_failure_details(tmp_path: Path):
    candidate = write_candidate(tmp_path)
    (candidate / "validation.toml").write_text(
        (candidate / "validation.toml")
        .read_text()
        .replace('strategy_path = "strategy.py"', 'strategy_path = "missing.py"')
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=RecordingBackend())

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("strategy_import_failed",)
    assert result.result_dir is not None
    decision_payload = json.loads((result.result_dir / "validation_decision.json").read_text())
    assert decision_payload["failure_details"][0]["stage"] == "strategy_import"
    assert decision_payload["failure_details"][0]["type"] == "ValidationStrategyLoadError"
    assert "missing.py" in decision_payload["failure_details"][0]["message"]
    robustness_matrix = json.loads((result.result_dir / "robustness_matrix.json").read_text())
    assert robustness_matrix["failure_details"] == decision_payload["failure_details"]
```

- [ ] **Step 3: Add param validation failure-detail assertions**

In existing `test_run_validation_rejects_unknown_params_with_strategy_validator`,
add:

```python
    assert decision_payload["failure_details"][0]["stage"] == "param_validation"
    assert decision_payload["failure_details"][0]["type"] == "ValueError"
    assert "unknown params" in decision_payload["failure_details"][0]["message"]
```

- [ ] **Step 4: Add backend selection failure test**

Add:

```python
def test_run_validation_records_backend_selection_failure_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path)

    def fail_backend_selection(name: str):
        raise RuntimeError("backend registry down")

    monkeypatch.setattr("quant_strategies.validation.get_backend", fail_backend_selection)

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path)

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("backend_selection_failed",)
    assert result.result_dir is not None
    decision_payload = json.loads((result.result_dir / "validation_decision.json").read_text())
    assert decision_payload["failure_details"] == [
        {
            "stage": "backend_selection",
            "type": "RuntimeError",
            "message": "backend registry down",
        }
    ]
```

- [ ] **Step 5: Run tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_runner.py -q
```

Expected: FAIL because `failure_details` is not included in validation artifacts.

- [ ] **Step 6: Add failure-detail helper**

In `src/quant_strategies/validation/__init__.py`, add near `_hard_no_decision`:

```python
def _failure_detail(stage: str, exc: Exception) -> dict[str, str]:
    return {
        "stage": stage,
        "type": type(exc).__name__,
        "message": str(exc),
    }
```

- [ ] **Step 7: Thread failure_details through artifact writing**

Change `_failure_result` signature:

```python
    failure_details: list[dict[str, str]] | None = None,
```

Pass it to `_write_validation_artifacts`:

```python
        failure_details=failure_details or [],
```

Change `_write_validation_artifacts` signature:

```python
    failure_details: list[dict[str, str]] | None = None,
) -> None:
    failure_details = failure_details or []
```

When writing `robustness_matrix.json`, add a top-level field:

```python
            "failure_details": failure_details,
```

When writing `validation_decision.json`, replace:

```python
    write_json_artifact(
        result_dir,
        "validation_decision.json",
        decision.model_dump(mode="json"),
    )
```

with:

```python
    decision_payload = decision.model_dump(mode="json")
    decision_payload["failure_details"] = failure_details
    write_json_artifact(result_dir, "validation_decision.json", decision_payload)
```

Update the normal completed call in `run_validation`:

```python
        failure_details=[],
```

- [ ] **Step 8: Add early exception details**

In the `except Exception as exc` branch around `get_backend`, call:

```python
            failure_details=[_failure_detail("backend_selection", exc)],
```

In the `except Exception as exc` branch around `load_decision_strategy`, call:

```python
            failure_details=[_failure_detail("strategy_import", exc)],
```

In the `except Exception as exc` branch around `validate_strategy_params`, call:

```python
            failure_details=[_failure_detail("param_validation", exc)],
```

- [ ] **Step 9: Run focused tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_runner.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit validation failure details**

```bash
git add src/quant_strategies/validation/__init__.py tests/test_validation_runner.py
git commit -m "feat: record validation failure details"
```

---

### Task 3: Add Hidden-Lookahead Check Module

**Files:**
- Create: `src/quant_strategies/validation/lookahead.py`
- Create: `tests/test_validation_lookahead.py`

- [ ] **Step 1: Write lookahead unit tests**

Create `tests/test_validation_lookahead.py`:

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from quant_strategies.decisions import (
    ExitPolicy,
    InstrumentRef,
    PositionTarget,
    StrategyDecision,
)
from quant_strategies.validation.lookahead import check_hidden_lookahead


AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
FUTURE = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)


def row(timestamp: datetime, close: float, *, available_at: datetime | None = None) -> dict[str, object]:
    payload = {
        "symbol": "BTC-PERP",
        "timestamp": timestamp,
        "close": close,
    }
    if available_at is not None:
        payload["available_at"] = available_at
    return payload


def decision(size: float = 1.0) -> StrategyDecision:
    return StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
        decision_time=DECISION,
        as_of_time=AS_OF,
        target=PositionTarget(direction="long", sizing_kind="target_weight", size=size),
        exit_policy=ExitPolicy(max_hold_bars=1),
    )


def as_of_strategy(rows: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
    visible = [item for item in rows if item.get("timestamp") == AS_OF]
    if not visible:
        return []
    return [decision(float(visible[-1]["close"]) / 100.0)]


def future_sensitive_strategy(rows: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
    future_rows = [item for item in rows if item.get("timestamp") == FUTURE]
    size = 2.0 if future_rows else 1.0
    return [decision(size)]


def replay_raising_strategy(rows: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
    if all(item.get("timestamp") != FUTURE for item in rows):
        raise RuntimeError("replay cannot run")
    return [decision()]


def test_hidden_lookahead_check_passes_as_of_only_strategy():
    rows = [row(AS_OF, 100.0, available_at=AS_OF), row(FUTURE, 999.0, available_at=FUTURE)]
    baseline = as_of_strategy(rows, {})

    result = check_hidden_lookahead(
        as_of_strategy,
        rows=rows,
        params={},
        baseline_decisions=baseline,
        strategy_id="demo",
    )

    assert result.passed is True
    assert result.violations == ()


def test_hidden_lookahead_check_detects_future_sensitive_strategy():
    rows = [row(AS_OF, 100.0, available_at=AS_OF), row(FUTURE, 999.0, available_at=FUTURE)]
    baseline = future_sensitive_strategy(rows, {})

    result = check_hidden_lookahead(
        future_sensitive_strategy,
        rows=rows,
        params={},
        baseline_decisions=baseline,
        strategy_id="demo",
    )

    assert result.passed is False
    assert result.violations == ("hidden_lookahead_detected",)


def test_hidden_lookahead_check_reports_replay_exceptions():
    rows = [row(AS_OF, 100.0, available_at=AS_OF), row(FUTURE, 999.0, available_at=FUTURE)]
    baseline = replay_raising_strategy(rows, {})

    result = check_hidden_lookahead(
        replay_raising_strategy,
        rows=rows,
        params={},
        baseline_decisions=baseline,
        strategy_id="demo",
    )

    assert result.passed is False
    assert result.violations == ("hidden_lookahead_check_failed: RuntimeError: replay cannot run",)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_lookahead.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `quant_strategies.validation.lookahead`.

- [ ] **Step 3: Implement lookahead module**

Create `src/quant_strategies/validation/lookahead.py`:

```python
from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from quant_strategies.boundary import frozen_params, frozen_rows
from quant_strategies.decisions import StrategyDecision, validate_decision_output
from quant_strategies.validation.datetime_utils import parse_aware_datetime


@dataclass(frozen=True)
class LookaheadCheckResult:
    passed: bool
    violations: tuple[str, ...] = ()


DecisionGenerator = Callable[
    [Sequence[Mapping[str, Any]], Mapping[str, Any]],
    object,
]


def check_hidden_lookahead(
    generate_decisions: DecisionGenerator,
    *,
    rows: Sequence[Mapping[str, Any]],
    params: Mapping[str, Any],
    baseline_decisions: list[StrategyDecision],
    strategy_id: str,
) -> LookaheadCheckResult:
    for baseline in baseline_decisions:
        replay_rows = [
            row
            for row in rows
            if _row_visible_for_decision(row, baseline)
        ]
        try:
            replay_output = generate_decisions(frozen_rows(replay_rows), frozen_params(params))
        except Exception as exc:
            return LookaheadCheckResult(
                passed=False,
                violations=(f"hidden_lookahead_check_failed: {type(exc).__name__}: {exc}",),
            )
        replay_decisions, violations = validate_decision_output(
            replay_output,
            strategy_id=strategy_id,
        )
        if violations:
            return LookaheadCheckResult(
                passed=False,
                violations=(f"hidden_lookahead_check_failed: {'; '.join(violations)}",),
            )
        replay_by_key: dict[str, StrategyDecision] = {}
        for replay in replay_decisions:
            key = _decision_key(replay)
            if key in replay_by_key:
                return LookaheadCheckResult(
                    passed=False,
                    violations=("hidden_lookahead_check_failed: duplicate replay decision key",),
                )
            replay_by_key[key] = replay
        replay = replay_by_key.get(_decision_key(baseline))
        if replay is None or _decision_fingerprint(replay) != _decision_fingerprint(baseline):
            return LookaheadCheckResult(
                passed=False,
                violations=("hidden_lookahead_detected",),
            )
    return LookaheadCheckResult(passed=True)


def _row_visible_for_decision(row: Mapping[str, Any], decision: StrategyDecision) -> bool:
    available_value = row.get("available_at")
    if available_value is not None:
        available_at, _ = parse_aware_datetime(available_value)
        if available_at is not None:
            return available_at <= decision.decision_time
    timestamp, _ = parse_aware_datetime(row.get("timestamp"))
    if timestamp is None:
        return False
    return timestamp <= decision.as_of_time


def _decision_key(decision: StrategyDecision) -> str:
    return json.dumps(
        {
            "strategy_id": decision.strategy_id,
            "instrument": decision.instrument.model_dump(mode="json"),
            "decision_time": decision.decision_time.isoformat(),
            "as_of_time": decision.as_of_time.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _decision_fingerprint(decision: StrategyDecision) -> str:
    return json.dumps(
        decision.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
```

- [ ] **Step 4: Run lookahead tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_lookahead.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit lookahead module**

```bash
git add src/quant_strategies/validation/lookahead.py tests/test_validation_lookahead.py
git commit -m "feat: add validation lookahead replay check"
```

---

### Task 4: Wire Hidden-Lookahead Into Validation

**Files:**
- Modify: `src/quant_strategies/validation/__init__.py`
- Modify: `tests/test_validation_runner.py`
- Verify unchanged: `tests/test_validation_future_poison.py`

- [ ] **Step 1: Add validation runner integration test**

In `tests/test_validation_runner.py`, add a strategy rewrite test near the other
validation failure tests:

```python
def test_run_validation_blocks_hidden_lookahead_strategy(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    future_rows = [row for row in rows if row['timestamp'] > rows[0]['timestamp']]\n"
        "    size = 2.0 if len(future_rows) > 1 else 1.0\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='short', sizing_kind='target_weight', size=size),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("hidden_lookahead_detected",)
    assert backend.calls == 0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["passed"] is False
    assert audit["windows"][0]["violations"] == ["hidden_lookahead_detected"]
```

- [ ] **Step 2: Add replay exception integration test**

Add:

```python
def test_run_validation_records_hidden_lookahead_replay_failure(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    if len(rows) < 3:\n"
        "        raise RuntimeError('need future row')\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='short', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("hidden_lookahead_check_failed",)
    assert backend.calls == 0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["violations"] == [
        "hidden_lookahead_check_failed: RuntimeError: need future row"
    ]
```

- [ ] **Step 3: Run validation runner tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_runner.py -q
```

Expected: FAIL because validation does not call the lookahead module yet.

- [ ] **Step 4: Wire lookahead into run_validation**

In `src/quant_strategies/validation/__init__.py`, import:

```python
from quant_strategies.validation.lookahead import check_hidden_lookahead
```

After `audit_payload = {"window_id": window.id, **audit.model_dump(mode="json")}`,
and before readiness checks, add:

```python
        if audit_payload["passed"]:
            lookahead = check_hidden_lookahead(
                generate_decisions,
                rows=loaded.rows,
                params=base_params,
                baseline_decisions=decisions,
                strategy_id=config.strategy_id,
            )
            if not lookahead.passed:
                reason = (
                    "hidden_lookahead_check_failed"
                    if any(item.startswith("hidden_lookahead_check_failed") for item in lookahead.violations)
                    else "hidden_lookahead_detected"
                )
                failure_reasons.append(reason)
                audit_payload["passed"] = False
                audit_payload["violations"] = list(audit.violations) + list(lookahead.violations)
```

Keep the existing readiness block below this. It should still run only when
`audit_payload["passed"]` is true.

- [ ] **Step 5: Run old future-poison tests unchanged**

Run:

```bash
conda run -n quant pytest tests/test_validation_future_poison.py -q
```

Expected: PASS without editing `tests/test_validation_future_poison.py`.

- [ ] **Step 6: Run validation focused tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_lookahead.py tests/test_validation_runner.py tests/test_validation_future_poison.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit validation integration**

```bash
git add src/quant_strategies/validation/__init__.py tests/test_validation_runner.py
git commit -m "feat: enforce validation lookahead replay"
```

---

### Task 5: Update Docs And Final Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README artifact language**

In `README.md`, update the runner artifact paragraph to mention evidence
quality:

```markdown
Runner summaries and data manifests include evidence-quality fields:
`data_availability_status`, `availability_coverage`, `causality_verified`, and
`evidence_quality_warnings`. Runner smoke keeps missing availability non-fatal
for search, but it records that uncertainty and never claims hidden-lookahead
causality verification.
```

In the validation section, add:

```markdown
Validation also runs a hidden-lookahead replay check before backend scenarios.
The check compares baseline decisions against decisions generated from rows
available within each decision's information set. A mismatch becomes
`hidden_lookahead_detected`; replay errors become
`hidden_lookahead_check_failed`.
```

- [ ] **Step 2: Run README contract test**

Run the existing README contract test without changing it:

```bash
conda run -n quant pytest tests/test_readme_contract.py -q
```

Expected: PASS.

- [ ] **Step 3: Run combined focused verification**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py tests/test_validation_lookahead.py tests/test_validation_runner.py tests/test_validation_future_poison.py tests/test_readme_contract.py -q
```

Expected: PASS.

- [ ] **Step 4: Run full suite**

Run:

```bash
conda run -n quant pytest -q
```

Expected: PASS.

- [ ] **Step 5: Run diff hygiene**

Run:

```bash
git diff --check
rg -n "check_research_manifest|research_manifest_integrity|researched/demo|path/to/researched/package|package_or_config" src tests README.md docs/quant-autoresearch-consumer.md
```

Expected:
- `git diff --check` has no output.
- `rg` has no output.

- [ ] **Step 6: Commit docs and final test updates**

```bash
git add README.md
git commit -m "docs: explain evidence honesty fields"
```

- [ ] **Step 7: Request code review**

Use `superpowers:requesting-code-review` against the implementation branch.

Review scope:
- runner evidence quality fields,
- validation hidden-lookahead replay,
- validation failure details,
- README evidence-honesty updates.

Critical review question:

```text
Does this implementation keep the bundle small and avoid reintroducing researched-package compatibility or market-validation claims?
```

---

## Self-Review Checklist

- [ ] Hidden-lookahead replay is validation-only and does not change runner search behavior.
- [ ] Runner missing `available_at` remains non-fatal.
- [ ] Validation policy reason strings remain stable.
- [ ] No `researched/` validation ontology is reintroduced.
- [ ] Evidence-quality fields are present in both `summary.json` and `data_manifest.json`.
- [ ] Full suite passes with `conda run -n quant pytest -q`.

## Plan-Eng Review Summary

- Step 0 Scope Challenge: scope accepted after keeping implementation to eight files and explicitly dropping the extra README contract-test edit.
- Architecture Review: 1 issue found and fixed in the plan: backend-selection failure must be tested by monkeypatching `get_backend`, not by invalid TOML.
- Code Quality Review: 1 issue found and fixed in the plan: runner coverage wording now distinguishes missing, partial, complete, and empty-row coverage.
- Test Review: diagram produced; 2 gaps fixed in the plan: empty-row runner quality assertions and replay-exception integration using `len(rows) < 3`.
- Performance Review: 0 issues. Replay is O(decisions * rows) and validation-only; acceptable for this advisory gate.
- TODOS.md updates: no repo `TODOS.md` exists and no deferred TODO is needed for this v1.
- Failure modes: 0 critical gaps after plan updates.
- Outside voice: skipped; prior cross-model review already informed the design, and no new outside-voice finding is being incorporated here.
- Parallelization: 3 lanes; 2 can start in parallel, README waits until code semantics settle.
- Lake Score: 4/4 review recommendations chose the complete option within the v1 scope.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | - | not run |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | - | not run |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 4 plan issues fixed, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | - | not applicable |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | - | not run |

- **UNRESOLVED:** 0.
- **VERDICT:** ENG CLEARED - ready to implement.
