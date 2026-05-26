# Foundation Contract Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `StrategyDecision` the single serious strategy output contract for runner and validation paths.

**Architecture:** Add one shared decision-strategy loader under `decisions/`, keep the smoke engine's `Signal` model internal, and convert `StrategyDecision` to engine signal rows in runner infrastructure. Validation and runner both load `generate_decisions`; signal-only strategy contracts stop being accepted by the foundation runner.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, existing `quant_strategies` runner/engine/validation modules.

---

## Scope Check

This is Plan 1 of the foundation repair rollout. It implements only the
contract reset:

```text
generate_decisions(rows, params) -> list[StrategyDecision]
```

It does not implement evidence eligibility fields, validation manifests,
artifact profiles, performance indexing, parameter schemas, causality metadata,
or backend capability expansion. Those get separate plans after this phase
lands and the test suite is green.

## File Structure

- Create `src/quant_strategies/decisions/strategy_loader.py`
  - Shared import/path validation for `generate_decisions`.
  - Raises `DecisionStrategyLoadError`.

- Modify `src/quant_strategies/decisions/__init__.py`
  - Export the shared loader and error type.

- Create `src/quant_strategies/runner/decision_adapter.py`
  - Convert `StrategyDecision` objects to internal signal dictionaries for the
    current smoke engine.
  - Reject decision semantics the smoke engine cannot represent.

- Modify `src/quant_strategies/runner/strategy_loader.py`
  - Delegate to the shared decision loader.
  - Keep runner-specific `StrategyLoadError` messages.

- Modify `src/quant_strategies/validation/strategy_loader.py`
  - Delegate to the shared decision loader.
  - Keep validation-specific `ValidationStrategyLoadError` messages.

- Modify `src/quant_strategies/runner/__init__.py`
  - Call `generate_decisions`.
  - Write canonical decision records.
  - Convert decisions to signal rows only before readiness/request building.

- Modify `src/quant_strategies/runner/artifacts.py`
  - Add `write_decision_records`.

- Modify `tested/simple_momentum.py`
  - Convert the smoke fixture to `generate_decisions`.

- Modify tests:
  - `tests/test_runner_strategy_loader.py`
  - `tests/test_validation_strategy_loader.py`
  - `tests/test_runner_engine_runner.py`
  - `tests/test_runner_api_cli.py`
  - `tests/test_simple_momentum.py`

- Modify docs:
  - `README.md`

## Task 1: Shared Decision Strategy Loader

**Files:**
- Create: `src/quant_strategies/decisions/strategy_loader.py`
- Modify: `src/quant_strategies/decisions/__init__.py`
- Test: `tests/test_validation_strategy_loader.py`

- [ ] **Step 1: Add tests for shared decision loading through validation**

Update `tests/test_validation_strategy_loader.py` so the existing tests still
describe the validation API, but assert that signal-only modules are rejected
because they lack the canonical decision contract:

```python
def test_load_decision_strategy_requires_generate_decisions(tmp_path: Path):
    strategy = write_strategy(
        tmp_path / "researched" / "demo" / "strategy.py",
        "def generate_signals(rows, params):\n    return []\n",
    )

    with pytest.raises(ValidationStrategyLoadError, match="generate_decisions"):
        load_decision_strategy(strategy, repo_root=tmp_path)
```

Keep the existing successful `generate_decisions` test unchanged except for any
imports that move.

- [ ] **Step 2: Run validation loader tests and verify baseline**

Run:

```bash
conda run -n quant pytest tests/test_validation_strategy_loader.py -q
```

Expected before implementation: current tests pass. They protect the existing
validation behavior while the shared loader is introduced.

- [ ] **Step 3: Create the shared loader**

Create `src/quant_strategies/decisions/strategy_loader.py`:

