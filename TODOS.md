# Foundation Handoff TODOs

Compact active handoff for remaining foundation work — current open work only.
Development chronology, the causality-replay investigation, and review
disposition live in `HISTORY.md`; locked contracts, accepted debt, and
deferred-until-trigger items live in `FOUNDATION_LOCK.md`.

Read first:

- `PRD.md`
- `FOUNDATION_LOCK.md`
- `HISTORY.md`

## 1. Current State

Implemented public surfaces:

```text
S1 quick run                      -> diagnose one strategy version with engine-derived evidence
S2 mechanical evidence validation -> audit retained-candidate evidence integrity
S3 research evaluation            -> stateless frozen-candidate portfolio/economic/path evidence
```

The foundation contract — a target book in, one causal netted NAV book scored on
every surface, an envelope breach as a typed fail-closed verdict — is owned by
`FOUNDATION_LOCK.md`.

Current quick-run state:

- **S4** `quant-strategies run config.toml` and `quant_strategies.runner.run_config`
  return `RunResult`.
- **S5** Completed, feasible quick runs expose `RunResult.foundation` (authoritative
  scored NAV book) and the derived `RunResult.economics` attribution ledger; a
  fail-closed breach is on `RunResult.feasibility` with `failure_stage="feasibility"`.
- **S6** Quick-run configs support explicit causality policy:
  `off`, `emitted`, `strict`, `focused`, or `micro`.
- **S7** Committed candidate quick-run configs declare an explicit causality policy;
  Train / iteration diagnostics use `micro`. `causality_check="off"` runs no replay and is
  **non-scoreable by default** (typed `failure_stage="causality"`); the
  operator-frozen `[causality_policy] allow_unverified_scoring=true` re-admits `off` for
  profiling/debugging and is not an agent-editable `[output]` key.
- **S8** `micro` evidence is a Train/autoresearch replay annotation, not validation,
  evaluation, promotion, paper-trading, or live-trading evidence; focused evidence
  remains an advanced source-oriented quick-run mode.

Current validation/evaluation state:

- **S9** Validation and evaluation remain the stronger survivor/audit gates.
- **S10** Validation/evaluation require `validate_params`.
- **S11** Validation/evaluation default to complete causality replay and can be
  explicitly configured for bounded replay on large panels.
- **S12** Evaluation returns `EvaluationRunResult` and writes detailed Parquet traces
  through `pyarrow`.
- **S13** benchmark-relative metrics and user-defined scenario matrices are implemented;
  annualized/risk metrics remain guarded by annualization cadence and the
  minimum return-sample floor.

Standard verification:

```bash
make check
git diff --check
```

Run `conda run -n quant pytest -q` for final confidence when source, tests, or
public APIs changed.

## 2. Current Open Work

Open items are prioritized feasibility-first: an item is high priority when it
closes a path by which a quick run can score evidence that is not genuinely
tradeable, and lower when it only widens which strategies can be scored (an
unpriced or under-contracted class already fails closed). In order:

1. **§2.2 data-contract gate (in-repo half) — highest.** It is unwired today, so a
   strategy that needs a stronger data contract than the dataset provides
   (survivorship-free, complete corporate-action events) is scored with no
   fail-closed verdict. Wiring it removes a class of biased-but-passing evidence;
   the need is sharpest once equity research is active.
2. **§2.1 market-model follow-ons and §2.3 data-coverage — coverage, not
   correctness.** Every unpriced class already fails closed (`unfinanced_leverage`,
   `unpriced_short_financing`, `capacity_unsupported_volume_semantics`), so pull a
   class forward only when it becomes an active research direction; §2.3 items also
   need upstream backfill first.

### 2.1 Market-Model Follow-Ons

The netted book prices crypto-perp funding and the operator-frozen ADV
capacity/market-impact envelope today. The remaining asset-class frictions are
**in-repo modeling**: consume the already-public `quant_data` loaders and catalog
integrity contracts, and add a localized market-model term per `DataKind`
(mirroring `funding.py`). Every loader and integrity enum exists; where an item is
blocked it is on upstream **data coverage** (a `blocked`/empty dataset), tracked in
§2.3. Read `quant_data.catalog.DATASET_STATUS[dataset]["status"]` at runtime —
never hand-copy.

Until a class is priced, a net exposure > 1.0 for it stays a fail-closed
`unfinanced_leverage` verdict (crypto perp is modeled, so it is exempt).

