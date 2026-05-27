# Single Validation Paper Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing researched-package validation workflow into one advisory validation ladder: `hard_no`, `mechanical_pass`, `watchlist`, and `paper_candidate`.

**Architecture:** Keep `quant-strategies validate` as the only retained-candidate validation command. Add optional `[paper_readiness]` config, classify existing validation scenario results through a layered policy, and enrich current artifacts instead of adding a new workflow. Preserve advisory-only semantics: all eligibility flags remain false.

**Tech Stack:** Python 3.12, Pydantic models, existing `quant_strategies.validation` package, pytest, VectorBT Pro optional backend.

---

## File Structure

- Modify `src/quant_strategies/validation/config.py`
  - Add `PaperReadinessConfig`.
  - Add `paper_readiness` to `ValidationConfig`.

- Modify `src/quant_strategies/validation/policy.py`
  - Replace `maybe` with `watchlist`.
  - Add `paper_candidate`.
  - Add gate output fields to `ValidationPolicyDecision`.
  - Extend `classify_validation(...)` with paper-readiness settings and scenario-aware classification.

- Modify `src/quant_strategies/validation/__init__.py`
  - Pass `config.paper_readiness` into `classify_validation(...)`.
  - Include richer decision output in `validation_report.md`.

- Modify `src/quant_strategies/runner/cli.py`
  - Return exit code `0` for completed advisory validation outcomes:
    `mechanical_pass`, `watchlist`, and `paper_candidate`.
  - Return exit code `1` for `hard_no` and validation errors.

- Modify `src/quant_strategies/validation/vectorbtpro_backend.py`
  - Add optional metric extraction for `max_drawdown`, `profit_factor`, and `win_rate` without making backend execution fail when those methods are unavailable.

- Modify `tests/test_validation_config.py`
  - Cover default and overridden `[paper_readiness]` config.

- Modify `tests/test_validation_backends_and_policy.py`
  - Update old `maybe` expectations to `watchlist`.
  - Add unit coverage for paper-candidate gates.

- Modify `tests/test_validation_runner.py`
  - Update one-window existing cases to expect `watchlist` where they have positive evidence but cannot be paper candidates.
  - Add two-window integration coverage for `paper_candidate`.
  - Assert artifacts include gate fields and false eligibility flags.

- Modify `tests/test_validation_cli.py`
  - Cover CLI exit codes for `mechanical_pass`, `watchlist`,
    `paper_candidate`, and `hard_no`.

- Modify `README.md`
  - Document the single validation ladder.
  - Keep runner `mode = "validate"` distinct from package validation.

---

### Task 1: Add Paper Readiness Config

**Files:**
- Modify: `src/quant_strategies/validation/config.py`
- Test: `tests/test_validation_config.py`

- [ ] **Step 1: Add failing tests for default and overridden paper readiness config**

Append these tests to `tests/test_validation_config.py`:

```python
def test_load_validation_config_uses_default_paper_readiness(tmp_path: Path):
    write_strategy(tmp_path / "researched" / "demo" / "strategy.py")
    write_config(tmp_path / "researched" / "demo" / "validation.toml")

    config = load_validation_config(tmp_path / "researched" / "demo", repo_root=tmp_path)

    assert config.paper_readiness.enabled is True
    assert config.paper_readiness.min_windows == 2
    assert config.paper_readiness.min_total_trades == 30
    assert config.paper_readiness.min_positive_window_fraction == 0.5
    assert config.paper_readiness.max_stressed_net_loss == -0.02
    assert config.paper_readiness.max_fill_lag_net_loss == -0.02


def test_load_validation_config_accepts_paper_readiness_overrides(tmp_path: Path):
    write_strategy(tmp_path / "researched" / "demo" / "strategy.py")
    config_path = tmp_path / "researched" / "demo" / "validation.toml"
    write_config(config_path)
    config_path.write_text(
        config_path.read_text()
        + """

[paper_readiness]
enabled = false
min_windows = 3
min_total_trades = 50
min_positive_window_fraction = 0.67
max_stressed_net_loss = -0.05
max_fill_lag_net_loss = -0.04
"""
    )

    config = load_validation_config(config_path, repo_root=tmp_path)

    assert config.paper_readiness.enabled is False
    assert config.paper_readiness.min_windows == 3
    assert config.paper_readiness.min_total_trades == 50
    assert config.paper_readiness.min_positive_window_fraction == 0.67
    assert config.paper_readiness.max_stressed_net_loss == -0.05
    assert config.paper_readiness.max_fill_lag_net_loss == -0.04


@pytest.mark.parametrize(
    ("paper_readiness_text", "message"),
    [
        (
            """
[paper_readiness]
min_windows = 0
""",
            "greater than or equal to 1",
        ),
        (
            """
[paper_readiness]
min_total_trades = 0
""",
            "greater than or equal to 1",
        ),
        (
            """
[paper_readiness]
min_positive_window_fraction = 1.5
""",
            "less than or equal to 1",
        ),
        (
            """
[paper_readiness]
max_stressed_net_loss = 0.01
""",
            "less than or equal to 0",
        ),
        (
            """
[paper_readiness]
max_fill_lag_net_loss = 0.01
""",
            "less than or equal to 0",
        ),
    ],
)
def test_load_validation_config_rejects_invalid_paper_readiness(
    tmp_path: Path,
    paper_readiness_text: str,
    message: str,
):
    write_strategy(tmp_path / "researched" / "demo" / "strategy.py")
    config_path = tmp_path / "researched" / "demo" / "validation.toml"
    write_config(config_path)
    config_path.write_text(config_path.read_text() + paper_readiness_text)

    with pytest.raises(ValidationConfigError, match=message):
        load_validation_config(config_path, repo_root=tmp_path)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_config.py -q
```

Expected: fail with an attribute error or config validation error mentioning `paper_readiness`.

- [ ] **Step 3: Implement `PaperReadinessConfig`**

In `src/quant_strategies/validation/config.py`, add this class after `ValidationReadinessConfig`:

```python
class PaperReadinessConfig(ValidationConfigModel):
    enabled: bool = True
    min_windows: int = Field(default=2, ge=1)
    min_total_trades: int = Field(default=30, ge=1)
    min_positive_window_fraction: float = Field(default=0.5, ge=0.0, le=1.0)
    max_stressed_net_loss: float = Field(default=-0.02, le=0.0)
    max_fill_lag_net_loss: float = Field(default=-0.02, le=0.0)
```

Then add this field to `ValidationConfig`:

```python
paper_readiness: PaperReadinessConfig = Field(default_factory=PaperReadinessConfig)
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
conda run -n quant pytest tests/test_validation_config.py -q
```

