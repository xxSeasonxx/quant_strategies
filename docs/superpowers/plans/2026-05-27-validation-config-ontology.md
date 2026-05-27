# Validation Config Ontology Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make validation operate on `validation.toml` plus its referenced `strategy.py` from any candidate workspace, with no active `researched/` package ontology or legacy layout gate.

**Architecture:** `validation.toml` is the validation unit. The validator accepts an explicit TOML file path, not a package or directory path. Relative paths in the config resolve from the TOML file's directory, and the config directory is the candidate workspace boundary. Validation artifacts snapshot and hash the actual config and strategy used; optional historical manifests are not validation gates.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, existing `quant_strategies.validation` and `quant_strategies.runner` modules.

---

## Scope

In scope:
- Validation config/path semantics.
- Validation runner removal of researched-package gates.
- Validation manifest schema cleanup.
- README and CLI wording updates.
- Focused tests proving config-addressed validation.

Out of scope:
- Hidden-lookahead replay checks.
- Runner smoke data availability status.
- VectorBT Pro dependency/extras behavior.
- Data-kind row contracts.
- Typed scenario backend config.
- Artifact reader APIs.

Those are separate review findings and should be planned independently after this refactor lands.

Hard constraint:
- Do not accommodate legacy researched-package layouts, family/variant trees, or
  manifest-gated validation. If old artifacts need validation, create a normal
  `validation.toml` + `strategy.py` candidate workspace. This refactor removes
  the old ontology rather than adapting to it.

## File Structure

Modify:
- `src/quant_strategies/validation/config.py`
  - Own validation path resolution.
  - Resolve `strategy_path` and `output.results_dir` relative to the config file directory.
  - Require `[readiness]` for every validation config.
  - Expose `ValidationConfig.base_dir` for runner/loader reuse.
- `src/quant_strategies/validation/__init__.py`
  - Treat the input as a validation config file path.
  - Remove `check_research_manifest` and all `research_manifest` failure plumbing.
  - Use `config.base_dir` as the strategy loader sandbox and runner config context.
- `src/quant_strategies/validation/manifest.py`
  - Remove required `research_manifest` field.
  - Keep config/strategy/data/backend/core artifact hashes.
- `src/quant_strategies/runner/cli.py`
  - Update validate subcommand help text.
- `README.md`
  - Replace researched-package validation contract with config-addressed validation.
- `docs/quant-autoresearch-consumer.md`
  - Clarify validation is a separate config-addressed handoff, not part of the search loop.
- `tests/test_validation_config.py`
  - Rewrite path tests around config-directory-relative semantics.
- `tests/test_validation_runner.py`
  - Replace researched-manifest gate tests with config-addressed validation tests.
- `tests/test_validation_cli.py`
  - Update argument naming/help expectations only if current tests assert help text.

Delete:
- `src/quant_strategies/validation/research_manifest.py`
  - No active code should special-case `researched/`.

Do not modify:
- `src/quant_strategies/runner/config.py`
  - Runner config remains repo-root-addressed for runner runs.
- `src/quant_strategies/decisions/strategy_loader.py`
  - Keep its optional sandbox behavior. Validation will pass `config.base_dir`.
- Strategy files under `untested/`, `tested/`, or `researched/`.

---

### Task 1: Write Config Ontology Tests

**Files:**
- Modify: `tests/test_validation_config.py`

- [ ] **Step 1: Replace the helper config shape with a config-local candidate**

Edit `tests/test_validation_config.py` so `write_config` defaults to `strategy_path = "strategy.py"` and includes `[readiness]` by default:

```python
def write_config(
    path: Path,
    strategy_path: str = "strategy.py",
    *,
    include_readiness: bool = True,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    readiness = (
        """

[readiness]
min_observations_per_decision = 1
required_observation_fields = ["close"]
"""
        if include_readiness
        else ""
    )
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
{readiness}

[output]
results_dir = "validation_results/demo"
""".lstrip()
    )
```

- [ ] **Step 2: Replace package-path resolution test with explicit file resolution**

Replace `test_resolve_validation_config_from_package_path` with:

```python
def test_resolve_validation_config_from_file_path(tmp_path: Path):
    candidate = tmp_path / "candidate"
    config_path = candidate / "validation.toml"
    write_config(config_path)

    resolved = resolve_validation_config_path(config_path)

    assert resolved == config_path
```

Add:

```python
def test_resolve_validation_config_rejects_directory_path(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_config(candidate / "validation.toml")

    with pytest.raises(ValidationConfigError, match="validation config path must be a TOML file"):
        resolve_validation_config_path(candidate)
```

- [ ] **Step 3: Replace repo-root path resolution test**

Replace `test_load_validation_config_resolves_paths_inside_repo` with:

