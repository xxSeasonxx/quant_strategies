# Phase 8 Plan: Lazy `quant_data` Imports

Date: 2026-05-28
Design: `docs/superpowers/specs/2026-05-28-foundation-review-p2-lazy-quant-data-design.md`

## Goal

Reduce runner cold-import overhead by loading `quant_data` only when real data
loading or default-engine construction is needed.

## Implementation Steps

- [x] **Step 1: Add lazy import helpers**

  Replace top-level `quant_data` imports with cached helper functions in
  `runner.data_loader`.

  Verify: import test confirms `quant_data` is not imported by `data_loader`
  import.

- [x] **Step 2: Preserve adapter behavior**

  Use the lazy loader helper inside `_load_rows` and preserve existing monkeypatch
  seams.

  Verify: existing `tests/test_runner_data_loader.py` adapter tests pass.

- [x] **Step 3: Docs/progress, verification, review**

  Update `progress.md`; run focused tests, full suite, diff checks, compile
  checks, and subagent code review before commit.

## Verification Commands

```bash
conda run -n quant pytest tests/test_runner_data_loader.py tests/test_runner_api_cli.py tests/test_readme_contract.py -q
conda run -n quant pytest -q
git diff --check
conda run -n quant python -m compileall -q src tests
```

## GSTACK REVIEW REPORT

### Scope Challenge

The hidden `.env` lookup is still a reproducibility smell. This phase does not
change it because lazy imports are a mechanical performance fix with minimal
behavior risk; environment provenance should be handled separately.

### Architecture Review

Target import flow:

```text
import quant_strategies.runner
        |
        v
runner.data_loader module loaded
        |
        v
no quant_data import until load_data/_default_engine
```

### Code Quality Review

- Keep helper functions small and explicit.
- Preserve monkeypatch seams for tests.
- Do not hide `ImportError`; let `load_data` translate loader failures to
  `DataLoadError` as before.

### Test Review

Tests must cover:

- adapter behavior for bars, universe bars, crypto funding, and FX quotes;
- default engine still uses the discovered `.env`;
- importing `runner.data_loader` does not import `quant_data`.