Expected: all tests in `tests/test_validation_config.py` pass.

- [ ] **Step 5: Commit**

```bash
git add src/quant_strategies/validation/config.py tests/test_validation_config.py
git commit -m "Add paper readiness validation config"
```

---

### Task 2: Extend Policy Decision Model

**Files:**
- Modify: `src/quant_strategies/validation/policy.py`
- Test: `tests/test_validation_backends_and_policy.py`

- [ ] **Step 1: Add failing model tests**

In `tests/test_validation_backends_and_policy.py`, update `assert_advisory_only` to also check gate fields:

```python
def assert_advisory_only(decision: ValidationPolicyDecision) -> None:
    assert decision.evidence_class == "validation_advisory"
    assert decision.advisory_decision == decision.decision
    assert decision.promotion_eligible is False
    assert decision.paper_trade_eligible is False
    assert decision.live_eligible is False
    assert decision.requires_manual_approval is True
    assert isinstance(decision.passed_gates, tuple)
    assert isinstance(decision.failed_gates, tuple)
    assert isinstance(decision.gate_details, dict)
    assert decision.overfit_controls == {
        "trial_count": None,
        "deflated_sharpe": None,
        "monte_carlo": None,
    }
```

Add this test near the existing policy tests:

```python
def test_policy_decision_supports_paper_candidate_gate_fields():
    decision = ValidationPolicyDecision(
        decision="paper_candidate",
        reasons=(),
        passed_gates=("mechanical_validation", "min_windows"),
        failed_gates=(),
        gate_details={"min_windows": "2 >= 2"},
    )

    assert decision.decision == "paper_candidate"
    assert decision.passed_gates == ("mechanical_validation", "min_windows")
    assert decision.failed_gates == ()
    assert decision.gate_details == {"min_windows": "2 >= 2"}
    assert_advisory_only(decision)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_backends_and_policy.py::test_policy_decision_supports_paper_candidate_gate_fields -q
```

Expected: fail because `paper_candidate`, `passed_gates`, `failed_gates`, `gate_details`, or `overfit_controls` are not supported.

- [ ] **Step 3: Update policy model**

In `src/quant_strategies/validation/policy.py`, update imports:

```python
from typing import Any, Literal
```

Also update the Pydantic import:

```python
from pydantic import BaseModel, ConfigDict, Field, model_validator
```

Replace the `ValidationDecision` literal with:

```python
ValidationDecision = Literal["hard_no", "mechanical_pass", "watchlist", "paper_candidate"]
```

Add fields to `ValidationPolicyDecision`:

```python
    passed_gates: tuple[str, ...] = ()
    failed_gates: tuple[str, ...] = ()
    gate_details: dict[str, str] = Field(default_factory=dict)
    overfit_controls: dict[str, Any | None] = Field(
        default_factory=lambda: {
            "trial_count": None,
            "deflated_sharpe": None,
            "monte_carlo": None,
        }
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
conda run -n quant pytest tests/test_validation_backends_and_policy.py::test_policy_decision_supports_paper_candidate_gate_fields -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/quant_strategies/validation/policy.py tests/test_validation_backends_and_policy.py
git commit -m "Extend validation policy decision states"
```

---

### Task 3: Implement Layered Policy Classification With Focused Helpers

**Files:**
- Modify: `src/quant_strategies/validation/policy.py`
- Test: `tests/test_validation_backends_and_policy.py`

- [ ] **Step 1: Add paper-readiness policy tests**

Append these helper functions to `tests/test_validation_backends_and_policy.py` before the paper-readiness tests:

```python
class PaperSettings:
    enabled = True
    min_windows = 2
    min_total_trades = 30
    min_positive_window_fraction = 0.5
    max_stressed_net_loss = -0.02
    max_fill_lag_net_loss = -0.02


def scenario(
    window_id: str,
    kind: str,
    net_return: float,
    trade_count: int,
    *,
    required: bool = True,
    status: str = "completed",
    unsupported_semantics: tuple[str, ...] = (),
) -> ScenarioBackendRunResult:
    scenario_id = f"{window_id}/{kind}"
    return ScenarioBackendRunResult(
        window_id=window_id,
        scenario_id=scenario_id,
        required=required,
        scenario_kind=kind,
        result=BackendRunResult(
            backend="fake",
            status=status,
            metrics={"net_return": net_return, "trade_count": trade_count},
            warnings=(),
            unsupported_semantics=unsupported_semantics,
        ),
    )


def passing_window(window_id: str) -> list[ScenarioBackendRunResult]:
    return [
        scenario(window_id, "base", 0.04, 20),
        scenario(window_id, "cost", 0.03, 20),
        scenario(window_id, "cost_stress", 0.01, 20),
        scenario(window_id, "fill_lag", 0.01, 20),
    ]
```

Append these tests:

```python
def test_policy_paper_candidate_for_two_positive_robust_windows():
    decision = classify_validation(
        data_passed=True,
        backend_results=[*passing_window("validation_2026_h1"), *passing_window("validation_2026_h2")],
        min_trades=10,
        required_scenario_ids=(
            "validation_2026_h1/base",
            "validation_2026_h1/cost",
            "validation_2026_h1/cost_stress",
            "validation_2026_h1/fill_lag",
            "validation_2026_h2/base",
            "validation_2026_h2/cost",
            "validation_2026_h2/cost_stress",
            "validation_2026_h2/fill_lag",
        ),
        paper_readiness=PaperSettings(),
    )

    assert decision.decision == "paper_candidate"
    assert decision.reasons == ()
    assert "mechanical_validation" in decision.passed_gates
    assert "min_windows" in decision.passed_gates
    assert "min_total_trades" in decision.passed_gates
    assert "aggregate_realistic_net_positive" in decision.passed_gates
    assert decision.failed_gates == ()
    assert_advisory_only(decision)


def test_policy_watchlist_when_one_window_cannot_be_paper_candidate():
    decision = classify_validation(
        data_passed=True,
        backend_results=passing_window("validation_2026_h1"),
        min_trades=10,
        required_scenario_count=4,
        paper_readiness=PaperSettings(),
    )

    assert decision.decision == "watchlist"
    assert "min_windows" in decision.failed_gates
    assert "paper_readiness_gates_failed" in decision.reasons
    assert_advisory_only(decision)


def test_policy_watchlist_when_stressed_costs_collapse():
    bad_window = [
        scenario("validation_2026_h1", "base", 0.04, 20),
        scenario("validation_2026_h1", "cost", 0.03, 20),
        scenario("validation_2026_h1", "cost_stress", -0.05, 20),
        scenario("validation_2026_h1", "fill_lag", 0.01, 20),
    ]
    decision = classify_validation(
        data_passed=True,
        backend_results=[*bad_window, *passing_window("validation_2026_h2")],
        min_trades=10,
        required_scenario_count=8,
        paper_readiness=PaperSettings(),
    )

    assert decision.decision == "watchlist"
    assert "stressed_net_floor" in decision.failed_gates
    assert ">= -0.02" in decision.gate_details["stressed_net_floor"]
    assert_advisory_only(decision)


def test_policy_mechanical_pass_without_positive_realistic_evidence():
    weak_window = [
        scenario("validation_2026_h1", "base", 0.02, 20),
        scenario("validation_2026_h1", "cost", 0.0, 20),
        scenario("validation_2026_h1", "cost_stress", 0.0, 20),
        scenario("validation_2026_h1", "fill_lag", 0.0, 20),
    ]
    decision = classify_validation(
        data_passed=True,
        backend_results=weak_window,
        min_trades=10,
        required_scenario_count=4,
        paper_readiness=PaperSettings(),
    )

    assert decision.decision == "mechanical_pass"
    assert "aggregate_realistic_net_positive" in decision.failed_gates
    assert_advisory_only(decision)
```

