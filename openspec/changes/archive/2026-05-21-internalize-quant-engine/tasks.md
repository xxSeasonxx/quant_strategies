## 1. Baseline And Safety Checks

- [x] 1.1 Record current dirty worktree state for `quant_strategies`, `quant_engine`, and `quant_autoresearch` before moving files.
- [x] 1.2 Run the current focused test suites that cover runner/evaluator integration.
- [x] 1.3 Identify active first-party imports or shell calls to `quant_engine` / `quant-engine`.

## 2. Internal Evaluator Migration

- [x] 2.1 Create the internal evaluator package/module under `src/quant_strategies/`.
- [x] 2.2 Move evaluator models, evaluation logic, evidence serialization, and public exports from `quant_engine` into the internal package.
- [x] 2.3 Move evaluator tests into the `quant_strategies` test suite and update import paths.
- [x] 2.4 Preserve funding-aware accounting, quote fills, validation gates, and evidence schema behavior with migrated tests.

## 3. Runner Cutover

- [x] 3.1 Update runner config and engine-adapter imports to use the internal evaluator.
- [x] 3.2 Remove `quant-engine` from `pyproject.toml` dependencies.
- [x] 3.3 Update run-manifest package capture so it no longer expects an external `quant-engine` package version.
- [x] 3.4 Update runner tests that assert package versions, engine request shape, or engine failure behavior.

## 4. Remove Public Engine Surface

- [x] 4.1 Ensure this repository does not provide a top-level `quant_engine` compatibility package.
- [x] 4.2 Ensure this repository does not provide a `quant-engine` console script.
- [x] 4.3 Add or update tests/search checks proving first-party source no longer imports `quant_engine`.

## 5. Autoresearch Cutover

- [x] 5.1 Update `quant_autoresearch` to call `quant_strategies.runner.run_config` or `quant-strategies run` instead of shelling `quant-engine`.
- [x] 5.2 Update `quant_autoresearch` tests and docs for runner-managed artifacts.
- [x] 5.3 Verify no active `quant_autoresearch` workflow invokes `quant-engine screen` or `quant-engine validate`.

## 6. Documentation And Decommissioning

- [x] 6.1 Update `README.md`, `PRODUCT_REQUIREMENTS.md`, and `AGENTS.md` in `quant_strategies` for the internal evaluator boundary.
- [x] 6.2 Preserve any useful standalone `quant_engine` docs or OpenSpec archive notes before decommissioning.
- [x] 6.3 Decommission or archive the standalone `/Users/Season_Yang/Personal/quant_engine` repository only after all cutover tests pass.
- [x] 6.4 Update OpenSpec docs/specs so archived contracts no longer direct users to standalone `quant_engine`.

## 7. Verification

- [x] 7.1 Run `conda run -n quant pytest` in `quant_strategies`.
- [x] 7.2 Run focused verification in `quant_autoresearch`.
- [x] 7.3 Run `git diff --check` in every touched repository.
- [x] 7.4 Run `openspec validate internalize-quant-engine --strict`.
- [x] 7.5 Report changed-line counts split by source, tests, docs, OpenSpec artifacts, and generated/artifact movement for each touched repository.