```python
def test_load_validation_config_resolves_paths_from_config_directory(tmp_path: Path):
    candidate = tmp_path / "scratch" / "candidate_a"
    write_strategy(candidate / "strategy.py")
    write_config(candidate / "validation.toml")

    config = load_validation_config(candidate / "validation.toml")

    assert config.base_dir == candidate
    assert config.strategy_path == candidate / "strategy.py"
    assert config.output.results_dir == candidate / "validation_results" / "demo"
    assert config.windows[0].id == "validation_2026_h1"
    assert config.readiness.min_observations_per_decision == 1
    assert config.readiness.required_observation_fields == ("close",)
    assert config.paper_readiness.enabled is True
```

- [ ] **Step 4: Replace outside-repo rejection with outside-candidate rejection**

Replace `test_load_validation_config_rejects_generate_strategy_outside_repo` with:

```python
def test_load_validation_config_rejects_strategy_path_outside_config_directory(tmp_path: Path):
    candidate = tmp_path / "candidate"
    outside = tmp_path / "outside.py"
    outside.write_text("def generate_decisions(rows, params):\n    return []\n")
    write_config(candidate / "validation.toml", strategy_path="../outside.py")

    with pytest.raises(ValidationConfigError, match="strategy_path must resolve inside config directory"):
        load_validation_config(candidate / "validation.toml")
```

Add:

```python
def test_load_validation_config_rejects_absolute_strategy_path_outside_config_directory(tmp_path: Path):
    candidate = tmp_path / "candidate"
    outside = tmp_path / "outside.py"
    outside.write_text("def generate_decisions(rows, params):\n    return []\n")
    write_config(candidate / "validation.toml", strategy_path=str(outside))

    with pytest.raises(ValidationConfigError, match="strategy_path must resolve inside config directory"):
        load_validation_config(candidate / "validation.toml")
```

Add:

```python
def test_load_validation_config_rejects_absolute_results_dir_outside_config_directory(tmp_path: Path):
    candidate = tmp_path / "candidate"
    outside_results = tmp_path / "validation_results"
    write_config(candidate / "validation.toml")
    config_path = candidate / "validation.toml"
    config_path.write_text(
        config_path.read_text().replace(
            'results_dir = "validation_results/demo"',
            f'results_dir = "{outside_results}"',
        )
    )

    with pytest.raises(ValidationConfigError, match="output.results_dir must resolve inside config directory"):
        load_validation_config(config_path)
```

- [ ] **Step 5: Add required readiness test**

Add:

```python
def test_load_validation_config_requires_readiness_for_every_validation_config(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    write_config(candidate / "validation.toml", include_readiness=False)

    with pytest.raises(ValidationConfigError, match="readiness"):
        load_validation_config(candidate / "validation.toml")
```

- [ ] **Step 6: Update remaining tests in this file**

In the remaining tests:
- Use `candidate = tmp_path / "candidate"` or `tmp_path / "scratch" / "candidate_a"`.
- Call `load_validation_config(candidate / "validation.toml")` unless the test specifically checks `repo_root` path anchoring.
- Keep `test_validation_config_converts_to_run_config_with_repo_root_override`, but rename it to `test_validation_config_converts_to_run_config_with_config_base_dir` and assert `run_config.output.results_dir == results_dir` where `results_dir` is under `candidate`.

- [ ] **Step 7: Run config tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_config.py -q
```

Expected: FAIL before implementation. Failures should mention `repo_root`, `researched/demo`, missing `base_dir`, or strategy paths resolving from the old repository root.

- [ ] **Step 8: Commit tests**

```bash
git add tests/test_validation_config.py
git commit -m "test: specify config-addressed validation paths"
```

---

### Task 2: Implement Config-Directory Path Semantics

**Files:**
- Modify: `src/quant_strategies/validation/config.py`

- [ ] **Step 1: Remove runner private path helper imports**

Change the imports from:

```python
from quant_strategies.runner.config import (
    CostModelConfig,
    DataConfig,
    FillModelConfig,
    OutputConfig as RunnerOutputConfig,
    RunConfig,
    _resolve_inside_repo,
    default_repo_root,
)
```

to:

```python
from quant_strategies.runner.config import (
    CostModelConfig,
    DataConfig,
    FillModelConfig,
    OutputConfig as RunnerOutputConfig,
    RunConfig,
)
```

- [ ] **Step 2: Add config base-dir helpers**

Add these helpers near the top of `validation/config.py`:

```python
def _path_anchor(path: str | Path, *, repo_root: Path | None = None) -> Path:
    if repo_root is not None:
        return Path(repo_root).resolve()
    if Path(path).is_absolute():
        return Path("/")
    return Path.cwd().resolve()


def _base_dir(info: ValidationInfo) -> Path:
    base = info.context.get("base_dir") if info.context else None
    if base is None:
        return Path.cwd().resolve()
    return Path(base).resolve()


def _resolve_inside_base(value: Path, base_dir: Path, field_name: str) -> Path:
    resolved = value if value.is_absolute() else base_dir / value
    resolved = resolved.resolve()
    try:
        resolved.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError(f"{field_name} must resolve inside config directory: {base_dir}") from exc
    return resolved