- [ ] **Step 2: Update old `maybe` expectations**

In `tests/test_validation_backends_and_policy.py`, rename these tests and assertions:

```python
def test_policy_maybe_for_unsupported_semantics():
```

to:

```python
def test_policy_watchlist_for_unsupported_semantics():
```

and change:

```python
assert decision.decision == "maybe"
```

to:

```python
assert decision.decision == "watchlist"
```

Do the same for:

```python
def test_policy_maybe_for_required_backend_unavailable():
```

renaming it to:

```python
def test_policy_watchlist_for_required_backend_unavailable():
```

Update the nonpositive-return policy tests because nonpositive performance is
now valid mechanical evidence but not paper-ready evidence. Rename:

```python
def test_policy_hard_no_for_nonpositive_net_return():
```

to:

```python
def test_policy_mechanical_pass_for_nonpositive_net_return_without_realistic_evidence():
```

and change the assertions to:

```python
assert decision.decision == "mechanical_pass"
assert "no_positive_realistic_cost_evidence" in decision.reasons
assert "aggregate_realistic_net_positive" in decision.failed_gates
assert_advisory_only(decision)
```

Rename:

```python
def test_policy_hard_no_for_zero_net_return():
```

to:

```python
def test_policy_mechanical_pass_for_zero_net_return_without_realistic_evidence():
```

and use the same assertions.

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_backends_and_policy.py -q
```

Expected: fail because paper-readiness classification is not implemented.

- [ ] **Step 4: Implement helper functions and keep policy orchestration short**

In `src/quant_strategies/validation/policy.py`, keep
`classify_validation(...)` responsible for top-level orchestration only:

```python
def classify_validation(
    *,
    data_passed: bool,
    backend_results: Sequence[BackendRunResult | ScenarioBackendRunResult],
    min_trades: int,
    required_scenario_count: int | None = None,
    required_scenario_ids: Sequence[str] | None = None,
    paper_readiness: object | None = None,
) -> ValidationPolicyDecision:
    if not data_passed:
        return _decision(
            "hard_no",
            reasons=("data_audit_failed",),
            failed=("data_audit",),
            details={"data_audit": "failed"},
        )
    if not backend_results:
        return _decision(
            "hard_no",
            reasons=("no_backend_results",),
            failed=("backend_results",),
            details={"backend_results": "none"},
        )

    scenario_results = tuple(_scenario_result(item) for item in backend_results)
    required_results = tuple(item for item in scenario_results if item.required)
    required_gate = _required_scenario_gate(
        required_results,
        required_scenario_count=required_scenario_count,
        required_scenario_ids=required_scenario_ids,
    )
    if required_gate is not None:
        return required_gate

    backend_gate = _backend_execution_gate(required_results, min_trades=min_trades)
    if backend_gate.decision != "mechanical_pass":
        return backend_gate

    return _paper_readiness_decision(
        required_results,
        min_trades=min_trades,
        paper_readiness=paper_readiness,
        base_passed_gates=backend_gate.passed_gates,
        base_gate_details=backend_gate.gate_details,
    )
```

Add these helpers below `_scenario_result(...)`:

```python
def _decision(
    decision: ValidationDecision,
    *,
    reasons: tuple[str, ...] = (),
    passed: tuple[str, ...] = (),
    failed: tuple[str, ...] = (),
    details: dict[str, str] | None = None,
) -> ValidationPolicyDecision:
    return ValidationPolicyDecision(
        decision=decision,
        reasons=reasons,
        passed_gates=passed,
        failed_gates=failed,
        gate_details={} if details is None else details,
    )


def _settings_value(settings: object | None, name: str, default: object) -> object:
    if settings is None:
        return default
    return getattr(settings, name, default)


def _paper_enabled(settings: object | None) -> bool:
    return bool(_settings_value(settings, "enabled", True))


def _scenario_key(item: ScenarioBackendRunResult) -> str:
    if item.scenario_kind:
        return item.scenario_kind
    return item.scenario_id.rsplit("/", 1)[-1]


