# Research Evaluation Surface MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the third public `quant-strategies evaluate` surface that produces stateless frozen-candidate portfolio, economic, and path evidence through VectorBT Pro with Parquet trace artifacts.

**Architecture:** Add a new `quant_strategies.evaluation` package parallel to `runner` and `validation`. Evaluation reuses shared execution primitives (`StrategyExecutionSpec`, `execute_strategy_run`, shared config primitives, causality helpers) but does not import validation policy, call `run_validation`, or emit validation verdicts. The surface owns candidate-local config, scenario expansion, VectorBT Pro portfolio evaluation, Parquet trace artifacts, JSON manifests, CLI/API result handling, and docs.

**Tech Stack:** Python 3.12, Pydantic v2, existing `quant_strategies` execution kernel, `quant_data`, VectorBT Pro, pandas, pyarrow/Parquet, pytest, `conda run -n quant` commands.

---

## Approved Spec

Implement:

```text
docs/superpowers/specs/2026-06-01-research-evaluation-surface-mvp-design.md
```

Do not implement benchmark-relative metrics, user-defined scenario matrices, autonomous ranking, search memory, stopping rules, promotion policy, paper/live readiness, an internal portfolio-engine fallback, or JSONL fallback for trace artifacts.

## Completed Pre-Execution Review Gate

This written plan was reviewed before source implementation by independent
read-only reviewers and concrete corrections were integrated into this file.
Repeat this gate only if the plan is materially rewritten.

- senior software developer / architecture reviewer;
- senior quant research / math semantics reviewer;
- data engineering / Parquet artifact contract reviewer;
- performance reviewer;
- testability / QA / developer experience reviewer.

Reviewers referenced this plan path, the approved spec path, and returned plan
defects, missing tests, false positives, and scope risks. Reviewers did not edit
files. Accepted feedback is captured in the integrated review decisions and task
updates below.

## Scope Check

This plan covers one cohesive product surface: the C research evaluation surface MVP. It is large but not multiple independent subsystems because the public config, scenario matrix, VectorBT Pro adapter, Parquet artifacts, runner orchestration, CLI, and docs all define one usable `evaluate` workflow. The task sequence below keeps commits independently reviewable.

## File Structure

Create:

- `src/quant_strategies/evaluation/__init__.py`
  Public API exports: `EvaluationRunResult`, `run_evaluation`.
- `src/quant_strategies/evaluation/errors.py`
  Evaluation-specific exception classes.
- `src/quant_strategies/evaluation/config.py`
  Candidate-local `evaluation.toml` models, path resolution, and config loading.
- `src/quant_strategies/evaluation/scenarios.py`
  Fixed window × cost × fill scenario expansion.
- `src/quant_strategies/evaluation/dependencies.py`
  Hard dependency checks for pandas, pyarrow, and vectorbtpro.
- `src/quant_strategies/evaluation/metrics.py`
  Metric semantics and JSON-safe metric helpers.
- `src/quant_strategies/evaluation/backend.py`
  VectorBT Pro portfolio adapter and backend result models.
- `src/quant_strategies/evaluation/artifacts.py`
  Result directory creation, static artifact copies, JSON writers, Parquet writers, table metadata, and manifest assembly.
- `src/quant_strategies/evaluation/runner.py`
  `run_evaluation` orchestration and `EvaluationRunResult`.

Modify:

- `src/quant_strategies/runner/cli.py`
  Add `evaluate` subcommand and exit code mapping.
- `pyproject.toml`
  Add optional dependency extra `evaluation = ["pandas>=2.2", "pyarrow>=16", "vectorbtpro"]`.
- `README.md`, `PRD.md`, `FOUNDATION_LOCK.md`, `TODOS.md`, `docs/foundation-surfaces.md`, `docs/vectorbtpro.md`, `docs/quant-autoresearch-consumer.md`
  Update public-surface docs after behavior exists.

Create tests:

- `tests/test_evaluation_config.py`
- `tests/test_evaluation_scenarios.py`
- `tests/test_evaluation_dependencies.py`
- `tests/test_evaluation_backend.py`
- `tests/test_evaluation_artifacts.py`
- `tests/test_evaluation_runner.py`
- `tests/test_evaluation_cli.py`
- `tests/test_evaluation_docs.py`

Modify tests:

- `tests/test_runner_api_cli.py` only if shared CLI helper expectations need the new subcommand.
- `tests/test_phase5_performance.py` for evaluation-specific performance guardrails when the behavior exists.

## Implementation Notes

- Use `apply_patch` for source, test, and doc edits.
- Use `conda run -n quant <command>` for all Python commands.
- Do not stage or revert unrelated existing worktree changes.
- Commit each task separately when its focused tests pass.
- Keep normal CI independent of a licensed VectorBT Pro install by monkeypatching
  `quant_strategies.evaluation.backend.require_evaluation_dependencies` for unit
  tests. Real VectorBT Pro smoke tests must be opt-in with
  `RUN_VECTORBTPRO_SMOKE=1`.

## Integrated Review Decisions

The plan was reviewed from architecture, quant research, data engineering,
performance, and testability perspectives before implementation. These decisions
are part of the implementation contract:

- Keep evaluation independent from validation: no `run_validation`, validation
  policy imports, validation artifacts, or validation verdict labels.
- Accept `quant_strategies.runner.execution` as the current shared strategy
  execution kernel for this MVP because validation already depends on it. Do not
  add wrappers. Revisit a neutral package move only if this boundary creates a
  concrete implementation problem.
- Execute strategy generation and strict lookahead preflight once per configured
  window, then fan out the six evaluation scenarios from the same normalized
  rows and decisions.
- Treat strict lookahead replay as the expensive preflight. It must not run per
  scenario.
- Pass normalized/projection rows to the portfolio backend, not raw loader rows.
- Add evaluation-owned row-contract preflight before portfolio evidence. A
  failed validation-mode row contract is an evaluation data failure with CLI
  exit `3`, not a validation verdict.
- Write exactly four aggregate Parquet trace tables per evaluation run:
  `tables/portfolio_path.parquet`, `tables/trades.parquet`,
  `tables/positions.parquet`, and `tables/per_asset_metrics.parquet`. Each table
  has a `scenario_id` column and covers all completed scenarios.
- Do not write per-scenario Parquet directories in the MVP. Aggregate table
  metadata carries scenario coverage.
- Write Parquet only after all required scenarios complete. If a scenario fails,
  return a structured failure before trace tables are written. Do not leave
  unmanifested partial trace tables.
- Add `data_manifest.json` with per-window normalized row identity, row contract
  summary, evidence quality, data config, row count/ranges, and decision count.
- Use persisted Arrow/Parquet footer metadata after write for table manifests:
  `file_sha256`, `schema_sha256`, row count, row groups, column logical types,
  byte size, compression, and scenario coverage.
- Do not recursively rehash Parquet trace tables in `evaluation_manifest.json`;
  use the hashes recorded by the table metadata.
- Map backend `status = "unavailable"` to
  `assessment_status = "portfolio_backend_unavailable"`.
- Make real VectorBT Pro smoke tests opt-in with `RUN_VECTORBTPRO_SMOKE=1`, not
  automatic when VectorBT Pro happens to be installed.

## Quant Semantics Contract

Evaluation metrics are portfolio path evidence net of configured fees/slippage
only. They exclude funding, borrow, financing, market impact, benchmark-relative
edge, promotion authority, paper-trading authority, and live-trading authority.

Use these formulas and conventions:

- `initial_nav = 100.0`.
- `portfolio_value` is VectorBT Pro portfolio NAV/value in initial-cash units.
- `period_return` is a simple return, not log return.
- The first synthetic or missing return is excluded from annualized metrics.
- `ending_value` is the last finite portfolio value.
- `total_return = ending_value / initial_nav - 1`.
- `drawdown` is high-water-mark drawdown as a non-positive decimal fraction.
- `max_drawdown` is the minimum drawdown value; monotonic-up paths have `0.0`.
- `annualized_return = (ending_value / initial_nav) ** (annualization_periods_per_year / observed_period_count) - 1` when `observed_period_count > 0`; otherwise `None`.
- `volatility` is sample standard deviation of finite periodic returns with
  `ddof = 1`, annualized by `sqrt(annualization_periods_per_year)`. If fewer
  than two returns exist, emit `None`.
- `sharpe = annualized_mean_excess_return / annualized_volatility`, with
  risk-free rate fixed at `0.0` for the MVP. If volatility is zero or unavailable,
  emit `None`.
- `sortino` uses downside periodic returns below target `0.0`; if downside
  deviation is zero or unavailable, emit `None`.
- `calmar = annualized_return / abs(max_drawdown)`. If `max_drawdown` is zero or
  unavailable, emit `None`.
- `win_rate = winning_closed_trades / closed_trades`; if there are no closed
  trades, emit `None`.
- `profit_factor = gross_profit / abs(gross_loss)`; if there are no losses or no
  trades, emit `None` rather than `inf`.
- `tail_loss_p05` is deferred unless an implementation task adds a precise
  quantile method and small-sample tests.
- Average win/loss, exposure, gross/net exposure, concentration, turnover, and
  per-asset contribution/exposure/turnover are deferred unless Task 5 implements
  non-empty typed tables and tests for them.
- VectorBT Pro must be called with `size_type = "valuepercent"`,
  `cash_sharing = True`, `group_by = True`, and `init_cash = 100.0`.
- Cost inputs convert bps to decimal per-side fractions with `/ 10_000`.
- Per-decision target size above `1.0`, unsupported base semantics, and
  simultaneous gross target exposure above `1.0` are unsupported for the MVP.

---

### Task 0: Plan Review Gate

**Files:**
- Review: `docs/superpowers/plans/2026-06-01-research-evaluation-surface-mvp.md`
- Review: `docs/superpowers/specs/2026-06-01-research-evaluation-surface-mvp-design.md`

- [x] **Step 1: Spawn architecture reviewer against the written plan**

Use a read-only subagent prompt with this content:

```text
Read-only plan review. Do not edit files.

Workspace: /Users/Season_Yang/Personal/quant_strategies
Plan: docs/superpowers/plans/2026-06-01-research-evaluation-surface-mvp.md
Spec: docs/superpowers/specs/2026-06-01-research-evaluation-surface-mvp-design.md

Perspective: senior software developer / software architect.

Review whether the plan preserves clean module boundaries, dependency direction, public API/CLI clarity, incremental delivery, and the separation between evaluation and validation. Ground findings in exact planned files/tasks and current code files where relevant.

Return:
1. Critical or important plan defects.
2. Missing implementation tasks or tests.
3. False-positive concerns you considered and rejected.
4. Concrete edits you recommend making to the plan.
```

- [x] **Step 2: Spawn quant research reviewer against the written plan**

Use a read-only subagent prompt with this content:

```text
Read-only plan review. Do not edit files.

Workspace: /Users/Season_Yang/Personal/quant_strategies
Plan: docs/superpowers/plans/2026-06-01-research-evaluation-surface-mvp.md
Spec: docs/superpowers/specs/2026-06-01-research-evaluation-surface-mvp-design.md

Perspective: senior quantitative researcher / quant math reviewer.

Review whether the plan defines NAV/path semantics, annualization, drawdown, Sharpe, Sortino, Calmar, win rate, profit factor, target-weight sizing, fill timing, cost/slippage, long/short signs, multi-asset cash sharing, and artifact labels precisely enough to avoid false evidence.

Return:
1. Quant semantics missing from the plan.
2. Edge-case tests needed.
3. Scope cuts needed to avoid misleading first-version metrics.
4. False-positive concerns you considered and rejected.
5. Concrete edits you recommend making to the plan.
```

- [x] **Step 3: Spawn data engineering reviewer against the written plan**

Use a read-only subagent prompt with this content:

```text
Read-only plan review. Do not edit files.

Workspace: /Users/Season_Yang/Personal/quant_strategies
Plan: docs/superpowers/plans/2026-06-01-research-evaluation-surface-mvp.md
Spec: docs/superpowers/specs/2026-06-01-research-evaluation-surface-mvp-design.md

Perspective: data engineer focused on Parquet artifacts, schemas, lineage, replayability, and data quality.

Review whether the plan locks down Parquet-only trace artifacts, manifest schemas, table hashes, row counts, column metadata, scenario coverage, lineage, and efficient review access. Do not recommend JSONL fallback.

Return:
1. Artifact/schema plan defects.
2. Missing data-quality or lineage tests.
3. Required manifest fields or hashing details.
4. False-positive concerns you considered and rejected.
5. Concrete edits you recommend making to the plan.
```

- [x] **Step 4: Spawn performance reviewer against the written plan**

Use a read-only subagent prompt with this content:

```text
Read-only plan review. Do not edit files.

Workspace: /Users/Season_Yang/Personal/quant_strategies
Plan: docs/superpowers/plans/2026-06-01-research-evaluation-surface-mvp.md
Spec: docs/superpowers/specs/2026-06-01-research-evaluation-surface-mvp-design.md

Perspective: performance-focused senior engineer.

Review whether the plan avoids repeated data loading, repeated strategy execution, unnecessary giant in-memory copies, slow hashing, slow normal test suites, and unbounded Parquet artifacts while preserving evidence quality.

Return:
1. Realistic performance risks in the plan.
2. Low-complexity tactics the plan should require.
3. Focused performance tests or guardrails.
4. False-positive concerns you considered and rejected.
5. Concrete edits you recommend making to the plan.
```

