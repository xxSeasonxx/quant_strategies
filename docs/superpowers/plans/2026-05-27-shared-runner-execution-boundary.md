# Shared Runner Execution Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor runner and validation to share one internal strategy execution boundary while preserving runner and validation artifact behavior.

**Architecture:** Add `quant_strategies.runner.execution` as the only shared execution boundary. It loads strategy/data, validates params and decisions, converts decisions to signals, and returns a typed result; runner and validation keep ownership of artifacts, smoke engine, audit, lookahead, readiness, backend matrix, and policy.

**Tech Stack:** Python 3.12, dataclasses, Pydantic config models, pytest, existing `quant_data` loader APIs.

---

## File Structure

- Create `src/quant_strategies/runner/execution.py`
  - Owns `StrategyExecutionResult`, `StrategyExecutionError`, and `execute_strategy_run`.
  - Depends on runner config/data/strategy loader, decision validation, signal adapter, row hash, and evidence quality.
  - Must not import validation modules or engine evaluation.

- Create `tests/test_runner_execution.py`
  - Focused tests for the new execution boundary success and failure stages.

- Modify `src/quant_strategies/runner/__init__.py`
  - Replace duplicated strategy/data/decision setup with `execute_strategy_run`.
  - Keep artifact writing, data readiness, engine request/evaluation, notes, manifest, and summary in runner.

- Modify `src/quant_strategies/validation/__init__.py`
  - Replace duplicated strategy/data/decision setup with `execute_strategy_run` per validation window.
  - Preserve validation-owned data audit, hidden-lookahead, readiness, scenario matrix, backend runs, and policy.

- Modify tests:
  - `tests/test_runner_api_cli.py`
  - `tests/test_validation_runner.py`
  - Keep other tests unchanged unless refactor requires import-path updates.

No docs behavior changes are required; this is an internal refactor. Do not edit README unless implementation changes user-facing behavior, which it should not.

---

### Task 1: Add The Internal Execution Boundary

**Files:**
- Create: `src/quant_strategies/runner/execution.py`
- Create: `tests/test_runner_execution.py`

- [ ] **Step 1: Write focused failing tests for the execution boundary**

Create `tests/test_runner_execution.py`:

```python
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from quant_strategies.decisions import (
    ExitPolicy,
    InstrumentRef,
    ObservationRef,
    PositionTarget,
    StrategyDecision,
)
from quant_strategies.runner.config import RunConfig
from quant_strategies.runner.data_loader import LoadedData
from quant_strategies.runner.errors import DataLoadError, StrategyLoadError
from quant_strategies.runner.execution import (
    StrategyExecutionError,
    execute_strategy_run,
)


AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_config(tmp_path: Path) -> RunConfig:
    (tmp_path / "strategy.py").write_text("def generate_decisions(rows, params): return []\n")
    return RunConfig.model_validate(
        {
            "strategy_path": "strategy.py",
            "strategy_id": "demo",
            "data": {
                "kind": "bars",
                "dataset": "equity_1min",
                "symbols": ["SPY"],
                "start": date(2026, 1, 1),
                "end": date(2026, 1, 2),
                "strict": True,
            },
            "params": {"weight": "0.5"},
            "fill_model": {
                "price": "close",
                "entry_lag_bars": 1,
                "exit_lag_bars": 0,
            },
            "cost_model": {
                "fee_bps_per_side": 0.0,
                "slippage_bps_per_side": 0.0,
            },
            "output": {
                "results_dir": "results",
                "mode": "validate",
            },
        },
        context={"repo_root": tmp_path},
    )


def rows() -> list[dict[str, object]]:
    return [
        {
            "symbol": "SPY",
            "timestamp": AS_OF,
            "available_at": AS_OF,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
        },
        {
            "symbol": "SPY",
            "timestamp": datetime(2026, 1, 2, tzinfo=timezone.utc),
            "available_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
            "open": 101.0,
            "high": 102.0,
            "low": 100.0,
            "close": 101.0,
        },
    ]


def decision(weight: float = 0.5) -> StrategyDecision:
    return StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="equity_or_etf", symbol="SPY"),
        decision_time=AS_OF,
        as_of_time=AS_OF,
        target=PositionTarget(
            direction="long",
            sizing_kind="target_weight",
            size=weight,
        ),
        exit_policy=ExitPolicy(max_hold_bars=1),
        observations=(
            ObservationRef(
                symbol="SPY",
                timestamp=AS_OF,
                field="close",
                source="strategy_input",
            ),
        ),
    )


def valid_generate_decisions(loaded_rows, params):
    return [decision(float(params["weight"]))]


def validate_params(params):
    return {"weight": float(params["weight"])}


valid_generate_decisions.validate_params = validate_params


def test_execute_strategy_run_returns_validated_decisions_and_signals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = make_config(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.runner.execution.strategy_loader.load_strategy",
        lambda path, repo_root: valid_generate_decisions,
    )
    monkeypatch.setattr(
        "quant_strategies.runner.execution.data_loader.load_data",
        lambda config: LoadedData(rows=rows()),
    )

    result = execute_strategy_run(config, repo_root=tmp_path)

    assert result.generate_decisions is valid_generate_decisions
    assert result.validated_params == {"weight": 0.5}
    assert result.loaded_rows == rows()
    assert len(result.decisions) == 1
    assert result.decisions[0].target.size == 0.5
    assert result.signals[0]["symbol"] == "SPY"
    assert result.signals[0]["weight"] == 0.5
    assert len(result.normalized_rows_sha256) == 64
    assert result.evidence_quality["data_availability_status"] == "complete"


def test_execute_strategy_run_reports_strategy_import_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = make_config(tmp_path)

    def fail_load_strategy(path, repo_root):
        raise StrategyLoadError("missing strategy")

    monkeypatch.setattr(
        "quant_strategies.runner.execution.strategy_loader.load_strategy",
        fail_load_strategy,
    )

    with pytest.raises(StrategyExecutionError) as exc_info:
        execute_strategy_run(config, repo_root=tmp_path)

    assert exc_info.value.stage == "strategy_import"
    assert str(exc_info.value) == "missing strategy"
    assert exc_info.value.loaded_rows is None
    assert exc_info.value.violations == ()


def test_execute_strategy_run_reports_param_validation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = make_config(tmp_path)

    def generate_decisions(loaded_rows, params):
        return [decision()]

    def fail_validate_params(params):
        raise ValueError("bad weight")

    generate_decisions.validate_params = fail_validate_params
    monkeypatch.setattr(
        "quant_strategies.runner.execution.strategy_loader.load_strategy",
        lambda path, repo_root: generate_decisions,
    )

    with pytest.raises(StrategyExecutionError) as exc_info:
        execute_strategy_run(config, repo_root=tmp_path)

    assert exc_info.value.stage == "param_validation"
    assert str(exc_info.value) == "param validation failed: bad weight"


def test_execute_strategy_run_reports_data_load_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = make_config(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.runner.execution.strategy_loader.load_strategy",
        lambda path, repo_root: valid_generate_decisions,
    )

    def fail_load_data(config):
        raise DataLoadError("data load returned no rows")

    monkeypatch.setattr(
        "quant_strategies.runner.execution.data_loader.load_data",
        fail_load_data,
    )

    with pytest.raises(StrategyExecutionError) as exc_info:
        execute_strategy_run(config, repo_root=tmp_path)

    assert exc_info.value.stage == "data_load"
    assert str(exc_info.value) == "data load returned no rows"
    assert exc_info.value.loaded_rows is None


def test_execute_strategy_run_reports_invalid_decision_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = make_config(tmp_path)

    def invalid_generate_decisions(loaded_rows, params):
        return "not decisions"

    monkeypatch.setattr(
        "quant_strategies.runner.execution.strategy_loader.load_strategy",
        lambda path, repo_root: invalid_generate_decisions,
    )
    monkeypatch.setattr(
        "quant_strategies.runner.execution.data_loader.load_data",
        lambda config: LoadedData(rows=rows()),
    )

    with pytest.raises(StrategyExecutionError) as exc_info:
        execute_strategy_run(config, repo_root=tmp_path)

    assert exc_info.value.stage == "decision_generation"
    assert str(exc_info.value) == "invalid_decision_output"
    assert exc_info.value.loaded_rows == rows()
    assert exc_info.value.decision_count == 0
    assert exc_info.value.violations == ("invalid_decision_output",)
    assert exc_info.value.evidence_quality["data_availability_status"] == "complete"
```

