# Migration — portfolio-book-spine (consumer-facing changes)

This change (`openspec/changes/portfolio-book-spine`) made the **target book** the
strategy contract and the **single causal netted portfolio book** the one scored
model of money on every surface. This doc records (1) what a `quant_strategies`
consumer must change, and (2) the **specific edits Season should apply in
`quant_autoresearch`** — that repo is not edited here, so the work is tracked below.

## What changed (consumer-visible contract)

- **Decision contract is a target book.** `generate_decisions(rows, params)` now
  returns `Sequence[TargetDecision]`. A `TargetDecision` is a standing, signed
  **weight-of-NAV** target per instrument (`0` = flat/close), idempotent
  (re-emitting the current target trades nothing), with an optional declared
  `RiskRule` (`stop_loss` / `take_profit` / `trailing` as **fractions of the entry
  mark**, engine-enforced, latches flat on fire). Retired and **deleted, no shim**:
  `StrategyDecision`, `PositionTarget`, `ExitPolicy`, `DecisionIntent`, `Direction`,
  `SizingKind`, `DecisionAction`. Data/time exits are explicit `target=0` decisions.
- **NAV path is the single scored object.** `RunResult.foundation` is the
  authoritative scored portfolio book (schema `v2`, basis
  `quick_run_netted_portfolio_book`), not an optional diagnostic. The per-trade
  ledger (`RunResult.economics`) is a **derived attribution view** of the same book
  walk (`net_return = gross_return + funding_return − cost_return`, reconciles with
  NAV) — first-class for alpha / IC analysis, never an independent scored number.
- **Feasibility is fail-closed.** `RunResult.feasibility` is a typed
  `FeasibilityVerdict`. A breach (`leverage_budget_breach`, `zero_cost`,
  `unfinanced_leverage`, `insufficient_samples`) sets `failure_stage="feasibility"`
  and `succeeded=False`. The book is never clamped/normalized to fit the budget and
  never collapsed into a silent `None`. `succeeded` now means **feasible and
  completed**.
- **Leverage budget is operator-frozen.** The agent-editable
  `foundation_max_gross_exposure` `[output]` key is **removed**; the gross+net
  budget lives with the protocol. Intended exposure beyond it is non-scoreable.
- **Return statistics are over at-risk bars** (capital-deployed), not a zero-padded
  calendar, with a minimum-sample gate; subwindows below the minimum report
  non-scoreable rather than a finite Sharpe from sample count alone.
- **One accounting model everywhere.** Quick run, validation, and evaluation run the
  same pure book (`netted_portfolio_book_v1`); evaluation adds only Parquet trace
  serialization. The VectorBT Pro backend, the `project_perp_ledger_v1` model name,
  and the single-trade agreement oracle are retired; validation's
  `[agreement_oracle]` config section is rejected, and `verdict_source` is
  `"engine"` only.

## Cross-repo doc updates needed (`quant_autoresearch`)

Do **not** edit these from this repo. Apply in `/Users/Season_Yang/Personal/quant_autoresearch`:

### `program.md`

1. **"Editable Surface" → `strategy.py` bullet.** It currently reads
   "causal signal logic via `generate_decisions(rows, params)`." Reframe to the
   target-book contract: `generate_decisions(rows, params)` returns a
   `Sequence[TargetDecision]` — a *complete portfolio* of standing, signed
   weight-of-NAV targets (idempotent; `0` = flat; optional declared `RiskRule`).
   The agent now owns allocation, sizing, netting intent, rebalancing, and
   explicit/declared exits, not just a signal. Note that same-symbol targets net
   (stacking is structurally inexpressible) — "build the book," not "emit a ticket."
2. **Frozen set (`protocol.toml` paragraph).** Add the **leverage budget (gross and
   net)** to the operator-frozen list alongside window/costs/fills/objective/gates.
   State that intended exposure beyond the budget is a fail-closed feasibility
   verdict (non-scoreable), and the agent must build *within* the budget — it is
   not silently scaled down. This matches `quant_strategies` PRD G8 / design D5–D6.
3. **"Allowed bold moves" / capability-wall paragraph.** The engine no longer blocks
   complete-portfolio expression (rebalance, signal-driven close, portfolio-level
   risk are all expressible now). Keep the "file an `UPSTREAM_LIMITATIONS_TODO.md`,
   do not approximate in strategy code" rule. Optionally note the named follow-ons
   still upstream (equity short-borrow/dividends, FX rollover, capacity/ADV/impact,
   intrabar OHLC stop fills) so the agent files rather than approximates those.
4. **Trade-tape / "inspect actual trades" guidance.** Clarify that the per-trade
   tape is now a *derived attribution view* of the one NAV book (one model of
   money), so trade-tape inspection and the scored NAV path can no longer disagree;
   the tape is for *alpha* attribution, the NAV path is what is scored.

### `docs/score_research.md`

5. **Add a feasibility / non-scoreable section.** The doc covers the keep rule and
   PSR-on-foundation but not the fail-closed verdict. Add: a quick run can now come
   back **infeasible** (`RunResult.succeeded == False`, `failure_stage="feasibility"`,
   typed `RunResult.feasibility.reason` + observed exposure). An infeasible run is
   **not a low score — it is no score**; the loop's failure interpretation should
   read the typed reason (`leverage_budget_breach` → reduce intended gross;
   `zero_cost` → configure costs; `unfinanced_leverage` → unpriced leverage for the
   asset class; `insufficient_samples` → too few at-risk bars) and respond, never
   treat it as a worst-case score to climb past.
6. **"Why This Score" wording.** It already demotes the trade-unit objective. Tighten
   the language to say the scored unit *is* the single netted-book NAV path and the
   per-trade ledger is a derived attribution view — there are no longer "two models
   of money" to reconcile.
7. **Scoring-record fields.** The required upstream fields list is still correct, but
   note `closed_trade_count` now counts **netted-book round trips** (a net position
   returning to flat), and return statistics are over **at-risk bars** with a
   minimum-sample gate (a subwindow below the minimum is non-scoreable, so PSR must
   handle a `None`/non-scoreable subwindow rather than assume a finite Sharpe). The
   foundation summary also exposes a per-scenario `feasibility` payload and live
   gross/net `*_utilization` series the loop may surface as diagnostics.

### Both files

8. Remove any remaining "open ticket" / `StrategyDecision` / `PositionTarget` /
   `ExitPolicy` / "linear per-trade sum" / "fail-open `foundation=None`" /
   `foundation_max_gross_exposure` references, and any claim of a separate
   VectorBT-Pro / perp-ledger evaluation backend, mirroring this repo's docs.
