## 1. Focused Causality Core

- [x] 1.1 Add focused causality result/config/cache-key types with source hash, strategy id, data kind, profile version, status, probe counts, timeout budget, cache usage, and rejection reason.
- [x] 1.2 Implement deterministic focused probe selection from strategy-visible rows and baseline decisions, including emitted-decision coverage, no-signal coverage, early/mid/late row-grid probes, symbol coverage, and a hard probe cap.
- [x] 1.3 Implement focused replay execution that reuses existing causality primitives where possible and returns `passed`, `failed`, or `timeout` without running full emitted/strict scoring-window replay.
- [x] 1.4 Add focused causality unit tests for deterministic probe selection, probe cap behavior, pass, lookahead failure, and timeout rejection.
- [x] 1.5 Avoid materializing the full strict row grid when building a focused replay plan, and add a regression test proving focused planning does not depend on `strict_replay_boundaries`.

## 2. Runner Policy And Cache

- [x] 2.1 Extend quick-run config with a focused causality policy while preserving existing explicit `off`, `emitted`, `strict`, and strict probe-limit behavior.
- [x] 2.2 Add focused certification cache read/write under generated results output, keyed by source hash, strategy id, data kind, row hash, parameter hash, focused profile version, probe cap, and timeout budget.
- [x] 2.3 Wire focused policy into `run_config` so cache-passed source variants can score, focused failures/timeouts fail before engine scoring, and existing explicit replay modes retain current behavior.
- [x] 2.4 Add runner tests for focused pass, focused failure, focused timeout, passed cache hit, failed cache hit, profile-version invalidation, and non-regression of existing explicit replay modes.

## 3. Evidence And Artifacts

- [x] 3.1 Extend `RunResult` evidence with focused causality status, source hash, focused profile version, cache usage, timeout budget, probe counts, scoring allowance, and rejection reason.
- [x] 3.2 Write focused causality fields to `summary.json`, `data_manifest.json`, and diagnostic artifacts when focused policy is selected.
- [x] 3.3 Add artifact/profile tests proving focused pass and focused reject states are visible without requiring emitted/strict replay internals.

## 4. Documentation And Consumer Contract

- [x] 4.1 Update consumer/autoresearch docs to recommend focused causality for Train iteration and validation/evaluation for survivor/audit gates.
- [x] 4.2 Keep low-level emitted/strict/off documentation in reference material only, clearly marked as advanced/debug/audit policy.
- [x] 4.3 Add docs tests or repository-boundary tests that prevent autoresearch-facing docs/templates from instructing the strategy LLM to choose emitted or strict replay.

## 5. Verification

- [x] 5.1 Run focused causality and runner unit tests.
- [x] 5.2 Run existing quick-run causality policy regression tests.
- [x] 5.3 Run formatting/lint cleanup through the repo-owned target.
- [x] 5.4 Run `openspec validate add-focused-causality-gate --strict`.
