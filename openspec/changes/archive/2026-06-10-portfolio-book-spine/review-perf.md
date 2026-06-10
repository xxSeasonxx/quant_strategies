# portfolio-book-spine — Performance Review (Claude `/review`, performance lens)

**Scope:** `git diff main...portfolio-book-spine`, performance only. Hot path is the
single causal netted-book walk in `core/portfolio_foundation.py`, with the evaluation
projection in `evaluation/_spine_metrics.py` + `evaluation/spine_backend.py`.

**Method:** read the walk + statistics pass; verified the import wall; profiled and
scaled a representative `build_portfolio_foundation` run (the ~1s Train path) from 2k →
1,000,000 rows on conda env `quant`. Read-only; no code changed.

---

## VERDICT

**PASS — the ~1s Train-path budget is preserved and the architecture is a net win.**
At the PRD G6 ceiling (1M rows, single strategy) the authoritative **2-scenario**
`build_portfolio_foundation` completes in **~3.6 s** wall, and per-row cost is **flat**
(3.6–4.6 µs/row) from 2k to 1M rows — **no O(n²) regression** introduced by the netted
walk. The old per-trade `screen`/`gate_screen` path and the two heavy vectorbtpro
backends (~1.5k LOC of pandas/vbt re-pricing) are deleted, so the surface is genuinely
lighter than before. The **import wall holds** (no pandas/numpy/vectorbtpro pulled by
`import quant_strategies.runner`).

There is **one clear, low-risk optimization** worth ~20–25% of walk time: the
per-lookup error message in `_RowIndex.mark_at` is built **eagerly on the happy path**,
so `datetime.isoformat()` is the single hottest function in the profile despite never
being shown to a user. Fixing it is a 2-line change. A second, structural item (3×
re-marking per bar) is a real redundancy but lower value on the Train path because open
position counts are typically small; it matters more on the heavy evaluation surface.

Representative numbers (conda `quant`, warm, min of 3, oscillating marks, gross within
budget):

| rows | decisions | 2-scenario build | `_RowIndex` build | µs/row |
|---:|---:|---:|---:|---:|
| 2,000 | 20 | 8.9 ms | 0.6 ms | 4.43 |
| 10,000 | 40 | 46 ms | 3.2 ms | 4.60 |
| 50,000 | 80 | 202 ms | 15.7 ms | 4.04 |
| 100,000 | 160 | 363 ms | 31.6 ms | 3.63 |
| 200,000 | 160 | 760 ms | 66 ms | 3.80 |
| 500,000 | 400 | 1.78 s | 182 ms | 3.56 |
| 1,000,000 | 800 | 3.63 s | 350 ms | 3.63 |

Flat µs/row across 500× scale = linear. `tests/test_performance_regressions.py` → **5
passed in 1.64s**.

---

## Severity-ranked findings