- [ ] **Step 2: Run execution tests to verify they fail**

Run:

```bash
conda run -n quant pytest tests/test_runner_execution.py -q
```

Expected: FAIL because `quant_strategies.runner.execution` does not exist.

- [ ] **Step 3: Implement `runner.execution`**

Create `src/quant_strategies/runner/execution.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quant_strategies.boundary import frozen_params, frozen_rows
from quant_strategies.decisions import (
    DecisionStrategyCallable,
    StrategyDecision,
    validate_decision_output,
    validate_strategy_params,
)
from quant_strategies.runner import artifacts, data_loader, strategy_loader
from quant_strategies.runner.artifact_profiles import normalized_rows_sha256
from quant_strategies.runner.config import RunConfig
from quant_strategies.runner.decision_adapter import decisions_to_signal_rows
from quant_strategies.runner.errors import RunnerError


ExecutionStage = Literal[
    "strategy_import",
    "param_validation",
    "data_load",
    "decision_generation",
]


@dataclass(frozen=True)
class StrategyExecutionResult:
    generate_decisions: DecisionStrategyCallable
    validated_params: dict[str, Any]
    loaded_rows: list[dict[str, Any]]
    decisions: list[StrategyDecision]
    signals: list[dict[str, Any]]
    normalized_rows_sha256: str
    evidence_quality: dict[str, Any]


class StrategyExecutionError(RunnerError):
    def __init__(
        self,
        stage: ExecutionStage,
        message: str,
        *,
        loaded_rows: list[dict[str, Any]] | None = None,
        evidence_quality: dict[str, Any] | None = None,
        violations: tuple[str, ...] = (),
        decision_count: int = 0,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.loaded_rows = loaded_rows
        self.evidence_quality = evidence_quality
        self.violations = violations
        self.decision_count = decision_count


def execute_strategy_run(
    config: RunConfig,
    *,
    repo_root: Path,
) -> StrategyExecutionResult:
    try:
        generate_decisions = strategy_loader.load_strategy(
            config.strategy_path,
            repo_root=repo_root,
        )
    except RunnerError as exc:
        raise StrategyExecutionError("strategy_import", str(exc)) from exc

    try:
        validated_params = validate_strategy_params(generate_decisions, config.params)
    except Exception as exc:
        raise StrategyExecutionError(
            "param_validation",
            f"param validation failed: {exc}",
        ) from exc

    try:
        loaded = data_loader.load_data(config)
    except RunnerError as exc:
        raise StrategyExecutionError("data_load", str(exc)) from exc

    rows = loaded.rows
    row_hash = normalized_rows_sha256(rows)
    evidence_quality = artifacts.evidence_quality(config, rows)

    try:
        decision_output = generate_decisions(
            frozen_rows(rows),
            frozen_params(validated_params),
        )
        decisions, violations = validate_decision_output(
            decision_output,
            strategy_id=config.strategy_id,
        )
        if violations:
            raise StrategyExecutionError(
                "decision_generation",
                "; ".join(violations),
                loaded_rows=rows,
                evidence_quality=evidence_quality,
                violations=tuple(violations),
                decision_count=len(decisions),
            )
        signals = decisions_to_signal_rows(decisions)
    except StrategyExecutionError:
        raise
    except Exception as exc:
        raise StrategyExecutionError(
            "decision_generation",
            f"strategy execution failed: {exc}",
            loaded_rows=rows,
            evidence_quality=evidence_quality,
        ) from exc

    return StrategyExecutionResult(
        generate_decisions=generate_decisions,
        validated_params=validated_params,
        loaded_rows=rows,
        decisions=decisions,
        signals=signals,
        normalized_rows_sha256=row_hash,
        evidence_quality=evidence_quality,
    )


__all__ = [
    "ExecutionStage",
    "StrategyExecutionError",
    "StrategyExecutionResult",
    "execute_strategy_run",
]
```