```python
from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from quant_strategies.decisions.models import StrategyDecision
from quant_strategies.runner.config import default_repo_root


DecisionStrategyCallable = Callable[
    [Sequence[Mapping[str, object]], Mapping[str, object]],
    list[StrategyDecision],
]


class DecisionStrategyLoadError(Exception):
    """Raised when a strategy module cannot provide generate_decisions."""


def load_decision_strategy(
    path: str | Path,
    *,
    repo_root: Path | None = None,
) -> DecisionStrategyCallable:
    root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
    strategy_path = Path(path).resolve()
    try:
        strategy_path.relative_to(root)
    except ValueError as exc:
        raise DecisionStrategyLoadError(
            f"strategy_path must resolve inside repository: {root}"
        ) from exc
    if not strategy_path.exists():
        raise DecisionStrategyLoadError(f"strategy file does not exist: {strategy_path}")
    if strategy_path.suffix != ".py":
        raise DecisionStrategyLoadError(f"strategy file must be a Python file: {strategy_path}")

    module_name = f"_quant_decision_strategy_{hashlib.sha1(str(strategy_path).encode()).hexdigest()}"
    spec = importlib.util.spec_from_file_location(module_name, strategy_path)
    if spec is None or spec.loader is None:
        raise DecisionStrategyLoadError(f"could not import strategy file: {strategy_path}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise DecisionStrategyLoadError(f"strategy import failed: {exc}") from exc

    generate_decisions = getattr(module, "generate_decisions", None)
    if not callable(generate_decisions):
        raise DecisionStrategyLoadError(
            "strategy file must define callable generate_decisions(rows, params)"
        )
    return generate_decisions
```

- [ ] **Step 4: Export the loader**

Modify `src/quant_strategies/decisions/__init__.py`:

```python
from quant_strategies.decisions.models import (
    Direction,
    ExitPolicy,
    InstrumentKind,
    InstrumentRef,
    PositionTarget,
    SizingKind,
    StrategyDecision,
)
from quant_strategies.decisions.strategy_loader import (
    DecisionStrategyCallable,
    DecisionStrategyLoadError,
    load_decision_strategy,
)

__all__ = [
    "DecisionStrategyCallable",
    "DecisionStrategyLoadError",
    "Direction",
    "ExitPolicy",
    "InstrumentKind",
    "InstrumentRef",
    "PositionTarget",
    "SizingKind",
    "StrategyDecision",
    "load_decision_strategy",
]
```

- [ ] **Step 5: Delegate validation loader to shared loader**

Replace the import machinery in `src/quant_strategies/validation/strategy_loader.py`
with a thin wrapper:

```python
from __future__ import annotations

from pathlib import Path

from quant_strategies.decisions import (
    DecisionStrategyCallable,
    DecisionStrategyLoadError,
    load_decision_strategy as _load_decision_strategy,
)
from quant_strategies.validation.errors import ValidationStrategyLoadError


def load_decision_strategy(
    path: str | Path,
    *,
    repo_root: Path | None = None,
) -> DecisionStrategyCallable:
    try:
        return _load_decision_strategy(path, repo_root=repo_root)
    except DecisionStrategyLoadError as exc:
        raise ValidationStrategyLoadError(str(exc)) from exc
```

- [ ] **Step 6: Run validation loader tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_strategy_loader.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/quant_strategies/decisions/__init__.py \
  src/quant_strategies/decisions/strategy_loader.py \
  src/quant_strategies/validation/strategy_loader.py \
  tests/test_validation_strategy_loader.py
git commit -m "refactor: share decision strategy loader"
```

## Task 2: Runner Loads Decisions

**Files:**
- Modify: `src/quant_strategies/runner/strategy_loader.py`
- Test: `tests/test_runner_strategy_loader.py`

- [ ] **Step 1: Replace runner loader tests**

Update `tests/test_runner_strategy_loader.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from quant_strategies.decisions import StrategyDecision
from quant_strategies.runner.errors import StrategyLoadError
from quant_strategies.runner.strategy_loader import load_strategy


