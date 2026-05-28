# Default Engine Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use TDD for behavior changes and
> request code review before commit. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Avoid repeated default `quant_data` engine creation in in-process
runner loops while preserving explicit engine injection and test isolation.

**Architecture:** `runner.data_loader` keeps a private cached default engine and
the factory object that produced it. `_default_engine()` returns the cached
engine when the factory is unchanged; if `data_loader.get_engine` changes, it
creates and caches a fresh engine. `load_data(config, engine=...)` remains a
direct bypass.

**Tech Stack:** Python 3.12, pytest via `conda run -n quant`.

---

## File Structure

- Modify `tests/test_runner_data_loader.py`: default engine cache regressions.
- Modify `src/quant_strategies/runner/data_loader.py`: process-local default
  engine cache.
- Modify `README.md`: document default engine reuse.
- Modify `docs/quant-autoresearch-consumer.md`: document in-process reuse
  contract.
- Modify `progress.md`.

## Implementation Steps

- [x] **Step 1: Add failing default-engine cache regression**

  Add tests proving repeated `_default_engine()` calls with one factory call the
  factory once and that replacing `data_loader.get_engine` refreshes the cache.

  Verify failure before implementation:

  ```bash
  conda run -n quant pytest tests/test_runner_data_loader.py::test_default_engine_reuses_current_factory_engine -q
  ```

- [x] **Step 2: Implement process-local cache**

  Add private cache state to `runner.data_loader`. `_default_engine()` should
  compare the current `_get_engine()` factory object with the cached factory and
  create a new engine only when needed.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_runner_data_loader.py::test_default_engine_reuses_current_factory_engine tests/test_runner_data_loader.py::test_default_engine_refreshes_when_factory_changes tests/test_runner_data_loader.py::test_default_engine_uses_public_quant_data_engine_factory_without_env_discovery -q
  ```

- [x] **Step 3: Docs, full verification, and review**

  Update README and the consumer doc so repeated in-process default loads are
  documented as sharing the process default engine.

  Run:

  ```bash
  conda run -n quant pytest tests/test_runner_data_loader.py tests/test_runner_api_cli.py tests/test_readme_contract.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused checks
  plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

The review also mentions pooling and live database behavior. That belongs to
`quant_data`; this phase only avoids repeated engine factory calls from this
repository.

### Architecture Review

Target flow:

```text
load_data(config, engine=explicit) -> use explicit engine
load_data(config, engine=None)
  -> _default_engine()
    -> factory = _get_engine()
    -> return cached engine if factory unchanged
    -> otherwise create/cache factory()
```

The factory-object key keeps tests and local overrides deterministic.

### Edge Cases

- A monkeypatched `data_loader.get_engine` should not inherit a cached engine
  created by a previous factory.
- Passing `engine=` should not create or consult the default cache.
- `quant_data` import laziness remains unchanged.

### Test Review

The red regression should fail on factory call count before implementation. A
second test should ensure the cache invalidates when the factory object changes.