```

- [ ] **Step 3: Replace private attr and base_dir property**

In `ValidationConfig`, replace `_repo_root_path` with:

```python
    _base_dir_path: Path = PrivateAttr(default_factory=lambda: Path.cwd().resolve())

    @property
    def base_dir(self) -> Path:
        return self._base_dir_path
```

Replace `model_post_init` with:

```python
    def model_post_init(self, context: Any, /) -> None:
        base = context.get("base_dir") if isinstance(context, dict) else None
        base_dir = Path(base).resolve() if base is not None else Path.cwd().resolve()
        object.__setattr__(self, "_base_dir_path", base_dir)
```

- [ ] **Step 4: Resolve validation paths from base_dir**

Replace `ValidationOutputConfig.validate_results_dir` with:

```python
    @field_validator("results_dir")
    @classmethod
    def validate_results_dir(cls, value: Path, info: ValidationInfo) -> Path:
        return _resolve_inside_base(value, _base_dir(info), "output.results_dir")
```

Replace `ValidationConfig.validate_strategy_path` with:

```python
    @field_validator("strategy_path")
    @classmethod
    def validate_strategy_path(cls, value: Path, info: ValidationInfo) -> Path:
        return _resolve_inside_base(value, _base_dir(info), "strategy_path")
```

- [ ] **Step 5: Require readiness**

Change:

```python
    readiness: ValidationReadinessConfig | None = None
```

to:

```python
    readiness: ValidationReadinessConfig
```

- [ ] **Step 6: Make to_run_config use the config base dir**

Replace:

```python
        context = {"repo_root": self._repo_root_path}
```

with:

```python
        context = {"repo_root": self._base_dir_path}
```

- [ ] **Step 7: Update config path resolution**

Replace `resolve_validation_config_path` and `load_validation_config` with:

```python
def resolve_validation_config_path(path: str | Path, *, repo_root: Path | None = None) -> Path:
    anchor = _path_anchor(path, repo_root=repo_root)
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = anchor / candidate
    candidate = candidate.resolve()
    if candidate.is_dir():
        raise ValidationConfigError("validation config path must be a TOML file, not a directory")
    if candidate.suffix != ".toml":
        raise ValidationConfigError(f"validation config path must be a TOML file: {candidate}")
    return candidate


def load_validation_config(path: str | Path, *, repo_root: Path | None = None) -> ValidationConfig:
    config_path = resolve_validation_config_path(path, repo_root=repo_root)
    try:
        payload = tomllib.loads(config_path.read_text())
    except OSError as exc:
        raise ValidationConfigError(f"could not read validation config: {config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValidationConfigError(f"invalid TOML in validation config: {exc}") from exc

    try:
        return ValidationConfig.model_validate(payload, context={"base_dir": config_path.parent})
    except ValidationError as exc:
        raise ValidationConfigError(str(exc)) from exc
```

- [ ] **Step 8: Run config tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_config.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit implementation**

```bash
git add src/quant_strategies/validation/config.py tests/test_validation_config.py
git commit -m "refactor: resolve validation paths from config directory"
```

---

### Task 3: Write Validation Runner Tests For Config-Addressed Runs

**Files:**
- Modify: `tests/test_validation_runner.py`

- [ ] **Step 1: Change helper package naming to candidate naming**

Rename `write_package` to `write_candidate` and make it create:

```text
<tmp_path>/candidate/
  strategy.py
  validation.toml
```

The helper should return the config path:

```python
def write_candidate(
    tmp_path: Path,
    *,
    backend: str | None = "fake",
    window_ids: tuple[str, ...] = ("validation_2026_h1",),
    include_readiness: bool = True,
) -> Path:
    candidate = tmp_path / "candidate"
    candidate.mkdir(parents=True)
    strategy_text = (
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, ObservationRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='short', sizing_kind='target_weight', size=float(params.get('weight', 1.0))),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[0]['timestamp'], field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    (candidate / "strategy.py").write_text(strategy_text)
    backend_line = f'backend = "{backend}"\n' if backend is not None else ""
    window_blocks = "\n".join(
        f"""
[[windows]]
id = "{window_id}"
start = "2026-01-01"
end = "2026-06-30"
""".strip()
        for window_id in window_ids
    )
    readiness = (
        """

[readiness]
min_observations_per_decision = 1
required_observation_fields = ["close"]
"""
        if include_readiness
        else ""
    )
    config_path = candidate / "validation.toml"
    config_path.write_text(
        f"""
strategy_path = "strategy.py"
strategy_id = "demo"
{backend_line}

{window_blocks}

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
{readiness}

[output]
results_dir = "validation_results/demo"
""".lstrip()
    )
    return config_path
```

- [ ] **Step 2: Update run_validation calls**

Replace calls like:

```python
package = write_package(tmp_path)
result = run_validation(package, repo_root=tmp_path, backend=backend)
```

with:

```python
config_path = write_candidate(tmp_path)
result = run_validation(config_path, backend=backend)
```

For tests that use `repo_root`, keep only tests specifically proving `repo_root` anchors a relative CLI-style config path.

- [ ] **Step 3: Remove researched manifest assertions from positive tests**

Delete assertions like:

```python
assert manifest["research_manifest"]["found"] is True
assert manifest["research_manifest"]["passed"] is True
assert manifest["research_manifest"]["lifecycle_status"] == "validation_ready"
assert manifest["research_manifest"]["violations"] == []
```

Replace with assertions about actual config/strategy provenance:

```python
assert manifest["validation"]["strategy_id"] == "demo"
assert manifest["validation"]["config_path"] == "validation.toml"
assert manifest["validation"]["config_sha256"]
assert manifest["strategy"]["path"] == "strategy.py"
assert manifest["strategy"]["snapshot_sha256"]
assert "research_manifest" not in manifest
```

- [ ] **Step 4: Replace stale manifest gate tests with manifest-ignored test**

Delete these tests:
- `test_run_validation_blocks_stale_validation_ready_research_manifest`
- `test_run_validation_blocks_malformed_research_manifest_variants`
- `test_run_validation_blocks_missing_research_manifest`
- `test_run_validation_blocks_missing_research_manifest_variant`
- `test_run_validation_blocks_invalid_researched_layout`
- `test_run_validation_blocks_external_config_pointing_at_researched_strategy`
- `test_run_validation_ignores_parent_manifest_for_non_researched_config`

Add:

```python
def test_run_validation_ignores_unconfigured_manifest_files(tmp_path: Path, monkeypatch):
    config_path = write_candidate(tmp_path)
    (config_path.parent / "manifest.json").write_text(
        json.dumps(
            {
                "variants": [
                    {
                        "directory": ".",
                        "lifecycle_status": "stale",
                        "strategy_sha256": "wrong",
                        "validation_config_sha256": "wrong",
                    }
                ]
            }
        )
    )
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))
    backend = RecordingBackend()

    result = run_validation(config_path, backend=backend)

    assert result.decision.decision == "watchlist"
    assert backend.calls == 6
    assert result.result_dir is not None
    manifest = json.loads((result.result_dir / "validation_manifest.json").read_text())
    assert "research_manifest" not in manifest
