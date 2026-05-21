## 1. Runner Assessment Semantics

- [x] 1.1 Add focused runner tests for `run_completed`, `assessment_status`, and `promotion_eligible` on screen, smoke-pass, smoke-fail, and runner-failure paths.
- [x] 1.2 Extend `RunResult` and `summary.json` generation with explicit assessment metadata while preserving existing fields.
- [x] 1.3 Update README artifact and runner sections to explain the new fields and the smoke-only promotion posture.

## 2. Failure Auditability

- [x] 2.1 Add tests proving strategy-import, data-load, and signal-generation failures write `run_manifest.json`.
- [x] 2.2 Centralize failure finalization so every created result directory writes notes, manifest, and summary consistently.

## 3. CLI Root Contract

- [x] 3.1 Add a CLI test for `quant-strategies run --repo-root <repo> runs/demo.toml` from another working directory.
- [x] 3.2 Implement the CLI `--repo-root` option and pass it through to `run_config`.
- [x] 3.3 Document the checkout-local CLI contract and explicit root option in README.

## 4. Data Readiness Guard

- [x] 4.1 Add tests for matching signal decision rows whose availability metadata is before, equal to, and after `decision_time`.
- [x] 4.2 Implement a small runner readiness helper and fail before engine request construction when matching decision-row metadata is late.
- [x] 4.3 Ensure readiness failures preserve prior artifacts and use a clear failed stage in `summary.json`.

## 5. Strategy Boundary Enforcement

- [x] 5.1 Add static tests enforcing flat strategy layout under `tested/` and `untested/`.
- [x] 5.2 Add static tests rejecting strategy imports of data/runner/evaluator packages and common side-effect primitives.
- [x] 5.3 Keep existing strategy docstring tests passing without requiring strategy API changes.

## 6. Verification

- [x] 6.1 Run `conda run -n quant pytest`.
- [x] 6.2 Run committed config parse smoke with `conda run -n quant python`.
- [x] 6.3 Report changed-line counts separated into source, tests, docs/specs, and generated/artifact movement.