- [x] **Step 5: Spawn testability reviewer against the written plan**

Use a read-only subagent prompt with this content:

```text
Read-only plan review. Do not edit files.

Workspace: /Users/Season_Yang/Personal/quant_strategies
Plan: docs/superpowers/plans/2026-06-01-research-evaluation-surface-mvp.md
Spec: docs/superpowers/specs/2026-06-01-research-evaluation-surface-mvp-design.md

Perspective: testability / QA / developer experience reviewer.

Review whether the plan has concrete TDD slices, robust optional-dependency tests, CLI/API exit behavior tests, artifact assertions, and docs checks without requiring a licensed VectorBT Pro install in normal CI.

Return:
1. Missing tests or brittle tests.
2. Better monkeypatch strategy for pandas, pyarrow, and vectorbtpro.
3. CLI/API/DX risks.
4. False-positive concerns you considered and rejected.
5. Concrete edits you recommend making to the plan.
```

- [x] **Step 6: Integrate accepted review feedback**

Edit this plan in place. Keep accepted edits concrete: add or modify exact tasks, file paths, test names, snippets, or commands. Do not add broad advice that an implementer cannot execute.

- [x] **Step 7: Re-run plan self-review**

Run:

```bash
rg -n "TBD|TODO|FIXME|placeholder|implement later|add appropriate|write tests for the above|similar to" docs/superpowers/plans/2026-06-01-research-evaluation-surface-mvp.md
git diff --check -- docs/superpowers/plans/2026-06-01-research-evaluation-surface-mvp.md
```

Expected:

```text
No red-flag matches other than the self-review command itself and literal `TODOS.md` path references.
No output from git diff --check.
```

- [x] **Step 8: Commit the reviewed plan**

Run:

```bash
git add docs/superpowers/plans/2026-06-01-research-evaluation-surface-mvp.md
git commit -m "docs: add research evaluation implementation plan"
```

Expected: one docs-only commit.

---

### Task 1: Evaluation Config Contract

**Files:**
- Create: `src/quant_strategies/evaluation/__init__.py`
- Create: `src/quant_strategies/evaluation/errors.py`
- Create: `src/quant_strategies/evaluation/config.py`
- Test: `tests/test_evaluation_config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/test_evaluation_config.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from quant_strategies.core.config import CostModelConfig, DataConfig, FillModelConfig, StrategyExecutionSpec
from quant_strategies.evaluation.config import (
    EvaluationConfigError,
    load_evaluation_config,
    resolve_evaluation_config_path,
)


def write_strategy(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    return []\n"
    )


def write_config(path: Path, *, strategy_path: str = "strategy.py", annualization: int = 252) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'''
strategy_path = "{strategy_path}"
strategy_id = "demo"

[[windows]]
id = "eval_2026_h1"
start = "2026-01-01"
end = "2026-06-30"

[data]
kind = "bars"
dataset = "equity_1min"
symbols = ["SPY", "QQQ"]
strict = true
start = "2026-01-01"
end = "2026-06-30"

[params]
weight = 0.5

[fill_model]
price = "close"
entry_lag_bars = 1
exit_lag_bars = 0

[cost_model]
fee_bps_per_side = 0.5
slippage_bps_per_side = 0.5

[metrics]
annualization_periods_per_year = {annualization}

[output]
results_dir = "evaluation_results/demo"
'''.lstrip()
    )


def test_load_evaluation_config_resolves_candidate_local_paths(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    write_config(candidate / "evaluation.toml")

    config = load_evaluation_config(candidate / "evaluation.toml")

    assert config.base_dir == candidate
    assert config.strategy_path == candidate / "strategy.py"
    assert config.output.results_dir == candidate / "evaluation_results" / "demo"
    assert config.strategy_id == "demo"
    assert config.windows[0].id == "eval_2026_h1"
    assert config.data.symbols == ("SPY", "QQQ")
    assert config.metrics.annualization_periods_per_year == 252
    assert config.to_execution_spec(config.windows[0]) == StrategyExecutionSpec(
        strategy_path=candidate / "strategy.py",
        strategy_id="demo",
        data=DataConfig(
            kind="bars",
            dataset="equity_1min",
            symbols=("SPY", "QQQ"),
            strict=True,
            start=config.windows[0].start,
            end=config.windows[0].end,
        ),
        params={"weight": 0.5},
        fill_model=FillModelConfig(price="close", entry_lag_bars=1, exit_lag_bars=0),
        cost_model=CostModelConfig(fee_bps_per_side=0.5, slippage_bps_per_side=0.5),
        require_param_validator=True,
    )


def test_resolve_evaluation_config_rejects_directory_path(tmp_path: Path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()

    with pytest.raises(EvaluationConfigError, match="evaluation config path must be a TOML file"):
        resolve_evaluation_config_path(candidate)


def test_load_evaluation_config_rejects_paths_outside_candidate_dir(tmp_path: Path):
    candidate = tmp_path / "candidate"
    outside = tmp_path / "outside.py"
    write_strategy(outside)
    write_config(candidate / "evaluation.toml", strategy_path="../outside.py")

    with pytest.raises(EvaluationConfigError, match="strategy_path must resolve inside config directory"):
        load_evaluation_config(candidate / "evaluation.toml")


def test_load_evaluation_config_requires_positive_annualization(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    write_config(candidate / "evaluation.toml", annualization=0)

    with pytest.raises(EvaluationConfigError, match="annualization_periods_per_year"):
        load_evaluation_config(candidate / "evaluation.toml")


def test_load_evaluation_config_rejects_empty_or_duplicate_window_ids(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    write_config(candidate / "evaluation.toml")
    payload = (candidate / "evaluation.toml").read_text()
    payload = payload.replace('id = "eval_2026_h1"', 'id = "dup"')
    payload += '''

[[windows]]
id = "dup"
start = "2026-07-01"
end = "2026-12-31"
'''
    (candidate / "evaluation.toml").write_text(payload)

    with pytest.raises(EvaluationConfigError, match="window ids cannot contain duplicates"):
        load_evaluation_config(candidate / "evaluation.toml")
```

- [ ] **Step 2: Run config tests to verify they fail**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_config.py -q
```

Expected: import failure for `quant_strategies.evaluation`.

- [ ] **Step 3: Add evaluation errors and config implementation**

Create `src/quant_strategies/evaluation/errors.py`:

```python
from __future__ import annotations


class EvaluationError(Exception):
    """Base exception for evaluation-surface failures."""


class EvaluationConfigError(EvaluationError):
    """Raised when an evaluation config cannot be loaded or validated."""
```

Create `src/quant_strategies/evaluation/config.py`:

```python
from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, ValidationInfo, field_validator, model_validator

from quant_strategies.core.config import CostModelConfig, DataConfig, FillModelConfig, StrategyExecutionSpec
from quant_strategies.evaluation.errors import EvaluationConfigError


class EvaluationConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _path_anchor(path: str | Path, *, repo_root: Path | None = None) -> Path:
    if repo_root is not None:
        return Path(repo_root).resolve()
    if Path(path).is_absolute():
        return Path("/")
    return Path.cwd().resolve()


def _config_base(info: ValidationInfo) -> Path:
    base = info.context.get("base_dir") if info.context else None
    return Path(base).resolve() if base is not None else Path.cwd().resolve()


def _resolve_inside_config_dir(value: Path, base_dir: Path, field_name: str) -> Path:
    resolved = value if value.is_absolute() else base_dir / value
    resolved = resolved.resolve()
    try:
        resolved.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError(f"{field_name} must resolve inside config directory: {base_dir}") from exc
    return resolved


class EvaluationWindow(EvaluationConfigModel):
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
    def validate_window(self) -> EvaluationWindow:
        if self.end < self.start:
            raise ValueError("window end must be on or after start")
        return self


class EvaluationMetricsConfig(EvaluationConfigModel):
    annualization_periods_per_year: int = Field(gt=0)


class EvaluationOutputConfig(EvaluationConfigModel):
    results_dir: Path

    @field_validator("results_dir")
    @classmethod
    def validate_results_dir(cls, value: Path, info: ValidationInfo) -> Path:
        return _resolve_inside_config_dir(value, _config_base(info), "output.results_dir")


class EvaluationConfig(EvaluationConfigModel):
    _base_dir_path: Path = PrivateAttr(default_factory=lambda: Path.cwd().resolve())

    strategy_path: Path
    strategy_id: str = Field(min_length=1)
    windows: tuple[EvaluationWindow, ...] = Field(min_length=1)
    data: DataConfig
    params: dict[str, Any] = Field(default_factory=dict)
    fill_model: FillModelConfig
    cost_model: CostModelConfig
    metrics: EvaluationMetricsConfig
    output: EvaluationOutputConfig

    def model_post_init(self, context: Any, /) -> None:
        base = context.get("base_dir") if isinstance(context, dict) else None
        base_dir = Path(base).resolve() if base is not None else Path.cwd().resolve()
        object.__setattr__(self, "_base_dir_path", base_dir)

    @property
    def base_dir(self) -> Path:
        return self._base_dir_path

    @field_validator("strategy_path")
    @classmethod
    def validate_strategy_path(cls, value: Path, info: ValidationInfo) -> Path:
        return _resolve_inside_config_dir(value, _config_base(info), "strategy_path")

    @field_validator("strategy_id")
    @classmethod
    def normalize_strategy_id(cls, value: str) -> str:
        strategy_id = value.strip()
        if not strategy_id:
            raise ValueError("strategy_id cannot be empty")
        return strategy_id

    @model_validator(mode="after")
    def validate_window_ids(self) -> EvaluationConfig:
        ids = tuple(window.id for window in self.windows)
        if len(ids) != len(set(ids)):
            raise ValueError("window ids cannot contain duplicates")
        return self

    def to_execution_spec(self, window: EvaluationWindow) -> StrategyExecutionSpec:
        return StrategyExecutionSpec(
            strategy_path=self.strategy_path,
            strategy_id=self.strategy_id,
            data=self.data.model_copy(update={"start": window.start, "end": window.end}),
            params=self.params,
            fill_model=self.fill_model,
            cost_model=self.cost_model,
            require_param_validator=True,
        )


def resolve_evaluation_config_path(path: str | Path, *, repo_root: Path | None = None) -> Path:
    anchor = _path_anchor(path, repo_root=repo_root)
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = anchor / candidate
    candidate = candidate.resolve()
    if candidate.is_dir() or candidate.suffix != ".toml":
        raise EvaluationConfigError("evaluation config path must be a TOML file")
    return candidate


