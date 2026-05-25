# Researched Strategy Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first conservative `researched/` to `tested/` validation gate around a typed `generate_decisions` strategy contract and backend adapters.

**Architecture:** Keep the current `runner/` and `engine/` smoke workflow intact. Add `decisions/` for canonical strategy decision models and `validation/` for package intake, data audit, backend execution, artifacts, decision policy, and the `quant-strategies validate` command. Use a fake backend in unit tests and keep VectorBT PRO behind `VectorBTProBackend` so strategy files never import backend-specific APIs.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, `quant_data` loader APIs through the existing runner data loader, VectorBT PRO 2026.4.7 for the first real backend.

---

## Scope Check

This plan implements the first end-to-end single-strategy validation slice. It does not implement portfolio allocation, paper trading, live execution, options, margin liquidation, borrow constraints, market impact, exchange rejects, or intrabar path ordering. Candidates requiring those semantics should be classified as `maybe` with an explicit unsupported-semantics reason.

## File Structure

- Create `src/quant_strategies/decisions/models.py`: typed validation strategy decision contract.
- Create `src/quant_strategies/decisions/__init__.py`: public decision model exports.
- Create `src/quant_strategies/validation/errors.py`: validation-specific exception types.
- Create `src/quant_strategies/validation/strategy_loader.py`: load `generate_decisions` from a strategy file.
- Create `src/quant_strategies/validation/config.py`: validation TOML parsing, package resolution, and per-window run config materialization.
- Create `src/quant_strategies/validation/data_audit.py`: decision/data causality and coverage checks.
- Create `src/quant_strategies/validation/matrix.py`: validation scenario definitions and matrix expansion.
- Create `src/quant_strategies/validation/backends.py`: backend protocol, result model, fake backend, backend selection.
- Create `src/quant_strategies/validation/vectorbtpro_backend.py`: VectorBT PRO adapter for v1 supported max-hold directional target decisions.
- Create `src/quant_strategies/validation/policy.py`: `hard_no` / `maybe` / `clear_yes` classification.
- Create `src/quant_strategies/validation/artifacts.py`: validation artifact writer.
- Create `src/quant_strategies/validation/__init__.py`: public `run_validation` API.
- Modify `src/quant_strategies/runner/cli.py`: add `validate` subcommand.
- Modify `.gitignore`: ignore `validation_results/`.
- Modify `README.md`: document validation command, lifecycle meaning, and generated artifacts.
- Modify one selected researched variant to expose `generate_decisions` after infrastructure exists.

---

## Eng Review Decisions

These decisions supersede any older code snippets below that show a simpler
one-backend-run-per-window validator:

- Validation must expand a required matrix before any `clear_yes` result:
  base windows, realistic costs, stressed costs, fill-lag sensitivity, and
  parameter perturbations.
- Validation must load rows once per window, then reuse those rows across all
  matrix scenarios for that window.
- When config loading succeeds, data load failures, strategy import failures,
  `generate_decisions` failures, audit failures, backend failures, and
  unsupported semantics must still write `promotion_decision.json` and
  `validation_report.md`.
- `PositionTarget.size` with `sizing_kind = "target_weight"` must affect the
  VectorBT PRO backend run. Unsupported sizing must be rejected explicitly.
- Missing symbols, missing decision bars, missing entry fills, and missing exit
  fills must not be silently skipped. Classify them as `hard_no` unless the
  artifact explicitly shows a fair-test data-coverage limitation, in which case
  use `maybe`.
- Tests must cover matrix expansion, failure artifacts, backend sizing, and
  unfillable-decision rejection.

Validation data flow:

```text
validation.toml
  -> load rows once per window
  -> generate_decisions(rows, params)
  -> data audit
  -> expand validation matrix
       base / realistic costs / stressed costs / fill lag / params
  -> backend adapter runs
  -> aggregate matrix results
  -> hard_no | maybe | clear_yes
  -> artifacts + report
```

---

### Task 1: Typed Strategy Decision Models

**Files:**
- Create: `src/quant_strategies/decisions/models.py`
- Create: `src/quant_strategies/decisions/__init__.py`
- Test: `tests/test_decision_models.py`

- [ ] **Step 1: Write failing tests for the decision contract**

Create `tests/test_decision_models.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from quant_strategies.decisions import (
    ExitPolicy,
    InstrumentRef,
    PositionTarget,
    StrategyDecision,
)


DECISION_TIME = datetime(2026, 1, 2, 12, 1, tzinfo=timezone.utc)
AS_OF_TIME = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)


def test_strategy_decision_accepts_explicit_position_target():
    decision = StrategyDecision(
        strategy_id="crypto_perp_funding_crowding_reversal",
        instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
        decision_time=DECISION_TIME,
        as_of_time=AS_OF_TIME,
        target=PositionTarget(direction="short", sizing_kind="target_weight", size=1.0),
        exit_policy=ExitPolicy(max_hold_bars=480),
        metadata={"funding_pressure_bps": 3.5},
    )

    assert decision.instrument.symbol == "BTC-PERP"
    assert decision.target.direction == "short"
    assert decision.exit_policy.max_hold_bars == 480


def test_strategy_decision_requires_timezone_aware_times():
    with pytest.raises(ValidationError, match="decision_time must be timezone-aware"):
        StrategyDecision(
            strategy_id="demo",
            instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
            decision_time=datetime(2026, 1, 2, 12, 1),
            as_of_time=AS_OF_TIME,
            target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
            exit_policy=ExitPolicy(max_hold_bars=5),
        )


def test_strategy_decision_rejects_lookahead_as_of_time():
    with pytest.raises(ValidationError, match="as_of_time must be on or before decision_time"):
        StrategyDecision(
            strategy_id="demo",
            instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
            decision_time=AS_OF_TIME,
            as_of_time=DECISION_TIME,
            target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
            exit_policy=ExitPolicy(max_hold_bars=5),
        )


def test_position_target_rejects_raw_order_language():
    with pytest.raises(ValidationError):
        PositionTarget(direction="sell", sizing_kind="target_weight", size=1.0)


def test_flat_target_must_have_zero_size():
    with pytest.raises(ValidationError, match="flat target size must be 0"):
        PositionTarget(direction="flat", sizing_kind="target_weight", size=1.0)


def test_non_flat_target_must_have_positive_size():
    with pytest.raises(ValidationError, match="long and short target size must be positive"):
        PositionTarget(direction="short", sizing_kind="target_weight", size=0.0)


def test_exit_policy_rejects_non_positive_thresholds():
    with pytest.raises(ValidationError, match="exit bps values must be finite and positive"):
        ExitPolicy(max_hold_bars=5, stop_loss_bps=0.0)


def test_metadata_must_be_json_compatible():
    with pytest.raises(ValidationError, match="metadata must be JSON-compatible"):
        StrategyDecision(
            strategy_id="demo",
            instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
            decision_time=DECISION_TIME,
            as_of_time=AS_OF_TIME,
            target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
            exit_policy=ExitPolicy(max_hold_bars=5),
            metadata={"bad": {1, 2, 3}},
        )
```

- [ ] **Step 2: Run the tests and verify they fail for missing module**

Run:

```bash
conda run -n quant pytest tests/test_decision_models.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'quant_strategies.decisions'`.

- [ ] **Step 3: Create the decision models**

Create `src/quant_strategies/decisions/models.py`:

```python
from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


InstrumentKind = Literal["equity_or_etf", "fx_pair", "crypto_perp"]
Direction = Literal["long", "short", "flat"]
SizingKind = Literal["target_weight", "notional"]


class DecisionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _timezone_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _validate_positive_bps(*values: float | None) -> None:
    if any(value is not None and (not math.isfinite(value) or value <= 0.0) for value in values):
        raise ValueError("exit bps values must be finite and positive")


class InstrumentRef(DecisionModel):
    kind: InstrumentKind
    symbol: str = Field(min_length=1)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        symbol = value.strip()
        if not symbol:
            raise ValueError("symbol cannot be empty")
        return symbol


class PositionTarget(DecisionModel):
    direction: Direction
    sizing_kind: SizingKind = "target_weight"
    size: float = Field(ge=0.0)

    @model_validator(mode="after")
    def validate_size(self) -> PositionTarget:
        if not math.isfinite(self.size):
            raise ValueError("size must be finite")
        if self.direction == "flat" and self.size != 0.0:
            raise ValueError("flat target size must be 0")
        if self.direction in {"long", "short"} and self.size <= 0.0:
            raise ValueError("long and short target size must be positive")
        return self


class ExitPolicy(DecisionModel):
    max_hold_bars: int = Field(ge=1)
    stop_loss_bps: float | None = None
    take_profit_bps: float | None = None
    trailing_stop_bps: float | None = None

    @model_validator(mode="after")
    def validate_thresholds(self) -> ExitPolicy:
        _validate_positive_bps(self.stop_loss_bps, self.take_profit_bps, self.trailing_stop_bps)
        return self


class StrategyDecision(DecisionModel):
    strategy_id: str = Field(min_length=1)
    instrument: InstrumentRef
    decision_time: datetime
    as_of_time: datetime
    target: PositionTarget
    exit_policy: ExitPolicy
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("strategy_id")
    @classmethod
    def normalize_strategy_id(cls, value: str) -> str:
        strategy_id = value.strip()
        if not strategy_id:
            raise ValueError("strategy_id cannot be empty")
        return strategy_id

    @field_validator("decision_time", "as_of_time")
    @classmethod
    def validate_time(cls, value: datetime, info) -> datetime:
        return _timezone_aware(value, info.field_name)

    @model_validator(mode="after")
    def validate_decision(self) -> StrategyDecision:
        if self.as_of_time > self.decision_time:
            raise ValueError("as_of_time must be on or before decision_time")
        try:
            json.dumps(self.metadata, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must be JSON-compatible") from exc
        return self
```

