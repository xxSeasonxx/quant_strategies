## 1. Restore Runnable Baseline

- [x] 1.1 Restore or recreate the curated TOML configs under `runs/`.
- [x] 1.2 Add a focused test that every committed `runs/*.toml` parses through `load_config()` without live data access.
- [x] 1.3 Verify the README's documented config paths exist in the working tree.

## 2. Stabilize Config Loading

- [x] 2.1 Resolve relative `config_path` values against the effective repo root in `run_config()`/`load_config()`.
- [x] 2.2 Ensure copied `config.toml` uses the resolved config path.
- [x] 2.3 Add a cwd-independent API test for `run_config("runs/<config>.toml", repo_root=<repo>)`.
- [x] 2.4 Add a test that missing relative configs report the resolved attempted path.

## 3. Simplify And Stage Artifacts

- [x] 3.1 Replace ambiguous success artifact writing with the simple contract: `config.toml`, `strategy_snapshot.py`, `strategy_input_rows.csv`, `strategy_input_rows.jsonl`, `signals.csv`, `engine_request.json`, `summary.json`, `notes.md`, and optional `evidence.json`.
- [x] 3.2 Write `strategy_input_rows.csv` and `strategy_input_rows.jsonl` immediately after data loading succeeds.
- [x] 3.3 Write `signals.csv` immediately after signal generation succeeds.
- [x] 3.4 Write `engine_request.json` immediately after request construction succeeds.
- [x] 3.5 Write `summary.json` and `notes.md` for every post-config success or failure.
- [x] 3.6 Keep artifact code as small helper functions in `artifacts.py` (`write_strategy_input_rows`, `write_jsonl`, `write_engine_request`, `write_summary`) instead of adding a registry or artifact model.
- [x] 3.7 Add tests proving funding and quote fields survive in `strategy_input_rows.csv` and `strategy_input_rows.jsonl`.
- [x] 3.8 Add tests proving JSONL preserves datetimes, booleans, nulls, funding fields, and quote fields in JSON-compatible form.
- [x] 3.9 Add tests proving `engine_request.json` excludes non-engine fields that remain in raw strategy input artifacts.
- [x] 3.10 Add tests proving request-build failures preserve prior-stage artifacts.
- [x] 3.11 Add tests proving `summary.json` has fixed top-level keys on success.
- [x] 3.12 Add tests proving `summary.json` has fixed top-level keys on data-load, strategy-import, request-build, and engine-evaluation failures.
- [x] 3.13 Add tests proving `summary.json.artifacts` lists files actually written.

## 4. Tighten Runner Execution Order And Errors

- [x] 4.1 Import and validate the configured strategy before loading data.
- [x] 4.2 Add a test that strategy import failure prevents any `quant_data` loader call.
- [x] 4.3 Translate missing or malformed engine bar/signal fields into `RequestBuildError` with useful field context.
- [x] 4.4 Add tests for missing required bar and signal fields.

## 5. Enforce Conservative Timing Safety

- [x] 5.1 Add `fill_model.allow_same_bar_close_fill = false` as the default config field.
- [x] 5.2 Reject `fill_model.price = "close"` with `entry_lag_bars = 0` during config validation unless `allow_same_bar_close_fill = true`.
- [x] 5.3 Add tests for rejected unsafe close fills, accepted explicit same-bar opt-in, and accepted future-bar close fills.
- [x] 5.4 Document that same-bar close-derived fills require explicit opt-in and remain the caller's causal responsibility.

## 6. Update Strategy And User-Facing Documentation

- [x] 6.1 Add exact rationale headings to each committed strategy module docstring: `Source / provenance:`, `Market rationale:`, `Required observables:`, `Signal rule:`, `Assumptions:`, and `Falsifier:`.
- [x] 6.2 Update `README.md` to describe setup assumptions, restored configs, and the simplified artifact contract.
- [x] 6.3 Update `PRODUCT_REQUIREMENTS.md` to match the simplified artifact set and remove stale numbering or artifact references.
- [x] 6.4 Keep internal evaluator validation described as smoke evidence, not promotion evidence.
- [x] 6.5 Add a lightweight docstring test that checks exact headings only, without semantic parsing.

## 7. Verify

- [x] 7.1 Run `conda run -n quant pytest`.
- [x] 7.2 Run `conda run -n quant quant-strategies --help`.
- [x] 7.3 Run or document the expected result of the simple curated CLI smoke config.
- [x] 7.4 Report changed-line counts separated by source, tests, docs, OpenSpec, and restored configs.