- [ ] **Step 4: Run execution tests to verify they pass**

Run:

```bash
conda run -n quant pytest tests/test_runner_execution.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add src/quant_strategies/runner/execution.py tests/test_runner_execution.py
git commit -m "refactor: add shared strategy execution boundary"
```

---

### Task 2: Refactor Runner To Use The Execution Boundary

**Files:**
- Modify: `src/quant_strategies/runner/__init__.py`
- Test: `tests/test_runner_api_cli.py`
- Test: `tests/test_runner_execution.py`

- [ ] **Step 1: Confirm existing runner artifact tests cover the behavior**

Open `tests/test_runner_api_cli.py` and confirm `test_run_config_writes_success_artifacts` already asserts these stable artifact fields:

```python
    assert len(data_manifest["normalized_rows_sha256"]) == 64
    assert data_manifest["row_contract"]["status"] == "passed"
    assert data_manifest["row_contract"] == summary["row_contract"]
```

If one of these assertions is missing, add it to `test_run_config_writes_success_artifacts`.

- [ ] **Step 2: Run the runner artifact test as a baseline**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_writes_success_artifacts -q
```

Expected: PASS before the refactor. This is a characterization check; the same test must still pass after the refactor.

- [ ] **Step 3: Refactor runner imports**

In `src/quant_strategies/runner/__init__.py`, remove now-unused imports:

```python
from quant_strategies.boundary import frozen_params, frozen_rows
from quant_strategies.decisions import (
    StrategyDecision,
    validate_decision_output,
    validate_strategy_params,
)
from quant_strategies.runner import (
    artifacts,
    config as config_module,
    data_loader,
    data_readiness,
    engine_runner,
    strategy_loader,
)
from quant_strategies.runner.artifact_profiles import normalized_rows_sha256, write_summary_profile_artifact
```

Replace them with:

```python
from quant_strategies.runner import (
    artifacts,
    config as config_module,
    data_readiness,
    engine_runner,
)
from quant_strategies.runner.artifact_profiles import write_summary_profile_artifact
from quant_strategies.runner.execution import (
    StrategyExecutionError,
    execute_strategy_run,
)
```

- [ ] **Step 4: Replace the duplicated execution block in `run_config`**

In `run_config`, replace the strategy load, param validation, data load, decision generation, and signal conversion blocks with:

```python
    try:
        execution = execute_strategy_run(config, repo_root=effective_repo_root)
    except StrategyExecutionError as exc:
        return _failure_result(
            config,
            result_dir,
            exc.stage,
            str(exc),
            repo_root=effective_repo_root,
            evidence_quality=exc.evidence_quality,
        )

    strategy_input_rows_jsonl_sha256 = None
    if config.output.artifact_profile == "full":
        strategy_input_rows_jsonl_sha256 = artifacts.write_strategy_input_rows(
            result_dir,
            execution.loaded_rows,
        )
    artifacts.write_data_manifest(
        result_dir,
        config,
        execution.loaded_rows,
        strategy_input_rows_jsonl_sha256=strategy_input_rows_jsonl_sha256,
        normalized_rows_hash=execution.normalized_rows_sha256,
    )
    if config.output.artifact_profile == "full":
        artifacts.write_decision_records(result_dir, execution.decisions)
        artifacts.write_signals(result_dir, execution.signals)
