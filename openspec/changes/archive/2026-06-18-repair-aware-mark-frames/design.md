## Context

The book walk in `core/portfolio_foundation.py` iterates `_RowIndex.timestamps` — the
**union** of every symbol's timestamps from the signal row index. At each bar it marks
every open position. A per-symbol gap (a bar one held symbol is missing, while another
symbol observed that minute and so put it in the union grid) makes `mark_at` miss the
exact-key lookup and raise `missing_mark`, killing the whole run.

`_RowIndex` is built from one frame that serves two roles:

- **Execution** — `row_at` for fills (`_flatten`), capacity/ADV (`:1743`), funding
  (`_apply_funding`), and signal projection. Needs a *tradable* price; a missing bar is a
  genuine error.
- **Valuation** — `mark_at` (NAV in `_equity_at_mark`, exposure in `_exposures`) and
  `bar_at` (barrier *detection*). Needs a *mark-eligible* price; a missing bar does not
  mean the position vanished.

Upstream `quant_data` already separates these. `load_strategy_universe_mark_frame(strict=True)`
returns the complete grid — observed rows (`is_repaired=False`) plus policy-bounded
`previous_close_mark` carry-forward rows (`is_repaired=True`, `tradable=False`,
`signal_eligible=False`, `mark_eligible=True`, flat OHLC `open=high=low=close=prev_close`,
`volume=0`) — and **raises at load** when a gap exceeds the dataset's
`max_repairable_gap_minutes` (30 for crypto). Repair policy is enabled for `crypto_perp_1min`,
`crypto_perp_1min_with_funding`, `crypto_spot_1min`, and `forex_1min`.

Constraints (from `CLAUDE.md` / `PRD.md`): repair belongs upstream in `quant_data`, not the
engine; envelope/feasibility failures are typed and fail-closed, never clamped or silently
`None`; no legacy/fallback code paths; strategy code stays pure.

## Goals / Non-Goals

**Goals:**

- Value an open position across a policy-repairable data gap without crashing, so a
  full multi-symbol Train window scores end to end.
- Keep the execution surface (fills, capacity, funding, signals) strictly on observed,
  tradable rows.
- Preserve fail-closed: an unrepairable gap stops the run with a typed error; the engine
  never invents a price.
- Emit an `is_repaired` audit trail for every synthetic mark consumed in scored P&L.
- Keep repair entirely upstream; the engine only *consumes* the upstream mark frame.

**Non-Goals:**

- No in-engine carry-forward or in-engine repair logic.
- No repair of the signal frame; signals/fills/funding/capacity never read repaired rows.
- No change to the walk grid beyond the existing signal union. A *per-symbol* gap (a bar
  some other symbol observed) is on the grid, so it is visited and the held symbol is marked
  from the repair frame — the case this change fixes. A *universe-wide* gap (no symbol
  observed the minute) stays off the grid and produces no NAV point, so a fully-synchronized
  outage collapses into one inter-bar return — this distorts at-risk-bar counts and
  Sharpe/vol inputs, but it is pre-existing walk behavior, unchanged here, and does not
  affect the staggered real outage. Expanding the walk to the full repaired calendar (a
  separate valuation timeline) is out of scope.
- No new strategy-facing API; strategies never see the mark frame.

## Decisions

### D1 — Separate frames by purpose; valuation has its own source

`_RowIndex` holds a second key map for the mark frame. Valuation (`mark_at`, `bar_at`)
resolves through `_valuation_row`: the observed signal bar when present, else the
repair-aware mark, else a fail-closed `missing_mark`. Execution (`row_at` — fills,
capacity, funding) is untouched and stays strictly on the signal index.