def test_load_strategy_returns_generate_decisions_callable(tmp_path: Path):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True)
    strategy.write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='equity_or_etf', symbol='SPY'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )

    generate_decisions = load_strategy(strategy, repo_root=tmp_path)
    rows = [{"symbol": "SPY", "timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc)}]

    decisions = generate_decisions(rows, {})

    assert callable(generate_decisions)
    assert isinstance(decisions[0], StrategyDecision)
    assert decisions[0].instrument.symbol == "SPY"


def test_load_strategy_rejects_file_without_generate_decisions(tmp_path: Path):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True)
    strategy.write_text("def generate_signals(rows, params):\n    return []\n")

    with pytest.raises(StrategyLoadError, match="generate_decisions"):
        load_strategy(strategy, repo_root=tmp_path)
```

- [ ] **Step 2: Run runner loader tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_runner_strategy_loader.py -q
```

Expected before implementation: fail because `load_strategy` still expects
`generate_signals`.

- [ ] **Step 3: Change runner loader to wrap shared decision loader**

Replace `src/quant_strategies/runner/strategy_loader.py`:

```python
from __future__ import annotations

from pathlib import Path

from quant_strategies.decisions import (
    DecisionStrategyCallable,
    DecisionStrategyLoadError,
    load_decision_strategy,
)
from quant_strategies.runner.errors import StrategyLoadError


StrategyCallable = DecisionStrategyCallable


def load_strategy(path: str | Path, *, repo_root: Path | None = None) -> StrategyCallable:
    try:
        return load_decision_strategy(path, repo_root=repo_root)
    except DecisionStrategyLoadError as exc:
        raise StrategyLoadError(str(exc)) from exc
```

- [ ] **Step 4: Run runner and validation loader tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_strategy_loader.py tests/test_validation_strategy_loader.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/quant_strategies/runner/strategy_loader.py tests/test_runner_strategy_loader.py
git commit -m "refactor: make runner load decision strategies"
```

## Task 3: Decision-To-Signal Adapter For The Smoke Engine

**Files:**
- Create: `src/quant_strategies/runner/decision_adapter.py`
- Test: `tests/test_runner_engine_runner.py`

- [ ] **Step 1: Add adapter tests**

Append to `tests/test_runner_engine_runner.py`:

```python
from datetime import datetime, timezone

import pytest

from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.runner.decision_adapter import decisions_to_signal_rows
from quant_strategies.runner.errors import RequestBuildError


def decision(
    *,
    direction: str = "long",
    sizing_kind: str = "target_weight",
    size: float = 0.5,
) -> StrategyDecision:
    timestamp = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    return StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="equity_or_etf", symbol="SPY"),
        decision_time=timestamp,
        as_of_time=timestamp,
        target=PositionTarget(direction=direction, sizing_kind=sizing_kind, size=size),
        exit_policy=ExitPolicy(
            max_hold_bars=3,
            stop_loss_bps=100.0,
            take_profit_bps=200.0,
        ),
        metadata={"source": "test"},
    )


def test_decisions_to_signal_rows_preserves_engine_fields():
    rows = decisions_to_signal_rows([decision()])

    assert rows == [
        {
            "symbol": "SPY",
            "decision_time": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
            "as_of_time": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
            "side": "long",
            "weight": 0.5,
            "hold_bars": 3,
            "max_hold_bars": 3,
            "stop_loss_bps": 100.0,
            "take_profit_bps": 200.0,
            "metadata": {"source": "test"},
        }
    ]


def test_decisions_to_signal_rows_rejects_flat_targets():
    with pytest.raises(RequestBuildError, match="flat target"):
        decisions_to_signal_rows([decision(direction="flat", size=0.0)])


def test_decisions_to_signal_rows_rejects_non_target_weight():
    with pytest.raises(RequestBuildError, match="target_weight"):
        decisions_to_signal_rows([decision(sizing_kind="notional")])
