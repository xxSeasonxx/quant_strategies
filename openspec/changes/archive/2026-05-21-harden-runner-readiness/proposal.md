## Why

The runner is structurally sound, but it is not yet ready to serve as durable
research infrastructure: the documented curated configs are missing from the
working tree, artifact files do not preserve the raw strategy inputs, relative
config paths are caller-cwd sensitive, and timing/no-lookahead semantics are not
explicit enough.

This change hardens the root runner contract without adding a registry,
autonomous workflow, or broad validation framework.

## What Changes

- Restore the curated run-config surface so documented CLI/API examples are
  runnable again.
- Resolve relative run-config paths against the effective repository root so
  `run_config("runs/<config>.toml", repo_root=...)` is stable outside the repo
  cwd.
- **BREAKING**: replace the ambiguous success artifact contract with a smaller
  explicit set:
  - `config.toml`
  - `strategy_snapshot.py`
  - `strategy_input_rows.csv`
  - `strategy_input_rows.jsonl`
  - `signals.csv`
  - `engine_request.json`
  - `summary.json`
  - `notes.md`
  - optional `evidence.json` when engine evidence is produced
- Write artifacts incrementally by run stage so failures preserve the most useful
  evidence already available.
- Treat engine validation as runner smoke evidence, not as sufficient evidence
  for strategy promotion.
- Clarify timing semantics with a conservative initial rule: close-derived
  signals require a future-bar entry fill unless
  `fill_model.allow_same_bar_close_fill = true` is explicitly set.
- Add audit-ready provenance and assumptions to strategy docstrings.
- Update README and product requirements to match the simplified runner and
  artifact contract.

## Capabilities

### New Capabilities

- `strategy-runner`: Defines config loading, runner execution, artifact
  semantics, failure-stage evidence, timing safety, and curated config readiness
  for one explicit strategy experiment at a time.

### Modified Capabilities

- None. The current `openspec/specs/` directory has no active capability specs
  in the working tree.

## Impact

- Affected code:
  - `src/quant_strategies/runner/config.py`
  - `src/quant_strategies/runner/__init__.py`
  - `src/quant_strategies/runner/artifacts.py`
  - `src/quant_strategies/runner/engine_runner.py`
  - strategy modules under `tested/` and `untested/`
- Affected tests:
  - runner API/CLI tests
  - artifact tests
  - config tests
  - strategy contract/docstring tests
- Affected docs:
  - `README.md`
  - `PRODUCT_REQUIREMENTS.md`
  - `AGENTS.md` only if wording needs cleanup
- Affected generated/runtime paths:
  - `runs/*.toml`
  - ignored `results/`
- No new runtime dependencies are intended.
