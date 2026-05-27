# Evidence Honesty v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make runner and validation evidence harder to overread by adding validation-only hidden-lookahead checks, runner evidence-quality artifact fields, and structured validation failure details.

**Architecture:** Keep the bundle narrow. Add a small runner evidence-quality helper, a small validation lookahead module, and explicit failure-detail plumbing through existing validation artifact writing. Do not change strategy APIs, researched layout semantics, `paper_candidate` policy, VectorBT Pro setup, or scenario backend typing in this plan.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, existing `quant_strategies.runner` and `quant_strategies.validation` modules.

---

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

- [ ] **Step 2: Add assertions for complete coverage**

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
    assert summary["availability_coverage"] == {
        "field": "available_at",
        "present": 2,
        "total": 3,
        "fraction": pytest.approx(2 / 3),
    }
    assert summary["evidence_quality_warnings"] == [
        "available_at_partial",
        "runner_causality_not_verified",
    ]
    assert data_manifest["data_availability_status"] == "partial"
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

- [ ] **Step 1: Add strategy import failure test**

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

- [ ] **Step 2: Add backend selection failure test**

Add:

```python
def test_run_validation_records_backend_selection_failure_details(tmp_path: Path):
    candidate = write_candidate(tmp_path)
    (candidate / "validation.toml").write_text(
        (candidate / "validation.toml")
        .read_text()
        .replace('backend = "fake"', 'backend = "unknown"')
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path)

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("backend_selection_failed",)
    assert result.result_dir is not None
    decision_payload = json.loads((result.result_dir / "validation_decision.json").read_text())
    assert decision_payload["failure_details"] == [
        {
            "stage": "backend_selection",
            "type": "ValueError",
            "message": "unsupported validation backend: unknown",
        }
    ]
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_runner.py -q
```

Expected: FAIL because `failure_details` is not included in validation artifacts.

- [ ] **Step 4: Add failure-detail helper**

In `src/quant_strategies/validation/__init__.py`, add near `_hard_no_decision`:

```python
def _failure_detail(stage: str, exc: Exception) -> dict[str, str]:
    return {
        "stage": stage,
        "type": type(exc).__name__,
        "message": str(exc),
    }
```

- [ ] **Step 5: Thread failure_details through artifact writing**

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

- [ ] **Step 6: Add early exception details**

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

- [ ] **Step 7: Run focused tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_runner.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit validation failure details**

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
- Modify: `tests/test_validation_future_poison.py`

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
        "    if len(rows) < 2:\n"
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
git add src/quant_strategies/validation/__init__.py tests/test_validation_runner.py tests/test_validation_future_poison.py
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

- [ ] **Step 2: Update README contract assertions**

Add these explicit assertions to `tests/test_readme_contract.py`:

```python
    assert "data_availability_status" in text
    assert "causality_verified" in text
    assert "hidden-lookahead replay check" in text
```

Then run:

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
git add README.md tests/test_readme_contract.py
git commit -m "docs: explain evidence honesty fields"
```

- [ ] **Step 7: Request code review**

Use `superpowers:requesting-code-review` against the implementation branch.

Review scope:
- runner evidence quality fields,
- validation hidden-lookahead replay,
- validation failure details,
- README contract updates.

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