```

- [ ] **Step 5: Replace downstream runner local variables**

In the rest of `run_config`, replace:

```python
loaded.rows
decisions
signals
normalized_rows_hash
evidence_quality
```

with:

```python
execution.loaded_rows
execution.decisions
execution.signals
execution.normalized_rows_sha256
execution.evidence_quality
```

Specific calls should look like:

```python
data_readiness.assert_decision_rows_ready(execution.loaded_rows, execution.signals)
```

```python
request = engine_runner.build_request(
    strategy_id=config.strategy_id,
    rows=execution.loaded_rows,
    signals=execution.signals,
    fill_model=config.fill_model,
    cost_model=config.cost_model,
)
```

```python
write_summary_profile_artifact(
    result_dir,
    config=config,
    rows=execution.loaded_rows,
    decisions=execution.decisions,
    signals=execution.signals,
    engine=engine_summary,
    normalized_rows_hash=execution.normalized_rows_sha256,
)
```

```python
artifacts.write_summary(
    result_dir,
    _summary_payload(
        config,
        success=success,
        status=_result_status(engine_run),
        stage="completed",
        message=notes.strip(),
        engine=engine_summary,
        assessment_status=assessment_status,
        evidence_quality=execution.evidence_quality,
    ),
)
```

- [ ] **Step 6: Delete `_validated_decisions` from runner**

Remove this function from `src/quant_strategies/runner/__init__.py`:

```python
def _validated_decisions(output: object, *, strategy_id: str) -> list[StrategyDecision]:
    decisions, violations = validate_decision_output(output, strategy_id=strategy_id)
    if violations:
        raise ValueError("; ".join(violations))
    return decisions
```

- [ ] **Step 7: Run focused runner tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_execution.py tests/test_runner_api_cli.py tests/test_runner_artifact_profiles.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 2**

Run:

```bash
git add src/quant_strategies/runner/__init__.py tests/test_runner_api_cli.py
git commit -m "refactor: route runner through execution boundary"
```

---

### Task 3: Refactor Validation To Use The Execution Boundary

**Files:**
- Modify: `src/quant_strategies/validation/__init__.py`
- Test: `tests/test_validation_runner.py`

- [ ] **Step 1: Add focused validation regression tests**

In `tests/test_validation_runner.py`, keep existing tests and add this test near the existing data-load failure test:

```python
def test_run_validation_preserves_invalid_decision_output_audit(
    tmp_path: Path,
    monkeypatch,
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.runner.execution.data_loader.load_data",
        lambda config: LoadedData(rows=rows()),
    )
    monkeypatch.setattr(
        "quant_strategies.runner.execution.strategy_loader.load_strategy",
        lambda path, repo_root: lambda loaded_rows, params: "not decisions",
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=RecordingBackend())

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("data_audit_failed",)
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["passed"] is False
    assert audit["windows"][0]["violations"] == ["invalid_decision_output"]