- [ ] **Step 4: Export the models**

Create `src/quant_strategies/decisions/__init__.py`:

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

__all__ = [
    "Direction",
    "ExitPolicy",
    "InstrumentKind",
    "InstrumentRef",
    "PositionTarget",
    "SizingKind",
    "StrategyDecision",
]
```

- [ ] **Step 5: Run model tests**

Run:

```bash
conda run -n quant pytest tests/test_decision_models.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/quant_strategies/decisions tests/test_decision_models.py
git commit -m "feat: add strategy decision models"
```

---

### Task 2: Validation Strategy Loader

**Files:**
- Create: `src/quant_strategies/validation/errors.py`
- Create: `src/quant_strategies/validation/strategy_loader.py`
- Test: `tests/test_validation_strategy_loader.py`

- [ ] **Step 1: Write failing loader tests**

Create `tests/test_validation_strategy_loader.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from quant_strategies.validation.errors import ValidationStrategyLoadError
from quant_strategies.validation.strategy_loader import load_decision_strategy


def write_strategy(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def test_load_decision_strategy_requires_generate_decisions(tmp_path: Path):
    strategy = write_strategy(tmp_path / "researched" / "demo" / "strategy.py", "def generate_signals(rows, params):\n    return []\n")

    with pytest.raises(ValidationStrategyLoadError, match="generate_decisions"):
        load_decision_strategy(strategy, repo_root=tmp_path)


def test_load_decision_strategy_rejects_outside_repo(tmp_path: Path):
    outside = write_strategy(tmp_path.parent / "outside_strategy.py", "def generate_decisions(rows, params):\n    return []\n")

    with pytest.raises(ValidationStrategyLoadError, match="inside repository"):
        load_decision_strategy(outside, repo_root=tmp_path)


def test_load_decision_strategy_returns_callable(tmp_path: Path):
    strategy = write_strategy(
        tmp_path / "researched" / "demo" / "strategy.py",
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n",
    )

    generate_decisions = load_decision_strategy(strategy, repo_root=tmp_path)
    rows = [
        {"timestamp": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)},
        {"timestamp": datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)},
    ]

    decisions = generate_decisions(rows, {})

    assert decisions[0].strategy_id == "demo"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_strategy_loader.py -q
```

Expected: fail because `quant_strategies.validation` does not exist.

- [ ] **Step 3: Add validation errors**

Create `src/quant_strategies/validation/errors.py`:

```python
from __future__ import annotations


class ValidationError(ValueError):
    """Base error for validation workflow failures."""


class ValidationConfigError(ValidationError):
    """Raised when validation configuration cannot be parsed."""


class ValidationStrategyLoadError(ValidationError):
    """Raised when a validation strategy cannot be imported."""


class ValidationDataError(ValidationError):
    """Raised when validation data or decision causality fails."""


class ValidationBackendError(ValidationError):
    """Raised when a validation backend cannot run the requested decisions."""
```

- [ ] **Step 4: Add the decision strategy loader**

Create `src/quant_strategies/validation/strategy_loader.py`:

```python
from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from quant_strategies.decisions import StrategyDecision
from quant_strategies.runner.config import default_repo_root
from quant_strategies.validation.errors import ValidationStrategyLoadError


DecisionStrategyCallable = Callable[[Sequence[Mapping[str, object]], Mapping[str, object]], list[StrategyDecision]]