```

If this creates duplicate imports in the file, merge them rather than adding a
second import block.

- [ ] **Step 2: Run adapter tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_runner_engine_runner.py::test_decisions_to_signal_rows_preserves_engine_fields tests/test_runner_engine_runner.py::test_decisions_to_signal_rows_rejects_flat_targets tests/test_runner_engine_runner.py::test_decisions_to_signal_rows_rejects_non_target_weight -q
```

Expected before implementation: fail because
`quant_strategies.runner.decision_adapter` does not exist.

- [ ] **Step 3: Implement the adapter**

Create `src/quant_strategies/runner/decision_adapter.py`:

```python
from __future__ import annotations

from typing import Any

from quant_strategies.decisions import StrategyDecision
from quant_strategies.runner.errors import RequestBuildError


def decisions_to_signal_rows(decisions: list[StrategyDecision]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for decision in decisions:
        if decision.target.direction == "flat":
            raise RequestBuildError(
                f"smoke engine cannot represent flat target for {decision.instrument.symbol}"
            )
        if decision.target.sizing_kind != "target_weight":
            raise RequestBuildError(
                "smoke engine decision adapter requires target_weight sizing: "
                f"{decision.instrument.symbol}"
            )

        row: dict[str, Any] = {
            "symbol": decision.instrument.symbol,
            "decision_time": decision.decision_time,
            "as_of_time": decision.as_of_time,
            "side": decision.target.direction,
            "weight": decision.target.size,
            "hold_bars": decision.exit_policy.max_hold_bars,
            "max_hold_bars": decision.exit_policy.max_hold_bars,
            "metadata": dict(decision.metadata),
        }
        if decision.exit_policy.stop_loss_bps is not None:
            row["stop_loss_bps"] = decision.exit_policy.stop_loss_bps
        if decision.exit_policy.take_profit_bps is not None:
            row["take_profit_bps"] = decision.exit_policy.take_profit_bps
        if decision.exit_policy.trailing_stop_bps is not None:
            row["trailing_stop_bps"] = decision.exit_policy.trailing_stop_bps
        rows.append(row)
    return rows
```

- [ ] **Step 4: Run adapter tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_engine_runner.py -q
```

Expected: all runner engine tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/quant_strategies/runner/decision_adapter.py tests/test_runner_engine_runner.py
git commit -m "feat: adapt strategy decisions for smoke engine"
```

## Task 4: Runner Executes Decisions And Writes Decision Records

**Files:**
- Modify: `src/quant_strategies/runner/__init__.py`
- Modify: `src/quant_strategies/runner/artifacts.py`
- Test: `tests/test_runner_api_cli.py`

- [ ] **Step 1: Add runner artifact expectations**

Update runner API tests that create temporary strategies so they expose
`generate_decisions`. A minimal temporary strategy body should look like:

```python
from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision

def generate_decisions(rows, params):
    return [
        StrategyDecision(
            strategy_id="demo",
            instrument=InstrumentRef(kind="equity_or_etf", symbol=rows[0]["symbol"]),
            decision_time=rows[1]["timestamp"],
            as_of_time=rows[0]["timestamp"],
            target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
            exit_policy=ExitPolicy(max_hold_bars=1),
        )
    ]
```

In the existing successful runner artifact test, add:

```python
assert (result.result_dir / "decision_records.jsonl").exists()
decision_records = (result.result_dir / "decision_records.jsonl").read_text().splitlines()
assert len(decision_records) == 1
assert '"strategy_id":"demo"' in decision_records[0] or '"strategy_id": "demo"' in decision_records[0]
```

Keep existing `signals.csv` assertions for this phase because `signals.csv`
remains an internal smoke-engine artifact generated from decisions.

- [ ] **Step 2: Run focused runner test and verify failure**