```

Also update existing validation monkeypatches that patch:

```python
"quant_strategies.runner.data_loader.load_data"
"quant_strategies.validation.load_decision_strategy"
```

to patch:

```python
"quant_strategies.runner.execution.data_loader.load_data"
"quant_strategies.runner.execution.strategy_loader.load_strategy"
```

Only update tests whose execution path now goes through `runner.execution`.

- [ ] **Step 2: Run focused validation tests to verify failure before refactor**

Run:

```bash
conda run -n quant pytest tests/test_validation_runner.py::test_run_validation_preserves_invalid_decision_output_audit -q
```

Expected: FAIL because validation has not been refactored to use `runner.execution` yet and the new monkeypatch path is not exercised.

- [ ] **Step 3: Refactor validation imports**

In `src/quant_strategies/validation/__init__.py`, remove:

```python
from quant_strategies.boundary import frozen_params, frozen_rows
from quant_strategies.decisions import (
    StrategyDecision,
    validate_decision_output,
    validate_strategy_params,
)
from quant_strategies.runner import data_loader
from quant_strategies.validation.strategy_loader import load_decision_strategy
```

Replace with:

```python
from quant_strategies.boundary import frozen_rows
from quant_strategies.decisions import StrategyDecision, validate_strategy_params
from quant_strategies.runner.execution import (
    StrategyExecutionError,
    StrategyExecutionResult,
    execute_strategy_run,
)
```

Keep `validate_strategy_params` because parameter scenarios still regenerate decisions with modified params.

- [ ] **Step 4: Remove setup-level strategy/param validation blocks**

Delete the setup blocks that call:

```python
generate_decisions = load_decision_strategy(...)
base_params = validate_strategy_params(...)
```

Validation will get `generate_decisions` and `validated_params` from each successful `StrategyExecutionResult`.

- [ ] **Step 5: Use `execute_strategy_run` per validation window**

Inside the `for window in config.windows:` loop, replace the current data-load and base decision-generation blocks with:

```python
        run_config = config.to_run_config(window, results_dir=result_dir / "runner_smoke" / window.id)
        try:
            execution = execute_strategy_run(run_config, repo_root=path_base)
        except StrategyExecutionError as exc:
            if exc.stage == "strategy_import":
                return _failure_result(
                    result_dir=result_dir,
                    repo_root=root,
                    path_base=path_base,
                    config=config,
                    config_path=resolved_config_path,
                    backend_name=backend_name,
                    decisions=all_decisions,
                    data_audits=data_audits,
                    data_provenance=data_provenance,
                    backend_results=backend_results,
                    reason="strategy_import_failed",
                    failure_details=[_failure_detail("strategy_import", exc)],
                )
            if exc.stage == "param_validation":
                data_audits.append(
                    _failed_data_audit(
                        "config",
                        row_count=0,
                        decision_count=0,
                        violations=(f"param_validation_failed: {exc}",),
                    )
                )
                return _failure_result(
                    result_dir=result_dir,
                    repo_root=root,
                    path_base=path_base,
                    config=config,
                    config_path=resolved_config_path,
                    backend_name=backend_name,
                    decisions=all_decisions,
                    data_audits=data_audits,
                    data_provenance=data_provenance,
                    backend_results=backend_results,
                    reason="param_validation_failed",
                    failure_details=[_failure_detail("param_validation", exc)],
                )
            if exc.stage == "data_load":
                data_provenance.append(
                    _data_provenance(
                        window.id,
                        run_config,
                        status="failed",
                        rows=None,
                        message=str(exc),
                    )
                )
                data_audits.append(
                    _failed_data_audit(
                        window.id,
                        row_count=0,
                        decision_count=0,
                        violations=(f"data_load_failed: {exc}",),
                    )
                )
                continue
            if exc.stage == "decision_generation":
                loaded_rows = exc.loaded_rows or []
                if exc.violations:
                    data_audits.append(
                        _failed_data_audit(
                            window.id,
                            row_count=len(loaded_rows),
                            decision_count=exc.decision_count,
                            violations=exc.violations,
                        )
                    )
                else:
                    failure_reasons.append("strategy_generation_failed")
                    data_audits.append(
                        _failed_data_audit(
                            window.id,
                            row_count=len(loaded_rows),
                            decision_count=0,
                            violations=(f"strategy_generation_failed: {exc}",),
                        )
                    )
                continue
```

Then immediately after the `try/except`, add:

```python
        data_provenance.append(
            _data_provenance(window.id, run_config, status="loaded", rows=execution.loaded_rows)
        )
        strategy_rows = frozen_rows(execution.loaded_rows)
        decisions = execution.decisions
        base_params = execution.validated_params
        generate_decisions = execution.generate_decisions
        all_decisions.extend(decisions)