def load_decision_strategy(path: str | Path, *, repo_root: Path | None = None) -> DecisionStrategyCallable:
    root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
    strategy_path = Path(path).resolve()
    try:
        strategy_path.relative_to(root)
    except ValueError as exc:
        raise ValidationStrategyLoadError(f"strategy_path must resolve inside repository: {root}") from exc
    if not strategy_path.exists():
        raise ValidationStrategyLoadError(f"strategy file does not exist: {strategy_path}")
    if strategy_path.suffix != ".py":
        raise ValidationStrategyLoadError(f"strategy file must be a Python file: {strategy_path}")

    module_name = f"_quant_validation_strategy_{hashlib.sha1(str(strategy_path).encode()).hexdigest()}"
    spec = importlib.util.spec_from_file_location(module_name, strategy_path)
    if spec is None or spec.loader is None:
        raise ValidationStrategyLoadError(f"could not import strategy file: {strategy_path}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ValidationStrategyLoadError(f"strategy import failed: {exc}") from exc

    generate_decisions = getattr(module, "generate_decisions", None)
    if not callable(generate_decisions):
        raise ValidationStrategyLoadError(
            "validation strategy file must define callable generate_decisions(rows, params)"
        )
    return generate_decisions
```

- [ ] **Step 5: Run loader tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_strategy_loader.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/quant_strategies/validation/errors.py src/quant_strategies/validation/strategy_loader.py tests/test_validation_strategy_loader.py
git commit -m "feat: load validation decision strategies"
```

---

### Task 3: Validation Configuration And Package Resolution

**Files:**
- Create: `src/quant_strategies/validation/config.py`
- Test: `tests/test_validation_config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/test_validation_config.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from quant_strategies.validation.config import load_validation_config, resolve_validation_config_path
from quant_strategies.validation.errors import ValidationConfigError


def write_strategy(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def generate_decisions(rows, params):\n    return []\n")


def write_config(path: Path, strategy_path: str = "researched/demo/strategy.py") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""
strategy_path = "{strategy_path}"
strategy_id = "demo"
backend = "fake"

[[windows]]
id = "validation_2026_h1"
start = "2026-01-01"
end = "2026-06-30"

[data]
kind = "crypto_perp_funding"
symbols = ["BTC-PERP"]
strict = true
start = "2026-01-01"
end = "2026-06-30"

[params]
weight = 1.0

[fill_model]
price = "close"
entry_lag_bars = 1
exit_lag_bars = 0

[cost_model]
fee_bps_per_side = 0.5
slippage_bps_per_side = 0.5

[output]
results_dir = "validation_results/demo"
""".lstrip()
    )


def test_resolve_validation_config_from_package_path(tmp_path: Path):
    package = tmp_path / "researched" / "demo"
    write_config(package / "validation.toml")

    resolved = resolve_validation_config_path(package, repo_root=tmp_path)

    assert resolved == package / "validation.toml"


def test_load_validation_config_resolves_paths_inside_repo(tmp_path: Path):
    write_strategy(tmp_path / "researched" / "demo" / "strategy.py")
    write_config(tmp_path / "researched" / "demo" / "validation.toml")

    config = load_validation_config(tmp_path / "researched" / "demo", repo_root=tmp_path)

    assert config.strategy_path == tmp_path / "researched" / "demo" / "strategy.py"
    assert config.output.results_dir == tmp_path / "validation_results" / "demo"
    assert config.windows[0].id == "validation_2026_h1"


def test_load_validation_config_rejects_generate_strategy_outside_repo(tmp_path: Path):
    outside = tmp_path.parent / "outside.py"
    outside.write_text("def generate_decisions(rows, params):\n    return []\n")
    write_config(tmp_path / "researched" / "demo" / "validation.toml", strategy_path=str(outside))

    with pytest.raises(ValidationConfigError, match="strategy_path must resolve inside repository"):
        load_validation_config(tmp_path / "researched" / "demo", repo_root=tmp_path)


def test_load_validation_config_rejects_empty_windows(tmp_path: Path):
    config_path = tmp_path / "researched" / "demo" / "validation.toml"
    write_config(config_path)
    config_text = config_path.read_text()
    config_path.write_text(config_text.replace("[[windows]]\nid = \"validation_2026_h1\"\nstart = \"2026-01-01\"\nend = \"2026-06-30\"\n\n", ""))

    with pytest.raises(ValidationConfigError, match="windows"):
        load_validation_config(tmp_path / "researched" / "demo", repo_root=tmp_path)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_config.py -q
```

Expected: fail because `quant_strategies.validation.config` does not exist.

- [ ] **Step 3: Add validation config models**

Create `src/quant_strategies/validation/config.py`:

```python
from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator, model_validator

from quant_strategies.runner.config import (
    CostModelConfig,
    DataConfig,
    FillModelConfig,
    OutputConfig as RunnerOutputConfig,
    RunConfig,
    _resolve_inside_repo,
    default_repo_root,
)
from quant_strategies.validation.errors import ValidationConfigError


BackendName = Literal["fake", "vectorbtpro"]


class ValidationConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _repo_root(info: ValidationInfo) -> Path:
    root = info.context.get("repo_root") if info.context else None
    return Path(root).resolve() if root is not None else default_repo_root()


class ValidationWindow(ValidationConfigModel):
    id: str = Field(min_length=1)
    start: date
    end: date

    @field_validator("id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        window_id = value.strip()
        if not window_id:
            raise ValueError("window id cannot be empty")
        return window_id

    @model_validator(mode="after")
    def validate_window(self) -> ValidationWindow:
        if self.end < self.start:
            raise ValueError("window end must be on or after start")
        return self


class ValidationOutputConfig(ValidationConfigModel):
    results_dir: Path

    @field_validator("results_dir")
    @classmethod
    def validate_results_dir(cls, value: Path, info: ValidationInfo) -> Path:
        return _resolve_inside_repo(value, _repo_root(info), "output.results_dir")


class ValidationConfig(ValidationConfigModel):
    strategy_path: Path
    strategy_id: str = Field(min_length=1)
    backend: BackendName = "vectorbtpro"
    windows: tuple[ValidationWindow, ...] = Field(min_length=1)
    data: DataConfig
    params: dict[str, Any] = Field(default_factory=dict)
    fill_model: FillModelConfig
    cost_model: CostModelConfig
    output: ValidationOutputConfig

    @field_validator("strategy_path")
    @classmethod
    def validate_strategy_path(cls, value: Path, info: ValidationInfo) -> Path:
        return _resolve_inside_repo(value, _repo_root(info), "strategy_path")

    @field_validator("strategy_id")
    @classmethod
    def normalize_strategy_id(cls, value: str) -> str:
        strategy_id = value.strip()
        if not strategy_id:
            raise ValueError("strategy_id cannot be empty")
        return strategy_id

    def to_run_config(self, window: ValidationWindow, *, results_dir: Path) -> RunConfig:
        return RunConfig(
            strategy_path=self.strategy_path,
            strategy_id=self.strategy_id,
            data=self.data.model_copy(update={"start": window.start, "end": window.end}),
            params=self.params,
            fill_model=self.fill_model,
            cost_model=self.cost_model,
            output=RunnerOutputConfig(results_dir=results_dir, mode="validate"),
        )


def resolve_validation_config_path(path: str | Path, *, repo_root: Path | None = None) -> Path:
    root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if candidate.is_dir():
        candidate = candidate / "validation.toml"
    return candidate


def load_validation_config(path: str | Path, *, repo_root: Path | None = None) -> ValidationConfig:
    root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
    config_path = resolve_validation_config_path(path, repo_root=root)
    try:
        payload = tomllib.loads(config_path.read_text())
    except OSError as exc:
        raise ValidationConfigError(f"could not read validation config: {config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValidationConfigError(f"invalid TOML in validation config: {exc}") from exc

    try:
        return ValidationConfig.model_validate(payload, context={"repo_root": root})
    except ValidationError as exc:
        raise ValidationConfigError(str(exc)) from exc
```

- [ ] **Step 4: Run config tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_config.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/quant_strategies/validation/config.py tests/test_validation_config.py
git commit -m "feat: add validation config loading"
```

---

### Task 3A: Validation Matrix Scenarios

**Files:**
- Create: `src/quant_strategies/validation/matrix.py`
- Test: `tests/test_validation_matrix.py`

- [ ] **Step 1: Write failing matrix tests**

Create `tests/test_validation_matrix.py`:

```python
from __future__ import annotations

from quant_strategies.validation.matrix import MatrixScenario, expand_validation_matrix


def test_expand_validation_matrix_includes_required_v1_scenarios():
    scenarios = expand_validation_matrix(
        window_id="validation_2026_h1",
        base_params={"threshold": 1.0},
        base_costs={"fee_bps_per_side": 0.5, "slippage_bps_per_side": 0.5},
        base_fill={"entry_lag_bars": 1, "exit_lag_bars": 0},
    )

    names = {scenario.id for scenario in scenarios}

    assert "validation_2026_h1/base" in names
    assert "validation_2026_h1/realistic_costs" in names
    assert "validation_2026_h1/stressed_costs" in names
    assert "validation_2026_h1/fill_lag_plus_1" in names
    assert "validation_2026_h1/param_threshold_down_10pct" in names
    assert "validation_2026_h1/param_threshold_up_10pct" in names
    assert all(scenario.required for scenario in scenarios)


def test_matrix_scenario_records_overrides_explicitly():
    scenario = MatrixScenario(
        id="validation_2026_h1/stressed_costs",
        kind="cost_stress",
        required=True,
        params={},
        cost_model={"fee_bps_per_side": 2.0, "slippage_bps_per_side": 2.0},
        fill_model={},
    )

    assert scenario.kind == "cost_stress"
    assert scenario.cost_model["fee_bps_per_side"] == 2.0
```

- [ ] **Step 2: Run matrix tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_matrix.py -q
```

Expected: fail because `quant_strategies.validation.matrix` does not exist.

- [ ] **Step 3: Add matrix scenario models and expansion**

Create `src/quant_strategies/validation/matrix.py`:

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ScenarioKind = Literal["base", "cost", "cost_stress", "fill_lag", "parameter"]


class MatrixScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    kind: ScenarioKind
    required: bool = True
    params: dict[str, Any] = Field(default_factory=dict)
    cost_model: dict[str, Any] = Field(default_factory=dict)
    fill_model: dict[str, Any] = Field(default_factory=dict)


def expand_validation_matrix(
    *,
    window_id: str,
    base_params: dict[str, Any],
    base_costs: dict[str, Any],
    base_fill: dict[str, Any],
) -> tuple[MatrixScenario, ...]:
    scenarios: list[MatrixScenario] = [
        MatrixScenario(id=f"{window_id}/base", kind="base", params=base_params),
        MatrixScenario(id=f"{window_id}/realistic_costs", kind="cost", cost_model=base_costs),
        MatrixScenario(
            id=f"{window_id}/stressed_costs",
            kind="cost_stress",
            cost_model={
                "fee_bps_per_side": float(base_costs.get("fee_bps_per_side", 0.0)) * 2.0,
                "slippage_bps_per_side": float(base_costs.get("slippage_bps_per_side", 0.0)) * 2.0,
            },
        ),
        MatrixScenario(
            id=f"{window_id}/fill_lag_plus_1",
            kind="fill_lag",
            fill_model={
                **base_fill,
                "entry_lag_bars": int(base_fill.get("entry_lag_bars", 1)) + 1,
            },
        ),
    ]
    for name, value in base_params.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        scenarios.append(
            MatrixScenario(
                id=f"{window_id}/param_{name}_down_10pct",
                kind="parameter",
                params={**base_params, name: float(value) * 0.9},
            )
        )
        scenarios.append(
            MatrixScenario(
                id=f"{window_id}/param_{name}_up_10pct",
                kind="parameter",
                params={**base_params, name: float(value) * 1.1},
            )
        )
        break
    return tuple(scenarios)
```

- [ ] **Step 4: Run matrix tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_matrix.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/quant_strategies/validation/matrix.py tests/test_validation_matrix.py
git commit -m "feat: expand validation matrix scenarios"
```

---

### Task 4: Decision Data Audit

**Files:**
- Create: `src/quant_strategies/validation/data_audit.py`
- Test: `tests/test_validation_data_audit.py`

- [ ] **Step 1: Write failing data audit tests**

Create `tests/test_validation_data_audit.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.validation.data_audit import audit_decision_rows


AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


def decision(symbol: str = "BTC-PERP") -> StrategyDecision:
    return StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol=symbol),
        decision_time=DECISION,
        as_of_time=AS_OF,
        target=PositionTarget(direction="short", sizing_kind="target_weight", size=1.0),
        exit_policy=ExitPolicy(max_hold_bars=2),
    )


def test_audit_passes_when_as_of_row_is_available_by_decision_time():
    rows = [
        {
            "symbol": "BTC-PERP",
            "timestamp": AS_OF,
            "available_at": DECISION,
            "close": 100.0,
        }
    ]

    audit = audit_decision_rows(rows, [decision()])

    assert audit.passed is True
    assert audit.decision_count == 1
    assert audit.violations == ()


def test_audit_fails_when_as_of_row_is_missing():
    audit = audit_decision_rows([], [decision()])

    assert audit.passed is False
    assert audit.violations == ("missing as_of row for BTC-PERP at 2026-01-01T00:00:00+00:00",)


def test_audit_fails_when_available_after_decision_time():
    rows = [
        {
            "symbol": "BTC-PERP",
            "timestamp": AS_OF,
            "available_at": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
            "close": 100.0,
        }
    ]

    audit = audit_decision_rows(rows, [decision()])

    assert audit.passed is False
    assert audit.violations == (
        "as_of row for BTC-PERP at 2026-01-01T00:00:00+00:00 was available after decision_time",
    )
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_data_audit.py -q
```

Expected: fail because `data_audit.py` does not exist.

- [ ] **Step 3: Add data audit implementation**

Create `src/quant_strategies/validation/data_audit.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from quant_strategies.decisions import StrategyDecision


class DataAudit(BaseModel):
    model_config = ConfigDict(frozen=True)

    row_count: int
    decision_count: int
    passed: bool
    violations: tuple[str, ...] = ()


def audit_decision_rows(rows: list[dict[str, Any]], decisions: list[StrategyDecision]) -> DataAudit:
    row_index = {
        (str(row.get("symbol")), row.get("timestamp")): row
        for row in rows
    }
    violations: list[str] = []
    for decision in decisions:
        key = (decision.instrument.symbol, decision.as_of_time)
        row = row_index.get(key)
        if row is None:
            violations.append(
                f"missing as_of row for {decision.instrument.symbol} at {decision.as_of_time.isoformat()}"
            )
            continue
        available_at = row.get("available_at")
        if isinstance(available_at, datetime) and available_at > decision.decision_time:
            violations.append(
                f"as_of row for {decision.instrument.symbol} at {decision.as_of_time.isoformat()} "
                "was available after decision_time"
            )

    return DataAudit(
        row_count=len(rows),
        decision_count=len(decisions),
        passed=not violations,
        violations=tuple(violations),
    )
```

- [ ] **Step 4: Run data audit tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_data_audit.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/quant_strategies/validation/data_audit.py tests/test_validation_data_audit.py
git commit -m "feat: audit validation decision data"
```

---

### Task 5: Backend Contract And Decision Policy

**Files:**
- Create: `src/quant_strategies/validation/backends.py`
- Create: `src/quant_strategies/validation/policy.py`
- Test: `tests/test_validation_backends_and_policy.py`

- [ ] **Step 1: Write failing backend and policy tests**

Create `tests/test_validation_backends_and_policy.py`:

```python
from __future__ import annotations

from quant_strategies.validation.backends import BackendRunResult, FakeBackend, get_backend
from quant_strategies.validation.policy import classify_validation


def test_fake_backend_returns_configured_result():
    backend = FakeBackend(
        BackendRunResult(
            backend="fake",
            status="completed",
            metrics={"net_return": 0.02, "trade_count": 25},
            warnings=(),
            unsupported_semantics=(),
        )
    )

    result = backend.run(decisions=[], rows=[], config=None)

    assert result.backend == "fake"
    assert result.metrics["trade_count"] == 25


def test_get_backend_rejects_unknown_backend_name():
    try:
        get_backend("missing")
    except ValueError as exc:
        assert "unsupported validation backend" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_policy_hard_no_for_data_failure():
    decision = classify_validation(
        data_passed=False,
        backend_results=[],
        min_trades=10,
    )

    assert decision.decision == "hard_no"
    assert "data_audit_failed" in decision.reasons


def test_policy_maybe_for_unsupported_semantics():
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            BackendRunResult(
                backend="fake",
                status="unsupported",
                metrics={},
                warnings=(),
                unsupported_semantics=("trailing_stop",),
            )
        ],
        min_trades=10,
    )

    assert decision.decision == "maybe"
    assert "unsupported_semantics" in decision.reasons