- **Dividends — in-repo, data ready.** `load_dividends` returns `ticker, ex_date,
  pay_date, declared_date, record_date, cash_amount, dividend_type, frequency`;
  `dividends` is `usable_with_caveats` (2008→2026). ⚠️ Equity OHLCV is
  `split_dividend_adjusted`, so do **not** re-add dividends on adjusted prices
  (double-count); model explicit dividend cashflows only for the short side or
  raw-price use.
- **Equity short-borrow — modeling ready, data-coverage blocked (§2.3).**
  `load_equity_borrow_rates` returns `borrow_fee_rate, availability_status,
  shares_available, notional_available, source`, but `equity_borrow_rates` is
  `blocked` (no rows).
- **FX rollover/carry — modeling ready, data-coverage blocked (§2.3).**
  `load_forex_rollover_rates` (`long_base_rate`/`short_base_rate`, roll dates);
  `forex_rollover_rates` is `blocked`.
- **Margin financing on gross > 1 — modeling ready, data-coverage blocked (§2.3).**
  `load_margin_reference_rates` returns an annualized reference `rate`; the broker
  spread, compounding, and margin policy are this repo's operator-frozen envelope.
  `margin_reference_rates` is `blocked`.

ADV capacity is calibrated for supported bars and crypto perp. FX `volume` is
tick count, not notional (`forex-volume-is-tick-count`), so `forex_with_quotes`
ADV impact stays a fail-closed `capacity_unsupported_volume_semantics` verdict
until FX notional liquidity is calibrated.

### 2.2 Survivorship / corporate-action gate

In-repo and fields present now: `quant_data.catalog.DATASET_CONTRACTS[dataset]`
exposes machine-readable `adjustment_status`, `survivorship_status`,
`corporate_action_event_status`, and `caveat_ids`, and
`quant_data.readiness.validate_dataset_window` is the gate. In-repo work: read
these to fail-closed when a strategy needs a stronger contract than the dataset
provides (equity is `not_survivorship_free`, `events_partial`). The PIT
`available_at < timestamp` row guard already ships. Delisting/rename
reconstruction uses `load_ticker_events`, whose `ticker_events` dataset is
`blocked` (no rows) → that half waits on data coverage (§2.3).

### 2.3 Upstream `quant-data` data-coverage dependencies

No outstanding upstream contract/field requests — every loader and the catalog
integrity enums already exist. The only remaining upstream dependency is **data
coverage**: the loader and schema exist but the dataset is `blocked` (zero rows),
so the corresponding in-repo friction cannot be priced until upstream backfills
it. Read `DATASET_STATUS[dataset]["status"]` at runtime and treat `blocked` as
"modeling ready, data pending." Raise backfill priority with Season.

| Blocked dataset | Loader | Unblocks (when backfilled) |
|---|---|---|
| `equity_borrow_rates` | `load_equity_borrow_rates` | equity short-borrow pricing |
| `forex_rollover_rates` | `load_forex_rollover_rates` | FX carry/rollover pricing |
| `margin_reference_rates` | `load_margin_reference_rates` | margin financing on gross > 1 |
| `ticker_events` | `load_ticker_events` | delisting/rename → survivorship reconstruction |

## 3. Locked Direction

Locked contracts that should not be reopened without a regression or documented
trigger are owned by `FOUNDATION_LOCK.md` (Locked Contracts, Accepted Debt,
Deferred Until Trigger). Read it as the source of truth.

## 4. Contained Residuals

Preserve these contained residuals unless they become active work:

- **R1** `_is_true_flag` coercion.
- **R2** `not_evaluated` soft-stop.
- **R3** causality's missing-`available_at` fallback.

## 5. Deferred Work

- **Restore the `researched/` archive-boundary test** once Season's active work in
  `researched/` settles (or relocate the artifacts). The repo currently does not
  enforce that boundary; the other repository-boundary tests (loop-memory markers,
  archive-pointer scan) are unchanged. Background: `HISTORY.md`.
- The other deferred-until-trigger items (mid-pipeline artifact I/O, independent
  netted-book cross-check, validation/evaluation source output paths) are owned by
  `FOUNDATION_LOCK.md`.

## 6. Stale-Reference Checks

When updating foundation docs, confirm cross-references still resolve:

```bash
rg -n "FOUNDATION_LOCK|HISTORY|accepted_debt|deferred_until_trigger|quick run|validation run|evaluation run" \
  FOUNDATION_LOCK.md HISTORY.md TODOS.md docs/reviews/README.md
```