```

- [ ] **Step 5: Replace missing readiness runtime-artifact test**

Replace `test_run_validation_blocks_missing_readiness_metadata` with:

```python
def test_run_validation_rejects_config_missing_readiness(tmp_path: Path):
    config_path = write_candidate(tmp_path, include_readiness=False)
    backend = RecordingBackend()

    with pytest.raises(Exception, match="readiness"):
        run_validation(config_path, backend=backend)

    assert backend.calls == 0
```

If the implementation raises `ValidationConfigError`, import it and use:

```python
with pytest.raises(ValidationConfigError, match="readiness"):
    run_validation(config_path, backend=backend)
```

- [ ] **Step 6: Run runner tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_validation_runner.py -q
```

Expected: FAIL before implementation. Failures should reference `research_manifest`, old package paths, or missing config-relative path behavior.

- [ ] **Step 7: Commit tests**

```bash
git add tests/test_validation_runner.py
git commit -m "test: make validation config-addressed"
```

---

### Task 4: Remove Researched Manifest Gate From Validation Runtime

**Files:**
- Modify: `src/quant_strategies/validation/__init__.py`
- Modify: `src/quant_strategies/validation/manifest.py`
- Delete: `src/quant_strategies/validation/research_manifest.py`

- [ ] **Step 1: Remove research_manifest imports**

In `validation/__init__.py`, remove:

```python
from quant_strategies.validation.research_manifest import check_research_manifest
```

- [ ] **Step 2: Simplify run_validation setup**

Replace the start of `run_validation` with:

```python
def run_validation(
    config_path: str | Path,
    *,
    repo_root: Path | None = None,
    backend: ValidationBackend | None = None,
) -> ValidationRunResult:
    resolved_config_path = resolve_validation_config_path(config_path, repo_root=repo_root)
    config = load_validation_config(resolved_config_path, repo_root=repo_root)
    git_root = Path(repo_root).resolve() if repo_root is not None else config.base_dir
    path_base = config.base_dir
    result_dir = create_validation_result_dir(config.output.results_dir, config.strategy_id)
    _write_static_validation_artifacts(result_dir=result_dir, config=config, config_path=resolved_config_path)
```

Keep the rest of the local variables, but remove `research_manifest`.

- [ ] **Step 3: Remove early researched gate blocks**

Delete the block that calls `check_research_manifest(...)`.

Delete the block:

```python
if research_manifest.get("is_researched_package") and config.readiness is None:
    ...
```

Readiness is now required by `ValidationConfig`.

- [ ] **Step 4: Update strategy loader sandbox**

Change:

```python
generate_decisions = load_decision_strategy(config.strategy_path, repo_root=root)
```