def load_evaluation_config(path: str | Path, *, repo_root: Path | None = None) -> EvaluationConfig:
    config_path = resolve_evaluation_config_path(path, repo_root=repo_root)
    try:
        payload = tomllib.loads(config_path.read_text())
    except OSError as exc:
        raise EvaluationConfigError(f"could not read evaluation config: {config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise EvaluationConfigError(f"invalid TOML in evaluation config: {exc}") from exc
    try:
        return EvaluationConfig.model_validate(payload, context={"base_dir": config_path.parent})
    except ValidationError as exc:
        raise EvaluationConfigError(str(exc)) from exc
```

Create `src/quant_strategies/evaluation/__init__.py`:

```python
from __future__ import annotations

from quant_strategies.evaluation.config import EvaluationConfig

__all__ = ["EvaluationConfig"]
```

- [ ] **Step 4: Run config tests**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_config.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add src/quant_strategies/evaluation/__init__.py src/quant_strategies/evaluation/errors.py src/quant_strategies/evaluation/config.py tests/test_evaluation_config.py
git commit -m "feat: add evaluation config contract"
```

---

### Task 2: Fixed Evaluation Scenario Matrix

**Files:**
- Create: `src/quant_strategies/evaluation/scenarios.py`
- Test: `tests/test_evaluation_scenarios.py`

- [ ] **Step 1: Write failing scenario tests**

Create `tests/test_evaluation_scenarios.py`:

```python
from __future__ import annotations

from datetime import date

from quant_strategies.core.config import CostModelConfig, FillModelConfig
from quant_strategies.evaluation.config import EvaluationWindow
from quant_strategies.evaluation.scenarios import expand_evaluation_scenarios


def test_expand_evaluation_scenarios_uses_fixed_cross_product():
    window = EvaluationWindow(id="eval_2026_h1", start=date(2026, 1, 1), end=date(2026, 6, 30))
    scenarios = expand_evaluation_scenarios(
        window=window,
        base_costs=CostModelConfig(fee_bps_per_side=0.5, slippage_bps_per_side=1.5),
        base_fill=FillModelConfig(price="close", entry_lag_bars=1, exit_lag_bars=0),
    )

    assert [item.scenario_id for item in scenarios] == [
        "eval_2026_h1/zero_costs/base_fill",
        "eval_2026_h1/realistic_costs/base_fill",
        "eval_2026_h1/stressed_costs/base_fill",
        "eval_2026_h1/zero_costs/fill_lag_plus_1",
        "eval_2026_h1/realistic_costs/fill_lag_plus_1",
        "eval_2026_h1/stressed_costs/fill_lag_plus_1",
    ]
    assert scenarios[0].cost_model.fee_bps_per_side == 0.0
    assert scenarios[0].cost_model.slippage_bps_per_side == 0.0
    assert scenarios[1].cost_model.fee_bps_per_side == 0.5
    assert scenarios[1].cost_model.slippage_bps_per_side == 1.5
    assert scenarios[2].cost_model.fee_bps_per_side == 1.0
    assert scenarios[2].cost_model.slippage_bps_per_side == 3.0
    assert scenarios[3].fill_model.entry_lag_bars == 2
    assert all(item.window_id == "eval_2026_h1" for item in scenarios)
    assert all(item.required is True for item in scenarios)


def test_expand_evaluation_scenarios_preserves_fill_fields_except_entry_lag():
    window = EvaluationWindow(id="w", start=date(2026, 1, 1), end=date(2026, 1, 31))
    scenarios = expand_evaluation_scenarios(
        window=window,
        base_costs=CostModelConfig(fee_bps_per_side=0.0, slippage_bps_per_side=0.0),
        base_fill=FillModelConfig(
            price="open",
            entry_lag_bars=3,
            exit_lag_bars=2,
            allow_same_bar_close_fill=False,
        ),
    )

    fill_lag = [item for item in scenarios if item.fill_scenario == "fill_lag_plus_1"]
    assert len(fill_lag) == 3
    assert all(item.fill_model.price == "open" for item in fill_lag)
    assert all(item.fill_model.entry_lag_bars == 4 for item in fill_lag)
    assert all(item.fill_model.exit_lag_bars == 2 for item in fill_lag)
```

- [ ] **Step 2: Run scenario tests to verify they fail**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_scenarios.py -q
```

Expected: import failure for `quant_strategies.evaluation.scenarios`.

- [ ] **Step 3: Add scenario expansion implementation**

Create `src/quant_strategies/evaluation/scenarios.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from quant_strategies.core.config import CostModelConfig, FillModelConfig
from quant_strategies.evaluation.config import EvaluationWindow


CostScenario = Literal["zero_costs", "realistic_costs", "stressed_costs"]
FillScenario = Literal["base_fill", "fill_lag_plus_1"]


class EvaluationScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str = Field(min_length=1)
    window_id: str = Field(min_length=1)
    cost_scenario: CostScenario
    fill_scenario: FillScenario
    cost_model: CostModelConfig
    fill_model: FillModelConfig
    required: bool = True


def expand_evaluation_scenarios(
    *,
    window: EvaluationWindow,
    base_costs: CostModelConfig,
    base_fill: FillModelConfig,
) -> tuple[EvaluationScenario, ...]:
    cost_scenarios: tuple[tuple[CostScenario, CostModelConfig], ...] = (
        ("zero_costs", CostModelConfig(fee_bps_per_side=0.0, slippage_bps_per_side=0.0)),
        ("realistic_costs", base_costs),
        (
            "stressed_costs",
            CostModelConfig(
                fee_bps_per_side=base_costs.fee_bps_per_side * 2.0,
                slippage_bps_per_side=base_costs.slippage_bps_per_side * 2.0,
            ),
        ),
    )
    fill_scenarios: tuple[tuple[FillScenario, FillModelConfig], ...] = (
        ("base_fill", base_fill),
        (
            "fill_lag_plus_1",
            base_fill.model_copy(update={"entry_lag_bars": base_fill.entry_lag_bars + 1}),
        ),
    )
    return tuple(
        EvaluationScenario(
            scenario_id=f"{window.id}/{cost_name}/{fill_name}",
            window_id=window.id,
            cost_scenario=cost_name,
            fill_scenario=fill_name,
            cost_model=cost_model,
            fill_model=fill_model,
        )
        for fill_name, fill_model in fill_scenarios
        for cost_name, cost_model in cost_scenarios
    )
```

- [ ] **Step 4: Run scenario tests**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_scenarios.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add src/quant_strategies/evaluation/scenarios.py tests/test_evaluation_scenarios.py
git commit -m "feat: add evaluation scenario matrix"
```

---

### Task 3: Dependency Gate And Optional Extra

**Files:**
- Create: `src/quant_strategies/evaluation/dependencies.py`
- Modify: `pyproject.toml`
- Test: `tests/test_evaluation_dependencies.py`

- [ ] **Step 1: Write failing dependency tests**

Create `tests/test_evaluation_dependencies.py`:

```python
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tomllib

import pytest

import quant_strategies.evaluation.dependencies as deps_module
from quant_strategies.evaluation.dependencies import EvaluationDependencyError, require_evaluation_dependencies


def test_require_evaluation_dependencies_returns_imported_modules(monkeypatch: pytest.MonkeyPatch):
    fake_pandas = SimpleNamespace(__name__="pandas")
    fake_pyarrow = SimpleNamespace(__name__="pyarrow")
    fake_vectorbtpro = SimpleNamespace(__name__="vectorbtpro")

    def fake_import_module(name: str):
        if name == "pandas":
            return fake_pandas
        if name == "pyarrow":
            return fake_pyarrow
        if name == "vectorbtpro":
            return fake_vectorbtpro
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(deps_module, "import_module", fake_import_module)

    deps = require_evaluation_dependencies()

    assert deps.pandas is fake_pandas
    assert deps.pyarrow is fake_pyarrow
    assert deps.vectorbtpro is fake_vectorbtpro


@pytest.mark.parametrize("missing", ["pandas", "pyarrow", "vectorbtpro"])
def test_require_evaluation_dependencies_fails_without_jsonl_fallback(
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
):
    def fake_import_module(name: str):
        if name == missing:
            raise ImportError(f"missing {name}")
        if name == "pyarrow":
            return SimpleNamespace(__name__="pyarrow")
        if name == "pandas":
            return SimpleNamespace(__name__="pandas")
        if name == "vectorbtpro":
            return SimpleNamespace(__name__="vectorbtpro")
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(deps_module, "import_module", fake_import_module)

    with pytest.raises(EvaluationDependencyError, match=f"{missing} import failed"):
        require_evaluation_dependencies()


def test_pyproject_declares_evaluation_extra_dependencies():
    payload = tomllib.loads(Path("pyproject.toml").read_text())
    evaluation = payload["project"]["optional-dependencies"]["evaluation"]

    assert "vectorbtpro" in evaluation
    assert any(item.startswith("pandas>=") for item in evaluation)
    assert any(item.startswith("pyarrow>=") for item in evaluation)
```

- [ ] **Step 2: Run dependency tests to verify they fail**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_dependencies.py -q
```

Expected: import failure for `quant_strategies.evaluation.dependencies`.

- [ ] **Step 3: Add dependency gate implementation**

Create `src/quant_strategies/evaluation/dependencies.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from quant_strategies.evaluation.errors import EvaluationError


class EvaluationDependencyError(EvaluationError):
    """Raised when the required evaluation optional dependencies are unavailable."""


@dataclass(frozen=True)
class EvaluationDependencies:
    pandas: Any
    pyarrow: Any
    vectorbtpro: Any


def require_evaluation_dependencies() -> EvaluationDependencies:
    try:
        pd = import_module("pandas")
    except ImportError as exc:
        raise EvaluationDependencyError(f"pandas import failed: {exc}") from exc
    try:
        pa = import_module("pyarrow")
    except ImportError as exc:
        raise EvaluationDependencyError(f"pyarrow import failed: {exc}") from exc
    try:
        vbt = import_module("vectorbtpro")
    except ImportError as exc:
        raise EvaluationDependencyError(f"vectorbtpro import failed: {exc}") from exc
    return EvaluationDependencies(pandas=pd, pyarrow=pa, vectorbtpro=vbt)
```

Modify `pyproject.toml` optional dependencies:

```toml
[project.optional-dependencies]
vectorbtpro = [
    "pandas>=2.2",
    "vectorbtpro",
]
evaluation = [
    "pandas>=2.2",
    "pyarrow>=16",
    "vectorbtpro",
]
```

- [ ] **Step 4: Run dependency tests and metadata check**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_dependencies.py -q
```

Expected:

```text
tests pass.
The metadata test confirms the evaluation extra contains pandas, pyarrow, and vectorbtpro.
```

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add src/quant_strategies/evaluation/dependencies.py tests/test_evaluation_dependencies.py pyproject.toml
git commit -m "feat: require evaluation optional dependencies"
```

---

### Task 4: Evaluation Metrics Semantics

**Files:**
- Create: `src/quant_strategies/evaluation/metrics.py`
- Test: `tests/test_evaluation_backend.py`

- [ ] **Step 1: Write failing metric-semantics tests**

Create the first section of `tests/test_evaluation_backend.py`:

```python
from __future__ import annotations

import math

from quant_strategies.evaluation.metrics import evaluation_metric_semantics, finite_metric_or_none


def test_evaluation_metric_semantics_label_nav_metrics_as_portfolio_evidence():
    semantics = evaluation_metric_semantics()

    assert semantics["total_return"]["base"] == "portfolio NAV path"
    assert semantics["sharpe"]["annualization"] == "explicit_config.annualization_periods_per_year"
    assert semantics["trade_count"]["base"] == "VectorBT Pro portfolio trade records"
    assert semantics["total_return"]["not_authority"] == "not validation, promotion, paper trading, or live trading authority"
    assert semantics["total_return"]["cost_scope"] == "net of configured fees/slippage; excludes funding, borrow, financing, market impact"
    assert "net_return" not in semantics
    assert "turnover" not in semantics


def test_finite_metric_or_none_rejects_nan_inf_and_booleans():
    assert finite_metric_or_none(1.25) == 1.25
    assert finite_metric_or_none(3) == 3.0
    assert finite_metric_or_none(float("nan")) is None
    assert finite_metric_or_none(float("inf")) is None
    assert finite_metric_or_none(True) is None
    assert finite_metric_or_none("1.0") is None
    assert finite_metric_or_none(math.nan) is None
```

- [ ] **Step 2: Run metric tests to verify they fail**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_backend.py::test_evaluation_metric_semantics_label_nav_metrics_as_portfolio_evidence tests/test_evaluation_backend.py::test_finite_metric_or_none_rejects_nan_inf_and_booleans -q
```

Expected: import failure for `quant_strategies.evaluation.metrics`.

- [ ] **Step 3: Add metric semantics implementation**

Create `src/quant_strategies/evaluation/metrics.py`:

```python
from __future__ import annotations

import math
import numbers
from typing import Any


MetricValue = float | int | str | bool | None


def finite_metric_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def evaluation_metric_semantics() -> dict[str, dict[str, object]]:
    not_authority = "not validation, promotion, paper trading, or live trading authority"
    annualization = "explicit_config.annualization_periods_per_year"
    cost_scope = "net of configured fees/slippage; excludes funding, borrow, financing, market impact"
    return {
        "total_return": {
            "unit": "decimal_fraction",
            "base": "portfolio NAV path",
            "aggregation": "scenario total",
            "backend": "vectorbtpro",
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "ending_value": {
            "unit": "portfolio_value",
            "base": "portfolio NAV path",
            "aggregation": "scenario final value",
            "backend": "vectorbtpro",
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "annualized_return": {
            "unit": "decimal_fraction_per_year",
            "base": "periodic portfolio returns",
            "aggregation": "annualized by explicit config",
            "backend": "vectorbtpro",
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "volatility": {
            "unit": "decimal_fraction_per_year",
            "base": "periodic portfolio returns",
            "aggregation": "sample standard deviation annualized by explicit config",
            "backend": "vectorbtpro",
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "sharpe": {
            "unit": "ratio",
            "base": "periodic portfolio returns",
            "aggregation": "mean return over volatility annualized by explicit config; risk-free rate zero",
            "backend": "vectorbtpro",
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "sortino": {
            "unit": "ratio",
            "base": "periodic portfolio returns",
            "aggregation": "mean return over downside volatility annualized by explicit config; target return zero",
            "backend": "vectorbtpro",
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "calmar": {
            "unit": "ratio",
            "base": "annualized return and max drawdown",
            "aggregation": "annualized_return / abs(max_drawdown)",
            "backend": "vectorbtpro",
            "annualization": annualization,
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "max_drawdown": {
            "unit": "decimal_fraction",
            "base": "portfolio NAV path",
            "aggregation": "minimum drawdown over scenario",
            "backend": "vectorbtpro",
            "cost_scope": cost_scope,
            "not_authority": not_authority,
        },
        "trade_count": {
            "unit": "count",
            "base": "VectorBT Pro portfolio trade records",
            "aggregation": "scenario total",
            "backend": "vectorbtpro",
            "not_authority": not_authority,
        },
        "win_rate": {
            "unit": "ratio",
            "base": "VectorBT Pro portfolio trade records",
            "aggregation": "winning trades / all closed trades",
            "backend": "vectorbtpro",
            "not_authority": not_authority,
        },
        "profit_factor": {
            "unit": "ratio",
            "base": "VectorBT Pro portfolio trade records",
            "aggregation": "gross profits / abs(gross losses)",
            "backend": "vectorbtpro",
            "not_authority": not_authority,
        },
    }
```

- [ ] **Step 4: Run metric tests**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_backend.py::test_evaluation_metric_semantics_label_nav_metrics_as_portfolio_evidence tests/test_evaluation_backend.py::test_finite_metric_or_none_rejects_nan_inf_and_booleans -q
```

Expected: both tests pass.

- [ ] **Step 5: Commit Task 4**

Run:

```bash
git add src/quant_strategies/evaluation/metrics.py tests/test_evaluation_backend.py
git commit -m "feat: define evaluation metric semantics"
```

---

### Task 5: VectorBT Pro Portfolio Backend

**Files:**
- Create: `src/quant_strategies/evaluation/backend.py`
- Modify: `tests/test_evaluation_backend.py`

- [ ] **Step 1: Add backend tests with fake VectorBT Pro**

Append to `tests/test_evaluation_backend.py`:

```python
import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import quant_strategies.evaluation.backend as backend_module
from quant_strategies.decisions import DecisionIntent, ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.evaluation.backend import VectorBTProEvaluationBackend
from quant_strategies.evaluation.config import EvaluationMetricsConfig
from quant_strategies.evaluation.dependencies import EvaluationDependencies
from quant_strategies.evaluation.scenarios import EvaluationScenario
from quant_strategies.core.config import CostModelConfig, FillModelConfig


AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


def rows():
    return [
        {"symbol": "BTC-PERP", "timestamp": AS_OF, "close": 100.0},
        {"symbol": "BTC-PERP", "timestamp": DECISION, "close": 101.0},
        {"symbol": "BTC-PERP", "timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc), "close": 102.0},
        {"symbol": "BTC-PERP", "timestamp": datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc), "close": 103.0},
    ]


def decision(*, symbol: str = "BTC-PERP", size: float = 1.0, direction: str = "long"):
    return StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol=symbol),
        intent=DecisionIntent(action="open"),
        decision_time=DECISION,
        as_of_time=AS_OF,
        target=PositionTarget(direction=direction, sizing_kind="target_weight", size=size),
        exit_policy=ExitPolicy(max_hold_bars=1),
    )


def scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="w/realistic_costs/base_fill",
        window_id="w",
        cost_scenario="realistic_costs",
        fill_scenario="base_fill",
        cost_model=CostModelConfig(fee_bps_per_side=1.0, slippage_bps_per_side=2.0),
        fill_model=FillModelConfig(price="close", entry_lag_bars=1, exit_lag_bars=0),
    )


def install_fake_vbt(monkeypatch: pytest.MonkeyPatch):
    pd = pytest.importorskip("pandas")

    class FakeSeries:
        def __init__(self, values):
            self._values = values

        def to_frame(self, name):
            import pandas as pd

            return pd.DataFrame({name: self._values})

        def pct_change(self):
            return FakeSeries([0.0, 0.01, -0.02])

        def fillna(self, value):
            return self

    class FakeTrades:
        def count(self):
            return 2

        def win_rate(self):
            return 0.5

        def profit_factor(self):
            return 1.5

        @property
        def records_readable(self):
            import pandas as pd

            return pd.DataFrame({"Trade Id": [1, 2], "Column": ["BTC-PERP", "BTC-PERP"]})

    class FakePortfolio:
        trades = FakeTrades()

        def __init__(self, close, **kwargs):
            self.close = close
            self.kwargs = kwargs

        def value(self):
            return FakeSeries([100.0, 101.0, 99.0])

        def returns(self):
            return FakeSeries([0.0, 0.01, -0.019801980198])

        def drawdowns(self):
            return FakeSeries([0.0, 0.0, -0.019801980198])

        def get_total_return(self):
            return -0.01

        def get_max_drawdown(self):
            return -0.019801980198

    captured = {}

    def from_signals(close, **kwargs):
        captured["close_columns"] = list(close.columns)
        captured["kwargs"] = kwargs
        return FakePortfolio(close, **kwargs)

    fake_vbt = SimpleNamespace(Portfolio=SimpleNamespace(from_signals=from_signals))
    fake_pyarrow = SimpleNamespace(__name__="pyarrow")
    monkeypatch.setattr(
        backend_module,
        "require_evaluation_dependencies",
        lambda: EvaluationDependencies(pandas=pd, pyarrow=fake_pyarrow, vectorbtpro=fake_vbt),
    )
    return captured


def test_vectorbtpro_evaluation_backend_returns_metrics_and_tables(monkeypatch: pytest.MonkeyPatch):
    captured = install_fake_vbt(monkeypatch)

    result = VectorBTProEvaluationBackend().run(
        decisions=[decision()],
        rows=rows(),
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
    )

    assert result.status == "completed"
    assert result.backend == "vectorbtpro"
    assert result.scenario_id == "w/realistic_costs/base_fill"
    assert result.metrics["total_return"] == pytest.approx(-0.01)
    assert result.metrics["max_drawdown"] == pytest.approx(-0.019801980198)
    assert result.metrics["trade_count"] == 2
    assert result.metrics["win_rate"] == pytest.approx(0.5)
    assert result.metrics["profit_factor"] == pytest.approx(1.5)
    assert "sharpe" in result.metrics
    assert result.tables is not None
    assert not result.tables.portfolio_path.empty
    assert not result.tables.trades.empty
    assert set(captured["close_columns"]) == {"BTC-PERP"}
    assert captured["kwargs"]["cash_sharing"] is True
    assert captured["kwargs"]["group_by"] is True


def test_vectorbtpro_evaluation_backend_reports_unsupported_threshold_exit():
    bad = decision()
    bad = bad.model_copy(update={"exit_policy": ExitPolicy(max_hold_bars=1, stop_loss_bps=100.0)})

    result = VectorBTProEvaluationBackend().run(
        decisions=[bad],
        rows=rows(),
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
    )

    assert result.status == "unsupported"
    assert result.unsupported_semantics == ("threshold_exit_policy",)
    assert result.tables is None


def test_vectorbtpro_evaluation_backend_reports_leveraged_target_weight():
    result = VectorBTProEvaluationBackend().run(
        decisions=[decision(size=1.25)],
        rows=rows(),
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
    )

    assert result.status == "unsupported"
    assert "leveraged_target_weight" in result.unsupported_semantics


def test_vectorbtpro_evaluation_backend_fails_when_simultaneous_gross_exposure_exceeds_one(
    monkeypatch: pytest.MonkeyPatch,
):
    install_fake_vbt(monkeypatch)
    overlapping = [
        decision(size=0.75),
        decision(size=0.75),
    ]

    result = VectorBTProEvaluationBackend().run(
        decisions=overlapping,
        rows=rows(),
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
    )

    assert result.status == "failed"
    assert "portfolio_target_weight_exceeds_one" in result.warnings[0]
```

- [ ] **Step 2: Run backend tests to verify they fail**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_backend.py -q
```

Expected: import failure for `quant_strategies.evaluation.backend`.

- [ ] **Step 3: Implement backend result models and adapter**

Create `src/quant_strategies/evaluation/backend.py` with these public models and helper boundaries:

```python
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from quant_strategies.decisions import StrategyDecision
from quant_strategies.engine.executable import base_unsupported_semantics
from quant_strategies.evaluation.config import EvaluationMetricsConfig
from quant_strategies.evaluation.dependencies import EvaluationDependencyError, require_evaluation_dependencies
from quant_strategies.evaluation.metrics import MetricValue, finite_metric_or_none
from quant_strategies.evaluation.scenarios import EvaluationScenario


EvaluationBackendStatus = Literal["completed", "failed", "unsupported", "unavailable"]


@dataclass(frozen=True)
class PortfolioTraceTables:
    portfolio_path: Any
    trades: Any
    positions: Any
    per_asset_metrics: Any


@dataclass(frozen=True)
class PreparedPortfolioInputs:
    close: Any
    decisions: tuple[StrategyDecision, ...]


class PortfolioEvaluationResult(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    scenario_id: str
    backend: str
    status: EvaluationBackendStatus
    metrics: dict[str, MetricValue] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    unsupported_semantics: tuple[str, ...] = ()
    tables: PortfolioTraceTables | None = None


class VectorBTProEvaluationBackend:
    name = "vectorbtpro"

    def prepare_inputs(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: Sequence[Mapping[str, Any]],
    ) -> PreparedPortfolioInputs:
        deps = require_evaluation_dependencies()
        close = _close_frame(deps.pandas, rows, decisions)
        return PreparedPortfolioInputs(close=close, decisions=tuple(decisions))

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: Sequence[Mapping[str, Any]],
        scenario: EvaluationScenario,
        metrics: EvaluationMetricsConfig,
    ) -> PortfolioEvaluationResult:
        try:
            prepared = self.prepare_inputs(decisions=decisions, rows=rows)
        except EvaluationDependencyError as exc:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="unavailable",
                warnings=(str(exc),),
            )
        except ValueError as exc:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="failed",
                warnings=(str(exc),),
            )
        return self.run_prepared(prepared=prepared, scenario=scenario, metrics=metrics)

    def run_prepared(
        self,
        *,
        prepared: PreparedPortfolioInputs,
        scenario: EvaluationScenario,
        metrics: EvaluationMetricsConfig,
    ) -> PortfolioEvaluationResult:
        unsupported = _unsupported_semantics(list(prepared.decisions), scenario)
        if unsupported:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="unsupported",
                unsupported_semantics=unsupported,
            )
        try:
            deps = require_evaluation_dependencies()
        except EvaluationDependencyError as exc:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="unavailable",
                warnings=(str(exc),),
            )
        pd = deps.pandas
        vbt = deps.vectorbtpro
        try:
            windows = _decision_windows(pd, prepared.close, list(prepared.decisions), scenario)
            portfolio = _run_portfolio(vbt, pd, prepared.close, windows, scenario)
            metric_payload = _portfolio_metrics(portfolio, metrics.annualization_periods_per_year)
            tables = _portfolio_tables(pd, portfolio, scenario.scenario_id)
        except ValueError as exc:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="failed",
                warnings=(str(exc),),
            )
        except Exception as exc:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="failed",
                warnings=(f"vectorbtpro_evaluation_failed:{type(exc).__name__}:{exc}",),
            )
        return PortfolioEvaluationResult(
            scenario_id=scenario.scenario_id,
            backend=self.name,
            status="completed",
            metrics=metric_payload,
            tables=tables,
        )
```

Complete the helper implementations in the same file:

```python
def _unsupported_semantics(decisions: list[StrategyDecision], scenario: EvaluationScenario) -> tuple[str, ...]:
    unsupported: list[str] = []
    for item in decisions:
        unsupported.extend(base_unsupported_semantics(item))
        if item.target.sizing_kind != "target_weight":
            unsupported.append("non_target_weight_sizing")
        if item.target.direction not in {"long", "short"}:
            unsupported.append("unsupported_direction")
        if item.target.size < 0:
            unsupported.append("negative_target_weight")
        if item.target.size > 1.0:
            unsupported.append("leveraged_target_weight")
        if (
            item.exit_policy.stop_loss_bps is not None
            or item.exit_policy.take_profit_bps is not None
            or item.exit_policy.trailing_stop_bps is not None
        ):
            unsupported.append("threshold_exit_policy")
    if scenario.fill_model.price != "close":
        unsupported.append("non_close_fill_price")
    return tuple(dict.fromkeys(unsupported))
```

After `_decision_windows(...)` builds entry/exit windows, validate simultaneous
gross exposure:

```python
def _validate_max_gross_target_weight(windows: list[dict[str, Any]]) -> float:
    max_gross = 0.0
    for current in windows:
        timestamp = current["entry_time"]
        gross = 0.0
        for window in windows:
            if window["entry_time"] <= timestamp <= window["exit_time"]:
                gross += abs(float(window["decision"].target.size))
        max_gross = max(max_gross, gross)
        if gross > 1.0 + 1e-12:
            raise ValueError(f"portfolio_target_weight_exceeds_one:{timestamp.isoformat()}:{gross}")
    return max_gross
```

Use the current `validation.vectorbtpro_backend` implementation as the source pattern for:

- `_close_frame`;
- `_decision_windows`;
- duplicate signal checks;
- missing symbol checks;
- unfillable entry/exit checks;
- long/short signal frame construction.

Use these evaluation-specific metric rules:

```python
def _portfolio_metrics(portfolio: Any, annualization_periods_per_year: int) -> dict[str, MetricValue]:
    returns = _series_or_none(portfolio, "returns")
    values = _series_or_none(portfolio, "value")
    total_return = _call_metric(portfolio, "get_total_return")
    max_drawdown = _call_metric(portfolio, "get_max_drawdown")
    trade_count = _call_metric(portfolio.trades, "count") if hasattr(portfolio, "trades") else None
    win_rate = _call_metric(portfolio.trades, "win_rate") if hasattr(portfolio, "trades") else None
    profit_factor = _call_metric(portfolio.trades, "profit_factor") if hasattr(portfolio, "trades") else None
    payload: dict[str, MetricValue] = {}
    _set_metric(payload, "total_return", total_return)
    ending_value = _last_finite(values)
    _set_metric(payload, "ending_value", ending_value)
    _set_metric(payload, "max_drawdown", max_drawdown)
    _set_metric(payload, "trade_count", trade_count)
    _set_metric(payload, "win_rate", win_rate)
    _set_metric(payload, "profit_factor", None if profit_factor in (float("inf"), float("-inf")) else profit_factor)
    if returns is not None:
        finite_returns = [float(value) for value in returns if finite_metric_or_none(value) is not None]
        observed_returns = finite_returns[1:] if len(finite_returns) > 1 else []
        if observed_returns:
            total = finite_metric_or_none(total_return)
            annualized_return = (
                None
                if total is None
                else ((1.0 + total) ** (annualization_periods_per_year / len(observed_returns))) - 1.0
            )
            mean_return = sum(observed_returns) / len(observed_returns)
            volatility = (
                None
                if len(observed_returns) < 2
                else _sample_stdev(observed_returns) * math.sqrt(annualization_periods_per_year)
            )
            downside_returns = [value for value in observed_returns if value < 0.0]
            downside_vol = (
                None
                if len(downside_returns) < 2
                else _sample_stdev(downside_returns) * math.sqrt(annualization_periods_per_year)
            )
            payload["annualized_return"] = annualized_return
            payload["volatility"] = volatility
            annualized_mean = mean_return * annualization_periods_per_year
            payload["sharpe"] = None if not volatility else annualized_mean / volatility
            payload["sortino"] = None if not downside_vol else annualized_mean / downside_vol
            max_dd = finite_metric_or_none(max_drawdown)
            payload["calmar"] = (
                None
                if annualized_return is None or max_dd in (None, 0.0)
                else annualized_return / abs(max_dd)
            )
            payload["worst_period_return"] = min(observed_returns)
    return payload
```

Add these helper contracts in the same file:

```python
def _last_finite(values: Sequence[Any] | None) -> float | None:
    if values is None:
        return None
    finite = [finite_metric_or_none(value) for value in values]
    finite = [value for value in finite if value is not None]
    return finite[-1] if finite else None


def _sample_stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)
```

Ensure `_portfolio_tables` returns pandas DataFrames with a `scenario_id` column:

```python
def _portfolio_tables(pd: Any, portfolio: Any, scenario_id: str) -> PortfolioTraceTables:
    path = _frame_from_series(pd, portfolio.value(), "portfolio_value")
    returns = _frame_from_series(pd, portfolio.returns(), "period_return")
    drawdown = _frame_from_series(pd, portfolio.drawdowns(), "drawdown")
    portfolio_path = path.join(returns, how="outer").join(drawdown, how="outer").reset_index()
    portfolio_path.insert(0, "scenario_id", scenario_id)
    trades = _records_frame(pd, getattr(getattr(portfolio, "trades", None), "records_readable", None), scenario_id)
    positions = pd.DataFrame({"scenario_id": []})
    per_asset_metrics = pd.DataFrame({"scenario_id": []})
    return PortfolioTraceTables(
        portfolio_path=portfolio_path,
        trades=trades,
        positions=positions,
        per_asset_metrics=per_asset_metrics,
    )
```

- [ ] **Step 4: Run backend tests**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_backend.py -q
```

Expected: all backend tests pass.

- [ ] **Step 5: Add optional real VectorBT Pro smoke test**

Append to `tests/test_evaluation_backend.py`:

```python
def test_vectorbtpro_evaluation_backend_real_smoke_if_installed():
    if os.environ.get("RUN_VECTORBTPRO_SMOKE") != "1":
        pytest.skip("set RUN_VECTORBTPRO_SMOKE=1 to run real VectorBT Pro smoke test")
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    pytest.importorskip("vectorbtpro")

    result = VectorBTProEvaluationBackend().run(
        decisions=[decision(size=0.25)],
        rows=rows(),
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
    )

    assert result.status == "completed"
    assert result.metrics["trade_count"] >= 1
    assert result.tables is not None
    assert "scenario_id" in result.tables.portfolio_path.columns
```

- [ ] **Step 6: Run backend smoke test file**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_backend.py -q
```

Expected: unit tests pass; real smoke test is skipped when VectorBT Pro is not installed.

- [ ] **Step 7: Commit Task 5**

Run:

```bash
git add src/quant_strategies/evaluation/backend.py tests/test_evaluation_backend.py
git commit -m "feat: add vectorbtpro evaluation backend"
```

---

### Task 6: Parquet Artifact Writers And Manifest Metadata

**Files:**
- Create: `src/quant_strategies/evaluation/artifacts.py`
- Test: `tests/test_evaluation_artifacts.py`

- [ ] **Step 1: Write failing artifact tests**

Create `tests/test_evaluation_artifacts.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from quant_strategies.evaluation.artifacts import (
    create_evaluation_result_dir,
    table_metadata,
    write_json_artifact,
    write_parquet_artifact,
    write_text_artifact,
)


def test_write_parquet_artifact_records_schema_hash_and_row_count(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    frame = pd.DataFrame(
        {
            "scenario_id": ["w/base", "w/base"],
            "timestamp": [
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 2, tzinfo=timezone.utc),
            ],
            "portfolio_value": [100.0, 101.0],
        }
    )

    metadata = write_parquet_artifact(
        result_dir,
        "tables/portfolio_path.parquet",
        frame,
        artifact_kind="portfolio_path",
        scenario_ids=("w/base",),
    )

    path = result_dir / "tables" / "portfolio_path.parquet"
    assert path.exists()
    assert metadata["path"] == "tables/portfolio_path.parquet"
    assert metadata["artifact_kind"] == "portfolio_path"
    assert metadata["format"] == "parquet"
    assert metadata["row_count"] == 2
    assert [column["name"] for column in metadata["columns"]] == ["scenario_id", "timestamp", "portfolio_value"]
    assert metadata["scenario_ids"] == ["w/base"]
    assert len(metadata["file_sha256"]) == 64
    assert len(metadata["schema_sha256"]) == 64
    assert metadata["byte_size"] > 0
    assert metadata["row_group_count"] >= 1


def test_table_metadata_is_stable_for_empty_table(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    frame = pd.DataFrame({"scenario_id": [], "asset": [], "turnover": []})

    metadata = write_parquet_artifact(
        result_dir,
        "tables/per_asset_metrics.parquet",
        frame,
        artifact_kind="per_asset_metrics",
        scenario_ids=(),
    )

    assert metadata["row_count"] == 0
    assert [column["name"] for column in metadata["columns"]] == ["scenario_id", "asset", "turnover"]
    assert "scenario_id" in metadata["arrow_schema"]


def test_write_json_artifact_rejects_path_escape(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()

    try:
        write_json_artifact(result_dir, "../escape.json", {"x": 1})
    except ValueError as exc:
        assert "Artifact name must stay inside result_dir" in str(exc)
    else:
        raise AssertionError("path escape should fail")


def test_write_text_artifact_writes_plain_markdown(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()

    path = write_text_artifact(result_dir, "notes.md", "# Notes\n")

    assert path == result_dir / "notes.md"
    assert path.read_text() == "# Notes\n"


def test_create_evaluation_result_dir_uses_strategy_id_and_suffix(tmp_path: Path):
    root = tmp_path / "evaluation_results"
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    first = create_evaluation_result_dir(root, "demo strategy", now=now)
    second = create_evaluation_result_dir(root, "demo strategy", now=now)

    assert first.name == "2026-01-01T120000Z-demo_strategy"
    assert second.name == "2026-01-01T120000Z-demo_strategy-2"
```

- [ ] **Step 2: Run artifact tests to verify they fail**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_artifacts.py -q
```

Expected: import failure for `quant_strategies.evaluation.artifacts`.

- [ ] **Step 3: Add artifact writer implementation**

Create `src/quant_strategies/evaluation/artifacts.py`:

```python
from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_strategies.core.serialization import json_safe_value
from quant_strategies.evaluation.metrics import evaluation_metric_semantics
from quant_strategies.provenance import artifact_hashes, environment_identity, file_sha256, source_identity, text_sha256


def create_evaluation_result_dir(results_root: Path, strategy_id: str, *, now: datetime | None = None) -> Path:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    safe_strategy_id = _safe_name(strategy_id)
    base_name = f"{timestamp}-{safe_strategy_id}"
    results_root.mkdir(parents=True, exist_ok=True)
    result_dir = results_root / base_name
    suffix = 2
    while True:
        try:
            result_dir.mkdir()
        except FileExistsError:
            result_dir = results_root / f"{base_name}-{suffix}"
            suffix += 1
            continue
        return result_dir


def initialize_evaluation_artifacts(config_path: Path, strategy_path: Path, result_dir: Path) -> None:
    shutil.copyfile(config_path, result_dir / "evaluation_config.toml")
    if strategy_path.is_file():
        shutil.copyfile(strategy_path, result_dir / "strategy_snapshot.py")


def write_json_artifact(result_dir: Path, name: str, payload: Any) -> Path:
    path = _artifact_path(result_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe_value(payload), indent=2, sort_keys=True, allow_nan=False) + "\n")
    return path


def write_text_artifact(result_dir: Path, name: str, payload: str) -> Path:
    path = _artifact_path(result_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if payload.endswith("\n") else payload + "\n")
    return path


def write_data_manifest(
    result_dir: Path,
    *,
    windows: list[dict[str, Any]],
) -> Path:
    return write_json_artifact(
        result_dir,
        "data_manifest.json",
        {
            "schema_version": "quant_strategies.evaluation.data_manifest/v1",
            "windows": windows,
        },
    )


def write_parquet_artifact(
    result_dir: Path,
    name: str,
    frame: Any,
    *,
    artifact_kind: str,
    scenario_ids: Iterable[str],
) -> dict[str, Any]:
    path = _artifact_path(result_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, engine="pyarrow", index=False, compression="zstd")
    return table_metadata(
        result_dir,
        path,
        frame,
        artifact_kind=artifact_kind,
        scenario_ids=tuple(scenario_ids),
    )


def table_metadata(
    result_dir: Path,
    path: Path,
    frame: Any,
    *,
    artifact_kind: str,
    scenario_ids: tuple[str, ...],
) -> dict[str, Any]:
    import pyarrow.parquet as pq

    parquet_file = pq.ParquetFile(path)
    schema = parquet_file.schema_arrow
    arrow_schema = str(schema)
    return {
        "path": path.resolve().relative_to(result_dir.resolve()).as_posix(),
        "artifact_kind": artifact_kind,
        "format": "parquet",
        "compression": "zstd",
        "row_count": int(parquet_file.metadata.num_rows),
        "row_group_count": int(parquet_file.metadata.num_row_groups),
        "column_count": len(schema.names),
        "columns": [
            {
                "name": field.name,
                "logical_type": str(field.type),
                "nullable": bool(field.nullable),
            }
            for field in schema
        ],
        "arrow_schema": arrow_schema,
        "schema_sha256": text_sha256(arrow_schema),
        "file_sha256": file_sha256(path),
        "byte_size": path.stat().st_size,
        "scenario_ids": list(scenario_ids),
    }


def write_evaluation_manifest(
    result_dir: Path,
    *,
    repo_root: Path,
    path_base: Path,
    config: Any,
    config_path: Path,
    backend_name: str,
    data_windows: list[dict[str, Any]],
    table_artifacts: list[dict[str, Any]],
    scenario_summary: Mapping[str, Any],
) -> Path:
    write_json_artifact(
        result_dir,
        "environment.json",
        environment_identity(
            repo_root,
            package_names=["quant-strategies", "quant-data", "pydantic", "pandas", "pyarrow", "vectorbtpro"],
            exclude_paths=(result_dir,),
        ),
    )
    payload = {
        "manifest_schema_version": "quant_strategies.evaluation.manifest/v1",
        "artifact_profile": "evaluation_parquet_trace_v1",
        "repository": source_identity(repo_root),
        "evaluation": {
            "strategy_id": config.strategy_id,
            "backend": {
                "name": backend_name,
                "version": None,
            },
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "config_path": _relative_path(config_path, path_base),
            "config_sha256": file_sha256(config_path),
            "assessment_status": "evaluation_complete",
            "evidence_class": "research_evaluation",
            "not_authority": "not validation, promotion, paper trading, or live trading authority",
        },
        "strategy": {
            "path": _relative_path(Path(config.strategy_path), path_base),
            "snapshot_sha256": _optional_hash(result_dir / "strategy_snapshot.py"),
        },
        "data": {
            "manifest_path": "data_manifest.json",
            "windows": data_windows,
        },
        "metric_semantics": evaluation_metric_semantics(),
        "scenario_summary": json_safe_value(scenario_summary),
        "scenario_coverage": scenario_summary["scenario_coverage"],
        "tables": table_artifacts,
        "replayability": {
            "basis": "candidate config, strategy snapshot, normalized row hash, scenario assumptions, and Parquet trace tables",
            "input_rows_embedded": False,
            "limitation": "input rows are identified by normalized hash and upstream data config; raw rows are not embedded in evaluation artifacts",
        },
        "trace_artifacts": {
            "format": "parquet",
            "table_count": len(table_artifacts),
            "total_byte_size": sum(int(item["byte_size"]) for item in table_artifacts),
        },
        "artifacts": artifact_hashes(
            result_dir,
            exclude_names={
                "evaluation_manifest.json",
                "environment.json",
                "portfolio_path.parquet",
                "trades.parquet",
                "positions.parquet",
                "per_asset_metrics.parquet",
            },
            recursive=True,
        ),
    }
    return write_json_artifact(result_dir, "evaluation_manifest.json", payload)


