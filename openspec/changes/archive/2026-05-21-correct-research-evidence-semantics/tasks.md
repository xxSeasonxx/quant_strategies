## 1. Failing Tests For Root-Cause Semantics

- [x] 1.1 Add a runner test proving screen-mode completion writes `status = "screened"` and does not set `engine.passed = true`.
- [x] 1.2 Add a runner test proving validation-mode pass/fail summaries still reflect validation gates.
- [x] 1.3 Add a timing trace test for the FX triangular residual strategy from residual observation to signal `decision_time`, engine entry time, and engine exit time.
- [x] 1.4 Add artifact tests for minimal `run_manifest.json` and `data_manifest.json` on completed runs.

## 2. Runner Evidence Semantics

- [x] 2.1 Update screen-mode `EngineRun`/summary handling so screen completion is not represented as validation pass.
- [x] 2.2 Update `notes.md` generation to distinguish screened, validation passed, and validation failed states.
- [x] 2.3 Keep post-config runner failures stage-aware and ensure their summaries still use the stable top-level schema.

## 3. FX Timing Correction

- [x] 3.1 Correct `untested/fx_triangular_residual_reversion.py` so emitted `decision_time` matches the completed residual decision timestamp intended by the run config.
- [x] 3.2 Update FX strategy tests to reflect the corrected signal timing and side behavior.

## 4. Minimal Reproducibility Manifests

- [x] 4.1 Add manifest-writing helpers for SHA-256 hashing of generated artifacts.
- [x] 4.2 Write `run_manifest.json` with best-effort git identity, Python version, key package versions, and hashes for existing config/strategy/input/signals/request artifacts.
- [x] 4.3 Write `data_manifest.json` after data loading succeeds with data kind, dataset, requested symbols/window, row counts, timestamp ranges, input JSONL hash, and simple metadata-field coverage.
- [x] 4.4 Ensure manifest capture is best-effort and does not fail an otherwise valid completed run when git or package metadata is unavailable.
- [x] 4.5 Include manifests in `summary.json.artifacts` whenever they exist.
- [x] 4.6 Record dirty git worktree state in `run_manifest.json` without treating the generated result directory itself as source-code dirtiness.

## 5. Funding And Availability Semantics

- [x] 5.1 Preserve existing `available_at` and ingestion/refresh metadata fields in raw strategy input artifacts when loaders return them.
- [x] 5.2 Pass supplied crypto funding event fields into internal evaluator requests.
- [x] 5.3 Add notes or summary messaging for `crypto_perp_funding` runs that supplied funding events are included when they fall inside engine-held intervals.

## 6. Documentation And Verification

- [x] 6.1 Update `README.md` runner artifact and screen/validation semantics.
- [x] 6.2 Update `PRODUCT_REQUIREMENTS.md` for manifests, screen semantics, FX timing, and funding-aware engine evidence.
- [x] 6.3 Mark stale historical design docs as superseded or update their artifact names.
- [x] 6.4 Run `conda run -n quant pytest`.
- [x] 6.5 Run the curated FX quote smoke config and inspect `summary.json`, `notes.md`, `run_manifest.json`, and `data_manifest.json`.
- [x] 6.6 Report changed-line counts split by source, tests, docs, and generated/artifact movement.