to:

```python
generate_decisions = load_decision_strategy(config.strategy_path, repo_root=config.base_dir)
```

- [ ] **Step 5: Update _failure_result signature and calls**

Remove `research_manifest` from `_failure_result` parameters and from every call.
Add `path_base: Path` to `_failure_result` and pass it through to
`_write_validation_artifacts`.

Every `_failure_result(...)` call should still pass:
- `result_dir`
- `repo_root=git_root`
- `path_base=path_base`
- `config`
- `config_path=resolved_config_path`
- `backend_name`
- `decisions`
- `data_audits`
- `data_provenance`
- `backend_results`
- `reason`

- [ ] **Step 6: Update _write_validation_artifacts signature and calls**

Remove `research_manifest` from `_write_validation_artifacts` parameters and from every call.
Add `path_base: Path` to `_write_validation_artifacts` and pass it through to
`write_validation_manifest`.

Change the manifest write call to:

```python
write_validation_manifest(
    result_dir,
    repo_root=repo_root,
    path_base=path_base,
    config=config,
    config_path=config_path,
    backend_name=backend_name,
    data_provenance=data_provenance,
    backend_results=backend_results,
    capability_matrix=capability_matrix,
)
```

- [ ] **Step 7: Update validation manifest schema**

In `validation/manifest.py`, remove `research_manifest` from the function signature:

```python
def write_validation_manifest(
    result_dir: Path,
    *,
    repo_root: Path,
    path_base: Path,
    config: Any,
    config_path: Path,
    backend_name: str,
    data_provenance: list[dict[str, Any]],
    backend_results: list[ScenarioBackendRunResult],
    capability_matrix: dict[str, Any],
) -> Path:
```

Remove this payload entry:

```python
"research_manifest": research_manifest,
```

Keep the rest of the payload unchanged.

- [ ] **Step 8: Make manifest paths relative to the config base**

Change the config and strategy path fields to use `path_base`, not `repo_root`:

```python
"validation": {
    "strategy_id": config.strategy_id,
    "backend": backend_name,
    "config_path": _relative_path(config_path, path_base),
    "config_sha256": _optional_hash(config_path),
},
"strategy": {
    "path": _relative_path(Path(config.strategy_path), path_base),
    "snapshot_sha256": _optional_hash(result_dir / "strategy_snapshot.py"),
},
```

Keep `git_identity(repo_root, ...)` on `repo_root`. `repo_root` records the git
working tree when the caller supplied one; `path_base` records the candidate-local
validation paths. Do not overload one variable for both jobs.

- [ ] **Step 9: Delete researched manifest module**

```bash
git rm src/quant_strategies/validation/research_manifest.py
```

- [ ] **Step 10: Run validation runner tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_runner.py -q
```

Expected: PASS after test updates and runtime changes.

- [ ] **Step 11: Commit runtime change**

```bash
git add src/quant_strategies/validation/__init__.py src/quant_strategies/validation/manifest.py tests/test_validation_runner.py
git add -u src/quant_strategies/validation/research_manifest.py
git commit -m "refactor: validate configs without researched package gates"
```

---

### Task 5: Update CLI And Docs

**Files:**
- Modify: `src/quant_strategies/runner/cli.py`
- Modify: `README.md`
- Modify: `docs/quant-autoresearch-consumer.md`
- Modify: `tests/test_readme_contract.py`
- Modify: `tests/test_validation_cli.py`

- [ ] **Step 1: Update CLI help text**

In `runner/cli.py`, change:

```python
validate_parser = subparsers.add_parser("validate", help="validate one researched strategy package or config")
validate_parser.add_argument("--repo-root", type=Path, default=None, help="repository root for relative paths")
validate_parser.add_argument("package_or_config", type=Path)
```

to:

```python
validate_parser = subparsers.add_parser("validate", help="validate one validation config")
validate_parser.add_argument("--repo-root", type=Path, default=None, help="anchor for a relative validation config path")
validate_parser.add_argument("config", type=Path)
```

Change:

```python
result = run_validation(args.package_or_config, repo_root=args.repo_root)
```

to:

```python
result = run_validation(args.config, repo_root=args.repo_root)
```

- [ ] **Step 2: Update README validation sections**

Replace the `## Researched Packages` and `## Package Validation` sections with:

```markdown
## Validation Configs

Validation runs are addressed by a `validation.toml` file. The validator does not
special-case `researched/`, `untested/`, or any other repository directory.

A minimal validation workspace is:

```text
candidate/
  strategy.py
  validation.toml
