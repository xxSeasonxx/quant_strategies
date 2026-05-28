# Phase 33 Design: Default Engine Cache

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` flags that default runner data loads create a new
`quant_data` database engine for each `run_config()` call. Phase 8 made
`quant_data` imports lazy, and Phase 14 removed hidden `.env` discovery, but
`runner.data_loader._default_engine()` still calls the configured engine factory
on every default load.

This is avoidable overhead for `quant_autoresearch` and other in-process
candidate sweeps.

## Assignment

Cache the default `quant_data` engine per Python process. Preserve explicit
`engine=` injection and preserve monkeypatch isolation by refreshing the cache
when the configured engine factory changes.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed
for Phase 33:

- Cache only the default engine created through `_default_engine()`.
- Do not cache or wrap explicit `load_data(config, engine=...)` inputs.
- Key the cache by the current engine factory object so tests and callers that
  replace `data_loader.get_engine` do not reuse a stale engine.
- Do not add pooling, disposal, or lifecycle management beyond reusing the
  factory-created engine object.

## Scope

- Add a focused regression that `_default_engine()` calls the current factory
  once across repeated default loads.
- Add a regression that changing the factory refreshes the cached engine.
- Implement a private process-local cache in `runner.data_loader`.
- Update README and the `quant_autoresearch` consumer doc with the new default
  engine reuse contract.
- Update `progress.md`.

## Not In Scope

- Changing `quant_data` internals.
- Adding connection pool configuration.
- Caching loaded rows or loader outputs.
- Recording live data-source identities in artifacts.

## Success Criteria

- Repeated `_default_engine()` calls with the same factory return the same engine
  and call the factory once.
- Replacing `data_loader.get_engine` refreshes the cached default engine.
- `load_data(config, engine=...)` still bypasses the default engine cache.
- Focused data-loader tests and the full suite pass.
