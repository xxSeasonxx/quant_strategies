## Why

The book walk values every open position by reading a price off the **signal/execution**
row index. When a held symbol is missing a bar that the walk still visits (because another
symbol observed that minute), valuation raises `missing_mark` and a full multi-symbol Train
baseline dies. The root cause is a category error: one frame is forced to answer two
different questions — *can I trade here?* (execution) and *what is this worth here?*
(valuation). Upstream `quant_data` already separates these (`tradable`/`signal_eligible`
vs. `mark_eligible`) and ships a bounded, provenance-carrying repair-aware mark loader; the
engine has not caught up.

## What Changes

- The portfolio foundation consumes **two** frames: the existing raw, causal
  signal/execution frame (fills, sizing, capacity, funding, signals) and a dedicated
  repair-aware **mark frame** (valuation only) loaded over the same full execution window.
- Valuation reads the mark frame: `_RowIndex.mark_at` (NAV/exposure) and `_RowIndex.bar_at`
  (barrier *detection*) resolve against the mark index. Execution reads
  (`row_at` for fills, capacity, funding, signals) stay strictly on the signal index — a
  `mark_eligible` repaired row (`volume=0`, `tradable=False`) MUST NOT reach them.
- The mark frame is loaded through the upstream repair-aware contract loader
  (`load_strategy_universe_mark_frame`, `strict=True`). An unrepairable gap fails closed at
  the **data-load stage**, before the walk — the engine never invents a price and never
  marks a half-valued book.
- The foundation emits an `is_repaired` audit trail: every synthetic mark consumed in P&L
  is recorded with its provenance, alongside the upstream repair summary.
- The strategy decision step never receives the mark frame (purity preserved).

No legacy path: marking moves to the mark frame outright; there is no per-lookup
"signal-then-mark" fallback ladder. For datasets with no repair policy the loader supplies
a trivial mark frame (signal OHLC, all `is_repaired=False`), so "valuation has its own
frame" holds universally and a within-window gap there still fails closed at walk time.

## Capabilities

### New Capabilities

(none — the affected contracts already have owning specs)

### Modified Capabilities

- `data-boundary`: a new requirement that the valuation/mark frame is loaded through the
  upstream repair-aware contract loader (strict, same load window as the signal frame), and
  that consuming upstream repair is distinct from — and does not relax — the existing
  "consumer MUST NOT repair locally" rule.
- `quick-run-portfolio-foundation`: a new requirement that valuation resolves against a
  dedicated mark frame separate from the execution frame; that repaired marks are
  valuation-only and never feed fills, capacity, funding, or signals; that an unrepairable
  gap is a fail-closed data-load failure; and that an `is_repaired` audit trail is emitted
  for every synthetic mark consumed in scored P&L.

## Impact

- **Code**: `core/data_loader.py` (load + carry the mark frame and its repair summary),
  `core/execution.py` (`StrategyExecutionResult` carries the mark frame; never passed to
  `generate_decisions`), `core/portfolio_foundation.py` (`_RowIndex` gains a mark index;
  `mark_at`/`bar_at` read it; `build_portfolio_foundation` takes the mark frame; new audit
  output), `runner/__init__.py` (`_build_portfolio_foundation` threads the mark frame),
  and the `validation`/`evaluation` backends that call `build_portfolio_foundation`.
- **Upstream dependency**: adds consumption of
  `quant_data.contract_loaders.load_strategy_universe_mark_frame`
  (with `return_summary=True`); mark dataset = the signal dataset when it supports
  regular-series repair, else no repair frame.
- **Artifacts**: the diagnostic foundation payload gains a compact `mark_repair` block
  (repaired-mark count, affected symbols, classification counts, consumed-mark provenance).
- **Validation unlocked**: a strict-causal (`causality_check = "micro"`) baseline for the
  funding-crowding reversal thesis on the full multi-symbol universe and full Train window.