```

Relative paths inside `validation.toml` resolve from the TOML file's directory.
The candidate directory is the validation boundary: `strategy_path` and
`output.results_dir` must resolve inside that directory.

Every validation config requires readiness metadata:

```toml
[readiness]
min_observations_per_decision = 1
required_observation_fields = ["close"]
```

This proves the strategy declared enough local row lineage for backend execution;
it is not a dependency DSL and not market evidence.

Validation configs can also override the advisory paper-readiness gates:

```toml
[paper_readiness]
enabled = true
min_windows = 2
min_total_trades = 30
min_positive_window_fraction = 0.5
max_stressed_net_loss = -0.02
max_fill_lag_net_loss = -0.02
```

The stress and fill-lag loss floors apply to the worst required scenario net
return across validation windows.

## Validation Runs

`quant-strategies validate path/to/validation.toml` runs advisory validation for
the strategy/config pair described by that TOML. It checks readiness metadata,
strategy import, parameter validation, data loading, decision output, and
observation lineage before backend execution.

For each validation window, the validator expands required and diagnostic
scenarios, runs the configured backend, and classifies the config as `hard_no`,
`mechanical_pass`, `watchlist`, or `paper_candidate`. A `mechanical_pass`
requires passing data audits, required backend scenarios, valid backend metrics,
and at least `10` trades per required scenario. A `watchlist` captures
unavailable or unsupported required backend semantics, or positive evidence that
misses paper-readiness gates. A `paper_candidate` requires mechanical validation
plus paper-readiness gates such as multiple windows, enough realistic-cost
trades, no zero-trade windows, positive realistic-cost evidence, sufficient
positive-window fraction, and stressed-cost and fill-lag loss floors. Eligibility
flags still remain false.
```

- [ ] **Step 3: Update README command**

Change:

```bash
conda run -n quant quant-strategies validate path/to/researched/package
```

to:

```bash
conda run -n quant quant-strategies validate path/to/validation.toml
```

- [ ] **Step 4: Update promotion discipline wording**

Keep the discipline that `researched/` is not market validation, but clarify it
is storage only:

```markdown
`researched/` may contain frozen candidates or upstream handoff artifacts, but
the validator does not infer validation status from that directory. Validation
status comes from running a `validation.toml` and reviewing its artifacts.
```

- [ ] **Step 5: Update consumer docs**

In `docs/quant-autoresearch-consumer.md`, keep the current search-loop guidance.
Add this paragraph near the handoff section:

```markdown
If a candidate later needs advisory validation, create a validation workspace
with `strategy.py` and `validation.toml`, then call `quant-strategies validate
path/to/validation.toml`. Validation is config-addressed and does not depend on
placing the files under `researched/`.
```

- [ ] **Step 6: Update README contract test**

In `tests/test_readme_contract.py`, keep forbidding `maybe` and old strategy names.
Add assertions:

```python
assert "quant-strategies validate path/to/validation.toml" in text
assert "The validator does not special-case `researched/`" in text
```

If the old test expects the researched layout block, remove that expectation.

- [ ] **Step 7: Run docs tests**

Update `tests/test_validation_cli.py` so every mocked validate command passes a
TOML file path, not `researched/demo`:

```python
code = cli.main(["validate", "--repo-root", str(tmp_path), "candidate/validation.toml"])
assert calls == [(Path("candidate/validation.toml"), tmp_path)]
```

Apply the same path replacement in the hard-no and validation-error tests.

- [ ] **Step 8: Run docs tests**

Run:

```bash
conda run -n quant pytest tests/test_readme_contract.py tests/test_validation_cli.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit docs**

```bash
git add README.md docs/quant-autoresearch-consumer.md src/quant_strategies/runner/cli.py tests/test_readme_contract.py tests/test_validation_cli.py
git commit -m "docs: document config-addressed validation"
```

---

### Task 6: Remove Remaining Research Manifest References

**Files:**
- Search all source, tests, and docs.
- Modify any remaining file with active `research_manifest` references.

- [ ] **Step 1: Search for active references**

Run:

```bash
rg -n "research_manifest|check_research_manifest|validation_ready|validated_for_testing|research_manifest_" src tests README.md docs
```

Expected remaining matches:
- Historical planning docs under `docs/superpowers/plans/` or `docs/superpowers/specs/` may still mention old terms.
- New active source/tests/README should have no `research_manifest` validation logic.

- [ ] **Step 2: Remove active code/test references**

For any active source or test match outside historical docs:
- remove the old assertion or import,
- replace with config/strategy provenance assertions,
- avoid adding compatibility branches.

- [ ] **Step 3: Add a historical-doc note only if needed**

If stale historical docs are confusing current tests or active documentation, add a short header to the historical file:

```markdown
> Historical plan: this file is not the current validation contract.
```

Do not rewrite historical plans in this task.

- [ ] **Step 4: Re-run reference search**

Run:

```bash
rg -n "research_manifest|check_research_manifest|research_manifest_" src tests README.md docs/quant-autoresearch-consumer.md
```

Expected: no output.

- [ ] **Step 5: Commit cleanup**

```bash
git add -A
git commit -m "chore: remove researched manifest validation references"
```

---

### Task 7: Final Verification

**Files:**
- No new source files unless previous tasks revealed a missing import or stale test helper.

- [ ] **Step 1: Run focused tests**

Run:

```bash
conda run -n quant pytest \
  tests/test_validation_config.py \
  tests/test_validation_runner.py \
  tests/test_validation_cli.py \
  tests/test_readme_contract.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run full suite**

