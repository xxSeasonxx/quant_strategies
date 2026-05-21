## Context

`quant_strategies` currently owns strategy files, run configs, data loading via
`quant_data`, artifact writing, and runner orchestration. It evaluates through a
separate `quant_engine` package that is about 600 source lines and has already
needed coordinated changes for quote fills, funding cashflows, evidence schema,
and runner artifact semantics.

The separate repository still has conceptual value as a deterministic evaluator
boundary, but its standalone distribution and CLI now create friction and a
bypass path: `quant_autoresearch` can shell `quant-engine` directly instead of
using the configured runner and its artifact/data/code manifest discipline.

## Goals / Non-Goals

**Goals:**

- Make `quant_strategies` the single repository that owns strategy execution,
  runner artifacts, and deterministic evaluation code.
- Preserve the evaluator as an internal package/module boundary with explicit
  models, fill/cost/accounting logic, validation, and evidence serialization.
- Remove the external `quant-engine` dependency and public `quant-engine` CLI
  from supported workflows.
- Update `quant_autoresearch` so configured experiments call
  `quant_strategies.runner.run_config` rather than invoking `quant-engine`.
- Keep existing evaluator behavior and tests through the migration.

**Non-Goals:**

- Do not merge evaluator logic into strategy files.
- Do not add autonomous research, strategy promotion, or paper-trading approval
  behavior.
- Do not keep compatibility shims such as `quant_engine/__init__.py` after the
  cutover; the old standalone import should fail.
- Do not physically delete the standalone `quant_engine` repository until the
  internal package and downstream caller migration are verified.

## Decisions

### 1. Internal package, not public standalone package

Move evaluator code into an internal package path such as
`quant_strategies.engine`. The runner will import that package directly. The old
top-level `quant_engine` package name will not be recreated in this repository.

Alternative considered: move `src/quant_engine` wholesale into this repository
and keep `from quant_engine import ...` working. That lowers migration effort,
but it keeps the public engine surface alive and contradicts the goal of making
the runner the only supported execution path.

### 2. Preserve evaluator boundaries and tests

The internal evaluator should keep the same separation it has today:

```text
models.py      explicit request/result contracts
evaluation.py  deterministic screen/validate accounting
evidence.py    deterministic evidence serialization
```

The tests should move with the code, adjusted only for import paths and intended
contract changes. Runner tests should continue to verify request construction
and failure semantics at the boundary.

Alternative considered: inline the evaluator into `runner/engine_runner.py`.
That would be fewer files but would mix orchestration, artifact staging,
request translation, accounting, and validation in one place.

### 3. Remove the engine CLI and route downstream through run configs

Do not preserve `quant-engine` as a console script. `quant_autoresearch` should
produce or select a TOML run config and call `quant_strategies.runner.run_config`
so data manifests, run manifests, strategy snapshots, and notes remain the
single execution record.

Alternative considered: add a new `quant-strategies engine ...` CLI. That would
mostly recreate the bypass path under another name. If a CLI is needed, it
should run configured strategies, not raw engine requests.

### 4. Record internal engine identity through artifacts

`run_manifest.json` should stop looking up `quant-engine` as a package version.
It should record the internal evaluator evidence schema/version and hash the
source/artifacts already captured for the run. This keeps auditability after the
external dependency disappears.

Alternative considered: keep a synthetic `quant-engine` version field. That
would be confusing once the package no longer exists.

## Risks / Trade-offs

- Direct users of `quant_engine` imports or `quant-engine` CLI will break.
  Mitigation: intentionally update known internal callers and docs; do not keep
  shims that hide the break.
- `quant_autoresearch` may not yet express every raw-engine request as a
  `quant_strategies` TOML config. Mitigation: migrate the smallest active flow
  first and add a clear task for any unsupported experiment shape discovered.
- Co-locating evaluator code could weaken the mental boundary between strategy
  generation and accounting. Mitigation: keep a separate internal package,
  separate tests, and AGENTS/README wording that strategy files must not call
  the evaluator directly.
- Deleting the standalone repo too early could lose useful archived docs or
  OpenSpec history. Mitigation: only decommission after code/tests/docs are
  verified, and preserve any still-useful docs before removal.

## Migration Plan

1. Move evaluator source and tests into `quant_strategies` under an internal
   package path.
2. Update runner imports, package metadata, manifests, and docs.
3. Remove `quant-engine` dependency and console script assumptions from this
   repository.
4. Update `quant_autoresearch` to call `quant_strategies.runner.run_config`.
5. Run full tests in `quant_strategies` and focused tests in
   `quant_autoresearch`.
6. Confirm no first-party code still imports `quant_engine` or shells
   `quant-engine`.
7. Decommission or archive the standalone `quant_engine` repository.

## Open Questions

- Should old `quant_engine` OpenSpec archive docs be copied into
  `quant_strategies` historical docs before deleting the repo?
- Should `quant_autoresearch` own any adapter for legacy experiment files, or
  should all active experiments be migrated directly to TOML run configs?