def _artifact_path(result_dir: Path, name: str) -> Path:
    artifact_name = Path(name)
    if artifact_name.is_absolute() or ".." in artifact_name.parts:
        raise ValueError("Artifact name must stay inside result_dir")
    root = result_dir.resolve()
    path = result_dir / artifact_name
    try:
        path.resolve().relative_to(root)
    except ValueError as exc:
        raise ValueError("Artifact name must stay inside result_dir") from exc
    return path


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("_") or "evaluation"


def _optional_hash(path: Path) -> str | None:
    try:
        return file_sha256(path)
    except OSError:
        return None


def _relative_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path)
```

- [ ] **Step 4: Run artifact tests**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_artifacts.py -q
```

Expected: all artifact tests pass.

- [ ] **Step 5: Commit Task 6**

Run:

```bash
git add src/quant_strategies/evaluation/artifacts.py tests/test_evaluation_artifacts.py
git commit -m "feat: add evaluation parquet artifacts"
```

---

### Task 7: Evaluation Runner Orchestration

**Files:**
- Create: `src/quant_strategies/evaluation/runner.py`
- Modify: `src/quant_strategies/evaluation/__init__.py`
- Test: `tests/test_evaluation_runner.py`

- [ ] **Step 1: Write failing runner integration tests**

Create `tests/test_evaluation_runner.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

import quant_strategies.evaluation.runner as evaluation_runner
from quant_strategies.evaluation.backend import PortfolioEvaluationResult, PortfolioTraceTables
from quant_strategies.evaluation.runner import run_evaluation
from quant_strategies.runner.data_loader import LoadedData


AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


def rows():
    return [
        {"symbol": "BTC-PERP", "timestamp": AS_OF, "available_at": AS_OF, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
        {"symbol": "BTC-PERP", "timestamp": DECISION, "available_at": DECISION, "open": 101.0, "high": 101.0, "low": 101.0, "close": 101.0},
        {"symbol": "BTC-PERP", "timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc), "available_at": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc), "open": 102.0, "high": 102.0, "low": 102.0, "close": 102.0},
        {"symbol": "BTC-PERP", "timestamp": datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc), "available_at": datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc), "open": 103.0, "high": 103.0, "low": 103.0, "close": 103.0},
    ]


def write_candidate(tmp_path: Path, *, with_param_validator: bool = True) -> Path:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    validator = "def validate_params(params):\n    return dict(params)\n" if with_param_validator else ""
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, ObservationRef, PositionTarget, StrategyDecision\n"
        f"{validator}"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[1]['timestamp'],\n"
        "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=0.25),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[1]['timestamp'], field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    (candidate / "evaluation.toml").write_text(
        '''
strategy_path = "strategy.py"
strategy_id = "demo"

[[windows]]
id = "eval_2026_h1"
start = "2026-01-01"
end = "2026-06-30"

[data]
kind = "crypto_perp_funding"
symbols = ["BTC-PERP"]
strict = true
start = "2026-01-01"
end = "2026-06-30"

[params]
weight = 0.25

[fill_model]
price = "close"
entry_lag_bars = 1
exit_lag_bars = 0

[cost_model]
fee_bps_per_side = 0.5
slippage_bps_per_side = 0.5

[metrics]
annualization_periods_per_year = 365

[output]
results_dir = "evaluation_results/demo"
'''.lstrip()
    )
    return candidate


class FakeBackend:
    name = "fake_evaluation"

    def run(self, *, decisions, rows, scenario, metrics):
        frame = pd.DataFrame(
            {
                "scenario_id": [scenario.scenario_id],
                "timestamp": [rows[0]["timestamp"]],
                "portfolio_value": [100.0],
                "period_return": [0.0],
                "drawdown": [0.0],
            }
        )
        tables = PortfolioTraceTables(
            portfolio_path=frame,
            trades=pd.DataFrame({"scenario_id": [scenario.scenario_id], "trade_id": [1]}),
            positions=pd.DataFrame({"scenario_id": [scenario.scenario_id], "asset": ["BTC-PERP"], "weight": [0.25]}),
            per_asset_metrics=pd.DataFrame({"scenario_id": [scenario.scenario_id], "asset": ["BTC-PERP"], "trade_count": [1]}),
        )
        return PortfolioEvaluationResult(
            scenario_id=scenario.scenario_id,
            backend=self.name,
            status="completed",
            metrics={"total_return": 0.01, "trade_count": 1},
            tables=tables,
        )


def test_run_evaluation_writes_evidence_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config, **_kwargs: LoadedData(rows=rows()))

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=FakeBackend())

    assert result.run_completed is True
    assert result.failure_stage is None
    assert result.assessment_status == "evaluation_complete"
    assert result.result_dir is not None
    assert (result.result_dir / "evaluation_config.toml").exists()
    assert (result.result_dir / "strategy_snapshot.py").exists()
    assert (result.result_dir / "data_manifest.json").exists()
    assert (result.result_dir / "evaluation_metrics.json").exists()
    assert (result.result_dir / "scenario_summary.json").exists()
    assert (result.result_dir / "tables" / "portfolio_path.parquet").exists()
    assert (result.result_dir / "tables" / "trades.parquet").exists()
    assert (result.result_dir / "tables" / "positions.parquet").exists()
    assert (result.result_dir / "tables" / "per_asset_metrics.parquet").exists()
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert data_manifest["schema_version"] == "quant_strategies.evaluation.data_manifest/v1"
    assert data_manifest["windows"][0]["window_id"] == "eval_2026_h1"
    assert data_manifest["windows"][0]["row_count"] == 4
    assert data_manifest["windows"][0]["row_contract"]["status"] == "passed"
    assert data_manifest["windows"][0]["decision_count"] == 1
    manifest = json.loads((result.result_dir / "evaluation_manifest.json").read_text())
    assert manifest["evaluation"]["evidence_class"] == "research_evaluation"
    assert manifest["evaluation"]["not_authority"] == "not validation, promotion, paper trading, or live trading authority"
    assert len(manifest["tables"]) == 4
    assert {item["artifact_kind"] for item in manifest["tables"]} == {
        "portfolio_path",
        "trades",
        "positions",
        "per_asset_metrics",
    }
    assert all(len(item["scenario_ids"]) == 6 for item in manifest["tables"])
    assert manifest["scenario_coverage"]["expected_count"] == 6
    assert manifest["scenario_coverage"]["missing_ids"] == []


def test_run_evaluation_requires_validate_params(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    candidate = write_candidate(tmp_path, with_param_validator=False)
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config, **_kwargs: LoadedData(rows=rows()))

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=FakeBackend())

    assert result.run_completed is False
    assert result.failure_stage == "param_validation"
    assert result.assessment_status == "evaluation_failed"
    assert "param validation failed" in result.message


def test_run_evaluation_fails_on_backend_unsupported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    class UnsupportedBackend(FakeBackend):
        def run(self, *, decisions, rows, scenario, metrics):
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="unsupported",
                unsupported_semantics=("non_target_weight_sizing",),
            )

    candidate = write_candidate(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config, **_kwargs: LoadedData(rows=rows()))

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=UnsupportedBackend())

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_evaluation_failed"
    assert "non_target_weight_sizing" in result.message


def test_run_evaluation_maps_backend_unavailable_to_public_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    class UnavailableBackend(FakeBackend):
        def run(self, *, decisions, rows, scenario, metrics):
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="unavailable",
                warnings=("vectorbtpro import failed",),
            )

    candidate = write_candidate(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config, **_kwargs: LoadedData(rows=rows()))

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=UnavailableBackend())

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_backend_unavailable"
    assert "vectorbtpro import failed" in result.message


def test_run_evaluation_fails_before_portfolio_on_failed_row_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path)
    invalid_rows = [
        {key: value for key, value in row.items() if key != "available_at"}
        for row in rows()
    ]
    monkeypatch.setattr(
        "quant_strategies.runner.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=invalid_rows),
    )

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=FakeBackend())

    assert result.run_completed is False
    assert result.failure_stage == "data_load"
    assert result.assessment_status == "evaluation_failed"
    assert "row contract failed" in result.message
```

- [ ] **Step 2: Run runner tests to verify they fail**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_runner.py -q
```

Expected: import failure for `quant_strategies.evaluation.runner`.

- [ ] **Step 3: Add runner orchestration**

Create `src/quant_strategies/evaluation/runner.py`:

```python
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quant_strategies.causality import check_hidden_lookahead
from quant_strategies.core.config import default_repo_root
from quant_strategies.evaluation.artifacts import (
    create_evaluation_result_dir,
    initialize_evaluation_artifacts,
    write_data_manifest,
    write_evaluation_manifest,
    write_json_artifact,
    write_parquet_artifact,
    write_text_artifact,
)
from quant_strategies.evaluation.backend import PortfolioEvaluationResult, VectorBTProEvaluationBackend
from quant_strategies.evaluation.config import load_evaluation_config, resolve_evaluation_config_path
from quant_strategies.evaluation.dependencies import EvaluationDependencyError
from quant_strategies.evaluation.errors import EvaluationConfigError
from quant_strategies.evaluation.metrics import evaluation_metric_semantics
from quant_strategies.evaluation.scenarios import expand_evaluation_scenarios
from quant_strategies.runner.execution import StrategyExecutionError, execute_strategy_run


@dataclass(frozen=True)
class EvaluationRunResult:
    result_dir: Path | None
    message: str
    run_completed: bool = False
    failure_stage: str | None = None
    assessment_status: str = "evaluation_failed"
    evidence_quality_warnings: tuple[str, ...] = ()


def run_evaluation(
    config_path: str | Path,
    *,
    repo_root: Path | None = None,
    backend: Any | None = None,
) -> EvaluationRunResult:
    root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
    try:
        resolved_config_path = resolve_evaluation_config_path(config_path, repo_root=repo_root)
        config = load_evaluation_config(resolved_config_path)
    except EvaluationConfigError as exc:
        return EvaluationRunResult(
            result_dir=None,
            message=str(exc),
            failure_stage="config_load",
            assessment_status="evaluation_failed",
        )
    try:
        result_dir = create_evaluation_result_dir(config.output.results_dir, config.strategy_id)
        initialize_evaluation_artifacts(resolved_config_path, config.strategy_path, result_dir)
    except OSError as exc:
        return EvaluationRunResult(
            result_dir=None,
            message=f"artifact initialization failed: {exc}",
            failure_stage="artifact_initialization",
            assessment_status="evaluation_failed",
        )

    selected_backend = backend or VectorBTProEvaluationBackend()
    backend_results: list[PortfolioEvaluationResult] = []
    trace_results: list[PortfolioEvaluationResult] = []
    data_windows: list[dict[str, Any]] = []
    expected_scenario_ids: list[str] = []
    table_artifacts: list[dict[str, Any]] = []
    all_warnings: list[str] = []
    try:
        for window in config.windows:
            execution = execute_strategy_run(
                config.to_execution_spec(window),
                repo_root=config.base_dir,
                row_contract_mode="validation",
            )
            row_contract = execution.normalized_rows.row_contract_summary()
            data_windows.append(
                {
                    "window_id": window.id,
                    "data": config.to_execution_spec(window).data.model_dump(mode="json"),
                    "row_count": len(execution.normalized_rows),
                    "ranges_by_symbol": execution.normalized_rows.ranges_by_symbol,
                    "availability_coverage": execution.normalized_rows.availability_coverage,
                    "normalized_rows_sha256": execution.normalized_rows_sha256,
                    "row_contract": row_contract,
                    "evidence_quality": execution.evidence_quality,
                    "decision_count": len(execution.decisions),
                }
            )
            if row_contract["status"] == "failed":
                return _failure_result(
                    result_dir,
                    "data_load",
                    "evaluation_failed",
                    "evaluation row contract failed",
                    warnings=tuple(all_warnings),
                )
            lookahead = check_hidden_lookahead(
                execution.generate_decisions,
                rows=execution.normalized_rows,
                params=execution.validated_params,
                baseline_decisions=execution.decisions,
                strategy_id=config.strategy_id,
                mode="strict",
            )
            if not lookahead.passed:
                return _failure_result(
                    result_dir,
                    "preflight",
                    "evaluation_preflight_failed",
                    "; ".join(lookahead.violations),
                    warnings=tuple(all_warnings),
                )
            all_warnings.extend(lookahead.skipped_probe_reasons)
            scenarios = expand_evaluation_scenarios(
                window=window,
                base_costs=config.cost_model,
                base_fill=config.fill_model,
            )
            expected_scenario_ids.extend(scenario.scenario_id for scenario in scenarios)
            try:
                prepared = (
                    selected_backend.prepare_inputs(
                        decisions=execution.decisions,
                        rows=execution.normalized_rows.projection_rows(),
                    )
                    if hasattr(selected_backend, "prepare_inputs")
                    else None
                )
            except EvaluationDependencyError as exc:
                return _failure_result(
                    result_dir,
                    "portfolio_evaluation",
                    "portfolio_backend_unavailable",
                    str(exc),
                    warnings=tuple(all_warnings),
                )
            except ValueError as exc:
                return _failure_result(
                    result_dir,
                    "portfolio_evaluation",
                    "portfolio_evaluation_failed",
                    str(exc),
                    warnings=tuple(all_warnings),
                )
            for scenario in scenarios:
                scenario_result = (
                    selected_backend.run_prepared(
                        prepared=prepared,
                        scenario=scenario,
                        metrics=config.metrics,
                    )
                    if prepared is not None and hasattr(selected_backend, "run_prepared")
                    else selected_backend.run(
                        decisions=execution.decisions,
                        rows=execution.normalized_rows.projection_rows(),
                        scenario=scenario,
                        metrics=config.metrics,
                    )
                )
                backend_results.append(_strip_trace_tables(scenario_result))
                if scenario_result.status != "completed":
                    status = (
                        "portfolio_backend_unavailable"
                        if scenario_result.status == "unavailable"
                        else "portfolio_evaluation_failed"
                    )
                    return _failure_result(
                        result_dir,
                        "portfolio_evaluation",
                        status,
                        _backend_failure_message(scenario_result),
                        warnings=tuple(all_warnings),
                    )
                if scenario_result.tables is None:
                    return _failure_result(
                        result_dir,
                        "portfolio_evaluation",
                        "portfolio_evaluation_failed",
                        f"{scenario_result.scenario_id}: completed backend emitted no trace tables",
                        warnings=tuple(all_warnings),
                    )
                trace_results.append(scenario_result)
    except StrategyExecutionError as exc:
        return _failure_result(
            result_dir,
            exc.stage,
            "evaluation_failed",
            str(exc),
            warnings=tuple(all_warnings),
        )
    except OSError as exc:
        return _failure_result(
            result_dir,
            "artifact_write",
            "evaluation_failed",
            f"artifact write failed: {exc}",
            warnings=tuple(all_warnings),
        )

    scenario_summary = _scenario_summary(backend_results, expected_scenario_ids)
    coverage = scenario_summary["scenario_coverage"]
    if coverage["missing_ids"] or coverage["unexpected_ids"]:
        return _failure_result(
            result_dir,
            "portfolio_evaluation",
            "portfolio_evaluation_failed",
            f"scenario coverage mismatch: missing={coverage['missing_ids']} unexpected={coverage['unexpected_ids']}",
            warnings=tuple(all_warnings),
        )
    metrics_payload = {
        "metric_semantics": evaluation_metric_semantics(),
        "scenarios": [
            {
                "scenario_id": item.scenario_id,
                "backend": item.backend,
                "status": item.status,
                "metrics": item.metrics,
                "warnings": list(item.warnings),
                "unsupported_semantics": list(item.unsupported_semantics),
            }
            for item in backend_results
        ],
    }
    try:
        write_data_manifest(result_dir, windows=data_windows)
        table_artifacts = _write_trace_tables(result_dir, trace_results)
        write_json_artifact(result_dir, "evaluation_metrics.json", metrics_payload)
        write_json_artifact(result_dir, "scenario_summary.json", scenario_summary)
        write_text_artifact(result_dir, "notes.md", _notes(config.strategy_id, backend_results))
        write_evaluation_manifest(
            result_dir,
            repo_root=root,
            path_base=config.base_dir,
            config=config,
            config_path=resolved_config_path,
            backend_name=getattr(selected_backend, "name", "unknown"),
            data_windows=data_windows,
            table_artifacts=table_artifacts,
            scenario_summary=scenario_summary,
        )
    except OSError as exc:
        return _failure_result(
            result_dir,
            "artifact_write",
            "evaluation_failed",
            f"artifact write failed: {exc}",
            warnings=tuple(all_warnings),
        )

    return EvaluationRunResult(
        result_dir=result_dir,
        message=f"evaluation complete: {len(backend_results)} scenarios",
        run_completed=True,
        failure_stage=None,
        assessment_status="evaluation_complete",
        evidence_quality_warnings=tuple(all_warnings),
    )
