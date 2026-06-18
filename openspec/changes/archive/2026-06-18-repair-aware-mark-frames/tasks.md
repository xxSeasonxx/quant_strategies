## 1. Upstream probe and dataset mapping

- [x] 1.1 Probe-load the mark frame over the real outage window — base `crypto_perp_1min` returns clean (8 gaps `repairable_minor`, ≈19–20 min, nothing `unrepairable_gap`); the derived `crypto_perp_1min_with_funding` is rejected by the strict loader's freshness validation, fixing design D3
- [x] 1.2 Add the `data.kind → base mark dataset` resolution in `core/data_loader._mark_dataset`, gated by `datasets_with_regular_series_repair`

## 2. Data layer: load and carry the mark frame

- [x] 2.1 `load_data` loads the mark frame via `load_strategy_universe_mark_frame(..., strict=True, return_summary=True)` over the same effective load window
- [x] 2.2 Subsumed — no trivial frame needed. A no-repair dataset yields an empty mark frame; valuation falls back to the signal index and a within-window gap still fails closed (`missing_mark`), which is the correct no-policy behavior
- [x] 2.3 `LoadedData` carries `mark_rows` and a compact `mark_repair` summary
- [x] 2.4 An upstream unrepairable-gap (or freshness) error surfaces as a typed `DataLoadError` — fail-closed at the data-load stage before any walk

## 3. Execution: thread the mark frame without breaking purity

- [x] 3.1 `StrategyExecutionResult` carries `mark_rows` + `mark_repair`
- [x] 3.2 `generate_decisions` receives only signal `strategy_rows`; covered by `test_execute_strategy_run_carries_mark_frame_without_exposing_it_to_strategy`

## 4. Engine: frame separation in `_RowIndex` and the builder

- [x] 4.1 `_RowIndex` gains a distinct `mark_by_key` index built from the mark frame
- [x] 4.2 `mark_at`/`bar_at` resolve through `_valuation_row` (signal bar, else repair mark, else `missing_mark`); `row_at` (fills, capacity, funding) stays signal-only
- [x] 4.3 `build_portfolio_foundation` and `walk_portfolio_book` take a defaulted `mark_rows`; a true miss still raises typed `missing_mark`
- [x] 4.4 The walk records consumed repaired marks `(symbol, timestamp)` for the audit trail

## 5. Runner and backends: pass the mark frame through

- [x] 5.1 `runner._build_portfolio_foundation` passes `mark_rows` + `mark_repair` into `build_portfolio_foundation`
- [ ] 5.2 Deferred (out of scope, see design): threading the mark frame through `validation`/`evaluation` backend protocols. They default to `mark_rows=()` and behave exactly as today — no regression. Blocking case is the quick-run path

## 6. Audit output

- [x] 6.1 `RunPortfolioFoundation.mark_repair` carries the upstream summary + consumed-mark provenance; surfaced via `summary_payload`
- [x] 6.2 Placement decided: `summary_payload` (present only when a repair was available or consumed); compact-default placement left as an open question

## 7. Tests

- [x] 7.1 Held position across a synthetic per-symbol repairable gap is valued at the repaired mark and the walk completes (`test_open_position_marked_from_repair_frame_across_gap`)
- [x] 7.2 A risk-rule position at a flat repaired bar does not fire; the barrier resolves on the next observed bar (`test_repaired_stop_position_does_not_fire_on_flat_bar_then_resolves_next_observed`)
- [x] 7.3 `row_at` (capacity/fills/funding) never reads a repaired row (`test_valuation_reads_repair_frame_but_execution_stays_signal_only`)
- [x] 7.4 A held bar with neither signal nor mark row raises typed `missing_mark` (existing `test_open_position_requires_mark_on_every_shared_multi_symbol_timestamp`)
- [x] 7.5 An unrepairable-gap window fails at the data-load stage (`test_unrepairable_mark_gap_fails_closed_at_data_load`)
- [x] 7.6 The `mark_repair` audit records each consumed repaired mark (`test_foundation_audits_consumed_repaired_marks`)
- [x] 7.7 `data-boundary`: the mark loader is called with the base dataset, same window, `strict=True` (asserted in the load-window test)
- [x] 7.8 Purity: the strategy never receives the mark frame (`test_execute_strategy_run_carries_mark_frame_without_exposing_it_to_strategy`)

## 8. Candidate verification and docs

- [x] 8.1 Over `2025-08-28..2025-08-31`, `build_portfolio_foundation` builds feasible with no `missing_mark` and audits the consumed repair `DOGE-PERP @ 06:18`. (The full runner trips an independent `hidden_lookahead` causality gate on that window — unrelated to marking)
- [x] 8.2 Docs updated: design D1/D3/D6 reconciled with the implementation; this task list; `HISTORY.md` entry
- [x] 8.3 `ruff format`/`check` clean on changed files; full suite green; changed-line counts reported