def test_policy_clear_yes_for_positive_sufficient_backend_result():
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            BackendRunResult(
                backend="fake",
                status="completed",
                metrics={"net_return": 0.03, "trade_count": 50},
                warnings=(),
                unsupported_semantics=(),
            )
        ],
        min_trades=10,
    )

    assert decision.decision == "clear_yes"
    assert decision.reasons == ()


def test_policy_hard_no_for_negative_net_return():
    decision = classify_validation(
        data_passed=True,
        backend_results=[
            BackendRunResult(
                backend="fake",
                status="completed",
                metrics={"net_return": -0.01, "trade_count": 50},
                warnings=(),
                unsupported_semantics=(),
            )
        ],
        min_trades=10,
    )

    assert decision.decision == "hard_no"
    assert "negative_net_return" in decision.reasons
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_backends_and_policy.py -q
```

Expected: fail because backend and policy modules do not exist.

- [ ] **Step 3: Add backend contract and fake backend**

Create `src/quant_strategies/validation/backends.py`:

```python
from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from quant_strategies.decisions import StrategyDecision


class BackendRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    backend: str
    status: str
    metrics: dict[str, float | int | str | bool | None]
    warnings: tuple[str, ...] = ()
    unsupported_semantics: tuple[str, ...] = ()


class ValidationBackend(Protocol):
    name: str

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: list[dict[str, Any]],
        config: Any,
    ) -> BackendRunResult:
        raise NotImplementedError


class FakeBackend:
    name = "fake"

    def __init__(self, result: BackendRunResult | None = None) -> None:
        self._result = result or BackendRunResult(
            backend=self.name,
            status="completed",
            metrics={"net_return": 0.0, "trade_count": 0},
            warnings=(),
            unsupported_semantics=(),
        )

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: list[dict[str, Any]],
        config: Any,
    ) -> BackendRunResult:
        return self._result


def get_backend(name: str) -> ValidationBackend:
    if name == "fake":
        return FakeBackend()
    if name == "vectorbtpro":
        from quant_strategies.validation.vectorbtpro_backend import VectorBTProBackend

        return VectorBTProBackend()
    raise ValueError(f"unsupported validation backend: {name}")
```

- [ ] **Step 4: Add decision policy**

Create `src/quant_strategies/validation/policy.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from quant_strategies.validation.backends import BackendRunResult


ValidationDecision = Literal["hard_no", "maybe", "clear_yes"]


class PromotionDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: ValidationDecision
    reasons: tuple[str, ...] = ()


def classify_validation(
    *,
    data_passed: bool,
    backend_results: list[BackendRunResult],
    min_trades: int,
) -> PromotionDecision:
    reasons: list[str] = []
    if not data_passed:
        reasons.append("data_audit_failed")
        return PromotionDecision(decision="hard_no", reasons=tuple(reasons))
    if not backend_results:
        return PromotionDecision(decision="hard_no", reasons=("no_backend_results",))

    unsupported = [result for result in backend_results if result.unsupported_semantics or result.status == "unsupported"]
    if unsupported:
        return PromotionDecision(decision="maybe", reasons=("unsupported_semantics",))

    for result in backend_results:
        if result.status != "completed":
            return PromotionDecision(decision="hard_no", reasons=(f"{result.backend}_failed",))
        net_return = float(result.metrics.get("net_return", 0.0) or 0.0)
        trade_count = int(result.metrics.get("trade_count", 0) or 0)
        if trade_count < min_trades:
            reasons.append("insufficient_trades")
        if net_return <= 0.0:
            reasons.append("negative_net_return")

    if reasons:
        return PromotionDecision(decision="hard_no", reasons=tuple(dict.fromkeys(reasons)))
    return PromotionDecision(decision="clear_yes")
```

- [ ] **Step 5: Run backend and policy tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_backends_and_policy.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/quant_strategies/validation/backends.py src/quant_strategies/validation/policy.py tests/test_validation_backends_and_policy.py
git commit -m "feat: add validation backend contract and policy"
```

---

### Task 6: Validation Artifact Writer

**Files:**
- Create: `src/quant_strategies/validation/artifacts.py`
- Test: `tests/test_validation_artifacts.py`

- [ ] **Step 1: Write failing artifact tests**

Create `tests/test_validation_artifacts.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from quant_strategies.validation.artifacts import create_validation_result_dir, write_json_artifact


def test_create_validation_result_dir_uses_strategy_id(tmp_path: Path):
    result_dir = create_validation_result_dir(tmp_path, "demo_strategy")

    assert result_dir.parent == tmp_path
    assert result_dir.name.endswith("-demo_strategy")
    assert result_dir.exists()


def test_write_json_artifact_is_stable(tmp_path: Path):
    path = write_json_artifact(tmp_path, "promotion_decision.json", {"b": 2, "a": 1})

    assert path == tmp_path / "promotion_decision.json"
    assert json.loads(path.read_text()) == {"a": 1, "b": 2}
    assert path.read_text().endswith("\n")
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_artifacts.py -q
```

Expected: fail because `artifacts.py` does not exist.

- [ ] **Step 3: Add artifact writer**

Create `src/quant_strategies/validation/artifacts.py`:

```python
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def create_validation_result_dir(results_root: Path, strategy_id: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    safe_strategy_id = strategy_id.replace("/", "_").replace(" ", "_")
    result_dir = results_root / f"{timestamp}-{safe_strategy_id}"
    result_dir.mkdir(parents=True, exist_ok=False)
    return result_dir


def write_json_artifact(result_dir: Path, name: str, payload: Any) -> Path:
    path = result_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    return path


def write_text_artifact(result_dir: Path, name: str, payload: str) -> Path:
    path = result_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if payload.endswith("\n") else payload + "\n")
    return path
```

- [ ] **Step 4: Run artifact tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_artifacts.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/quant_strategies/validation/artifacts.py tests/test_validation_artifacts.py
git commit -m "feat: write validation artifacts"
```

---

### Task 7: Validation Orchestration API

**Files:**
- Create: `src/quant_strategies/validation/__init__.py`
- Test: `tests/test_validation_runner.py`

- [ ] **Step 1: Write failing orchestration tests**

Create `tests/test_validation_runner.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_strategies.runner.data_loader import LoadedData
from quant_strategies.validation import run_validation
from quant_strategies.validation.backends import BackendRunResult, FakeBackend


AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


def write_package(tmp_path: Path) -> Path:
    package = tmp_path / "researched" / "demo"
    package.mkdir(parents=True)
    (package / "strategy.py").write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='short', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )
    (package / "validation.toml").write_text(
        """
strategy_path = "researched/demo/strategy.py"
strategy_id = "demo"
backend = "fake"

[[windows]]
id = "validation_2026_h1"
start = "2026-01-01"
end = "2026-06-30"

[data]
kind = "crypto_perp_funding"
symbols = ["BTC-PERP"]
strict = true
start = "2026-01-01"
end = "2026-06-30"

[params]
weight = 1.0

[fill_model]
price = "close"
entry_lag_bars = 1
exit_lag_bars = 0

[cost_model]
fee_bps_per_side = 0.5
slippage_bps_per_side = 0.5

[output]
results_dir = "validation_results/demo"
""".lstrip()
    )
    return package


def rows():
    return [
        {"symbol": "BTC-PERP", "timestamp": AS_OF, "available_at": AS_OF, "close": 100.0},
        {"symbol": "BTC-PERP", "timestamp": DECISION, "available_at": DECISION, "close": 101.0},
        {"symbol": "BTC-PERP", "timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc), "close": 102.0},
    ]


def test_run_validation_writes_clear_yes_artifacts(tmp_path: Path, monkeypatch):
    package = write_package(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.runner.data_loader.load_data",
        lambda config: LoadedData(rows=rows()),
    )
    backend = FakeBackend(
        BackendRunResult(
            backend="fake",
            status="completed",
            metrics={"net_return": 0.02, "trade_count": 20},
            warnings=(),
            unsupported_semantics=(),
        )
    )

    result = run_validation(package, repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "clear_yes"
    assert result.result_dir is not None
    promotion = json.loads((result.result_dir / "promotion_decision.json").read_text())
    assert promotion["decision"] == "clear_yes"
    assert (result.result_dir / "decision_records.jsonl").exists()
    assert (result.result_dir / "data_audit.json").exists()


def test_run_validation_records_data_audit_failure(tmp_path: Path, monkeypatch):
    package = write_package(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=[]))

    result = run_validation(package, repo_root=tmp_path, backend=FakeBackend())

    assert result.decision.decision == "hard_no"
    assert "data_audit_failed" in result.decision.reasons
```

- [ ] **Step 2: Run orchestration tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_runner.py -q
```

Expected: fail because `run_validation` is not exported.

- [ ] **Step 3: Add orchestration API**

Create `src/quant_strategies/validation/__init__.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quant_strategies.decisions import StrategyDecision
from quant_strategies.runner import data_loader
from quant_strategies.runner.config import default_repo_root
from quant_strategies.validation.artifacts import create_validation_result_dir, write_json_artifact, write_text_artifact
from quant_strategies.validation.backends import ValidationBackend, get_backend
from quant_strategies.validation.config import load_validation_config
from quant_strategies.validation.data_audit import audit_decision_rows
from quant_strategies.validation.policy import PromotionDecision, classify_validation
from quant_strategies.validation.strategy_loader import load_decision_strategy


@dataclass(frozen=True)
class ValidationRunResult:
    success: bool
    result_dir: Path | None
    decision: PromotionDecision
    message: str


def run_validation(
    package_or_config_path: str | Path,
    *,
    repo_root: Path | None = None,
    backend: ValidationBackend | None = None,
) -> ValidationRunResult:
    root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
    config = load_validation_config(package_or_config_path, repo_root=root)
    selected_backend = backend or get_backend(config.backend)
    result_dir = create_validation_result_dir(config.output.results_dir, config.strategy_id)
    generate_decisions = load_decision_strategy(config.strategy_path, repo_root=root)

    all_decisions: list[StrategyDecision] = []
    backend_results = []
    data_audits = []
    min_trades = 10

    for window in config.windows:
        run_config = config.to_run_config(window, results_dir=result_dir / "runner_smoke" / window.id)
        loaded = data_loader.load_data(run_config)
        decisions = generate_decisions(loaded.rows, config.params)
        all_decisions.extend(decisions)
        audit = audit_decision_rows(loaded.rows, decisions)
        data_audits.append({"window_id": window.id, **audit.model_dump(mode="json")})
        if audit.passed:
            backend_results.append(
                selected_backend.run(decisions=decisions, rows=loaded.rows, config=config)
            )

    data_passed = all(audit["passed"] for audit in data_audits)
    decision = classify_validation(
        data_passed=data_passed,
        backend_results=backend_results,
        min_trades=min_trades,
    )
    _write_validation_artifacts(
        result_dir=result_dir,
        decisions=all_decisions,
        data_audits=data_audits,
        backend_results=backend_results,
        decision=decision,
    )
    return ValidationRunResult(
        success=decision.decision == "clear_yes",
        result_dir=result_dir,
        decision=decision,
        message=f"validation decision: {decision.decision}",
    )


def _write_validation_artifacts(
    *,
    result_dir: Path,
    decisions: list[StrategyDecision],
    data_audits: list[dict[str, Any]],
    backend_results: list[Any],
    decision: PromotionDecision,
) -> None:
    decision_lines = [item.model_dump_json() for item in decisions]
    write_text_artifact(result_dir, "decision_records.jsonl", "\n".join(decision_lines))
    write_json_artifact(result_dir, "data_audit.json", {"windows": data_audits})
    write_json_artifact(
        result_dir,
        "backend_runs/summary.json",
        {"results": [result.model_dump(mode="json") for result in backend_results]},
    )
    write_json_artifact(
        result_dir,
        "promotion_decision.json",
        decision.model_dump(mode="json"),
    )
    write_text_artifact(
        result_dir,
        "validation_report.md",
        f"# Validation Report\n\nDecision: `{decision.decision}`\n\nReasons: {', '.join(decision.reasons) or 'none'}\n",
    )
```

- [ ] **Step 4: Run orchestration tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_runner.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/quant_strategies/validation/__init__.py tests/test_validation_runner.py
git commit -m "feat: orchestrate validation runs"
```

---

### Task 8: CLI Validate Command

**Files:**
- Modify: `src/quant_strategies/runner/cli.py`
- Test: `tests/test_validation_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_validation_cli.py`:

```python
from __future__ import annotations

from pathlib import Path

from quant_strategies.runner import cli
from quant_strategies.validation import ValidationRunResult
from quant_strategies.validation.policy import PromotionDecision


def test_validate_cli_returns_zero_for_clear_yes(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(
        "quant_strategies.runner.cli.run_validation",
        lambda path, repo_root=None: ValidationRunResult(
            success=True,
            result_dir=tmp_path / "validation_results" / "run",
            decision=PromotionDecision(decision="clear_yes"),
            message="validation decision: clear_yes",
        ),
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "researched/demo"])

    assert code == 0
    assert "clear_yes" in capsys.readouterr().out


def test_validate_cli_returns_one_for_hard_no(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(
        "quant_strategies.runner.cli.run_validation",
        lambda path, repo_root=None: ValidationRunResult(
            success=False,
            result_dir=tmp_path / "validation_results" / "run",
            decision=PromotionDecision(decision="hard_no", reasons=("negative_net_return",)),
            message="validation decision: hard_no",
        ),
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "researched/demo"])

    assert code == 1
    assert "hard_no" in capsys.readouterr().out


def test_validate_cli_returns_two_for_maybe(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(
        "quant_strategies.runner.cli.run_validation",
        lambda path, repo_root=None: ValidationRunResult(
            success=False,
            result_dir=tmp_path / "validation_results" / "run",
            decision=PromotionDecision(decision="maybe", reasons=("unsupported_semantics",)),
            message="validation decision: maybe",
        ),
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "researched/demo"])

    assert code == 2
    assert "maybe" in capsys.readouterr().out
```

- [ ] **Step 2: Run CLI tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_cli.py -q
```

Expected: fail because `validate` is not a known subcommand.

- [ ] **Step 3: Add validate subcommand**

Modify `src/quant_strategies/runner/cli.py`:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from quant_strategies.runner import run_config
from quant_strategies.validation import run_validation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quant-strategies")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run one strategy config")
    run_parser.add_argument("--repo-root", type=Path, default=None, help="repository root for relative config paths")
    run_parser.add_argument("config", type=Path)

    validate_parser = subparsers.add_parser("validate", help="validate one researched strategy package")
    validate_parser.add_argument("--repo-root", type=Path, default=None, help="repository root for relative paths")
    validate_parser.add_argument("package_or_config", type=Path)

    args = parser.parse_args(argv)

    if args.command == "run":
        result = run_config(args.config, repo_root=args.repo_root)
        if result.success:
            print(result.result_dir)
            return 0
        if result.notes_path is not None:
            print(f"run failed; see {result.notes_path}")
        else:
            print(f"run failed: {result.message}")
        return 1

    if args.command == "validate":
        result = run_validation(args.package_or_config, repo_root=args.repo_root)
        print(f"{result.message}; artifacts: {result.result_dir}")
        if result.decision.decision == "clear_yes":
            return 0
        if result.decision.decision == "hard_no":
            return 1
        return 2

    parser.error(f"unknown command: {args.command}")
    return 2
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_cli.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/quant_strategies/runner/cli.py tests/test_validation_cli.py
git commit -m "feat: add validation CLI"
```

---

### Task 9: VectorBT PRO Backend Adapter

**Files:**
- Create: `src/quant_strategies/validation/vectorbtpro_backend.py`
- Test: `tests/test_vectorbtpro_backend.py`

- [ ] **Step 1: Write VectorBT PRO backend tests**

Create `tests/test_vectorbtpro_backend.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.validation.vectorbtpro_backend import VectorBTProBackend


AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


def rows():
    return [
        {"symbol": "BTC-PERP", "timestamp": AS_OF, "close": 100.0},
        {"symbol": "BTC-PERP", "timestamp": DECISION, "close": 101.0},
        {"symbol": "BTC-PERP", "timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc), "close": 102.0},
        {"symbol": "BTC-PERP", "timestamp": datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc), "close": 103.0},
    ]


def decision(**exit_kwargs):
    return StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
        decision_time=DECISION,
        as_of_time=AS_OF,
        target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
        exit_policy=ExitPolicy(max_hold_bars=1, **exit_kwargs),
    )


def test_vectorbtpro_backend_reports_unsupported_threshold_exits():
    result = VectorBTProBackend().run(
        decisions=[decision(stop_loss_bps=100.0)],
        rows=rows(),
        config=None,
    )

    assert result.status == "unsupported"
    assert result.unsupported_semantics == ("threshold_exit_policy",)


def test_vectorbtpro_backend_runs_max_hold_decisions():
    pytest.importorskip("vectorbtpro")

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=rows(),
        config=None,
    )

    assert result.status == "completed"
    assert result.backend == "vectorbtpro"
    assert result.metrics["trade_count"] >= 0
    assert "net_return" in result.metrics
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_vectorbtpro_backend.py -q
```

Expected: fail because `vectorbtpro_backend.py` does not exist.

- [ ] **Step 3: Add VectorBT PRO backend**

Create `src/quant_strategies/validation/vectorbtpro_backend.py`:

```python
from __future__ import annotations

from collections import defaultdict
from typing import Any

from quant_strategies.decisions import StrategyDecision
from quant_strategies.validation.backends import BackendRunResult


class VectorBTProBackend:
    name = "vectorbtpro"

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: list[dict[str, Any]],
        config: Any,
    ) -> BackendRunResult:
        unsupported = _unsupported_semantics(decisions)
        if unsupported:
            return BackendRunResult(
                backend=self.name,
                status="unsupported",
                metrics={},
                warnings=(),
                unsupported_semantics=unsupported,
            )
        try:
            import pandas as pd
            import vectorbtpro as vbt
        except ImportError as exc:
            return BackendRunResult(
                backend=self.name,
                status="unavailable",
                metrics={},
                warnings=(f"vectorbtpro import failed: {exc}",),
                unsupported_semantics=(),
            )

        close = _close_frame(pd, rows)
        long_entries = close == "__never_true__"
        long_exits = close == "__never_true__"
        short_entries = close == "__never_true__"
        short_exits = close == "__never_true__"

        for item in decisions:
            symbol = item.instrument.symbol
            if symbol not in close.columns:
                continue
            entry_idx = _index_after_lag(close.index, item.decision_time, _entry_lag(config))
            exit_idx = entry_idx + item.exit_policy.max_hold_bars + _exit_lag(config)
            if entry_idx >= len(close.index) or exit_idx >= len(close.index):
                continue
            if item.target.direction == "long":
                long_entries.loc[close.index[entry_idx], symbol] = True
                long_exits.loc[close.index[exit_idx], symbol] = True
            elif item.target.direction == "short":
                short_entries.loc[close.index[entry_idx], symbol] = True
                short_exits.loc[close.index[exit_idx], symbol] = True

        fees = _bps_fraction(getattr(getattr(config, "cost_model", None), "fee_bps_per_side", 0.0))
        slippage = _bps_fraction(getattr(getattr(config, "cost_model", None), "slippage_bps_per_side", 0.0))
        portfolio = vbt.Portfolio.from_signals(
            close,
            long_entries=long_entries,
            long_exits=long_exits,
            short_entries=short_entries,
            short_exits=short_exits,
            fees=fees,
            slippage=slippage,
        )
        return BackendRunResult(
            backend=self.name,
            status="completed",
            metrics={
                "net_return": float(portfolio.get_total_return()),
                "trade_count": int(portfolio.trades.count()),
            },
            warnings=(),
            unsupported_semantics=(),
        )


def _unsupported_semantics(decisions: list[StrategyDecision]) -> tuple[str, ...]:
    for item in decisions:
        policy = item.exit_policy
        if policy.stop_loss_bps is not None or policy.take_profit_bps is not None or policy.trailing_stop_bps is not None:
            return ("threshold_exit_policy",)
        if item.target.sizing_kind != "target_weight":
            return ("non_target_weight_sizing",)
    return ()


def _close_frame(pd, rows: list[dict[str, Any]]):
    values: dict[str, dict[Any, float]] = defaultdict(dict)
    for row in rows:
        symbol = str(row["symbol"])
        values[symbol][row["timestamp"]] = float(row["close"])
    return pd.DataFrame(values).sort_index()


def _index_after_lag(index, timestamp, lag: int) -> int:
    matches = index.get_indexer([timestamp])
    if len(matches) != 1 or matches[0] < 0:
        return len(index)
    return int(matches[0]) + lag


def _entry_lag(config: Any) -> int:
    return int(getattr(getattr(config, "fill_model", None), "entry_lag_bars", 1))


def _exit_lag(config: Any) -> int:
    return int(getattr(getattr(config, "fill_model", None), "exit_lag_bars", 0))


def _bps_fraction(value: float) -> float:
    return float(value) / 10_000.0
```

- [ ] **Step 4: Run VectorBT PRO backend tests**

Run:

```bash
conda run -n quant pytest tests/test_vectorbtpro_backend.py -q
```

Expected: all tests pass. If `vectorbtpro` import is slow, keep the test focused and do not broaden it into a full validation dry run.

- [ ] **Step 5: Commit**

```bash
git add src/quant_strategies/validation/vectorbtpro_backend.py tests/test_vectorbtpro_backend.py
git commit -m "feat: add vectorbtpro validation backend"
```

---

### Task 10: Convert One Researched Variant To `generate_decisions`

**Files:**
- Modify: `researched/crypto_perp_funding_crowding_reversal/families/family_03_exploratory_time_only_exit/variants/rank_03/strategy.py`
- Create: `researched/crypto_perp_funding_crowding_reversal/families/family_03_exploratory_time_only_exit/variants/rank_03/validation.toml`
- Test: `tests/test_researched_crypto_perp_validation_contract.py`

- [ ] **Step 1: Write failing contract test**

Create `tests/test_researched_crypto_perp_validation_contract.py`:

```python
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_strategies.decisions import StrategyDecision


STRATEGY_PATH = Path(
    "researched/crypto_perp_funding_crowding_reversal/"
    "families/family_03_exploratory_time_only_exit/variants/rank_03/strategy.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("researched_rank_03_strategy", STRATEGY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_rows():
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(80):
        timestamp = start + timedelta(minutes=i)
        for symbol, funding_rate, close_base in (
            ("BTC-PERP", 0.0003, 100.0 + i),
            ("ETH-PERP", -0.0003, 100.0 - i * 0.5),
            ("DOGE-PERP", 0.0001, 50.0 + i * 0.1),
            ("ADA-PERP", -0.0001, 40.0 - i * 0.1),
        ):
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": timestamp,
                    "close": close_base,
                    "funding_timestamp": timestamp,
                    "funding_rate": funding_rate,
                    "has_funding_event": i % 8 == 0,
                    "available_at": timestamp,
                }
            )
    return rows