```

Complete helper functions in `runner.py`:

```python
def _write_trace_tables(result_dir: Path, results: list[PortfolioEvaluationResult]) -> list[dict[str, Any]]:
    # Implementation requirement: write all four tables into a staging directory
    # first, then rename the complete staging directory to `tables/` only after
    # every Parquet write and footer metadata read succeeds. Metadata paths must
    # be normalized to the final `tables/*.parquet` paths.
    scenario_ids = tuple(result.scenario_id for result in results)
    portfolio_path = _combine_trace_frames(results, "portfolio_path")
    trades = _combine_trace_frames(results, "trades")
    positions = _combine_trace_frames(results, "positions")
    per_asset_metrics = _combine_trace_frames(results, "per_asset_metrics")
    return [
        write_parquet_artifact(
            result_dir,
            "tables/portfolio_path.parquet",
            portfolio_path,
            artifact_kind="portfolio_path",
            scenario_ids=scenario_ids,
        ),
        write_parquet_artifact(
            result_dir,
            "tables/trades.parquet",
            trades,
            artifact_kind="trades",
            scenario_ids=scenario_ids,
        ),
        write_parquet_artifact(
            result_dir,
            "tables/positions.parquet",
            positions,
            artifact_kind="positions",
            scenario_ids=scenario_ids,
        ),
        write_parquet_artifact(
            result_dir,
            "tables/per_asset_metrics.parquet",
            per_asset_metrics,
            artifact_kind="per_asset_metrics",
            scenario_ids=scenario_ids,
        ),
    ]


def _combine_trace_frames(results: list[PortfolioEvaluationResult], table_name: str) -> Any:
    import pandas as pd

    frames = []
    for result in results:
        assert result.tables is not None
        frames.append(getattr(result.tables, table_name))
    if not frames:
        return pd.DataFrame({"scenario_id": []})
    return pd.concat(frames, ignore_index=True)


def _strip_trace_tables(result: PortfolioEvaluationResult) -> PortfolioEvaluationResult:
    return result.model_copy(update={"tables": None})


def _backend_failure_message(result: PortfolioEvaluationResult) -> str:
    parts = [result.scenario_id, result.status]
    parts.extend(result.unsupported_semantics)
    parts.extend(result.warnings)
    return ": ".join(parts)


def _failure_result(
    result_dir: Path | None,
    failure_stage: str,
    assessment_status: str,
    message: str,
    *,
    warnings: Sequence[str],
) -> EvaluationRunResult:
    return EvaluationRunResult(
        result_dir=result_dir,
        message=message,
        run_completed=False,
        failure_stage=failure_stage,
        assessment_status=assessment_status,
        evidence_quality_warnings=tuple(warnings),
    )