```

- [ ] **Step 6: Keep validation-owned audit/lookahead/readiness code**

The code after base decision generation should still:

```python
audit = audit_decision_rows(strategy_rows, decisions)
lookahead = check_hidden_lookahead(...)
readiness_violations = check_validation_readiness(...)
```

Use these values:

```python
rows=execution.loaded_rows
params=base_params
baseline_decisions=decisions
generate_decisions=generate_decisions
```

- [ ] **Step 7: Update scenario execution to use execution result values**

In scenario matrix code, use:

```python
base_params=_plain_mapping(base_params)
```

and pass:

```python
rows=execution.loaded_rows
```

to `_scenario_decision_outcome`.

For backend calls, pass:

```python
rows=frozen_rows(execution.loaded_rows)
```

Keep `_scenario_config(..., data=run_config.data)` unchanged so scenario configs keep window-scoped dates.

- [ ] **Step 8: Run focused validation tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_runner.py tests/test_validation_future_poison.py tests/test_validation_lookahead.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit Task 3**

Run:

```bash
git add src/quant_strategies/validation/__init__.py tests/test_validation_runner.py
git commit -m "refactor: route validation through execution boundary"
```

---

### Task 4: Clean Imports And Verify No Boundary Leaks

**Files:**
- Modify only if needed: `src/quant_strategies/runner/__init__.py`
- Modify only if needed: `src/quant_strategies/validation/__init__.py`
- Modify only if needed: `tests/test_runner_execution.py`

- [ ] **Step 1: Search for duplicated execution imports**

Run:

```bash
rg -n "validate_decision_output|load_decision_strategy|load_strategy|data_loader.load_data|normalized_rows_sha256|decisions_to_signal_rows|frozen_params" src/quant_strategies/runner src/quant_strategies/validation
```

Expected:

- `runner/execution.py` may contain all shared execution dependencies.
- `runner/__init__.py` should not contain `validate_decision_output`, `load_strategy`, `data_loader.load_data`, `normalized_rows_sha256`, `decisions_to_signal_rows`, or `frozen_params`.
- `validation/__init__.py` may still contain `validate_strategy_params` and `frozen_rows` for parameter scenario regeneration and backend row freezing.
- `validation/__init__.py` should not contain direct base-window `data_loader.load_data`, `load_decision_strategy`, or `validate_decision_output`.

- [ ] **Step 2: Remove any stale imports found by the search**

If stale imports remain, delete only the unused imports. Do not refactor unrelated code.

- [ ] **Step 3: Confirm no active researched layout behavior returned**

Run:

```bash
rg -n "research_manifest|check_research_manifest|researched/.*validation|package_or_config" src tests README.md docs/quant-autoresearch-consumer.md docs/reviews/foundation-review-20260527.md
```

Expected: only historical review/status mentions are allowed. No active source or tests should import or call research manifest validation.

- [ ] **Step 4: Run focused boundary tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_execution.py tests/test_runner_api_cli.py tests/test_validation_runner.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4 if cleanup changed files**

If Step 2 changed files, run:

```bash
git add src/quant_strategies/runner/__init__.py src/quant_strategies/validation/__init__.py tests/test_runner_execution.py
git commit -m "chore: clean execution boundary imports"
```

If no files changed, do not create an empty commit.

---

### Task 5: Full Verification And Review

**Files:**
- No planned source changes.

- [ ] **Step 1: Run full test suite**

Run:

```bash
conda run -n quant pytest -q
```

Expected: PASS.

- [ ] **Step 2: Run diff whitespace check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 3: Report changed-line counts**

Run:

```bash
git diff --stat HEAD~3..HEAD
git diff --numstat HEAD~3..HEAD
```

If the number of commits differs because Task 4 did not need a commit, adjust the range to cover only this implementation work.

- [ ] **Step 4: Request code review**

Use `superpowers:requesting-code-review` with:

```text
Description: Refactored runner and validation to share runner.execution strategy execution boundary.
Requirements: docs/superpowers/specs/2026-05-27-shared-runner-execution-boundary-design.md and this plan.
Base SHA: commit before Task 1.
Head SHA: current HEAD.
```

- [ ] **Step 5: Fix any Critical or Important review issues**

For each real review issue:

1. Write or update a focused failing test.
2. Make the smallest implementation fix.
3. Run the focused test.
4. Commit the fix.

Do not fix unrelated cleanup or style suggestions unless they affect correctness.

- [ ] **Step 6: Final full-suite verification**

Run:

```bash
conda run -n quant pytest -q
git diff --check
git status --short
```

Expected:

- tests pass,
- whitespace check is clean,
- only intentionally untracked old draft review files remain if they are still present.

---

## Self-Review

Spec coverage:

- Shared execution module: Task 1.
- Runner uses shared boundary and keeps artifacts/engine ownership: Task 2.
- Validation uses shared boundary and keeps audit/lookahead/readiness/backend/policy ownership: Task 3.
- No researched layout accommodation: Task 4.
- Focused and full tests: Tasks 1-5.
- Code review before merge: Task 5.

Placeholder scan:

- No placeholder markers remain.
- Every code-changing task includes exact file paths, code snippets, and commands.

Type consistency:

- `StrategyExecutionResult`, `StrategyExecutionError`, and `execute_strategy_run` are introduced in Task 1 and used by runner/validation in Tasks 2-3.
- `StrategyExecutionError.stage` values match the design spec.
- Validation-specific `failure_details`, audit payloads, and policy decisions remain validation-owned.
