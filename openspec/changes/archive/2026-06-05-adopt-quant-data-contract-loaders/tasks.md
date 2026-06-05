## 1. Loader migration (`core/data_loader.py`)

- [x] 1.1 Redesign `_LazyLoaderProxy` to expose `load_strategy_bars` + `load_strategy_universe_bars` (from `quant_data.contract_loaders`) and `load_fx_bars_with_quotes` + `load_crypto_perp_bars_with_funding` (from `quant_data.loader`), keeping per-function override seams for both modules.
- [x] 1.2 Preserve the lazy-import purity invariant: importing `core.data_loader` must not import `quant_data` (lazy-import both `quant_data.loader` and `quant_data.contract_loaders` on first real use only).
- [x] 1.3 Migrate `_load_rows` `bars` single-symbol path to `load_strategy_bars(engine, symbol, dataset, start, end, strict=True)`.
- [x] 1.4 Migrate `_load_rows` `bars` multi-symbol path to `load_strategy_universe_bars(...)` (one frame); replace `_rows_from_universe` (dict) with `_rows_from_frame` on the single returned frame.
- [x] 1.5 Update `crypto_perp_funding` path to call `load_crypto_perp_bars_with_funding(..., strict=True)`.
- [x] 1.6 Update `forex_with_quotes` path to call `load_fx_bars_with_quotes(..., strict=True, require_quotes=<fill_model.price == "quote">)`.
- [x] 1.7 Delete `rows.sort(key=_row_sort_key)`, `_row_sort_key`, and `_json_sort_value`; remove now-unused imports.

## 2. Drop the `data.strict` toggle

- [x] 2.1 Remove `strict: bool` from the data config model in `core/config.py` (loads are always strict; `extra="forbid"` now rejects a `strict` key).
- [x] 2.2 Remove `strict = true` from all in-repo configs: `examples/strategies/*.toml` and `runs/*.toml` (7 files).

## 3. Tighten `available_at`

- [x] 3.1 In `data_contract.py`, make `available_at` an unconditional required field with `error` severity in all modes (remove the SEARCH/VALIDATION branching at the `required_row_fields` mode check and the missing-`available_at` severity check).
- [x] 3.2 In `causality.py`, KEEP `_row_available_for_boundary` treating an absent `available_at` as visible (resolved deviation): a missing/invalid `available_at` is a hard row-contract error that fails the run at the row-contract gate, so the guard only prevents a provenance defect from masquerading as a false hidden-lookahead verdict; valid rows gate strictly on `available_at <= decision_time`.

## 4. Remove the now-dead `RowContractMode` (largest blast radius)

- [x] 4.1 Delete the `RowContractMode` enum and drop the `mode=` parameter from `required_row_fields` / `NormalizedRows.from_rows` in `data_contract.py`.
- [x] 4.2 Remove `row_contract_mode` threading from `core/data_loader.py`, `core/execution.py`, `validation/_pipeline.py`, `evaluation/_pipeline.py`, `runner/__init__.py`.
- [x] 4.3 Remove the runner `row_contract` config field and `RowContractStrictness` from `runner/config.py` (and `_runner_row_contract_mode`).
- [x] 4.4 Remove the `row_contract_mode` field emitted into artifacts/manifests (`runner/artifacts.py`, `validation/manifest.py`, `validation/_pipeline.py`).

## 5. Upstream contract smoke

- [x] 5.1 Add an env-gated smoke test (e.g. `RUN_QUANT_DATA_CONTRACT_SMOKE=1`) that calls `load_strategy_bars` + `load_strategy_universe_bars` (and FX/funding loaders where in use) against real `quant_data`, asserting required fields incl. `available_at`, tz-aware `timestamp`/`available_at`, `available_at > timestamp` for bars, `(timestamp, symbol)` universe order, and no duplicate keys; skipped when the flag is unset.
- [x] 5.2 Add a `make check-quant-data-contract` target running the smoke under the env flag in the `quant` env.

## 6. Tests

- [x] 6.1 Rewrite `tests/test_runner_data_loader.py`: patch `contract_loaders.load_strategy_bars` / `load_strategy_universe_bars` (single ordered frame; fakes MUST include `available_at`); drop the symbol-first sort assertion; keep the FX/crypto and purity/error-path cases updated to the new seams.
- [x] 6.2 Update the ~8 test files referencing `RowContractMode` / `row_contract` / `row_contract_mode` and the manifest/artifact shape (`test_data_contract.py`, `test_validation_*`, `test_evaluation_runner.py`, `test_runner_api_cli.py`, `test_repository_boundaries.py`).
- [x] 6.3 Update `tests/test_repository_boundaries.py` to allow/expect the `quant_data.contract_loaders` import at the boundary.
- [x] 6.4 Add/adjust a regression test that a `bars` row missing `available_at` now fails the row contract in quick-run (search) surface.

## 7. Docs

- [x] 7.1 Rewrite `docs/quant-data-upstream-contract.md`: remove the "open local follow-up" hedge; state bars/universe consume `contract_loaders` and FX/crypto consume the derived joins; upstream owns order + `available_at`; link the new upstream consumer docs (`quant-data/docs/consumer/{README,usage-guide,reference}.md`).
- [x] 7.2 Fix row-order / data-boundary claims and remove the dropped `strict` toggle + `row_contract` strictness from `README.md`, `FOUNDATION_LOCK.md`, and `docs/foundation-surfaces.md`.

## 8. Verify

- [x] 8.1 Run `conda run -n quant pytest -q` green; run the contract smoke once with `RUN_QUANT_DATA_CONTRACT_SMOKE=1` against real `quant_data`.
- [x] 8.2 Report changed-line counts (source / tests / docs / configs separated) and confirm no remaining references to `_row_sort_key`, `RowContractMode`, `row_contract`, or `data.strict`.