def _scenario_summary(results: list[PortfolioEvaluationResult], expected_ids: list[str]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for result in results:
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
    completed_ids = [result.scenario_id for result in results if result.status == "completed"]
    unexpected_ids = sorted(set(completed_ids) - set(expected_ids))
    missing_ids = sorted(set(expected_ids) - set(completed_ids))
    return {
        "scenario_count": len(results),
        "status_counts": dict(sorted(status_counts.items())),
        "scenario_coverage": {
            "expected_count": len(expected_ids),
            "completed_count": len(completed_ids),
            "expected_ids": expected_ids,
            "completed_ids": completed_ids,
            "missing_ids": missing_ids,
            "unexpected_ids": unexpected_ids,
        },
        "scenarios": [
            {
                "scenario_id": result.scenario_id,
                "backend": result.backend,
                "status": result.status,
                "metric_count": len(result.metrics),
                "warnings": list(result.warnings),
                "unsupported_semantics": list(result.unsupported_semantics),
            }
            for result in results
        ],
    }


def _notes(strategy_id: str, results: list[PortfolioEvaluationResult]) -> str:
    return (
        f"# Evaluation Notes\n\n"
        f"- Strategy: `{strategy_id}`\n"
        f"- Scenarios: {len(results)}\n"
        "- Evidence class: research evaluation\n"
        "- Authority: evidence only; not validation, promotion, paper trading, or live trading authority.\n"
    )
```

Modify `src/quant_strategies/evaluation/__init__.py`:

```python
from __future__ import annotations

from quant_strategies.evaluation.config import EvaluationConfig
from quant_strategies.evaluation.runner import EvaluationRunResult, run_evaluation

__all__ = ["EvaluationConfig", "EvaluationRunResult", "run_evaluation"]
```

- [ ] **Step 4: Run runner tests**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_runner.py -q
```

Expected: all runner tests pass.

- [ ] **Step 5: Run accumulated evaluation tests**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_config.py tests/test_evaluation_scenarios.py tests/test_evaluation_dependencies.py tests/test_evaluation_backend.py tests/test_evaluation_artifacts.py tests/test_evaluation_runner.py -q
```

Expected: all evaluation package tests pass; optional real VectorBT Pro smoke test skips when unavailable.

- [ ] **Step 6: Commit Task 7**

Run:

```bash
git add src/quant_strategies/evaluation/__init__.py src/quant_strategies/evaluation/runner.py tests/test_evaluation_runner.py
git commit -m "feat: add evaluation runner"
```

---

### Task 8: CLI Surface

**Files:**
- Modify: `src/quant_strategies/runner/cli.py`
- Test: `tests/test_evaluation_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_evaluation_cli.py`:

```python
from __future__ import annotations

from pathlib import Path

from quant_strategies.runner import cli
from quant_strategies.evaluation.runner import EvaluationRunResult


def test_cli_evaluate_prints_artifact_path_on_success(tmp_path: Path, monkeypatch, capsys):
    result_dir = tmp_path / "result"
    result_dir.mkdir()

    def fake_run_evaluation(config, *, repo_root=None):
        assert config == Path("candidate/evaluation.toml")
        assert repo_root == tmp_path
        return EvaluationRunResult(
            result_dir=result_dir,
            message="evaluation complete: 6 scenarios",
            run_completed=True,
            assessment_status="evaluation_complete",
        )

    monkeypatch.setattr(cli, "run_evaluation", fake_run_evaluation)

    exit_code = cli.main(["evaluate", "--repo-root", str(tmp_path), "candidate/evaluation.toml"])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == str(result_dir)


def test_cli_evaluate_maps_data_failure_to_exit_3(tmp_path: Path, monkeypatch, capsys):
    def fake_run_evaluation(config, *, repo_root=None):
        return EvaluationRunResult(
            result_dir=None,
            message="data unavailable",
            run_completed=False,
            failure_stage="data_load",
            assessment_status="evaluation_failed",
        )

    monkeypatch.setattr(cli, "run_evaluation", fake_run_evaluation)

    exit_code = cli.main(["evaluate", "--repo-root", str(tmp_path), "candidate/evaluation.toml"])

    assert exit_code == 3
    assert capsys.readouterr().out.strip() == "evaluation failed: data unavailable"


def test_cli_evaluate_maps_portfolio_failure_to_exit_1(tmp_path: Path, monkeypatch, capsys):
    def fake_run_evaluation(config, *, repo_root=None):
        return EvaluationRunResult(
            result_dir=tmp_path / "partial",
            message="portfolio backend unavailable",
            run_completed=False,
            failure_stage="portfolio_evaluation",
            assessment_status="portfolio_backend_unavailable",
        )

    monkeypatch.setattr(cli, "run_evaluation", fake_run_evaluation)

    exit_code = cli.main(["evaluate", "--repo-root", str(tmp_path), "candidate/evaluation.toml"])

    assert exit_code == 1
    assert "artifacts:" in capsys.readouterr().out


def test_cli_evaluate_handles_oserror_without_traceback(tmp_path: Path, monkeypatch, capsys):
    def fake_run_evaluation(config, *, repo_root=None):
        raise OSError("disk full")

    monkeypatch.setattr(cli, "run_evaluation", fake_run_evaluation)

    exit_code = cli.main(["evaluate", "--repo-root", str(tmp_path), "candidate/evaluation.toml"])

    assert exit_code == 1
    assert capsys.readouterr().out.strip() == "evaluation failed: disk full"
```

- [ ] **Step 2: Run CLI tests to verify they fail**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_cli.py -q
```

Expected: failure because `cli.run_evaluation` is not imported and `evaluate` subcommand is absent.

- [ ] **Step 3: Add CLI evaluate command**

Modify `src/quant_strategies/runner/cli.py`:

```python
from quant_strategies.evaluation import run_evaluation
```

Add parser setup after `validate_parser`:

```python
    evaluate_parser = subparsers.add_parser("evaluate", help="evaluate one candidate evaluation TOML config")
    evaluate_parser.add_argument("--repo-root", type=Path, default=None, help="anchor for a relative evaluation config path")
    evaluate_parser.add_argument("config", type=Path)
```

Add command handling before `parser.error`:

```python
    if args.command == "evaluate":
        try:
            result = run_evaluation(args.config, repo_root=args.repo_root)
        except OSError as exc:
            print(f"evaluation failed: {exc}")
            return 1
        if _evaluation_exit_code(result) == 0:
            print(result.result_dir)
            return 0
        if result.result_dir is None:
            print(f"evaluation failed: {result.message}")
        else:
            print(f"evaluation failed: {result.message}; artifacts: {result.result_dir}")
        return _evaluation_exit_code(result)
```

Add exit code helper:

```python
def _evaluation_exit_code(result: object) -> int:
    failure_stage = getattr(result, "failure_stage", None)
    if failure_stage in _DATA_FAILURE_STAGES or failure_stage == "data_load":
        return 3
    if failure_stage is not None or not getattr(result, "run_completed", False):
        return 1
    return 0
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_cli.py -q
```

Expected: all CLI tests pass.

- [ ] **Step 5: Run runner and validation CLI regression tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py tests/test_validation_cli.py tests/test_evaluation_cli.py -q
```

Expected: all CLI-related tests pass.

- [ ] **Step 6: Commit Task 8**

Run:

```bash
git add src/quant_strategies/runner/cli.py tests/test_evaluation_cli.py
git commit -m "feat: expose evaluation CLI"
```

---

### Task 9: Docs For The Implemented Evaluation Surface

**Files:**
- Modify: `README.md`
- Modify: `PRD.md`
- Modify: `FOUNDATION_LOCK.md`
- Modify: `TODOS.md`
- Modify: `docs/foundation-surfaces.md`
- Modify: `docs/vectorbtpro.md`
- Modify: `docs/quant-autoresearch-consumer.md`
- Test: `tests/test_evaluation_docs.py`

- [ ] **Step 1: Write failing docs contract tests**

Create `tests/test_evaluation_docs.py`:

```python
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_public_docs_describe_evaluate_surface_without_promotion_authority():
    for path in [
        "README.md",
        "PRD.md",
        "FOUNDATION_LOCK.md",
        "docs/foundation-surfaces.md",
        "docs/vectorbtpro.md",
    ]:
        text = read(path)
        assert "quant-strategies evaluate" in text, path
        assert "run_evaluation" in text, path
        assert "evaluation.toml" in text, path
        assert "Parquet" in text, path
        assert "pyarrow" in text, path
        assert "does not authorize promotion, paper trading, or live trading" in text, path
        assert "Benchmark-relative metrics are deferred" in text, path


def test_todos_collapses_c_to_follow_up_work_only():
    text = read("TODOS.md")

    assert "Research evaluation surface MVP" not in text
    assert "benchmark-relative metrics" in text
    assert "user-defined scenario matrices" in text


def test_docs_do_not_call_evaluation_validation_verdict():
    docs = "\n".join(
        read(path)
        for path in [
            "README.md",
            "PRD.md",
            "FOUNDATION_LOCK.md",
            "docs/foundation-surfaces.md",
            "docs/vectorbtpro.md",
            "docs/quant-autoresearch-consumer.md",
        ]
        if (ROOT / path).exists()
    )

    forbidden = [
        "evaluation verdict",
        "evaluation hard_no",
        "evaluation watchlist",
        "evaluation validates alpha",
        "evaluation proves alpha",
        "evaluation authorizes paper",
        "evaluation authorizes live",
        "fallback to JSONL",
        "JSONL fallback is allowed",
    ]
    lowered = docs.lower()
    assert not any(term.lower() in lowered for term in forbidden)
```

- [ ] **Step 2: Run docs tests to verify they fail**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_docs.py -q
```

Expected: docs tests fail because docs do not yet describe the implemented evaluation surface.

- [ ] **Step 3: Update `README.md`**

Add an evaluation command section with this exact contract language:

```markdown
**Evaluation run** — `quant-strategies evaluate candidate/evaluation.toml`

Runs a frozen candidate through the research evaluation surface and writes
portfolio, economic, and path evidence. Evaluation uses VectorBT Pro and writes
detailed trace artifacts as Parquet through `pyarrow`; there is no JSONL fallback
for trace-level evaluation artifacts.

Evaluation is not validation. It does not authorize promotion, paper trading, or
live trading. Benchmark-relative metrics are deferred.
```

- [ ] **Step 4: Update `docs/foundation-surfaces.md`**

Add the third implemented surface:

```text
evaluation run input: candidate strategy.py + evaluation.toml
               output: EvaluationRunResult + evaluation artifacts
```

Add an evaluation config and output reference using the fields from Task 1 and artifact names from Task 6. Include:

```markdown
Detailed trace artifacts are Parquet only and require `pyarrow`.
There is no JSONL fallback path for evaluation traces.
```

- [ ] **Step 5: Update product-boundary docs**

Update `PRD.md`, `FOUNDATION_LOCK.md`, `TODOS.md`, `docs/vectorbtpro.md`, and `docs/quant-autoresearch-consumer.md` so they state:

```markdown
Evaluation is now an implemented stateless surface for frozen-candidate
portfolio/economic/path evidence. It remains separate from validation and does
not authorize promotion, paper trading, or live trading. Benchmark-relative
metrics are deferred.
```

In `TODOS.md`, remove or collapse C as open implementation work and leave follow-up work limited to benchmark-relative metrics, user-defined scenario matrices, and any residual backend limitations found during implementation.

- [ ] **Step 6: Run docs tests**

Run:

```bash
conda run -n quant pytest tests/test_evaluation_docs.py -q
```

Expected: docs tests pass.

- [ ] **Step 7: Run stale-language checks**

Run:

```bash
rg -n "evaluation verdict|evaluation hard_no|evaluation watchlist|evaluation validates alpha|evaluation proves alpha|evaluation authorizes paper|evaluation authorizes live|fallback to JSONL|JSONL fallback is allowed" README.md PRD.md FOUNDATION_LOCK.md TODOS.md docs
rg -n "Benchmark-relative metrics are deferred|quant-strategies evaluate|run_evaluation|evaluation.toml|pyarrow" README.md PRD.md FOUNDATION_LOCK.md docs/foundation-surfaces.md docs/vectorbtpro.md
```

Expected:

```text
First rg command returns no matches.
Second rg command returns matches in the updated public docs.
```

- [ ] **Step 8: Commit Task 9**

Run:

```bash
git add README.md PRD.md FOUNDATION_LOCK.md TODOS.md docs/foundation-surfaces.md docs/vectorbtpro.md docs/quant-autoresearch-consumer.md tests/test_evaluation_docs.py
git commit -m "docs: document evaluation surface"
```

---

### Task 10: Performance Guardrails

**Files:**
- Modify: `tests/test_phase5_performance.py`

- [ ] **Step 1: Add evaluation performance guardrails**

Append to `tests/test_phase5_performance.py`:

```python
def test_run_evaluation_executes_once_per_window_and_fans_out_scenarios(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from tests.test_evaluation_runner import FakeBackend, write_candidate, rows
    import quant_strategies.evaluation.runner as evaluation_runner
    from quant_strategies.evaluation.runner import run_evaluation
    from quant_strategies.runner.data_loader import LoadedData

    candidate = write_candidate(tmp_path)
    execution_calls = 0
    backend_calls = 0
    backend_row_ids: list[int] = []

    original_execute = evaluation_runner.execute_strategy_run

    def counting_execute(*args, **kwargs):
        nonlocal execution_calls
        execution_calls += 1
        return original_execute(*args, **kwargs)

    class CountingBackend(FakeBackend):
        def run(self, *, decisions, rows, scenario, metrics):
            nonlocal backend_calls
            backend_calls += 1
            backend_row_ids.append(id(rows))
            return super().run(decisions=decisions, rows=rows, scenario=scenario, metrics=metrics)

    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config, **_kwargs: LoadedData(rows=rows()))
    monkeypatch.setattr(evaluation_runner, "execute_strategy_run", counting_execute)

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=CountingBackend())

    assert result.run_completed is True
    assert execution_calls == 1
    assert backend_calls == 6
    assert len(set(backend_row_ids)) == 1


def test_strip_trace_tables_removes_dataframe_payload_from_summaries():
    import pandas as pd
    from quant_strategies.evaluation.backend import PortfolioEvaluationResult, PortfolioTraceTables
    from quant_strategies.evaluation.runner import _strip_trace_tables

    tables = PortfolioTraceTables(
        portfolio_path=pd.DataFrame({"scenario_id": ["s"]}),
        trades=pd.DataFrame({"scenario_id": ["s"]}),
        positions=pd.DataFrame({"scenario_id": ["s"]}),
        per_asset_metrics=pd.DataFrame({"scenario_id": ["s"]}),
    )
    result = PortfolioEvaluationResult(
        scenario_id="s",
        backend="fake",
        status="completed",
        metrics={"total_return": 0.0},
        tables=tables,
    )

    stripped = _strip_trace_tables(result)

    assert stripped.tables is None
    assert stripped.metrics == {"total_return": 0.0}


def test_evaluation_manifest_uses_table_hashes_without_rehashing_parquet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from quant_strategies.evaluation.artifacts import write_evaluation_manifest

    result_dir = tmp_path / "result"
    result_dir.mkdir()
    (result_dir / "evaluation_config.toml").write_text("strategy_id = 'demo'\n")
    (result_dir / "strategy_snapshot.py").write_text("")
    table_artifacts = [
        {
            "path": "tables/portfolio_path.parquet",
            "artifact_kind": "portfolio_path",
            "format": "parquet",
            "row_count": 1,
            "column_count": 1,
            "columns": [{"name": "scenario_id", "logical_type": "string", "nullable": True}],
            "arrow_schema": "scenario_id: string",
            "schema_sha256": "a" * 64,
            "file_sha256": "b" * 64,
            "byte_size": 128,
            "row_group_count": 1,
            "scenario_ids": ["s"],
        }
    ]

    class Config:
        strategy_id = "demo"
        strategy_path = tmp_path / "strategy.py"

    write_evaluation_manifest(
        result_dir,
        repo_root=tmp_path,
        path_base=tmp_path,
        config=Config(),
        config_path=result_dir / "evaluation_config.toml",
        backend_name="fake",
        data_windows=[],
        table_artifacts=table_artifacts,
        scenario_summary={"scenario_coverage": {"expected_count": 1, "missing_ids": [], "unexpected_ids": []}},
    )

    manifest = json.loads((result_dir / "evaluation_manifest.json").read_text())
    assert manifest["tables"][0]["file_sha256"] == "b" * 64
    assert manifest["trace_artifacts"]["total_byte_size"] == 128
    assert "tables/portfolio_path.parquet" not in manifest["artifacts"]
```

These tests are guardrails for execution fan-out, summary memory retention, and
manifest hashing. They are not VectorBT Pro benchmarks.

- [ ] **Step 2: Run performance tests**

Run:

```bash
conda run -n quant pytest tests/test_phase5_performance.py -q
```

Expected: all performance tests pass within existing budgets.

- [ ] **Step 3: Commit Task 10**

Run:

```bash
git add tests/test_phase5_performance.py
git commit -m "test: add evaluation artifact performance guardrail"
```

---

### Task 11: End-To-End Verification

**Files:**
- No source changes expected.

- [ ] **Step 1: Run all focused evaluation tests**

Run:

```bash
conda run -n quant pytest \
  tests/test_evaluation_config.py \
  tests/test_evaluation_scenarios.py \
  tests/test_evaluation_dependencies.py \
  tests/test_evaluation_backend.py \
  tests/test_evaluation_artifacts.py \
  tests/test_evaluation_runner.py \
  tests/test_evaluation_cli.py \
  tests/test_evaluation_docs.py \
  -q
```

Expected: all focused evaluation tests pass.

- [ ] **Step 2: Run adjacent regression tests**

Run:

```bash
conda run -n quant pytest \
  tests/test_runner_api_cli.py \
  tests/test_validation_config.py \
  tests/test_validation_runner.py \
  tests/test_validation_cli.py \
  tests/test_vectorbtpro_backend.py \
  tests/test_phase5_performance.py \
  -q
```

Expected: adjacent runner, validation, VectorBT Pro agreement, and performance tests pass.

- [ ] **Step 3: Run full test suite**

Run:

```bash
conda run -n quant pytest -q
```

Expected: full suite passes. If a failure is unrelated to evaluation and predates the branch, stop and report it without changing unrelated contracts.

- [ ] **Step 4: Run docs and whitespace checks**

Run:

```bash
rg -n "evaluation verdict|evaluation hard_no|evaluation watchlist|evaluation validates alpha|evaluation proves alpha|evaluation authorizes paper|evaluation authorizes live|fallback to JSONL|JSONL fallback is allowed" README.md PRD.md FOUNDATION_LOCK.md TODOS.md docs
git diff --check
```

Expected:

```text
No forbidden language matches.
No output from git diff --check.
```

- [ ] **Step 5: Report changed-line counts**

Run:

```bash
git diff --stat HEAD~10..HEAD
```

Report changed-line counts separated into source, tests, docs, and packaging. If the task count or commit count differs from this plan during execution, use the actual merge-base or implementation branch base instead of `HEAD~10`.

---

## Final Acceptance Criteria

- `quant_strategies.evaluation.run_evaluation` exists and returns `EvaluationRunResult`.
- `quant-strategies evaluate path/to/evaluation.toml` exists.
- Evaluation config is candidate-local and requires `validate_params`.
- Evaluation does not call `run_validation`, import validation policy, emit validation verdicts, or require validation artifacts.
- Scenario expansion covers every window × `zero_costs|realistic_costs|stressed_costs` × `base_fill|fill_lag_plus_1`.
- VectorBT Pro, pandas, and pyarrow are required for evaluation runs through the new `evaluation` extra.
- Trace artifacts are Parquet only; no JSONL fallback exists.
- Manifest records table path, kind, row count, columns/schema, sha256, scenario coverage, backend context, and metric semantics.
- Metrics are labeled as research evaluation evidence, not gates or promotion authority.
- Benchmark-relative metrics remain deferred.
- Focused evaluation tests, adjacent regression tests, full suite, stale-language checks, and `git diff --check` pass or any pre-existing failures are reported plainly.
