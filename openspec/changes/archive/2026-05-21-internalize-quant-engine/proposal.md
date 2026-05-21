## Why

`quant_engine` is now small enough that keeping it as a separate repository and
distribution creates more coordination cost than boundary value. Funding and
fill-accounting changes should be updateable with the runner and strategy tests
that consume them, while preserving the deterministic evaluator as a separate
internal boundary.

## What Changes

- **BREAKING** Remove the standalone `quant-engine` package dependency and
  `quant-engine` CLI as public surfaces for this project.
- Move the deterministic evaluator source and tests into this repository under
  an internal `quant_strategies` package boundary.
- Update the runner to import the internal evaluator instead of `quant_engine`.
- Update run manifests and docs so engine identity is recorded as internal
  project code/evidence schema, not an external package version.
- Update `quant_autoresearch` to call `quant_strategies.runner.run_config`
  instead of shelling `quant-engine`, so it cannot bypass the strategy runner.
- Decommission the standalone `/Users/Season_Yang/Personal/quant_engine`
  repository only after both repositories verify the cutover.

## Capabilities

### New Capabilities

- `internal-evaluation-engine`: Deterministic screening, validation, accounting,
  and evidence serialization owned inside `quant_strategies`.

### Modified Capabilities

- `strategy-runner`: Runner evaluation uses the internal evaluator and remains
  the only supported execution path for configured strategy experiments.

## Impact

- Affected source: `src/quant_strategies/runner/`, new internal evaluator
  package/module, package metadata, and possibly `quant_autoresearch`.
- Affected tests: migrate existing engine tests, runner engine-adapter tests,
  CLI/API tests, and any autoresearch runner tests that shell `quant-engine`.
- Affected docs: `README.md`, `PRODUCT_REQUIREMENTS.md`, `AGENTS.md`, OpenSpec
  specs, and any `quant_autoresearch` docs that mention direct engine usage.
- Affected dependencies/APIs: remove `quant-engine` from project dependencies,
  remove direct `quant_engine` imports, and intentionally avoid compatibility
  shims that keep the old standalone engine import alive.
