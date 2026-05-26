# Foundation Evidence Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make runner and validation artifacts explicitly state their evidence class, return/funding model, and non-deployability semantics.

**Architecture:** Add a tiny shared evidence-semantics module, write those fields into runner summaries/manifests and validation decisions, label funding-adjusted metrics, and remove smoke fixture ambiguity from `tested/`. This phase does not add validation manifests, performance profiles, or richer backend capability support.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, existing `quant_strategies` runner/validation artifacts.

---

## Scope Check

This is Plan 2 of the foundation repair rollout. It assumes Phase 1 has landed:
runner and validation share `generate_decisions` / `StrategyDecision`.

This phase implements only evidence semantics:

- evidence class labels
- strategy contract labels
- return model labels
- funding model labels
- paper/live eligibility flags
- manual-approval flags
- smoke fixture lifecycle cleanup

It does not implement validation manifests, manifest hash checks, immutable
boundaries, `BaseException` cleanup, artifact profiles, timestamp indexing, or
causality metadata.

## File Structure

- Create `src/quant_strategies/evidence_semantics.py`
  - Shared constants and helpers for runner and validation evidence meaning.

- Modify `src/quant_strategies/runner/__init__.py`
  - Add evidence semantics fields to runner summaries.
  - Pass evidence semantics to runner manifest writing.

- Modify `src/quant_strategies/runner/artifacts.py`
  - Include evidence semantics in `run_manifest.json`.

- Modify `src/quant_strategies/validation/policy.py`
  - Add advisory/deployability fields to `PromotionDecision`.

- Modify `src/quant_strategies/validation/vectorbtpro_backend.py`
  - Add explicit funding model label when funding is linearly added.

- Move `tested/simple_momentum.py` to `examples/strategies/simple_momentum.py`
  - Remove smoke fixture ambiguity from `tested/`.
  - Update `runs/simple_momentum_spy_daily.toml`.
  - Update tests that import the fixture.

- Modify docs:
  - `README.md`

- Modify tests:
  - `tests/test_runner_api_cli.py`
  - `tests/test_validation_backends_and_policy.py`
  - `tests/test_validation_runner.py`
  - `tests/test_vectorbtpro_backend.py`
  - `tests/test_simple_momentum.py`
  - `tests/test_strategy_docstrings.py`

## Task 1: Shared Evidence Semantics

**Files:**
- Create: `src/quant_strategies/evidence_semantics.py`
- Test: `tests/test_runner_api_cli.py`

- [ ] **Step 1: Add runner summary assertions**

In `tests/test_runner_api_cli.py`, update `assert_summary` so every runner
summary must include the explicit non-deployability fields:

```python
def assert_summary(
    result: RunResult,
    *,
    success: bool,
    status: str,
    stage: str,
    assessment_status: str,
    promotion_eligible: bool = False,
):
    assert result.result_dir is not None
    summary = json.loads((result.result_dir / "summary.json").read_text())
    assert summary["success"] is success
    assert summary["status"] == status
    assert summary["stage"] == stage
    assert summary["assessment_status"] == assessment_status
    assert summary["promotion_eligible"] is promotion_eligible
    assert summary["evidence_class"] == "runner_smoke"
    assert summary["strategy_contract"] == "decision"
    assert summary["return_model"] == "sum_weighted_trade_return"
    assert summary["paper_trade_eligible"] is False
    assert summary["live_eligible"] is False
    assert summary["requires_manual_approval"] is True
```

In the crypto funding notes test, also assert:

```python
summary = json.loads((result.result_dir / "summary.json").read_text())
assert summary["funding_model"] == "linear_additive_adjustment"
```

For a non-funding runner test, assert:

```python
summary = json.loads((result.result_dir / "summary.json").read_text())
assert summary["funding_model"] == "none"
```

- [ ] **Step 2: Run focused runner tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_writes_success_artifacts tests/test_runner_api_cli.py::test_crypto_perp_funding_notes_label_returns_as_funding_aware -q
```

Expected before implementation: fail because the summary does not include the
new evidence semantics fields.

- [ ] **Step 3: Create evidence semantics helpers**

Create `src/quant_strategies/evidence_semantics.py`:

```python
from __future__ import annotations

from typing import Literal


EvidenceClass = Literal["runner_smoke", "validation_advisory"]
StrategyContract = Literal["decision"]
RunnerReturnModel = Literal["sum_weighted_trade_return"]
FundingModel = Literal["none", "linear_additive_adjustment"]


def funding_model_for_data_kind(data_kind: str) -> FundingModel:
    if data_kind == "crypto_perp_funding":
        return "linear_additive_adjustment"
    return "none"