Run the updated successful-run artifact test:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_writes_success_artifacts -q
```

Expected before implementation: failure because `decision_records.jsonl` is
not written and runner still calls the loaded callable as signals.

- [ ] **Step 3: Add decision artifact writer**

Add to `src/quant_strategies/runner/artifacts.py`:

```python
def write_decision_records(result_dir: Path, decisions: list[Any]) -> None:
    lines = [
        item.model_dump_json() if hasattr(item, "model_dump_json") else json.dumps(_json_value(item), sort_keys=True)
        for item in decisions
    ]
    (result_dir / "decision_records.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""))
```

Place it near `write_signals`.

- [ ] **Step 4: Change runner flow to call decisions**

Modify `src/quant_strategies/runner/__init__.py`:

```python
from quant_strategies.runner import artifacts, config as config_module, data_loader, data_readiness, engine_runner, strategy_loader
from quant_strategies.runner.decision_adapter import decisions_to_signal_rows
```

Then replace the signal generation block:

```python
try:
    decisions = generate_signals(loaded.rows, config.params)
    artifacts.write_signals(result_dir, signals)
except Exception as exc:
    ...
```

with:

```python
try:
    decisions = generate_decisions(loaded.rows, config.params)
    artifacts.write_decision_records(result_dir, decisions)
    signals = decisions_to_signal_rows(decisions)
    artifacts.write_signals(result_dir, signals)
except Exception as exc:
    return _failure_result(
        config,
        result_dir,
        "decision_generation",
        f"strategy execution failed: {exc}",
        repo_root=effective_repo_root,
    )
```

Also rename the local loaded callable:

```python
generate_decisions = strategy_loader.load_strategy(config.strategy_path, repo_root=effective_repo_root)
```

The stage name changes from `signal_generation` to `decision_generation`.
Update tests that assert the old stage string.

- [ ] **Step 5: Run runner API tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py -q
```

Expected: runner API tests pass after updating test strategy bodies and stage
expectations.

- [ ] **Step 6: Commit**

```bash
git add src/quant_strategies/runner/__init__.py \
  src/quant_strategies/runner/artifacts.py \
  tests/test_runner_api_cli.py
git commit -m "feat: run strategies through decision contract"
```

## Task 5: Convert The Smoke Fixture Strategy

**Files:**
- Modify: `tested/simple_momentum.py`
- Test: `tests/test_simple_momentum.py`

- [ ] **Step 1: Update smoke fixture tests**

Change `tests/test_simple_momentum.py` to import `generate_decisions`:

```python
from tested.simple_momentum import generate_decisions
```

Update assertions so they check `StrategyDecision` fields instead of signal
dict fields. For the first positive-momentum test, assert:

```python
decisions = generate_decisions(bars_for([100.0, 101.0, 100.0]), {"weight": 1.0, "hold_bars": 1})

assert len(decisions) == 1
decision = decisions[0]
assert decision.instrument.symbol == "SPY"
assert decision.decision_time == bars_for([100.0, 101.0, 100.0])[1]["timestamp"]
assert decision.as_of_time == decision.decision_time
assert decision.target.direction == "long"
assert decision.target.size == 1.0
assert decision.exit_policy.max_hold_bars == 1
```

For tests that expected empty signal lists, assert `generate_decisions(...) == []`.

- [ ] **Step 2: Run fixture tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_simple_momentum.py -q
```

Expected before implementation: fail because `generate_decisions` does not
exist.

- [ ] **Step 3: Convert `tested/simple_momentum.py`**

Replace the public function with:

```python
from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision


def generate_decisions(
    bars: Sequence[Mapping[str, object]],
    params: Mapping[str, object],
) -> list[StrategyDecision]:
    weight = float(params.get("weight", 1.0))
    hold_bars = int(params.get("hold_bars", 1))
    decisions: list[StrategyDecision] = []

    for index in range(1, len(bars)):
        previous_close = float(bars[index - 1]["close"])
        current_close = float(bars[index]["close"])
        if current_close > previous_close:
            timestamp = bars[index]["timestamp"]
            decisions.append(
                StrategyDecision(
                    strategy_id="simple_momentum",
                    instrument=InstrumentRef(
                        kind="equity_or_etf",
                        symbol=str(bars[index]["symbol"]),
                    ),
                    decision_time=timestamp,
                    as_of_time=timestamp,
                    target=PositionTarget(
                        direction="long",
                        sizing_kind="target_weight",
                        size=weight,
                    ),
                    exit_policy=ExitPolicy(max_hold_bars=hold_bars),
                )
            )
            break

    return decisions
```

Keep the module docstring. Remove `generate_signals`.

- [ ] **Step 4: Run fixture tests**

Run:

```bash
conda run -n quant pytest tests/test_simple_momentum.py -q
```

Expected: all fixture tests pass.

- [ ] **Step 5: Commit**

```bash
git add tested/simple_momentum.py tests/test_simple_momentum.py
git commit -m "refactor: convert smoke fixture to decisions"
```

## Task 6: Documentation And Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-05-26-foundation-repair-design.md` only if implementation reveals a design correction

- [ ] **Step 1: Update README strategy contract language**

In `README.md`, replace the opening contract claim:

```markdown
Strategy files stay pure: they expose `generate_signals(bars, params)` and do
not call engines, load data, start loops, or write artifacts.
```

with:

```markdown
Strategy files stay pure: foundation strategies expose
`generate_decisions(rows, params)` and do not call engines, load data, start
loops, or write artifacts.
```

In the validation section, keep the `generate_decisions` snippet and remove
language that treats `generate_signals` as an equal quick-research contract.
Use:

```markdown
The runner and validation workflows share the same decision contract. The
runner adapts `StrategyDecision` objects to its internal smoke engine request;
strategy files do not emit engine-specific signals.
```

- [ ] **Step 2: Run focused phase tests**

Run:

```bash
conda run -n quant pytest \
  tests/test_runner_strategy_loader.py \
  tests/test_validation_strategy_loader.py \
  tests/test_runner_engine_runner.py \
  tests/test_runner_api_cli.py \
  tests/test_simple_momentum.py \
  -q
```

Expected: all focused tests pass.

- [ ] **Step 3: Run the full suite**

Run:

```bash
conda run -n quant pytest -q
```

Expected: all tests pass.

- [ ] **Step 4: Search for stale foundation contract wording**

Run:

```bash
rg -n "generate_signals|signal-only|StrategyCallable|signal_generation" README.md src tests docs/superpowers/specs/2026-05-26-foundation-repair-design.md
```

Expected:

- `generate_signals` may still appear in historical design docs, old strategy
  files not touched by this phase, and review docs.
- It should not appear as the current foundation runner contract in `README.md`,
  `src/quant_strategies/runner/strategy_loader.py`, or active runner tests.
- `signal_generation` should not appear as a runner failure stage.

- [ ] **Step 5: Commit docs and any final cleanup**

```bash
git add README.md docs/superpowers/specs/2026-05-26-foundation-repair-design.md
git commit -m "docs: document decision strategy contract"
```

Skip this commit if README and spec already match the implementation and no
files changed in this task.

## Task 7: Phase 1 Completion Review

**Files:**
- No required source changes.

- [ ] **Step 1: Inspect final diff**

Run:

```bash
git status --short
git log --oneline -6
```

Expected:

- Only intended Phase 1 files are changed/committed.
- Pre-existing unrelated dirty files remain untouched.

- [ ] **Step 2: Record phase result**

Append a short note to the final response, not a file:

```text
Phase 1 complete:
- runner and validation now share generate_decisions / StrategyDecision
- smoke engine signal conversion is internal
- focused tests passed
- full suite passed
- next plan should be Phase 2 evidence semantics
```

- [ ] **Step 3: Stop before Phase 2**

Do not implement evidence semantics in this plan. Write a separate Phase 2 plan
after Phase 1 is merged and the repo state is rechecked.