def test_rank_03_strategy_exposes_generate_decisions():
    module = load_module()

    assert callable(module.generate_decisions)


def test_rank_03_generate_decisions_returns_typed_decisions():
    module = load_module()
    params = {
        "funding_lookback_events": 2,
        "return_lookback_minutes": 20,
        "decision_interval_minutes": 20,
        "decision_lag_minutes": 1,
        "top_n": 1,
        "min_cross_section": 4,
        "min_abs_funding_bps": 0.1,
        "min_abs_return_bps": 0.1,
        "include_positive_funding_shorts": True,
        "include_negative_funding_longs": True,
        "hold_bars": 2,
        "short_hold_bars": 2,
        "long_hold_bars": 2,
        "require_exit_horizon": False,
        "weight": 1.0,
    }

    decisions = module.generate_decisions(synthetic_rows(), params)

    assert decisions
    assert all(isinstance(item, StrategyDecision) for item in decisions)
    assert {item.instrument.kind for item in decisions} == {"crypto_perp"}
```

- [ ] **Step 2: Run contract test and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_researched_crypto_perp_validation_contract.py -q
```

Expected: fail because the strategy does not expose `generate_decisions`.

- [ ] **Step 3: Add explicit decision generation to the researched variant**

Modify the selected strategy imports:

```python
from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
```

Modify `__all__`:

```python
__all__ = ["generate_signals", "generate_decisions"]
```

Add this function near `generate_signals`:

```python
def generate_decisions(bars: Sequence[Mapping[str, object]], params: Mapping[str, object]) -> list[StrategyDecision]:
    decisions: list[StrategyDecision] = []
    for signal in generate_signals(bars, params):
        side = str(signal["side"])
        if side not in {"long", "short"}:
            raise ValueError(f"unsupported decision side: {side}")
        decisions.append(
            StrategyDecision(
                strategy_id="crypto_perp_funding_crowding_reversal",
                instrument=InstrumentRef(kind="crypto_perp", symbol=str(signal["symbol"])),
                decision_time=_as_datetime(signal["decision_time"]),
                as_of_time=_as_datetime(signal["as_of_time"]),
                target=PositionTarget(
                    direction=side,
                    sizing_kind="target_weight",
                    size=float(signal["weight"]),
                ),
                exit_policy=ExitPolicy(
                    max_hold_bars=_positive_int(signal.get("max_hold_bars", signal["hold_bars"]), "max_hold_bars"),
                    take_profit_bps=_optional_positive_float(signal.get("take_profit_bps"), "take_profit_bps"),
                    stop_loss_bps=_optional_positive_float(signal.get("stop_loss_bps"), "stop_loss_bps"),
                    trailing_stop_bps=_optional_positive_float(signal.get("trailing_stop_bps"), "trailing_stop_bps"),
                ),
                metadata={
                    "funding_pressure_bps": signal.get("funding_pressure_bps"),
                    "entry_return_extension_bps": signal.get("entry_return_extension_bps"),
                    "signal_family": signal.get("signal_family"),
                },
            )
        )
    return decisions
```

This migration is explicit inside the strategy file. The validation runner must not contain a hidden `generate_signals` adapter.

- [ ] **Step 4: Add package-local validation config**

Create `researched/crypto_perp_funding_crowding_reversal/families/family_03_exploratory_time_only_exit/variants/rank_03/validation.toml`:

```toml
strategy_path = "researched/crypto_perp_funding_crowding_reversal/families/family_03_exploratory_time_only_exit/variants/rank_03/strategy.py"
strategy_id = "crypto_perp_funding_crowding_reversal"
backend = "vectorbtpro"

[[windows]]
id = "validation_2025_h1"
start = "2025-01-01"
end = "2025-06-30"

[[windows]]
id = "validation_2025_h2"
start = "2025-07-01"
end = "2025-12-31"

[[windows]]
id = "locked_recent_2026"
start = "2026-01-01"
end = "2026-04-13"

[data]
kind = "crypto_perp_funding"
symbols = ["BTC-PERP", "ETH-PERP", "DOGE-PERP", "ADA-PERP", "LINK-PERP"]
strict = true
start = "2025-01-01"
end = "2026-04-13"

[params]
funding_lookback_events = 5
return_lookback_minutes = 120
decision_interval_minutes = 240
session_start_hour = 4
session_end_hour = 20
top_n = 5
min_abs_funding_bps = 1.0
min_abs_return_bps = 5.0
max_short_return_extension_bps = 250.0
include_positive_funding_shorts = true
include_negative_funding_longs = true
min_same_sign_funding_events = 3
min_latest_abs_funding_bps = 0.0
volatility_lookback_minutes = 0
min_abs_return_z = 0.0
recent_return_lookback_minutes = 0
max_recent_same_direction_return_bps = 0.0
min_idiosyncratic_return_bps = 2.5
min_long_idiosyncratic_return_bps = 0.0
symbol_cooldown_minutes = 0
min_tail_count = 1
balance_sides = false
selection_score = "funding"
require_exit_horizon = true
weight = 1.0
hold_bars = 600
short_hold_bars = 480
long_hold_bars = 960
high_extension_short_return_bps = 120.0
high_extension_short_hold_bars = 120

[fill_model]
price = "close"
entry_lag_bars = 1
exit_lag_bars = 1

[cost_model]
fee_bps_per_side = 0.5
slippage_bps_per_side = 0.5

[output]
results_dir = "validation_results/researched/crypto_perp_funding_crowding_reversal/family_03_exploratory_time_only_exit/rank_03"
```

- [ ] **Step 5: Run researched contract test**

Run:

```bash
conda run -n quant pytest tests/test_researched_crypto_perp_validation_contract.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add researched/crypto_perp_funding_crowding_reversal/families/family_03_exploratory_time_only_exit/variants/rank_03/strategy.py researched/crypto_perp_funding_crowding_reversal/families/family_03_exploratory_time_only_exit/variants/rank_03/validation.toml tests/test_researched_crypto_perp_validation_contract.py
git commit -m "feat: add validation decisions for researched crypto perp variant"
```

---

### Task 11: Documentation And Ignored Artifacts

**Files:**
- Modify: `.gitignore`
- Modify: `README.md`
- Test: no dedicated test

- [ ] **Step 1: Update ignored artifacts**

Modify `.gitignore`:

```text
__pycache__/
*.py[cod]
.pytest_cache/
.coverage
.DS_Store
results/
validation_results/
*.egg-info/
```

- [ ] **Step 2: Add README validation section**

Add this section after the current Runner section in `README.md`:

````markdown
## Validation

The validation workflow is separate from runner smoke evidence.

```bash
conda run -n quant quant-strategies validate researched/<strategy_id-or-variant>
```

Validation candidates must expose:

```python
def generate_decisions(rows, params):
    return []
```

`generate_signals` remains valid for fast research and smoke runs, but it is not
enough to move a researched candidate toward `tested/`.

Validation writes generated artifacts under ignored `validation_results/` and
classifies each run as `hard_no`, `maybe`, or `clear_yes`. A `clear_yes`
recommendation does not automatically move code into `tested/`; Season must
approve that repository change.
````

- [ ] **Step 3: Run README smoke check**

Run:

```bash
conda run -n quant python -m py_compile src/quant_strategies/runner/cli.py
```

Expected: command exits 0.

- [ ] **Step 4: Commit**

```bash
git add .gitignore README.md
git commit -m "docs: document researched validation workflow"
```

---

### Task 11A: Eng Review Hardening

**Files:**
- Modify: `src/quant_strategies/validation/__init__.py`
- Modify: `src/quant_strategies/validation/backends.py`
- Modify: `src/quant_strategies/validation/vectorbtpro_backend.py`
- Modify: `src/quant_strategies/validation/policy.py`
- Test: `tests/test_validation_runner.py`
- Test: `tests/test_validation_backends_and_policy.py`
- Test: `tests/test_vectorbtpro_backend.py`

- [ ] **Step 1: Add tests for required matrix gating**

Extend `tests/test_validation_runner.py`:

```python
def test_run_validation_runs_each_matrix_scenario_once_per_loaded_window(tmp_path: Path, monkeypatch):
    package = write_package(tmp_path)
    load_calls = []
    backend_calls = []

    def fake_load(config):
        load_calls.append(config.data.start)
        return LoadedData(rows=rows())

    class RecordingBackend:
        name = "recording"

        def run(self, *, decisions, rows, config):
            backend_calls.append(config.scenario_id)
            return BackendRunResult(
                backend="recording",
                status="completed",
                metrics={"net_return": 0.02, "trade_count": 20},
                warnings=(),
                unsupported_semantics=(),
            )

    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", fake_load)

    result = run_validation(package, repo_root=tmp_path, backend=RecordingBackend())

    assert result.decision.decision == "clear_yes"
    assert len(load_calls) == 1
    assert {
        "validation_2026_h1/base",
        "validation_2026_h1/realistic_costs",
        "validation_2026_h1/stressed_costs",
        "validation_2026_h1/fill_lag_plus_1",
    }.issubset(set(backend_calls))
```

- [ ] **Step 2: Add tests for failure-envelope artifacts**

Extend `tests/test_validation_runner.py`:

```python
def test_run_validation_writes_artifacts_when_generate_decisions_fails(tmp_path: Path, monkeypatch):
    package = write_package(tmp_path)
    (package / "strategy.py").write_text("def generate_decisions(rows, params):\n    raise RuntimeError('bad strategy')\n")
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))

    result = run_validation(package, repo_root=tmp_path, backend=FakeBackend())

    assert result.decision.decision == "hard_no"
    assert "strategy_generation_failed" in result.decision.reasons
    assert result.result_dir is not None
    assert (result.result_dir / "promotion_decision.json").exists()
    assert (result.result_dir / "validation_report.md").exists()


def test_run_validation_writes_artifacts_when_backend_fails(tmp_path: Path, monkeypatch):
    package = write_package(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))

    class FailingBackend:
        name = "failing"

        def run(self, *, decisions, rows, config):
            raise RuntimeError("backend exploded")

    result = run_validation(package, repo_root=tmp_path, backend=FailingBackend())

    assert result.decision.decision == "hard_no"
    assert "backend_failed" in result.decision.reasons
    assert result.result_dir is not None
    assert (result.result_dir / "promotion_decision.json").exists()
```

- [ ] **Step 3: Add backend sizing and fillability tests**

Extend `tests/test_vectorbtpro_backend.py`:

```python
def test_vectorbtpro_backend_rejects_unfillable_missing_symbol():
    missing_symbol_decision = StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol="ETH-PERP"),
        decision_time=DECISION,
        as_of_time=AS_OF,
        target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
        exit_policy=ExitPolicy(max_hold_bars=1),
    )

    result = VectorBTProBackend().run(decisions=[missing_symbol_decision], rows=rows(), config=None)

    assert result.status == "failed"
    assert "missing_symbol" in result.warnings


def test_vectorbtpro_backend_rejects_unfillable_exit_bar():
    too_long = StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
        decision_time=DECISION,
        as_of_time=AS_OF,
        target=PositionTarget(direction="long", sizing_kind="target_weight", size=1.0),
        exit_policy=ExitPolicy(max_hold_bars=999),
    )

    result = VectorBTProBackend().run(decisions=[too_long], rows=rows(), config=None)

    assert result.status == "failed"
    assert "unfillable_exit" in result.warnings


def test_vectorbtpro_backend_honors_target_weight_size(monkeypatch):
    captured = {}

    def fake_from_signals(close, **kwargs):
        captured.update(kwargs)

        class FakeTrades:
            def count(self):
                return 1

        class FakePortfolio:
            trades = FakeTrades()

            def get_total_return(self):
                return 0.01

        return FakePortfolio()

    import vectorbtpro as vbt

    monkeypatch.setattr(vbt.Portfolio, "from_signals", fake_from_signals)

    VectorBTProBackend().run(decisions=[decision()], rows=rows(), config=None)

    assert "size" in captured
    assert "size_type" in captured
```

- [ ] **Step 4: Update validation orchestration**

Modify `run_validation(...)` so it:

```text
1. creates result_dir immediately after config load,
2. loads rows once per validation window,
3. generates decisions once per window,
4. audits decisions once per window,
5. expands matrix scenarios for that window,
6. runs the backend once per required scenario using the already-loaded rows,
7. catches data, strategy, audit, and backend failures into PromotionDecision,
8. always writes promotion_decision.json and validation_report.md after result_dir exists.
```

The scenario config object passed to the backend must include `scenario_id`,
scenario-specific `params`, `cost_model`, and `fill_model` so tests can verify
which scenario ran.

- [ ] **Step 5: Update policy aggregation**

Modify `classify_validation(...)` so `clear_yes` requires:

```text
all required scenarios completed
no required scenario has unsupported semantics
each required scenario has trade_count >= min_trades
each required scenario has net_return > 0
```

Diagnostic scenarios may be recorded in `robustness_matrix.json` without
blocking `clear_yes`.

- [ ] **Step 6: Update VectorBT PRO backend implementation**

Modify `VectorBTProBackend.run(...)` so it:

```text
honors target_weight size through VectorBT size/size_type inputs
returns status="failed" for missing symbols
returns status="failed" for missing decision bars
returns status="failed" for missing entry fills
returns status="failed" for missing exit fills
returns status="unsupported" for unsupported sizing or threshold exits
never silently continues past an unfillable decision
```

- [ ] **Step 7: Run focused hardening tests**

Run:

```bash
conda run -n quant pytest \
  tests/test_validation_matrix.py \
  tests/test_validation_runner.py \
  tests/test_validation_backends_and_policy.py \
  tests/test_vectorbtpro_backend.py \
  -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/quant_strategies/validation tests/test_validation_matrix.py tests/test_validation_runner.py tests/test_validation_backends_and_policy.py tests/test_vectorbtpro_backend.py
git commit -m "feat: harden validation matrix and backend semantics"
```

---

### Task 12: Final Verification

**Files:**
- No new files unless verification exposes a defect.

- [ ] **Step 1: Run focused validation test suite**

Run:

```bash
conda run -n quant pytest \
  tests/test_decision_models.py \
  tests/test_validation_strategy_loader.py \
  tests/test_validation_config.py \
  tests/test_validation_matrix.py \
  tests/test_validation_data_audit.py \
  tests/test_validation_backends_and_policy.py \
  tests/test_validation_artifacts.py \
  tests/test_validation_runner.py \
  tests/test_validation_cli.py \
  tests/test_vectorbtpro_backend.py \
  tests/test_researched_crypto_perp_validation_contract.py \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run full suite**

Run:

```bash
conda run -n quant pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Run CLI help checks**

Run:

```bash
conda run -n quant quant-strategies --help
conda run -n quant quant-strategies validate --help
```

Expected: both commands exit 0 and list the `validate` command/options.

- [ ] **Step 4: Run one validation dry run**

Run:

```bash
conda run -n quant quant-strategies validate \
  researched/crypto_perp_funding_crowding_reversal/families/family_03_exploratory_time_only_exit/variants/rank_03
```

Expected: command writes a directory under `validation_results/researched/crypto_perp_funding_crowding_reversal/family_03_exploratory_time_only_exit/rank_03/` and prints one of `hard_no`, `maybe`, or `clear_yes`. A `maybe` caused by unsupported threshold exits is acceptable only if the selected variant emits threshold exit policies; the time-only rank_03 config should proceed through the VectorBT PRO max-hold path.

- [ ] **Step 5: Inspect generated report**

Run:

```bash
latest_dir=$(ls -td validation_results/researched/crypto_perp_funding_crowding_reversal/family_03_exploratory_time_only_exit/rank_03/* | head -1)
test -f "$latest_dir/promotion_decision.json"
test -f "$latest_dir/validation_report.md"
test -f "$latest_dir/decision_records.jsonl"
test -f "$latest_dir/data_audit.json"
```

Expected: command exits 0.

- [ ] **Step 6: Final status check**

Run:

```bash
git status --short
git log --oneline -12
```

Expected: implementation commits are present. Existing unrelated worktree changes may still be present; do not revert them.

---

## Self-Review Notes

- Spec coverage: the plan covers typed decisions, validation intake, data audit, validation matrix expansion, backend boundary, failure-envelope artifacts, fake backend tests, VectorBT PRO backend, sizing and fillability semantics, CLI command, first researched variant migration, docs, and verification.
- Scope control: portfolio validation, paper trading, live execution, options, margin, partial fills, and market impact remain outside this first implementation slice.
- Type consistency: the canonical strategy function is `generate_decisions`; the typed output is `StrategyDecision`; the decision states are `hard_no`, `maybe`, and `clear_yes`.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | not run | Not requested for this backend validation plan. |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | not run | Not requested. |
| Eng Review | `/plan-eng-review` | Architecture & tests | 1 | applied | 6 issues accepted: matrix gating, failure envelope, sizing fidelity, fail-closed fillability, expanded tests, per-window data reuse. |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | not applicable | Backend/docs-only plan. |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | not run | CLI/docs behavior covered by eng review. |

- **UNRESOLVED:** 0.
- **VERDICT:** ENG REVIEW APPLIED - ready to implement after current docs are committed.