| Severity | Location | Issue | Impact (measured) | Fix |
|---|---|---|---|---|
| **Major** | `core/portfolio_foundation.py:544` (`mark_at`), reinforced at `:540` (`row_at`) | Error message `f"missing_mark:{symbol}:{timestamp.isoformat()}"` is **eagerly constructed and passed into `_positive_float` on every successful lookup**. `isoformat()` is the #1 hot function in the profile. | **~20–25% of walk time.** Profile @1M rows: `isoformat` = 1.82 s of 8.5 s (21%), all from this path (2.67M calls). Isolated microbench: eager message = 2.01 s vs 0.24 s deferred → **1.77 s wasted (88% of that loop)**. | Defer message construction to the failure branch only. `mark_at`: read `close`, and only build the `missing_mark:...` string inside the raise. Same for `row_at`'s `KeyError` branch (already lazy — keep) and ensure `mark_at` doesn't pre-format. Pure happy-path win, zero behavior change. |
| **Minor** | `core/portfolio_foundation.py:664-714` — `_walk_book` per bar | Each open position's mark is fetched **3× per bar**: risk overlay (`mark_at`, :668), `_equity_at_mark` for NAV (:711), `_exposures` (:712); +1 more on decision bars (`_equity_at_mark`, :684). Each fetch re-does the `by_key` tuple-key lookup + `_positive_float`→`_finite_float` (`isinstance`+`float`+`isfinite`). Marks are identical within a bar. | Measured ~267 `mark_at`/bar ≈ **3× the open-position count**; `_equity_at_mark`+`_exposures` together ≈ 4.5 s cumtime @1M (overlapping with the Major row above). Low *fractional* value once the Major fix lands, and small in absolute terms when few positions are open (typical Train case). | Mark each open position **once per bar** into a small `dict[str,float]` (or compute `signed_qty*mark` once) and feed both NAV (`signed_qty*mark - cost_basis`) and exposures (`signed_qty*mark`) from it; risk overlay needs the raw mark, which the same pass produces. Collapses 3 scans → 1. Worth doing **with** the Major fix since they touch the same code. |
| **Minor** | `core/portfolio_foundation.py:433-434` via `evaluation/spine_backend.py:137` (`_walk_for_scenario`) | `walk_portfolio_book` rebuilds `_RowIndex` **and** `_DecisionPlan` on every call. Evaluation fans out **S cost/fill scenarios per window** and calls `run_prepared` → `walk_portfolio_book` once each, so `_RowIndex` (full row sort + 3 dicts) is rebuilt S times per window even though `PreparedPortfolioInputs` already holds the window-constant rows/decisions. `build_portfolio_foundation` (Train) correctly builds them **once** and shares across both scenarios — so the Train path is unaffected. | `_RowIndex` build ≈ **10% of one walk** (350 ms @1M). On the **heavy** evaluation surface only (NOT the ~1s Train path). For the realistic crypto-perp case (a few scenarios) it is a few extra index builds per window — measurable, not dominant. | Hoist `_RowIndex`/`_DecisionPlan` construction into `prepare_inputs` (store on `PreparedPortfolioInputs`) and have `run_prepared` pass the prebuilt index to a lower walk entry. Defer unless evaluation latency is a concern; the Train budget does not need it. |
| **Minor / nit** | `core/portfolio_foundation.py:474-476` (`is_flat` property), called 6.0M× @1M | `_NetPosition.is_flat` is a `@property` doing `signed_qty == 0.0`; it shows as 0.30 s tottime (6M calls) purely from attribute-descriptor + call overhead vs an inline compare. | ~0.3 s @1M (~3.5%). Trivial in isolation; only worth touching if the two rows above are being edited anyway. | Optional: inline `position.signed_qty == 0.0` in the two tight loops (`_equity_at_mark`, `_exposures`) that dominate the call count, or convert to a plain attribute updated on write. Low priority. |

---

## What is efficient (preserve)

- **Single causal walk replaces screen + re-pricing.** Old per-trade `screen`/
  `gate_screen` (`core/engine_runner.py`) and both `vectorbtpro_backend.py` +
  `project_perp_ledger.py` (~1.5k LOC pandas/vbt) are deleted. One walk now serves Train;
  evaluation reuses the *same* walk per fold (design D9). This is the headline perf win —
  no double money model, no separate foundation re-price.
- **Import wall intact.** `import quant_strategies.runner` pulls **no** pandas/numpy/
  vectorbtpro (verified). The quick-run path stays dependency-light; pandas is imported
  lazily only inside the evaluation backend (`require_pandas_dependency`).
- **`build_portfolio_foundation` shares one `_RowIndex` + one `_DecisionPlan`** across
  both cost scenarios (`:381-382`) — the index is built once, not per scenario, on the
  Train path. Correct and the right call.
- **`_DecisionPlan` is O(decisions·log)**, grouped by effective fill timestamp; the walk
  reads `decision_plan.by_time.get(timestamp, ())` — a dict.get per bar, no per-bar scan
  over all decisions.
- **`_check_intended_budget` is gated to decision bars** (`if planned:`), not every bar —
  the budget rebuild is bounded by rebalance count, not row count.
- **`_apply_funding` is a single `dict.get` per bar** (`funding_events_by_apply_time`);
  no-funding bars cost one miss. Funding marks reuse the same `mark_at`.
- **Statistics pass is single-pass and streaming.** `_scenario_metrics` assigns each
  path point to its subwindow bucket in one loop; `_compute_return_statistics_from_chunks`
  / `_*_from_chunks` stream over chunks without materializing a concatenated list.
  Subwindows are capped (`MAX_FOUNDATION_SUBWINDOWS = 64`). No quadratic stats behavior.
- **Lazy error messages elsewhere are correct** — e.g. the `nonpositive_equity_for_entry`
  f-string (`:686`) sits inside its `if equity <= 0.0` guard. Only `mark_at` regressed.

---

## Notes / out of scope

- The 2 deferred test failures and the `foundation_enabled` / VBT-build residuals were
  not investigated; no perf issue hides in them for this lens.
- Numbers are wall-clock on conda `quant`, warm runs, synthetic oscillating marks with
  ~89/100 symbols held (a deliberately position-heavy stress so the per-bar scans bind);
  a sparser real book will be proportionally faster. The **Major** finding's fraction is
  position-count-independent on the happy path (it fires per successful `mark_at`), so the
  ~20–25% estimate is robust.