Run:

```bash
conda run -n quant pytest -q
```

Expected: PASS.

- [ ] **Step 3: Inspect changed-line counts**

Run:

```bash
git diff --stat HEAD~5..HEAD
git diff --numstat HEAD~5..HEAD
```

Expected: source/tests/docs changes only. No generated result artifacts should be tracked.

- [ ] **Step 4: Confirm no generated artifacts are staged**

Run:

```bash
git status --short
```

Expected: clean, or only intentional untracked review drafts that pre-existed this implementation.

- [ ] **Step 5: Write final implementation note**

In the implementation summary, include:
- files changed,
- source/test/docs insertion/deletion counts,
- tests run and results,
- explicit note that this only fixes the validation ontology finding and does not implement causality replay, runner availability status, VectorBT Pro setup, or data-kind row contracts.

---

## Self-Review Checklist

- Spec coverage:
  - Config-addressed validation: Tasks 1-4.
  - Relative paths from TOML directory: Tasks 1-2.
  - No `researched/` special handling: Tasks 3-6.
  - Required readiness: Tasks 1-4.
  - Artifact provenance based on actual config/strategy: Tasks 3-4.
  - Docs updated: Task 5.
- Placeholder scan:
  - The plan contains no deferred implementation holes.
  - Each code-changing task names exact files and commands.
- Type consistency:
  - `ValidationConfig.base_dir` is introduced in Task 2 and used in Task 4.
  - `resolve_validation_config_path` keeps the existing `repo_root` parameter only as a path anchor.
  - `write_validation_manifest` loses `research_manifest` in both caller and callee.
  - `path_base` is threaded through `_failure_result`, `_write_validation_artifacts`, and `write_validation_manifest`.

---

## Engineering Review Notes

### What Already Exists

- `ValidationConfig.to_run_config(...)` already converts validation windows to runner configs. Reuse it; do not build a parallel data-loading path.
- `load_decision_strategy(..., repo_root=...)` already enforces a strategy sandbox. Validation should pass `config.base_dir` rather than inventing a new loader.
- `write_validation_manifest(...)` already records config/strategy hashes, data provenance, backend summaries, and artifact hashes. Keep it and remove only the researched-manifest concept.
- `runner.cli` already delegates validate to `run_validation`. Update wording and argument names only.

### NOT In Scope

- Hidden-lookahead replay: separate evidence-quality fix after validation ontology lands.
- Runner data availability status: separate smoke-artifact contract change.
- VectorBT Pro setup behavior: separate dependency/operational clarity change.
- Data-kind row contracts: separate data-boundary change with its own tests.
- Typed scenario backend config: useful boundary cleanup, but not required to remove researched-package gates.
- Artifact readers: defer until `quant_autoresearch` actually needs a stable reader API.
- Legacy researched package support: explicitly not in scope; old artifacts must become normal `validation.toml` + `strategy.py` candidates.

### Data Flow Diagram

```text
caller / CLI
  |
  | explicit path: path/to/validation.toml
  v
resolve_validation_config_path
  | rejects directories and non-.toml paths
  v
load_validation_config
  | base_dir = validation.toml parent
  | strategy_path, output.results_dir confined to base_dir
  v
run_validation
  | load strategy with repo_root=config.base_dir
  | load rows through runner.data_loader via config.to_run_config(...)
  | generate and audit StrategyDecision records
  | expand matrix and run backend
  v
validation artifacts
  | config/strategy paths rendered relative to path_base=config.base_dir
  | git identity rendered relative to repo_root when provided
  v
validation_decision.json + validation_manifest.json
```

### Test Coverage Diagram

```text
CODE PATHS                                                TEST PLAN
[+] validation.config.resolve_validation_config_path
  ├── explicit .toml path                                 Task 1 Step 2
  ├── directory path rejected                             Task 1 Step 2
  └── non-.toml path rejected                             Task 2 Step 7

[+] validation.config.load_validation_config
  ├── config-local strategy_path                          Task 1 Step 3
  ├── config-local output.results_dir                     Task 1 Step 3
  ├── relative strategy escape rejected                   Task 1 Step 4
  ├── absolute strategy escape rejected                   Task 1 Step 4
  ├── absolute results_dir escape rejected                Task 1 Step 4
  └── missing readiness rejected                          Task 1 Step 5

[+] validation.run_validation
  ├── config-addressed run succeeds                       Task 3 Steps 1-3
  ├── unconfigured manifest ignored                       Task 3 Step 4
  ├── missing readiness fails at config load              Task 3 Step 5
  ├── wrong strategy id still hard-no                     Existing runner tests retained
  ├── non-decision output still hard-no                   Existing runner tests retained
  └── backend matrix behavior unchanged                   Existing runner tests retained

[+] validation.manifest.write_validation_manifest
  ├── no research_manifest field                          Task 3 Step 3
  ├── config path relative to config base                 Task 3 Step 3
  └── strategy path relative to config base               Task 3 Step 3

[+] runner.cli validate
  ├── mocked completed advisory decisions exit 0          Task 5 Step 7
  ├── hard_no exits 1                                     Task 5 Step 7
  └── validation error exits 1                            Task 5 Step 7
```