def _metric_number(metrics: dict[str, float | int | str | bool | None], name: str) -> float | None:
    if name not in metrics:
        return None
    value = metrics[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _validated_backend_metrics(
    metrics: dict[str, float | int | str | bool | None],
) -> tuple[float, int] | None:
    net_return = _metric_number(metrics, "net_return")
    trade_count = _metric_number(metrics, "trade_count")
    if net_return is None or trade_count is None:
        return None
    if trade_count < 0 or not trade_count.is_integer():
        return None
    return net_return, int(trade_count)


def _gate_detail(actual: object, operator: str, expected: object) -> str:
    return f"{actual} {operator} {expected}"
```

Keep the existing `_metric_number` and `_validated_backend_metrics` helpers in
place. Add only `_settings_value`, `_paper_enabled`, `_scenario_key`, and
`_gate_detail` when the metric helpers already exist.

- [ ] **Step 5: Add required-scenario and backend execution gates**

Add these helpers below `_decision(...)`:

```python
def _required_scenario_gate(
    required_results: tuple[ScenarioBackendRunResult, ...],
    *,
    required_scenario_count: int | None = None,
    required_scenario_ids: Sequence[str] | None = None,
) -> ValidationPolicyDecision | None:
    if required_scenario_ids is not None:
        expected_ids = set(required_scenario_ids)
        actual_ids = [item.scenario_id for item in required_results]
        if len(actual_ids) != len(set(actual_ids)):
            return _decision(
                "hard_no",
                reasons=("duplicate_required_scenarios",),
                failed=("required_scenarios",),
                details={"required_scenarios": "duplicate required scenario ids"},
            )
        if set(actual_ids) != expected_ids:
            return _decision(
                "hard_no",
                reasons=("missing_required_scenarios",),
                failed=("required_scenarios",),
                details={
                    "required_scenarios": f"{len(actual_ids)} actual ids != {len(expected_ids)} expected ids"
                },
            )
    if required_scenario_count is not None and len(required_results) < required_scenario_count:
        return _decision(
            "hard_no",
            reasons=("missing_required_scenarios",),
            failed=("required_scenarios",),
            details={
                "required_scenarios": _gate_detail(len(required_results), ">=", required_scenario_count)
            },
        )
    if not required_results:
        return _decision(
            "hard_no",
            reasons=("no_required_backend_results",),
            failed=("required_backend_results",),
            details={"required_backend_results": "none"},
        )
    return None


def _backend_execution_gate(
    required_results: tuple[ScenarioBackendRunResult, ...],
    *,
    min_trades: int,
) -> ValidationPolicyDecision:
    for item in required_results:
        result = item.result
        if result.status == "failed":
            return _decision(
                "hard_no",
                reasons=(f"{result.backend}_failed",),
                failed=("required_backend_completed",),
                details={"required_backend_completed": f"{item.scenario_id} failed"},
            )

    unavailable = [item.result for item in required_results if item.result.status == "unavailable"]
    if unavailable:
        return _decision(
            "watchlist",
            reasons=("backend_unavailable",),
            failed=("required_backend_available",),
            details={"required_backend_available": f"{len(unavailable)} unavailable"},
        )

    unsupported = [
        item.result
        for item in required_results
        if item.result.unsupported_semantics or item.result.status == "unsupported"
    ]
    if unsupported:
        return _decision(
            "watchlist",
            reasons=("unsupported_semantics",),
            failed=("required_backend_semantics",),
            details={"required_backend_semantics": f"{len(unsupported)} unsupported"},
        )

    invalid_metrics = False
    insufficient_trades = False
    total_required_trades = 0
    for item in required_results:
        result = item.result
        if result.status != "completed":
            return _decision(
                "hard_no",
                reasons=(f"{result.backend}_failed",),
                failed=("required_backend_completed",),
                details={"required_backend_completed": f"{item.scenario_id} status={result.status}"},
            )
        metrics = _validated_backend_metrics(result.metrics)
        if metrics is None:
            invalid_metrics = True
            continue
        net_return, trade_count = metrics
        total_required_trades += trade_count
        if trade_count < min_trades:
            insufficient_trades = True

    if invalid_metrics:
        return _decision(
            "hard_no",
            reasons=("invalid_backend_metrics",),
            failed=("backend_metrics",),
            details={"backend_metrics": "missing or invalid net_return/trade_count"},
        )
    if insufficient_trades:
        return _decision(
            "hard_no",
            reasons=("insufficient_trades",),
            failed=("mechanical_min_trades",),
            details={"mechanical_min_trades": f"one or more required scenarios < {min_trades}"},
        )

    return _decision(
        "mechanical_pass",
        passed=("mechanical_validation",),
        details={
            "mechanical_validation": "required scenarios completed with valid metrics",
            "mechanical_total_required_trades": str(total_required_trades),
        },
    )
```

- [ ] **Step 6: Add paper-readiness decision helper**

Add this helper below `_backend_execution_gate(...)`:

```python
def _paper_readiness_decision(
    required_results: tuple[ScenarioBackendRunResult, ...],
    *,
    min_trades: int,
    paper_readiness: object | None,
    base_passed_gates: tuple[str, ...],
    base_gate_details: dict[str, str],
) -> ValidationPolicyDecision:
    metrics_by_scenario = {
        item.scenario_id: _validated_backend_metrics(item.result.metrics)
        for item in required_results
    }
    complete_metrics = {
        scenario_id: metrics
        for scenario_id, metrics in metrics_by_scenario.items()
        if metrics is not None
    }

    passed_gates = list(base_passed_gates)
    failed_gates: list[str] = []
    gate_details = dict(base_gate_details)

    if not _paper_enabled(paper_readiness):
        return _decision(
            "mechanical_pass",
            reasons=("paper_readiness_disabled",),
            passed=tuple(passed_gates),
            failed=("paper_readiness_enabled",),
            details={**gate_details, "paper_readiness_enabled": "false"},
        )

    min_windows = int(_settings_value(paper_readiness, "min_windows", 2))
    min_total_trades = int(_settings_value(paper_readiness, "min_total_trades", 30))
    min_positive_window_fraction = float(
        _settings_value(paper_readiness, "min_positive_window_fraction", 0.5)
    )
    max_stressed_net_loss = float(_settings_value(paper_readiness, "max_stressed_net_loss", -0.02))
    max_fill_lag_net_loss = float(_settings_value(paper_readiness, "max_fill_lag_net_loss", -0.02))

    realistic = [item for item in required_results if _scenario_key(item) == "cost"]
    stressed = [item for item in required_results if _scenario_key(item) == "cost_stress"]
    fill_lag = [item for item in required_results if _scenario_key(item) == "fill_lag"]
    windows = sorted({item.window_id for item in realistic})
    realistic_metrics = [complete_metrics[item.scenario_id] for item in realistic]
    stressed_metrics = [complete_metrics[item.scenario_id] for item in stressed]
    fill_lag_metrics = [complete_metrics[item.scenario_id] for item in fill_lag]

    window_count = len(windows)
    if window_count >= min_windows:
        passed_gates.append("min_windows")
    else:
        failed_gates.append("min_windows")
    gate_details["min_windows"] = _gate_detail(window_count, ">=", min_windows)

    realistic_total_trades = sum(trade_count for _, trade_count in realistic_metrics)
    if realistic_total_trades >= min_total_trades:
        passed_gates.append("min_total_trades")
    else:
        failed_gates.append("min_total_trades")
    gate_details["min_total_trades"] = _gate_detail(realistic_total_trades, ">=", min_total_trades)

    zero_trade_windows = [
        item.window_id
        for item in realistic
        if complete_metrics[item.scenario_id][1] == 0
    ]
    if not zero_trade_windows and realistic:
        passed_gates.append("no_zero_trade_windows")
    else:
        failed_gates.append("no_zero_trade_windows")
    gate_details["no_zero_trade_windows"] = ",".join(zero_trade_windows) if zero_trade_windows else "passed"

    realistic_net = sum(net_return for net_return, _ in realistic_metrics)
    positive_realistic_evidence = realistic_net > 0.0
    if positive_realistic_evidence:
        passed_gates.append("aggregate_realistic_net_positive")
    else:
        failed_gates.append("aggregate_realistic_net_positive")
    gate_details["aggregate_realistic_net_positive"] = _gate_detail(realistic_net, ">", 0.0)

    positive_windows = sum(
        1 for item in realistic if complete_metrics[item.scenario_id][0] > 0.0
    )
    positive_fraction = positive_windows / window_count if window_count else 0.0
    if positive_fraction >= min_positive_window_fraction:
        passed_gates.append("positive_window_fraction")
    else:
        failed_gates.append("positive_window_fraction")
    gate_details["positive_window_fraction"] = _gate_detail(
        positive_fraction,
        ">=",
        min_positive_window_fraction,
    )

    stressed_net = sum(net_return for net_return, _ in stressed_metrics)
    if stressed_metrics and stressed_net >= max_stressed_net_loss:
        passed_gates.append("stressed_net_floor")
    else:
        failed_gates.append("stressed_net_floor")
    gate_details["stressed_net_floor"] = _gate_detail(stressed_net, ">=", max_stressed_net_loss)

    fill_lag_net = sum(net_return for net_return, _ in fill_lag_metrics)
    if fill_lag_metrics and fill_lag_net >= max_fill_lag_net_loss:
        passed_gates.append("fill_lag_net_floor")
    else:
        failed_gates.append("fill_lag_net_floor")
    gate_details["fill_lag_net_floor"] = _gate_detail(fill_lag_net, ">=", max_fill_lag_net_loss)

    if not failed_gates:
        return _decision(
            "paper_candidate",
            passed=tuple(passed_gates),
            details=gate_details,
        )
    if positive_realistic_evidence:
        return _decision(
            "watchlist",
            reasons=("paper_readiness_gates_failed",),
            passed=tuple(passed_gates),
            failed=tuple(failed_gates),
            details=gate_details,
        )
    return _decision(
        "mechanical_pass",
        reasons=("no_positive_realistic_cost_evidence",),
        passed=tuple(passed_gates),
        failed=tuple(failed_gates),
        details=gate_details,
    )
```

- [ ] **Step 7: Run policy tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_backends_and_policy.py -q
```

Expected: all policy tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/quant_strategies/validation/policy.py tests/test_validation_backends_and_policy.py
git commit -m "Classify validation paper readiness ladder"
```

---

### Task 4: Integrate Paper Readiness Into Validation Runner

**Files:**
- Modify: `src/quant_strategies/validation/__init__.py`
- Test: `tests/test_validation_runner.py`

- [ ] **Step 1: Add two-window paper-candidate integration test**

Append this backend helper to `tests/test_validation_runner.py` near `ScenarioAwareBackend`:

```python
class WindowScenarioBackend(RecordingBackend):
    name = "window_scenario"

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: list[dict[str, Any]],
        config: Any,
    ) -> BackendRunResult:
        super().run(decisions=decisions, rows=rows, config=config)
        kind_returns = {
            "base": 0.04,
            "realistic_costs": 0.03,
            "stressed_costs": 0.01,
            "fill_lag_plus_1": 0.01,
        }
        scenario_tail = config.scenario_id.rsplit("/", 1)[-1]
        return BackendRunResult(
            backend=self.name,
            status="completed",
            metrics={"net_return": kind_returns.get(scenario_tail, 0.02), "trade_count": 20},
            warnings=(),
            unsupported_semantics=(),
        )
