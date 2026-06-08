## 1. Tests First

- [x] 1.1 Add config tests for optional `data.load_start` / `data.load_end`, defaults, and invalid load windows that do not cover `data.start` / `data.end`.
- [x] 1.2 Add data-loader tests proving strict loaders receive the load window while preserving existing loader behavior when buffer fields are omitted.
- [x] 1.3 Add runner tests proving strategy generation and causality replay see only decision-window rows when buffer rows exist.
- [x] 1.4 Add runner tests proving engine request building can use post-window buffer rows to fill exits for decision-window decisions.
- [x] 1.5 Add artifact tests proving data manifests or summary artifacts distinguish decision-window rows from execution/load rows.
- [x] 1.6 Add downstream autoresearch protocol tests proving generated quick-run TOML includes the execution buffer and emitted causality policy.

## 2. Upstream Config And Data Boundary

- [x] 2.1 Add optional quick-run data fields for `load_start` and `load_end` with validation that the load window covers the decision window.
- [x] 2.2 Extend the shared execution/data-load path to load execution rows from the load window while deriving strategy-visible rows from the decision window.
- [x] 2.3 Preserve existing single-window behavior when `load_start` and `load_end` are omitted.
- [x] 2.4 Keep strict upstream loading, row-order preservation, and row-contract validation for both decision rows and execution rows.

## 3. Runner Execution Semantics

- [x] 3.1 Ensure strategy generation receives only strategy-visible decision-window rows.
- [x] 3.2 Ensure hidden-lookahead replay uses only decision-window rows.
- [x] 3.3 Ensure engine request construction receives execution/load rows plus decision-window decisions.
- [x] 3.4 Exclude any out-of-window decisions from engine evaluation and report excluded counts if they can occur.
- [x] 3.5 Preserve request-build failure when exits still fall outside the loaded execution window.

## 4. Artifacts And Public Docs

- [x] 4.1 Update data manifest and compact artifacts to expose decision window, load window, strategy-visible row counts/hashes, and execution row counts/hashes.
- [x] 4.2 Keep existing replayability semantics tied to strategy-visible rows.
- [x] 4.3 Update consumer docs to describe decision/scoring window versus execution/load window.

## 5. Downstream Autoresearch Integration

- [x] 5.1 Update `quant_autoresearch` protocol parsing and quick-run materialization to support an execution buffer.
- [x] 5.2 Update active autoresearch protocol to set a post-Train `load_end` or equivalent execution buffer.
- [x] 5.3 Remove the temporary strategy-level `last_entry_time` workaround and keep `require_exit_horizon = false`.
- [x] 5.4 Run an emitted-causality quick-run smoke proving the current funding strategy completes request build and returns trade economics.

## 6. Verification

- [x] 6.1 Run focused upstream runner/data-boundary tests.
- [x] 6.2 Run upstream formatting/lint checks.
- [x] 6.3 Run the upstream Python test suite under `conda run -n quant`.
- [x] 6.4 Run `quant_autoresearch` tests.
- [x] 6.5 Run one short `quant_autoresearch` quick-run or climb smoke through public `run_config`.
