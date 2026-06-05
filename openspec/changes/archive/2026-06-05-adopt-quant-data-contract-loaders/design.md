## Context

`quant-data` now exposes two layers. The **strategy contract layer**
(`quant_data.contract_loaders`: `load_strategy_bars`, `load_strategy_universe_bars`,
`load_strategy_fx_quotes`, `load_strategy_funding_events`) is the documented
strategy/backtest boundary: `strict=True` by default, deterministic order, a synthesized
causal `available_at` (single upstream policy), window validation, and duplicate-key
rejection. The **raw exploratory layer** (`quant_data.loader`) is for EDA and also hosts
the precomputed derived joins (`load_fx_bars_with_quotes`,
`load_crypto_perp_bars_with_funding`).

`quant_strategies/core/data_loader.py` currently loads the `bars` kind through the raw
layer (`load_bars` / `load_universe_bars`). Verified in upstream source: `load_bars` →
`query_market_bars` (`market_store.py:305`) selects **no `available_at`**; only
`contract_loaders._prepare_bar_frame:190` adds it. So real bars reach the local pipeline
with no `available_at` and no order guarantee. That produced a local
`rows.sort(key=_row_sort_key)` band-aid (which sorts symbol-first, fighting the upstream
`(timestamp, symbol)` order, locked by `test_runner_data_loader.py:123`) and left the
causal guard inert on real bars: `causality.py:447-453` returns "visible" when
`available_at` is `None`, and `data_contract.py:256` downgrades missing `available_at` to
a warning in SEARCH mode.

Constraint from Season: **no fallback code, no legacy compatibility** — tighten fully and
delete the tolerant branches rather than keep them as defense-in-depth. FX and crypto
already consume the derived joins, which carry `available_at`, so only the bars/universe
path is causally deficient.

## Goals / Non-Goals

**Goals:**
- Load `bars`/universe through `contract_loaders` so `available_at`, ordering, and window
  validation come from the upstream contract, not local code.
- Delete every workaround the raw layer forced: the local sort, the dict-universe
  handling, the SEARCH-mode `available_at` leniency, and the causality fallback.
- Make `available_at` an unconditional hard requirement across all surfaces.
- Always load strictly; remove the `data.strict` toggle.
- Remove the now-behaviorally-dead `RowContractMode` and its threading/artifact field.
- Prove the consumed upstream boundary with an opt-in real smoke.

**Non-Goals:**
- Moving FX/crypto to contract loaders (no contract loader returns the combined
  bars+quotes / bars+funding frame; the derived joins are the correct source).
- Changing `NormalizedRows` consumer-side validation responsibilities.
- Adopting new upstream knobs (`as_of`, `trading_days_only`, `max_lag_days`) — separate opportunity.
- Migrating existing result artifacts — they regenerate.

## Decisions

### Decision 1: Adopt `contract_loaders` for bars/universe; keep derived joins for FX/crypto
Bars/universe move to `load_strategy_bars` / `load_strategy_universe_bars`. The contract
signatures are positionally compatible with today's calls; universe returns **one frame
ordered `(timestamp, symbol)`** instead of a `{symbol: frame}` dict, so `_rows_from_universe`
collapses into a single `_rows_from_frame`. FX/crypto keep `load_fx_bars_with_quotes` /
`load_crypto_perp_bars_with_funding` called with `strict=True`.
**Alternative considered:** route everything through contract loaders — rejected because
the combined bars+quotes / bars+funding frames the FX/crypto strategies consume only exist
in the derived-join loaders; splitting and re-joining locally would violate the "no local
join" boundary rule.

### Decision 2: `_LazyLoaderProxy` sources from two modules, preserving import purity
The proxy must expose `load_strategy_bars` / `load_strategy_universe_bars` (from
`quant_data.contract_loaders`) and `load_fx_bars_with_quotes` /
`load_crypto_perp_bars_with_funding` (from `quant_data.loader`). The lazy-import purity
invariant — importing `quant_strategies.core.data_loader` must not import `quant_data`
(`test_runner_data_loader.py:80`) — and per-function test override seams MUST be preserved
for both modules.
**Alternative considered:** two separate proxy objects (`contract_loaders` + `loader`).
Either a single attribute→module map or two proxies is acceptable; the build step picks the
simpler one that keeps both override seams and the purity test green.

