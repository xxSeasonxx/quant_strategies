# Phase 14 Design: Quant Data Environment Boundary

Date: 2026-05-28
Mode: Builder
Source review: `review-codex.md`, `review-claude.md`

## Problem

`review-codex.md` flags that `runner.data_loader._default_engine()` discovers
an upstream `.env` by walking from `quant_data.loader.__file__` and passing that
path into `quant_data.config.DataConfig`. This is still current behavior and is
covered by `tests/test_runner_data_loader.py`. The repo contract says
`quant_strategies` should use public `quant_data` loader APIs and leave data
configuration, materialization, refresh, and source joining upstream.

## Assignment

Remove hidden `quant_data` checkout-layout coupling from the runner. The default
runner path should call the public `quant_data.db.get_engine()` factory without
discovering or constructing a private `_env_file` configuration. Callers that
need an explicit engine can keep passing `engine=` into `load_data()`.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 14:

- Delete the hidden `.env` lookup instead of documenting it as acceptable.
- Keep lazy `quant_data` imports from Phase 8.
- Keep monkeypatch seams for `loader` and `get_engine`.
- Do not introduce process-level engine caching in this phase.
- Do not add runner config fields for data credentials in this phase.
- Do not import `quant_data.config.DataConfig` from this repository.

## Scope

- Replace the old env-discovery regression with a regression proving
  `_default_engine()` delegates directly to `get_engine()` with no config args.
- Remove `DataConfig`, `_quant_data_env_file()`, and `_data_config_type()` from
  `runner.data_loader`.
- Remove the unused `Path` import and `__file__` lazy-loader proxy attribute.
- Update README and consumer docs to clarify that `quant_data` owns environment
  configuration.
- Update progress tracking.

## Not In Scope

- DB engine caching.
- Manifest data-source identity beyond existing row/data hashes.
- Changing `quant_data` internals.
- Changing data loader function signatures.
- Changing validation config ownership.

## Success Criteria

- `_default_engine()` calls the configured `get_engine` factory with no
  positional or keyword arguments.
- The runner no longer imports or references `quant_data.config.DataConfig`.
- The runner no longer walks from `quant_data.loader.__file__` to locate `.env`.
- Existing loader monkeypatch tests and lazy import tests continue to pass.
- Focused tests, full suite, diff check, compile check, and code review pass.