```

Add this test before the backend helper classes:

```python
def test_run_validation_returns_paper_candidate_for_two_robust_windows(
    tmp_path: Path,
    monkeypatch,
):
    package = write_package(tmp_path, window_ids=("validation_2026_h1", "validation_2026_h2"))
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))
    backend = WindowScenarioBackend()

    result = run_validation(package, repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "paper_candidate"
    assert result.success is True
    assert result.decision.promotion_eligible is False
    assert result.decision.paper_trade_eligible is False
    assert result.decision.live_eligible is False
    assert result.result_dir is not None
    decision = json.loads((result.result_dir / "validation_decision.json").read_text())
    assert decision["decision"] == "paper_candidate"
    assert decision["paper_trade_eligible"] is False
    assert "min_windows" in decision["passed_gates"]
    assert "min_total_trades" in decision["passed_gates"]
    assert decision["failed_gates"] == []
    robustness = json.loads((result.result_dir / "robustness_matrix.json").read_text())
    assert robustness["decision"]["decision"] == "paper_candidate"
    report = (result.result_dir / "validation_report.md").read_text()
    assert "Decision: `paper_candidate`" in report
```

- [ ] **Step 2: Update existing one-window success assertions**

In `tests/test_validation_runner.py`, update these exact positive one-window
assertions from `mechanical_pass` to `watchlist`:

```python
def test_run_validation_writes_mechanical_pass_artifacts(tmp_path: Path, monkeypatch):
```

Rename it to:

```python
def test_run_validation_writes_watchlist_artifacts_for_one_window(tmp_path: Path, monkeypatch):
```

and update:

```python
assert result.decision.decision == "mechanical_pass"
assert promotion["decision"] == "mechanical_pass"
assert promotion["advisory_decision"] == "mechanical_pass"
assert robustness_matrix["decision"]["decision"] == "mechanical_pass"
```

to:

```python
assert result.decision.decision == "watchlist"
assert promotion["decision"] == "watchlist"
assert promotion["advisory_decision"] == "watchlist"
assert robustness_matrix["decision"]["decision"] == "watchlist"
assert "min_windows" in promotion["failed_gates"]
```

In these tests, change the single final-decision assertion from
`mechanical_pass` to `watchlist`:

```python
def test_run_validation_ignores_parent_manifest_for_non_researched_config(
    tmp_path: Path,
    monkeypatch,
):
    assert result.decision.decision == "watchlist"


def test_run_validation_passes_merged_scenario_config_to_backend(
    tmp_path: Path,
    monkeypatch,
):
    assert result.decision.decision == "watchlist"


def test_run_validation_records_failed_parameter_generation_without_backend_call(
    tmp_path: Path,
    monkeypatch,
):
    assert result.decision.decision == "watchlist"
```

In this two-window test, change the final-decision assertion from
`mechanical_pass` to `watchlist` because the default recording backend produces
only 20 realistic-cost trades, below the default 30-trade paper-readiness gate:

```python
def test_run_validation_loads_rows_once_per_window_and_reuses_across_matrix(
    tmp_path: Path,
    monkeypatch,
):
    assert result.decision.decision == "watchlist"
```

- [ ] **Step 3: Run integration tests to verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_runner.py::test_run_validation_returns_paper_candidate_for_two_robust_windows -q
```

Expected: fail because `run_validation(...)` does not pass `config.paper_readiness` into policy yet.

- [ ] **Step 4: Pass paper readiness config into classifier**

In `src/quant_strategies/validation/__init__.py`, update the `classify_validation(...)` call:

```python
decision = classify_validation(
    data_passed=data_passed,
    backend_results=backend_results,
    min_trades=min_trades,
    required_scenario_ids=tuple(required_scenario_ids),
    paper_readiness=config.paper_readiness,
)
```

Update `_validation_result(...)` so `watchlist` and `paper_candidate` count as
completed validation results, while `hard_no` remains unsuccessful:

```python
def _validation_result(result_dir: Path, decision: ValidationPolicyDecision) -> ValidationRunResult:
    return ValidationRunResult(
        success=decision.decision in {"mechanical_pass", "watchlist", "paper_candidate"},
        result_dir=result_dir,
        decision=decision,
        message=f"validation decision: {decision.decision}",
    )
```

- [ ] **Step 5: Improve validation report text**

In `_write_validation_artifacts(...)`, replace the `validation_report.md` write with:

```python
    failed_gates = ", ".join(decision.failed_gates) or "none"
    passed_gates = ", ".join(decision.passed_gates) or "none"
    reasons = ", ".join(decision.reasons) or "none"
    write_text_artifact(
        result_dir,
        "validation_report.md",
        (
            "# Validation Report\n\n"
            f"Decision: `{decision.decision}`\n\n"
            f"Reasons: {reasons}\n\n"
            f"Passed gates: {passed_gates}\n\n"
            f"Failed gates: {failed_gates}\n"
        ),
    )
```

- [ ] **Step 6: Run validation runner tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_runner.py -q
```

Expected: all validation runner tests pass after updating assertions for the new ladder.

- [ ] **Step 7: Commit**

```bash
git add src/quant_strategies/validation/__init__.py tests/test_validation_runner.py
git commit -m "Integrate paper readiness into validation runner"
```

---

### Task 5: Add Optional VectorBT Pro Metrics

**Files:**
- Modify: `src/quant_strategies/validation/vectorbtpro_backend.py`
- Test: `tests/test_vectorbtpro_backend.py`

- [ ] **Step 1: Add metric extraction unit test**

Append this test to `tests/test_vectorbtpro_backend.py`:

```python
def test_optional_portfolio_metrics_extracts_available_values():
    from quant_strategies.validation.vectorbtpro_backend import _optional_portfolio_metrics

    class Trades:
        def profit_factor(self):
            return 1.7

        def win_rate(self):
            return 0.55

    class Portfolio:
        trades = Trades()

        def get_max_drawdown(self):
            return -0.12

    assert _optional_portfolio_metrics(Portfolio()) == {
        "max_drawdown": -0.12,
        "profit_factor": 1.7,
        "win_rate": 0.55,
    }


def test_optional_portfolio_metrics_ignores_missing_values():
    from quant_strategies.validation.vectorbtpro_backend import _optional_portfolio_metrics

    class Portfolio:
        pass

    assert _optional_portfolio_metrics(Portfolio()) == {}
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
conda run -n quant pytest tests/test_vectorbtpro_backend.py::test_optional_portfolio_metrics_extracts_available_values tests/test_vectorbtpro_backend.py::test_optional_portfolio_metrics_ignores_missing_values -q
```

Expected: fail because `_optional_portfolio_metrics` does not exist.

- [ ] **Step 3: Implement optional metric extraction**

In `src/quant_strategies/validation/vectorbtpro_backend.py`, update `_portfolio_metrics(...)`:

```python
def _portfolio_metrics(portfolio: Any) -> dict[str, float | int]:
    net_return = _float_metric(portfolio.get_total_return())
    if not math.isfinite(net_return):
        raise ValueError(f"nonfinite_net_return:{net_return}")

    trade_count = _int_metric(portfolio.trades.count())
    if trade_count < 0:
        raise ValueError(f"invalid_trade_count:{trade_count}")

    metrics: dict[str, float | int] = {"net_return": net_return, "trade_count": trade_count}
    metrics.update(_optional_portfolio_metrics(portfolio))
    return metrics
```

Add these helpers below `_portfolio_metrics(...)`:

```python
def _optional_portfolio_metrics(portfolio: Any) -> dict[str, float]:
    metrics: dict[str, float] = {}
    values = {
        "max_drawdown": _try_metric_call(portfolio, ("get_max_drawdown",)),
        "profit_factor": _try_metric_call(portfolio, ("trades", "profit_factor")),
        "win_rate": _try_metric_call(portfolio, ("trades", "win_rate")),
    }
    for name, value in values.items():
        if value is None:
            continue
        numeric = _optional_float_metric(value)
        if numeric is not None:
            metrics[name] = numeric
    return metrics


def _try_metric_call(root: Any, path: tuple[str, ...]) -> Any | None:
    value = root
    for name in path:
        value = getattr(value, name, None)
        if value is None:
            return None
    if callable(value):
        try:
            return value()
        except Exception:
            return None
    return value


def _optional_float_metric(value: Any) -> float | None:
    try:
        number = _float_metric(value)
    except Exception:
        return None
    return number if math.isfinite(number) else None
```

- [ ] **Step 4: Run backend tests**

Run:

```bash
conda run -n quant pytest tests/test_vectorbtpro_backend.py -q
```

Expected: all VectorBT Pro backend tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/quant_strategies/validation/vectorbtpro_backend.py tests/test_vectorbtpro_backend.py
git commit -m "Add optional vectorbtpro validation metrics"
```

---

### Task 6: Update CLI Exit Semantics

**Files:**
- Modify: `src/quant_strategies/runner/cli.py`
- Test: `tests/test_validation_cli.py`

- [ ] **Step 1: Add failing CLI tests for new advisory outcomes**

In `tests/test_validation_cli.py`, rename:

```python
def test_validate_cli_returns_two_for_maybe(monkeypatch, tmp_path: Path, capsys):
```

to:

```python
def test_validate_cli_returns_zero_for_watchlist(monkeypatch, tmp_path: Path, capsys):
```

and change the fake decision and assertions:

```python
decision=ValidationPolicyDecision(decision="watchlist", reasons=("unsupported_semantics",)),
message="validation decision: watchlist",
```

```python
assert code == 0
assert "watchlist" in capsys.readouterr().out
```

Add this test below it:

```python
def test_validate_cli_returns_zero_for_paper_candidate(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(
        "quant_strategies.runner.cli.run_validation",
        lambda path, repo_root=None: ValidationRunResult(
            success=True,
            result_dir=tmp_path / "validation_results" / "run",
            decision=ValidationPolicyDecision(decision="paper_candidate"),
            message="validation decision: paper_candidate",
        ),
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "researched/demo"])

    assert code == 0
    assert "paper_candidate" in capsys.readouterr().out
```

- [ ] **Step 2: Run CLI tests to verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_cli.py -q
```

Expected: fail because CLI still returns `2` for non-`mechanical_pass`
non-`hard_no` decisions.

- [ ] **Step 3: Implement advisory exit behavior**

In `src/quant_strategies/runner/cli.py`, replace:

```python
        if result.decision.decision == "mechanical_pass":
            return 0
        if result.decision.decision == "hard_no":
            return 1
        return 2
```

with:

```python
        if result.decision.decision == "hard_no":
            return 1
        return 0
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_cli.py -q
```

Expected: all CLI tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/quant_strategies/runner/cli.py tests/test_validation_cli.py
git commit -m "Update validation CLI advisory exits"
```

---

### Task 7: Update README Validation Semantics

**Files:**
- Modify: `README.md`
- Test: `tests/test_readme_contract.py`

- [ ] **Step 1: Update README text**

In `README.md`, replace this sentence in the `Boundaries` section:

```markdown
`validation` runs advisory researched-package checks. Its best positive outcome
is `mechanical_pass`; `promotion_eligible`, `paper_trade_eligible`, and
`live_eligible` remain false.
```

with:

```markdown
`validation` runs advisory researched-package checks. Its advisory outcomes are
`hard_no`, `mechanical_pass`, `watchlist`, and `paper_candidate`;
`promotion_eligible`, `paper_trade_eligible`, and `live_eligible` remain false.
```

In the `Package Validation` section, replace:

```markdown
For each validation window, the validator expands required and diagnostic
scenarios, runs the configured backend, and classifies the package as
`mechanical_pass`, `maybe`, or `hard_no`. A `mechanical_pass` requires passing
data audits, required backend scenarios, valid backend metrics, at least `10`
trades, and positive backend net return. Eligibility flags still remain false.
```

with:

```markdown
For each validation window, the validator expands required and diagnostic
scenarios, runs the configured backend, and classifies the package as `hard_no`,
`mechanical_pass`, `watchlist`, or `paper_candidate`. A `mechanical_pass`
requires passing data audits, required backend scenarios, valid backend metrics,
and at least `10` trades. `paper_candidate` additionally requires multiple
windows, enough realistic-cost trades, positive aggregate realistic-cost net
return, most windows positive, and cost/fill robustness. Eligibility flags
still remain false.
```

- [ ] **Step 2: Run README contract test**

Run:

```bash
conda run -n quant pytest tests/test_readme_contract.py -q
```

Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Document validation paper readiness ladder"
```

---

### Task 8: Full Focused Verification

**Files:**
- Verify changed validation and docs behavior.

- [ ] **Step 1: Run focused validation suite**

Run:

```bash
conda run -n quant pytest \
  tests/test_validation_config.py \
  tests/test_validation_backends_and_policy.py \
  tests/test_validation_runner.py \
  tests/test_vectorbtpro_backend.py \
  tests/test_validation_cli.py \
  tests/test_readme_contract.py
```

Expected: all selected tests pass.

- [ ] **Step 2: Run runner config smoke checks**

Run:

```bash
conda run -n quant pytest tests/test_runner_config.py
```

Expected: pass. This ensures validation config changes did not disturb runner config parsing.

- [ ] **Step 3: Inspect artifacts from a two-window test run**

Run:

```bash
conda run -n quant pytest tests/test_validation_runner.py::test_run_validation_returns_paper_candidate_for_two_robust_windows -q
```

Expected: pass and show `paper_candidate` in the assertion output when run with
pytest verbosity.

- [ ] **Step 4: Final status check**

Run:

```bash
git status --short
git diff --stat HEAD
```

Expected: no unexpected unrelated files staged. Existing unrelated dirty files from earlier work should remain untouched unless deliberately included in a task.

- [ ] **Step 5: Commit verification fixes when Task 7 changes files**

If Task 7 changed files, commit them:

```bash
git add \
  src/quant_strategies/validation/config.py \
  src/quant_strategies/validation/policy.py \
  src/quant_strategies/validation/__init__.py \
  src/quant_strategies/validation/vectorbtpro_backend.py \
  src/quant_strategies/runner/cli.py \
  tests/test_validation_config.py \
  tests/test_validation_backends_and_policy.py \
  tests/test_validation_runner.py \
  tests/test_vectorbtpro_backend.py \
  tests/test_validation_cli.py \
  tests/test_readme_contract.py \
  README.md
git commit -m "Stabilize validation paper readiness tests"
```

If Task 7 changed no files, record that no verification-fix commit was needed
in the final implementation summary.

---

## Self-Review Checklist

- Spec coverage:
  - One validation command remains unchanged: covered by Tasks 4 and 6.
  - `hard_no`, `mechanical_pass`, `watchlist`, `paper_candidate`: covered by Tasks 2 and 3.
  - `[paper_readiness]` config with defaults: covered by Task 1.
  - Multi-window paper gates: covered by Tasks 3 and 4.
  - Artifacts and report enrichment: covered by Task 4.
  - Optional VectorBT Pro metrics: covered by Task 5.
  - CLI advisory exits: covered by Task 6.
  - Documentation: covered by Task 7.

- No placeholders:
  - All planned code changes include concrete snippets.
  - All test commands include expected outcomes.

- Type consistency:
  - `ValidationDecision` values match the spec.
  - `paper_readiness` is passed as an object to policy to avoid coupling policy to Pydantic config models.
  - `ScenarioBackendRunResult.scenario_kind` drives paper-readiness scenario grouping.

---

## Engineering Review Addendum

### Step 0 Scope Challenge

- Scope accepted with one safety change: commit/staging commands must name exact files because this worktree is dirty.
- The minimum implementation is still one advisory validation ladder inside the existing validation workflow. Do not add a second `paper-readiness` command.
- Complexity is acceptable because the touched surface is existing validation code plus tests/docs. No new runtime services, data loaders, engines, or artifact families are introduced.
- Prior learning applied: keep `README.md` generic and avoid strategy-specific content.

### What Already Exists

- `ValidationConfig` already parses researched package validation TOML and converts each window to a runner config. Reuse it and add only `paper_readiness`.
- `expand_validation_matrix(...)` already creates base, realistic-cost, stressed-cost, fill-lag, and parameter scenarios. Reuse `scenario_kind` instead of matching scenario IDs by string.
- `classify_validation(...)` already gates data audit, backend completion, required scenarios, valid metrics, and minimum trades. Keep it as the single policy entry point.
- `run_validation(...)` already writes `validation_decision.json`, `robustness_matrix.json`, and `validation_report.md`. Enrich those artifacts rather than adding a new artifact tree.
- `VectorBTProBackend` already enforces no overlapping active symbol windows and portfolio target-weight limits. Do not duplicate this in policy.

### NOT in Scope

- Portfolio construction across retained strategies: defer until multiple validated strategies exist.
- Monte Carlo, deflated Sharpe, and trial-count corrections: reserve fields now, but do not fake unavailable controls.
- Promotion to `tested/`, paper-trade eligibility, or live eligibility: all eligibility flags remain false.
- New backend engine or VectorBT Pro-only runner: validation may use VectorBT Pro, but the smoke runner remains the internal reproducibility path.
- Strategy-specific README additions: root README stays a stable project contract.

### Data Flow Diagram

```text
quant-strategies validate
  |
  v
load_validation_config
  |-- existing config sections
  |-- new optional [paper_readiness]
  v
run_validation
  |
  |-- for each validation window
  |     |-- load rows once
  |     |-- expand_validation_matrix
  |     |-- generate or reuse decisions per scenario
  |     |-- run backend per required/diagnostic scenario
  |
  v
classify_validation
  |-- hard_no: failed data audit, missing required scenarios, failed backend, invalid metrics, insufficient trades
  |-- watchlist: required backend unavailable/unsupported, or positive evidence with failed paper gates
  |-- mechanical_pass: mechanically valid but not enough positive realistic-cost evidence
  |-- paper_candidate: multiple windows plus realistic-cost, stress-cost, fill-lag, trade-count, and positive-window gates
  v
write artifacts + CLI exit
  |-- hard_no -> exit 1
  |-- mechanical_pass/watchlist/paper_candidate -> exit 0
```

### Test Coverage Diagram

```text
CODE PATHS                                            VALIDATION FLOWS
[+] config.py                                          [+] Config loading
  |-- [***] default paper_readiness                      |-- [***] default section absent
  |-- [***] override paper_readiness                     |-- [***] invalid limits rejected

[+] policy.py                                          [+] Policy ladder
  |-- [***] data/backend hard_no                         |-- [***] legacy maybe renamed watchlist
  |-- [***] required scenario gates                      |-- [***] one-window watchlist/mechanical pass
  |-- [***] backend unavailable/unsupported              |-- [***] two-window paper_candidate
  |-- [***] paper gate pass/fail                         |-- [***] stress/fill-lag failure stays advisory

[+] validation/__init__.py                             [+] Artifact output
  |-- [***] pass paper_readiness to policy               |-- [***] decision JSON includes gate fields
  |-- [***] success true for advisory pass states        |-- [***] report explains gates

[+] runner/cli.py                                      [+] CLI behavior
  |-- [***] hard_no exits 1                              |-- [***] validation errors exit 1
  |-- [***] advisory completed states exit 0             |-- [***] paper_candidate/watchlist print result

[+] vectorbtpro_backend.py                             [+] Optional metrics
  |-- [***] available optional metrics extracted         |-- [***] missing optional methods ignored
  |-- [***] required metrics remain fail-closed

Legend: [***] planned test covers behavior, edge case, and failure path.
Coverage target: all planned branches covered by focused pytest tests.
```

### Failure Modes

- Invalid `[paper_readiness]` values: covered by config tests; Pydantic raises `ValidationConfigError`; user sees validation config failure.
- Required scenario missing or duplicated: covered by policy tests; returns `hard_no`; artifacts contain failed gate details.
- Backend unavailable or unsupported semantics: covered by policy and CLI tests; returns `watchlist`; CLI exits `0` because validation completed with advisory output.
- Positive base return but weak realistic-cost evidence: covered by policy tests; returns `mechanical_pass`, not `paper_candidate`.
- Stressed-cost or fill-lag collapse: covered by policy tests; returns `watchlist` with failed gate detail.
- Optional VectorBT Pro metric method missing or throwing: covered by backend tests; required `net_return` and `trade_count` still fail closed.
- Broad staging in dirty worktree: fixed in this plan by exact file staging; implementation agents must not use `git add -A` or broad `git add tests`.

### Parallelization

| Step | Modules touched | Depends on |
|------|-----------------|------------|
| Config | `validation/`, `tests/` | - |
| Policy model and classification | `validation/`, `tests/` | Config |
| Runner integration and artifacts | `validation/`, `tests/` | Policy |
| VectorBT Pro optional metrics | `validation/`, `tests/` | - |
| CLI exits | `runner/`, `tests/` | Policy model |
| README | docs | Policy decisions finalized |

Lane A: Config -> Policy -> Runner integration -> CLI -> README.
Lane B: VectorBT Pro optional metrics can run in parallel after the plan is accepted.
Conflict flag: Lane A and Lane B both touch `validation/`; merge Lane B before final focused verification.

### Implementation Tasks From Review

- [ ] **T1 (P1, human: ~10min / CC: ~2min)** — Git safety — Use exact file staging only.
  - Surfaced by: Code quality review — broad final `git add ... tests README.md` could stage unrelated dirty files.
  - Files: `docs/superpowers/plans/2026-05-27-single-validation-paper-readiness.md`
  - Verify: review each `git add` block and confirm it names only exact implementation files; no `git add -A`, `git add tests`, or `git add .`.

_No new tasks from Architecture review after accepted CLI contract._
_No new tasks from Test review after accepted invalid-config tests._
_No new tasks from Performance review._

### Review Completion Summary

- Step 0 Scope Challenge: scope accepted with exact-staging safety fix.
- Architecture Review: 1 issue found and resolved in the plan, CLI advisory exit contract.
- Code Quality Review: 2 issues found and resolved in the plan, helper-oriented policy structure and exact staging.
- Test Review: coverage diagram produced, 1 gap found and resolved in the plan, invalid `[paper_readiness]` tests.
- Performance Review: 0 issues found.
- NOT in scope: written.
- What already exists: written.
- TODOS.md updates: 0 items proposed; no durable TODO needed for this implementation.
- Failure modes: 0 critical gaps flagged.
- Outside voice: skipped.
- Parallelization: 2 lanes, 1 primary sequential lane and 1 optional parallel lane.
- Lake Score: 4/4 recommendations chose the complete option.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | - | Not run |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | - | Not run |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 4 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | - | Not applicable |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | - | Not run |

- **UNRESOLVED:** 0
- **VERDICT:** ENG CLEARED - ready to implement.