def runner_evidence_semantics(data_kind: str) -> dict[str, object]:
    return {
        "evidence_class": "runner_smoke",
        "strategy_contract": "decision",
        "return_model": "sum_weighted_trade_return",
        "funding_model": funding_model_for_data_kind(data_kind),
        "promotion_eligible": False,
        "paper_trade_eligible": False,
        "live_eligible": False,
        "requires_manual_approval": True,
    }


def validation_evidence_semantics() -> dict[str, object]:
    return {
        "evidence_class": "validation_advisory",
        "paper_trade_eligible": False,
        "live_eligible": False,
        "requires_manual_approval": True,
    }
```

- [ ] **Step 4: Add evidence semantics to runner summary payloads**

Modify `src/quant_strategies/runner/__init__.py`:

```python
from quant_strategies.evidence_semantics import runner_evidence_semantics
```

Inside `_summary_payload`, add the shared fields:

```python
    semantics = runner_evidence_semantics(config.data.kind)
    return {
        "strategy_id": config.strategy_id,
        "mode": config.output.mode,
        "success": success,
        "status": status,
        "stage": stage,
        "message": message,
        "artifacts": [],
        "engine": engine,
        "run_completed": True,
        "assessment_status": assessment_status,
        **semantics,
    }
```

Remove the separate hard-coded `"promotion_eligible": False` entry because the
semantics helper now owns it.

- [ ] **Step 5: Run runner tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py -q
```

Expected: runner API tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/quant_strategies/evidence_semantics.py \
  src/quant_strategies/runner/__init__.py \
  tests/test_runner_api_cli.py
git commit -m "feat: label runner evidence semantics"
```

## Task 2: Runner Manifest Evidence Semantics

**Files:**
- Modify: `src/quant_strategies/runner/artifacts.py`
- Modify: `src/quant_strategies/runner/__init__.py`
- Test: `tests/test_runner_api_cli.py`

- [ ] **Step 1: Add manifest assertions**

In `tests/test_runner_api_cli.py::test_completed_run_writes_minimal_manifests`,
add:

```python
assert run_manifest["evidence"] == {
    "evidence_class": "runner_smoke",
    "strategy_contract": "decision",
    "return_model": "sum_weighted_trade_return",
    "funding_model": "none",
    "promotion_eligible": False,
    "paper_trade_eligible": False,
    "live_eligible": False,
    "requires_manual_approval": True,
}
```

In the crypto funding run manifest test, assert:

```python
assert run_manifest["evidence"]["funding_model"] == "linear_additive_adjustment"
```

- [ ] **Step 2: Run manifest tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py::test_completed_run_writes_minimal_manifests -q
```

Expected before implementation: fail because `run_manifest.json` lacks
`evidence`.

- [ ] **Step 3: Add evidence parameter to manifest writer**

Modify `src/quant_strategies/runner/artifacts.py`:

```python
def write_run_manifest(
    result_dir: Path,
    *,
    repo_root: Path,
    evidence: dict[str, object],
) -> None:
    payload = {
        "repository": _git_identity(repo_root, result_dir),
        "python": {"version": sys.version.split()[0]},
        "packages": _package_versions(["quant-strategies", "quant-data", "pydantic"]),
        "engine": {"evidence_schema": EVIDENCE_SCHEMA_VERSION},
        "evidence": evidence,
        "artifacts": _artifact_hashes(result_dir),
    }
    _write_json(result_dir / "run_manifest.json", payload)
```

- [ ] **Step 4: Pass runner evidence semantics into manifest writer**

Modify both calls in `src/quant_strategies/runner/__init__.py`:

```python
artifacts.write_run_manifest(
    result_dir,
    repo_root=effective_repo_root,
    evidence=runner_evidence_semantics(config.data.kind),
)
```

and in `_failure_result`:

```python
artifacts.write_run_manifest(
    result_dir,
    repo_root=repo_root,
    evidence=runner_evidence_semantics(config.data.kind),
)
```

- [ ] **Step 5: Run runner API tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py -q
```

Expected: all runner API tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/quant_strategies/runner/artifacts.py \
  src/quant_strategies/runner/__init__.py \
  tests/test_runner_api_cli.py
git commit -m "feat: record runner evidence semantics in manifests"
```

## Task 3: Validation Advisory Deployability Fields

**Files:**
- Modify: `src/quant_strategies/validation/policy.py`
- Test: `tests/test_validation_backends_and_policy.py`
- Test: `tests/test_validation_runner.py`
- Test: `tests/test_validation_cli.py`