- On an observed bar the signal close and the mark close are the **same number** (the
  mark frame's observed rows come from the same source), so reading the signal bar is a
  trivially-equal fast path; the mark index is consulted only on a gap. This is the
  valuation source, not a "signal-is-primary" patch — the category-error fix is that
  valuation reads have a mark source at all and execution reads never do. It is also
  strictly robust to any coverage divergence between the two upstream loaders.
- **Why not in-engine carry-forward** (synthesize the last close on a miss): reinvents
  repair inside the engine with **no gap-size guardrail** — it would silently mark across
  a multi-day outage, the exact fail-open the foundation exists to prevent — and loses
  provenance (`repair_source_timestamp`, `repair_gap_minutes`).
- **Why not repair the signal rows**: violates `tradable=False`/`signal_eligible=False` and
  corrupts fills, funding, volume, and signals.

A global `row_at` fallback is explicitly rejected: it would feed `volume=0` repaired rows
into ADV participation (`:1743`).

### D2 — `bar_at` reads the mark frame too (not a separate decision)

Barrier *detection* asks "did price touch the level?" — a valuation read. The *fill* is
computed from the level and bar open (`_barrier_fill_price`), not a fresh row read. So
`bar_at` resolves against the mark index for the same reason `mark_at` does. On a repaired
flat bar (`high=low=close=prev_close`) a barrier cannot fire spuriously; it resolves on the
first observed bar, with the existing gap-through fill protection. This is the honest
semantics: no intrabar data during an outage ⇒ no intrabar fill during the outage.

**Trade-off:** intrabar stop protection is suspended across a repaired gap; a stop fires one
bar late (at the first observed bar, possibly gapping through the level). The committed
funding-crowding config declares no risk rule today, but the strategy supports stops, so
covering `bar_at` now prevents a latent re-crash the instant a variant adds one.

### D3 — Mark dataset = the base OHLCV dataset under the signal frame

Load the mark frame from the **base** OHLCV dataset, gated by
`supports_regular_series_repair`. For `kind=crypto_perp_funding` that is the base
`crypto_perp_1min` (not the derived `crypto_perp_1min_with_funding`); for `kind=bars` it is
`data.dataset` (already a base dataset). The mark loader returns bar columns only, which is
correct for valuation.

- **Why base, not the derived signal dataset**: the strict mark loader validates the
  window via a freshness lookup (`get_symbol_data_end`) that only supports base OHLCV
  datasets — passing the derived `crypto_perp_1min_with_funding` raises
  `Unsupported dataset for freshness lookup`. Base bars are also a superset of the derived
  signal grid (the funding join adds columns, not bar timestamps), so
  `mark grid ⊇ signal grid` and valuation provably covers every walked timestamp.
- **Mapping location**: one explicit `kind → base mark dataset` resolution in
  `core/data_loader.py`, never hardcoded in the runner. `forex_with_quotes` has no mark
  frame today: its signal dataset (`forex_1min_with_quotes`) lacks a repair policy. A
  sibling (`forex_1min`) has one and is freshness-supported, so FX could be mapped the
  same way later — left as an open question, not silently mapped.

### D4 — Absent repair modeled as a trivial mark frame, not optional/`None`

For a dataset with no repair policy the loader still produces a mark frame: the signal OHLC
re-exposed with `is_repaired=False`. `build_portfolio_foundation` therefore always receives a
real mark frame and `_RowIndex` always has a distinct mark index — no optional parameter, no
`None`, no collapse branch. A within-window gap on a no-repair dataset still raises
`missing_mark` at walk time, which is correct: no policy means any gap is genuinely
unscoreable.

This keeps fail-closed at two principled points: **load time** for repair-capable datasets
(the policy boundary is the refusal point) and **walk time** for no-repair datasets (any gap
is fatal at first touch).

### D5 — `is_repaired` audit rides the frame into the foundation payload

The mark frame is loaded with `return_summary=True`; the `RegularSeriesRepairSummary`
(repaired-row count, affected symbols, classification counts, gaps) is carried alongside it.
The walk additionally records the `(symbol, timestamp)` of repaired marks it actually
consumes in P&L — the stronger statement the validation requires ("every synthetic mark used
in P&L"). Both surface in a compact `mark_repair` block in the diagnostic foundation payload.
This is a first-class output, not a silent rescue.

### D6 — Threading: load in the data layer, carry through execution, consume in the runner

`load_data` (`core/data_loader.py`) performs the second load using the same resolved engine
and the same effective load window (including the `load_end` exit buffer) so buffer exits get
marks. `LoadedData` carries `mark_rows` + repair summary; `StrategyExecutionResult` carries
them through; `generate_decisions` never receives them (purity). The runner's
`_build_portfolio_foundation` passes the mark frame to `build_portfolio_foundation`.

**Scope: quick-run path only.** `build_portfolio_foundation` and `walk_portfolio_book` take a
defaulted `mark_rows` parameter, so the `validation` and `evaluation` backends compile and
behave exactly as today (`mark_rows=()` → no repair frame, gap on a fold fails closed as
before — no regression). Threading the mark frame through those backend protocols is a
clean follow-on (it touches the `PreparedPortfolioInputs` contract and every test fake) and
is deliberately out of scope here: the blocking case is the quick-run Train baseline.

## Risks / Trade-offs

- **Double load of overlapping source data** (signal load + mark load both hit the
  with-funding table) → Accepted: deriving marks from already-loaded rows would pull repair
  into the engine, breaking the boundary. A combined upstream loader is a future
  `quant_data` request, not this change.
- **Stop fires one bar late across a repaired gap** (D2) → Honest given no intrabar data
  during an outage; gap-through fill protection already handles the worst case. Documented in
  the foundation spec so it is a known, audited behavior.
- **Coverage skew if a future change loads marks from a different dataset than signals**
  (D3) → Mitigated by the same-dataset rule and a load-time check that the mark grid covers
  the signal grid.
- **`causality_check = "micro"` validity** → Unaffected: decisions derive from signal rows
  only; marks touch NAV valuation, which is not a decision. Strict replay stays valid.
- **Repaired rows leaking into capacity/funding** → Prevented structurally: only `mark_at`/
  `bar_at` read the mark index; `row_at`, ADV prefix, and funding remain signal-only.

## Open Questions

- **FX mark dataset (D3):** map `forex_with_quotes` valuation to base `forex_1min` (repair
  enabled, freshness-supported) or leave FX without a repair frame? FX has no observed
  gap-driven failure yet, so no repair frame is the low-risk default for now.
- **Audit placement (D5):** the `mark_repair` block surfaces in the foundation
  `summary_payload`; confirm whether it should also appear in any compact default artifact
  or only the diagnostic profile.

**Resolved during implementation:**

- **Mark dataset (D3):** a probe over the real outage window confirmed base
  `crypto_perp_1min` returns clean — 8 gaps all `repairable_minor` (≈19–20 min, within the
  30-min policy), nothing `unrepairable_gap`. The derived `crypto_perp_1min_with_funding`
  is rejected by the strict loader's freshness validation, so base is the correct source.
- **End-to-end (8.1):** over `2025-08-28..2025-08-31`, the foundation builds feasible with
  no `missing_mark`, and the audit records the consumed repair `DOGE-PERP @ 06:18` — the
  named blocking case. (The full runner trips an independent `hidden_lookahead` causality
  gate on that window, unrelated to marking.)