### Decision 3: Delete local row ordering
With order owned by the contract, `rows.sort` / `_row_sort_key` / `_json_sort_value` are
removed. For multi-symbol FX/crypto the per-symbol loop concatenates each
internally-sorted frame in deterministic config-symbol order; execution indexes per
`(symbol, timestamp)` so global interleaving does not affect results — only the
`normalized_rows_sha256`, which regenerates.

### Decision 4: Unconditional `available_at` (row contract is the enforcement point)
`available_at` becomes a required field with `error` severity in all modes; a missing or
invalid value is a hard row-contract error and the run fails at the row-contract gate.
Causality replay (`_row_available_for_boundary`) keeps treating a row with absent
`available_at` as visible — NOT a tolerance, but a deliberate guard: such a row has already
failed the row contract, so the run fails there with a clear data-quality message, and the
guard ensures a provenance defect is never misreported as a (false) hidden-lookahead
verdict. For valid rows visibility is strict (`available_at <= decision_time`). The branch
is unreachable in any run whose row contract passes — validation/evaluation enforce a passed
row contract before replay, and the quick run fails at its row-contract gate.
**Resolved deviation:** the initial plan was to delete this branch; during implementation
that was found to misreport provenance defects as false `hidden_lookahead_suppression_detected`
verdicts, so the branch is kept and the spec encodes the corrected behavior ("Provenance
defects fail at the row contract, not as lookahead").

### Decision 5: Drop the `data.strict` toggle
`core/config.py` removes `strict`; loads are always strict. With `extra="forbid"`, configs
carrying `strict = true` must drop the key — all 7 in-repo configs are updated in this change.

### Decision 6 (largest blast radius — read-gate item): Remove `RowContractMode` entirely
`RowContractMode` (SEARCH/VALIDATION) and the runner `row_contract`
(`RowContractStrictness`) config field exist **only** to gate `available_at` requiredness
(`data_contract.py:480`, `:256`). Once `available_at` is unconditional (Decision 4), the two
modes are behaviorally identical, so under the no-legacy directive the enum, the config
field, the `row_contract_mode` parameter threaded through `data_loader` / `execution` /
`validation/_pipeline` / `evaluation/_pipeline` / `runner`, and the `row_contract_mode`
field emitted into run/validation manifests are all removed.
**This is the one decision a reviewer should consciously confirm**, because it (a) removes a
public runner config field and (b) changes emitted artifact shape. Both are acceptable per
the no-legacy directive and the project rule to regenerate rather than preserve old artifact
shapes — but it is the largest-surface part of the change and is cleanly separable if it must
be deferred.
**Alternative considered:** keep `RowContractMode` as a now-inert label — rejected: a
behaviorally-dead enum threaded through 8 modules is exactly the legacy cruft this change
removes.

### Decision 7: Opt-in real `quant_data` contract smoke
A new env-gated smoke (mirroring `RUN_VECTORBTPRO_SMOKE`, e.g.
`RUN_QUANT_DATA_CONTRACT_SMOKE=1`) plus a `make check-quant-data-contract` target asserts the
boundary guarantees against live `quant_data`. The fakes-only loader tests are precisely why
the `available_at` gap went unnoticed; this proves the real contract without materializing data.

## Risks / Trade-offs

- **Artifact hashes/shape change** → regenerate; project rule already favors regeneration over
  artifact back-compat. No migration of old result dirs.
- **Removing a runner config field (`row_contract`) and `data.strict`** → BREAKING for any
  external config; in-repo configs are updated here and the breakage is loud (`extra="forbid"`).
- **Contract-loader strictness raises where the raw layer clamped** (e.g. window before clean
  start, missing universe member) → intended: silent coverage gaps become loud failures.
- **Smoke requires a live database** → mitigated by env-gating; default unit run stays offline.
- **`RowContractMode` removal touches ~8 source + ~8 test files** → larger diff, but mechanical;
  isolating it as the final task group keeps it reviewable and deferrable.

## Migration Plan

1. Migrate `core/data_loader.py` (loaders + proxy + delete sort/dict-universe).
2. Tighten `available_at` and remove the causality fallback.
3. Drop `data.strict`; update the 7 configs.
4. Remove `RowContractMode` threading + artifact field.
5. Add the contract smoke + Make target.
6. Update tests and docs.
7. Run `conda run -n quant pytest -q`; regenerate any committed example artifacts if present.
No runtime rollback concern (advisory research tool); revert is a git revert + artifact regen.

## Open Questions

- None blocking. Decision 6's artifact-field removal is the item to confirm at the read gate.