- [ ] **Step 1: Add policy assertions**

In `tests/test_validation_backends_and_policy.py`, add this helper:

```python
def assert_advisory_only(decision: PromotionDecision):
    assert decision.evidence_class == "validation_advisory"
    assert decision.advisory_decision == decision.decision
    assert decision.paper_trade_eligible is False
    assert decision.live_eligible is False
    assert decision.requires_manual_approval is True
```

Call it in tests that create policy decisions, including:

```python
decision = classify_validation(...)
assert decision.decision == "clear_yes"
assert_advisory_only(decision)
```

In `tests/test_validation_runner.py::test_run_validation_writes_clear_yes_artifacts`,
add:

```python
assert promotion["evidence_class"] == "validation_advisory"
assert promotion["advisory_decision"] == "clear_yes"
assert promotion["paper_trade_eligible"] is False
assert promotion["live_eligible"] is False
assert promotion["requires_manual_approval"] is True
```

In `tests/test_validation_cli.py`, construct `PromotionDecision` without new
arguments to prove defaults work:

```python
decision=PromotionDecision(decision="clear_yes")
```

- [ ] **Step 2: Run validation policy tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_backends_and_policy.py tests/test_validation_runner.py::test_run_validation_writes_clear_yes_artifacts -q
```

Expected before implementation: fail because `PromotionDecision` lacks the
new fields.

- [ ] **Step 3: Extend PromotionDecision**

Modify `src/quant_strategies/validation/policy.py`:

```python
from pydantic import BaseModel, ConfigDict, model_validator

from quant_strategies.evidence_semantics import validation_evidence_semantics
```

Then update `PromotionDecision`:

```python
class PromotionDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: ValidationDecision
    reasons: tuple[str, ...] = ()
    advisory_decision: ValidationDecision | None = None
    evidence_class: str = "validation_advisory"
    paper_trade_eligible: bool = False
    live_eligible: bool = False
    requires_manual_approval: bool = True

    @model_validator(mode="after")
    def default_advisory_decision(self) -> PromotionDecision:
        if self.advisory_decision is None:
            object.__setattr__(self, "advisory_decision", self.decision)
        semantics = validation_evidence_semantics()
        object.__setattr__(self, "evidence_class", str(semantics["evidence_class"]))
        object.__setattr__(self, "paper_trade_eligible", bool(semantics["paper_trade_eligible"]))
        object.__setattr__(self, "live_eligible", bool(semantics["live_eligible"]))
        object.__setattr__(
            self,
            "requires_manual_approval",
            bool(semantics["requires_manual_approval"]),
        )
        return self
```

- [ ] **Step 4: Run validation tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_backends_and_policy.py tests/test_validation_runner.py tests/test_validation_cli.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/quant_strategies/validation/policy.py \
  tests/test_validation_backends_and_policy.py \
  tests/test_validation_runner.py \
  tests/test_validation_cli.py
git commit -m "feat: mark validation decisions advisory only"
```

## Task 4: Funding Model Labels In Validation Metrics

**Files:**
- Modify: `src/quant_strategies/validation/vectorbtpro_backend.py`
- Test: `tests/test_vectorbtpro_backend.py`

- [ ] **Step 1: Add funding model assertions**

In `tests/test_vectorbtpro_backend.py`, update funding-aware tests:

```python
assert result.metrics["price_cost_return"] == pytest.approx(0.01)
assert result.metrics["funding_return"] == pytest.approx(-0.0003)
assert result.metrics["funding_model"] == "linear_additive_adjustment"
```

For the no-funding crypto-perp funding-row test, assert:

```python
assert result.metrics["funding_model"] == "linear_additive_adjustment"
```

- [ ] **Step 2: Run funding backend tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_vectorbtpro_backend.py::test_vectorbtpro_backend_adds_funding_return_for_crypto_perp_rows -q
```

Expected before implementation: fail because `funding_model` is not present.

- [ ] **Step 3: Add funding model metric**

Modify `_funding_adjusted_metrics` in
`src/quant_strategies/validation/vectorbtpro_backend.py`:

```python
    return {
        **metrics,
        "price_cost_return": price_cost_return,
        "funding_return": funding_return,
        "funding_model": "linear_additive_adjustment",
        "net_return": price_cost_return + funding_return,
    }
```

- [ ] **Step 4: Run VectorBT backend tests**

Run:

```bash
conda run -n quant pytest tests/test_vectorbtpro_backend.py -q
```

Expected: all VectorBT backend tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/quant_strategies/validation/vectorbtpro_backend.py tests/test_vectorbtpro_backend.py
git commit -m "feat: label validation funding model"
```

