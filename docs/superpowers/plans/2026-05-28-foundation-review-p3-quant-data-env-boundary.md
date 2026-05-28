# Quant Data Environment Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove hidden `quant_data` `.env` discovery from the runner data loader.

**Architecture:** `quant_strategies` will keep using `quant_data` public loader and engine APIs, but it will stop constructing a `quant_data.config.DataConfig` from an inferred upstream checkout path. `_default_engine()` becomes a direct lazy call to `quant_data.db.get_engine()`, while explicit test/consumer engine injection remains available through `load_data(config, engine=...)`.

**Tech Stack:** Python 3.12, existing runner data-loader tests, pytest via `conda run -n quant`.

---

## File Structure

- Modify `tests/test_runner_data_loader.py`: replace the env-discovery test with a direct-public-engine-factory test.
- Modify `src/quant_strategies/runner/data_loader.py`: remove hidden env lookup and unused DataConfig lazy import.
- Modify `README.md`: state that `quant_data` owns database/environment configuration.
- Modify `docs/quant-autoresearch-consumer.md`: clarify downstream setup should configure `quant_data`, not rely on runner `.env` discovery.
- Modify `progress.md`: record Phase 14 status and verification.

## Implementation Steps

- [x] **Step 1: Add the boundary regression**

  Replace `test_default_engine_uses_quant_data_repo_env_file()` with a test named
  `test_default_engine_uses_public_quant_data_engine_factory_without_env_discovery()`.
  The test should:

  - create a fake `quant-data/.env` next to a fake `quant_data.loader.__file__`;
  - monkeypatch `data_loader.DataConfig` to a class that raises if constructed;
  - monkeypatch `data_loader.get_engine` to capture call args;
  - call `data_loader._default_engine()`;
  - assert `get_engine` was called with no args and no kwargs.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_runner_data_loader.py::test_default_engine_uses_public_quant_data_engine_factory_without_env_discovery -q
  ```

  Expected before implementation: fails because `_default_engine()` constructs
  `DataConfig(_env_file=...)`.

- [x] **Step 2: Remove hidden env discovery**

  In `src/quant_strategies/runner/data_loader.py`:

  - remove `from pathlib import Path`;
  - remove `DataConfig`;
  - remove `"__file__"` from `_LazyLoaderProxy._loader_attributes`;
  - replace `_default_engine()` with `return _get_engine()()`;
  - delete `_quant_data_env_file()`;
  - delete `_data_config_type()`.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_runner_data_loader.py -q
  rg "_env_file|_quant_data_env_file|_data_config_type|quant_data.config|DataConfig" src/quant_strategies/runner/data_loader.py tests/test_runner_data_loader.py
  ```

  Expected after implementation: runner data-loader tests pass; `rg` finds no
  matches in the runner data-loader source and only intentional test names if
  any.

- [x] **Step 3: Update docs and progress**

  Update docs so users know `quant_data` environment configuration is upstream
  and explicit `engine=` injection remains the local escape hatch for tests or
  specialized callers.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_readme_contract.py -q
  ```

- [x] **Step 4: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest tests/test_runner_data_loader.py tests/test_runner_api_cli.py tests/test_readme_contract.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix any valid findings and rerun the
  relevant focused checks plus the full suite.

## GSTACK REVIEW REPORT

### Scope Challenge

The larger review also recommends engine caching and manifest data-source
identity. Those are real but separate. This phase fixes the hidden local
checkout-layout dependency without changing runtime connection lifecycle or
artifact schemas.

### Architecture Review

Target flow:

```text
load_data(config, engine=None)
        |
        v
_default_engine()
        |
        v
quant_data.db.get_engine()
```

The runner still calls public `quant_data.loader.*` functions and still allows
test or advanced callers to pass an engine object directly.

### Edge Cases

- Tests that monkeypatch `data_loader.get_engine` continue to work.
- Importing `runner.data_loader` still does not import `quant_data`.
- If `quant_data` needs environment variables or config files, that remains a
  `quant_data` setup concern and should fail from `get_engine()` with its own
  error.
- Existing direct `engine=` injection bypasses `_default_engine()` unchanged.

### Test Review

Tests cover removal of the hidden `.env` behavior, preservation of the lazy
import behavior, preservation of loader adapters, docs contract, and existing
runner API behavior through focused and full suites.