Coverage target: all new branches listed above must have tests before runtime
implementation is considered complete.

### Failure Modes

| Flow | Failure mode | Covered by plan | User-visible behavior |
|---|---|---|---|
| Config path resolution | Caller passes a directory or non-TOML path | Yes | `ValidationConfigError` explains explicit TOML requirement |
| Strategy path resolution | Config points outside candidate directory | Yes | Config load fails before import |
| Output path resolution | Config writes outside candidate directory | Yes | Config load fails before creating artifacts |
| Missing readiness | Config omits `[readiness]` | Yes | Config load fails before backend work |
| Stale manifest nearby | Candidate directory has old `manifest.json` | Yes | Manifest is ignored unless a future explicit provenance feature is added |
| Manifest path rendering | `repo_root` differs from config directory | Yes | Paths stay candidate-relative; git identity still uses repo root |

Critical gaps flagged: 0 after accepted test additions.

### Performance Review

No issues found. This refactor changes config resolution and artifact metadata.
It does not add new data loading, backend loops, database queries, or expensive
per-row work.

### Parallelization

Sequential implementation, no parallelization opportunity. The work touches the
same validation config/runtime/test surface, and splitting it across worktrees
would create merge conflicts in `tests/test_validation_runner.py`,
`validation/__init__.py`, and `validation/manifest.py`.

## Implementation Tasks

Synthesized from this review's findings. Each task derives from a specific
finding above. Run with Claude Code or Codex; checkbox as you ship.

- [ ] **T1 (P1, human: ~30min / CC: ~5min)** — validation config — Require explicit TOML paths
  - Surfaced by: Code quality — directory input convenience preserves old package habits.
  - Files: `src/quant_strategies/validation/config.py`, `tests/test_validation_config.py`, `tests/test_validation_runner.py`, `src/quant_strategies/runner/cli.py`, `tests/test_validation_cli.py`
  - Verify: `conda run -n quant pytest tests/test_validation_config.py tests/test_validation_cli.py -q`

- [ ] **T2 (P1, human: ~45min / CC: ~10min)** — validation manifest — Split git identity root from candidate path base
  - Surfaced by: Architecture — one `repo_root` overloaded git identity and path rendering.
  - Files: `src/quant_strategies/validation/__init__.py`, `src/quant_strategies/validation/manifest.py`, `tests/test_validation_runner.py`
  - Verify: generated `validation_manifest.json` has `validation.toml` and `strategy.py` paths while repository identity still records git state.

- [ ] **T3 (P1, human: ~30min / CC: ~5min)** — validation runtime — Thread `path_base` through helper chain
  - Surfaced by: Code quality — helper signatures must carry the accepted architecture explicitly.
  - Files: `src/quant_strategies/validation/__init__.py`, `src/quant_strategies/validation/manifest.py`
  - Verify: `conda run -n quant pytest tests/test_validation_runner.py -q`

- [ ] **T4 (P1, human: ~30min / CC: ~5min)** — config tests — Cover absolute path escapes
  - Surfaced by: Test review — absolute `strategy_path` and `output.results_dir` can bypass a boundary if untested.
  - Files: `tests/test_validation_config.py`, `src/quant_strategies/validation/config.py`
  - Verify: `conda run -n quant pytest tests/test_validation_config.py -q`

- [ ] **T5 (P2, human: ~15min / CC: ~5min)** — CLI tests — Remove legacy-shaped path examples
  - Surfaced by: Test review — active CLI tests still used `researched/demo`.
  - Files: `tests/test_validation_cli.py`, `src/quant_strategies/runner/cli.py`
  - Verify: `conda run -n quant pytest tests/test_validation_cli.py -q`

- [ ] **T6 (P2, human: ~20min / CC: ~5min)** — docs — State no legacy accommodation
  - Surfaced by: User constraint — no accommodation for researched-package or family/variant legacy layouts.
  - Files: `README.md`, `docs/quant-autoresearch-consumer.md`, `tests/test_readme_contract.py`
  - Verify: `conda run -n quant pytest tests/test_readme_contract.py -q`

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | Not run | Not requested for this plan |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | Not run | Not requested for this plan |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | Clean | 6 findings surfaced and resolved into the plan; 0 unresolved, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | Not applicable | No UI/UX surface in this refactor |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | Not run | CLI/docs changes covered by Eng Review tasks |

- **UNRESOLVED:** 0
- **VERDICT:** ENG CLEARED — ready for subagent-driven implementation with no legacy researched-package accommodation.
