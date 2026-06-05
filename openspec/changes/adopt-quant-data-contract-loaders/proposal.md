## Why

`quant-data` shipped a strategy contract layer (`quant_data.contract_loaders`) that
owns deterministic row ordering, the causal `available_at` stamp, strict window
validation, and duplicate-key rejection. `quant_strategies` still consumes the old
**raw exploratory layer** (`quant_data.loader.load_bars` / `load_universe_bars`) for
the `bars` kind. That raw layer returns bars **without `available_at`** and with **no
order guarantee**, which forced a local sort workaround and — more seriously — left
the hidden-lookahead guard silently disabled on real bars (causality falls back to
"always visible" when `available_at` is absent). Adopting the contract layer fixes the
root cause and lets us delete the band-aids instead of patching around them.

## What Changes

- Consume `quant_data.contract_loaders.load_strategy_bars` / `load_strategy_universe_bars`
  for the `bars` kind (causal-ready, ordered, window-validated, loud-fail on missing
  universe symbols). Keep the derived-join loaders (`load_fx_bars_with_quotes`,
  `load_crypto_perp_bars_with_funding`) for FX/crypto — they already carry `available_at` —
  called with `strict=True`.
- **BREAKING** Remove the local row-order sort (`rows.sort` / `_row_sort_key` /
  `_json_sort_value`) and collapse the dict-based universe handling. Row order is now
  the upstream contract `(timestamp, symbol)`; artifact hashes change and regenerate.
- **BREAKING** Make `available_at` an unconditional hard requirement: a missing or
  invalid `available_at` is a row-contract error in every surface and the run fails at
  the row-contract gate. Causality keeps gating valid rows strictly on
  `available_at <= decision_time`; a provenance defect surfaces as a row-contract
  failure, never as a (false) hidden-lookahead accusation.
- **BREAKING** Drop the `data.strict` config toggle — strategy-evidence loads are always
  strict. The `strict` key is removed from all configs.
- **BREAKING** Remove the now-dead `RowContractMode` (SEARCH/VALIDATION) and the runner
  `row_contract` strictness config field. Their only behavioral effect was gating
  `available_at` requiredness, which is now unconditional. The `row_contract_mode` field
  is removed from emitted artifacts/manifests.
- Add an opt-in real `quant_data` contract smoke (env-gated) plus a
  `make check-quant-data-contract` target, proving the upstream layer returns the shape,
  order, and `available_at` the boundary now assumes.
- Update docs (`docs/quant-data-upstream-contract.md`, `README.md`, `FOUNDATION_LOCK.md`,
  `docs/foundation-surfaces.md`) to state upstream ownership of order and `available_at`,
  drop the "open follow-up" hedge, and remove the dropped toggle/mode.

## Capabilities

### New Capabilities
- `data-boundary`: how `quant_strategies` consumes `quant_data` — loader selection per
  data kind, always-strict loads, upstream-owned row ordering preserved locally,
  unconditional causal `available_at` enforcement, consumer-side row-contract validation,
  and the upstream contract smoke.

### Modified Capabilities
<!-- None: openspec/specs/ has no existing baseline specs. -->

## Impact

- **Source**: `core/data_loader.py` (loader migration, proxy redesign, delete sort),
  `core/config.py` (drop `strict`), `data_contract.py` (unconditional `available_at`,
  remove mode), `causality.py` (gate valid rows on available_at), `core/execution.py`,
  `validation/_pipeline.py`, `evaluation/_pipeline.py`, `runner/__init__.py`,
  `runner/config.py`, `runner/artifacts.py`, `validation/manifest.py` (remove
  `row_contract_mode` threading + artifact field).
- **Configs**: `examples/strategies/*.toml`, `runs/*.toml` (remove `strict = true`).
- **Upstream dependency**: now imports `quant_data.contract_loaders` in addition to
  `quant_data.loader`; preserves the lazy-import purity invariant.
- **Artifacts**: hashes regenerate (row order change); `row_contract_mode` field removed
  from run/validation manifests — old result dirs are not migrated, they are regenerated.
- **Tests**: `test_runner_data_loader.py` rewrite, `test_repository_boundaries.py`, and
  ~8 files referencing `RowContractMode` / `row_contract` / `row_contract_mode`.
- **Not affected**: `NormalizedRows` consumer-side validation, FX/crypto per-symbol
  loops, the decision ontology, evaluation NAV/portfolio math.