## Task 5: Remove Smoke Fixture Ambiguity From `tested/`

**Files:**
- Move: `tested/simple_momentum.py` -> `examples/strategies/simple_momentum.py`
- Modify: `runs/simple_momentum_spy_daily.toml`
- Modify: `tests/test_simple_momentum.py`
- Modify: `tests/test_strategy_docstrings.py`

- [ ] **Step 1: Update tests to import the example strategy by path**

Modify `tests/test_simple_momentum.py` so it imports the example without making
`examples/` a package:

```python
import importlib.util
from pathlib import Path


def load_example_strategy():
    path = Path("examples/strategies/simple_momentum.py")
    spec = importlib.util.spec_from_file_location("_simple_momentum_example", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
```

Then replace direct `generate_decisions(...)` calls with:

```python
module = load_example_strategy()
decisions = module.generate_decisions(...)
```

- [ ] **Step 2: Update strategy docstring test scope**

In `tests/test_strategy_docstrings.py`, add examples to contract checks:

```python
def example_strategy_files() -> list[Path]:
    return sorted(Path("examples/strategies").glob("*.py"))
```

Then update:

```python
def all_strategy_files_for_contract() -> list[Path]:
    return strategy_files() + researched_strategy_files() + example_strategy_files()
```

Do not add `examples/strategies` to `strategy_python_files()` because the flat
layout rule applies to lifecycle strategy directories only.

- [ ] **Step 3: Move the file and update run config**

Run:

```bash
mkdir -p examples/strategies
git mv tested/simple_momentum.py examples/strategies/simple_momentum.py
```

Modify `runs/simple_momentum_spy_daily.toml`:

```toml
strategy_path = "examples/strategies/simple_momentum.py"
```

- [ ] **Step 4: Run fixture and docstring tests**

Run:

```bash
conda run -n quant pytest tests/test_simple_momentum.py tests/test_strategy_docstrings.py -q
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add examples/strategies/simple_momentum.py \
  runs/simple_momentum_spy_daily.toml \
  tests/test_simple_momentum.py \
  tests/test_strategy_docstrings.py
git add -u tested/simple_momentum.py
git commit -m "refactor: move smoke fixture out of tested lifecycle"
```

## Task 6: README Evidence Semantics

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**

Update README to state:

```markdown
Runner artifacts are smoke evidence. They include `evidence_class`,
`strategy_contract`, `return_model`, `funding_model`, `promotion_eligible`,
`paper_trade_eligible`, `live_eligible`, and `requires_manual_approval` so
automation and humans do not overread a quick run.
```

Update validation language:

```markdown
Validation decisions are advisory until Season approves a stronger promotion
policy. `promotion_decision.json` includes `advisory_decision`,
`paper_trade_eligible`, `live_eligible`, and `requires_manual_approval`.
```

Update lifecycle layout:

```text
examples/    example or smoke strategies that are not lifecycle-promoted
tested/      strategies that passed the separate validation process
```

- [ ] **Step 2: Search for stale current-contract wording**

Run:

```bash
rg -n "generate_signals remains valid|clear_yes recommendation does not automatically|tested/simple_momentum|paper_trade_eligible|return_model|funding_model" README.md
```

Expected:

- No `generate_signals remains valid` wording.
- No `tested/simple_momentum` path.
- README mentions `paper_trade_eligible`, `return_model`, and `funding_model`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document evidence semantics"
```

## Task 7: Phase 2 Verification

**Files:**
- No planned source edits.

- [ ] **Step 1: Run focused phase tests**

Run:

```bash
conda run -n quant pytest \
  tests/test_runner_api_cli.py \
  tests/test_validation_backends_and_policy.py \
  tests/test_validation_runner.py \
  tests/test_validation_cli.py \
  tests/test_vectorbtpro_backend.py \
  tests/test_simple_momentum.py \
  tests/test_strategy_docstrings.py \
  -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run full suite**

Run:

```bash
conda run -n quant pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Verify evidence semantic fields are not missing from active code**

Run:

```bash
rg -n "evidence_class|strategy_contract|return_model|funding_model|paper_trade_eligible|live_eligible|requires_manual_approval" src tests README.md
```

Expected:

- Runner code/tests mention all runner evidence fields.
- Validation code/tests mention advisory/deployability fields.
- VectorBT backend tests mention `funding_model`.

- [ ] **Step 4: Stop before Phase 3**

Do not implement validation manifests or researched manifest integrity in this
plan. Write a separate Phase 3 plan after Phase 2 lands and the repo state is
rechecked.
