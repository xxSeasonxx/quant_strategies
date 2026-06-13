# Consumer integration & migration guide

For `quant_autoresearch` and any consumer wiring a strategy loop into
`quant_strategies`. It states the integration contract you build against today,
a checklist of what your own loop and docs must reflect, and a compact mapping
for code still on an older decision shape. The authoritative contract lives in
the linked owning sections; this guide does not restate them in full.

## Integration contract (what you emit and consume)

- **Emit a target book.** Your strategy file exposes
  `generate_decisions(rows, params) -> Sequence[TargetDecision]` — standing, signed
  weight-of-NAV targets per instrument (`0` = flat/close), idempotent, with an
  optional declared `RiskRule`. The agent owns the complete portfolio (allocation,
  sizing, netting intent, rebalancing, explicit/declared exits), not a per-signal
  ticket; same-symbol targets net, so stacking is structurally inexpressible.
  Schema: [`reference.md`](reference.md); contract: [`README.md`](README.md#for-ai-agents-read-this-first).
- **Consume `RunResult`.** The single netted-book **NAV path** is the authoritative
  scored object (`result.foundation`); the per-trade ledger (`result.economics`) is
  a derived attribution view of the same walk — first-class for alpha/IC analysis,
  never an independent scored number. Use `result.succeeded` (feasible **and**
  completed) as the terminal check, and `result.retainable` before advancing
  quick-run evidence to validation/evaluation. Fields: [`reference.md`](reference.md).
- **Build within the operator-frozen envelope.** The leverage budget (gross and
  net), costs, fills, capacity model, universe, and window are frozen — the strategy
  cannot relax them. Intended exposure beyond the budget is **non-scoreable**, not
  silently scaled down. Contract: [`../../FOUNDATION_LOCK.md`](../../FOUNDATION_LOCK.md)
  and `PRD.md` G8.
- **Treat an infeasible run as no-score, not low-score.** A breach returns
  `result.succeeded == False`, `failure_stage="feasibility"`, and a typed
  `result.feasibility.reason` + observed exposure. Read the reason and respond
  (`leverage_budget_breach` → reduce intended gross; `zero_cost` → configure costs;
  `zero_slippage` → set positive `slippage_bps_per_side`;
  `unfinanced_leverage` → unpriced leverage for the asset class;
  `insufficient_samples` → too few at-risk bars). Never climb past it as a worst
  score.
- **One model of money.** The trade tape and the scored NAV path cannot disagree —
  the tape is a derived attribution view of the one book. Inspect the tape for
  *alpha* attribution; score the NAV path.

## Checklist for `quant_autoresearch`

Ensure the consumer loop and its docs reflect the current contract. Apply in
`/Users/Season_Yang/Personal/quant_autoresearch`.

In `program.md`:

- The editable `strategy.py` surface is the **target-book** contract above (a
  complete portfolio of standing weight-of-NAV targets), not a per-signal ticket.
- The operator-frozen set includes the **leverage budget (gross and net)**
  alongside window / costs / fills / objective / gates; intended exposure beyond it
  is a fail-closed, non-scoreable feasibility verdict, and the agent must build
  *within* the budget.
- Complete-portfolio expression (rebalance, signal-driven close, portfolio-level
  risk) is expressible — keep the "file an `UPSTREAM_LIMITATIONS_TODO.md`, do not
  approximate in strategy code" rule for the named upstream follow-ons (equity
  short-borrow/dividends, FX rollover, capacity/ADV/impact calibration).
- The per-trade tape is a derived attribution view of the one NAV book; tape
  inspection and the scored NAV path cannot disagree.

In `docs/score_research.md`:

- A quick run can come back **infeasible** (`succeeded == False`,
  `failure_stage="feasibility"`, typed `feasibility.reason` + observed exposure):
  no score, not a low score. The loop's failure interpretation reads the typed
  reason and responds.
- The scored unit **is** the single netted-book NAV path; there is one model of
  money, so PSR-on-foundation and the keep rule run on that NAV path, not a
  per-trade sum.
- `closed_trade_count` counts netted-book round trips; return statistics are over
  **at-risk bars** with a minimum-sample gate, so a subwindow below the minimum is
  non-scoreable — PSR must handle a `None`/non-scoreable subwindow rather than
  assume a finite Sharpe. The foundation summary also exposes a per-scenario
  `feasibility` payload and live gross/net `*_utilization` series.

## Migration aid (older decision shape → current)

If consumer or strategy code still uses an older shape, map it onto the current
contract. Rationale and the full list of removed types are in
[`../../HISTORY.md`](../../HISTORY.md#2026-06-10--portfolio-book-spine-migration).

| Older shape | Current |
| --- | --- |
| `StrategyDecision` / `PositionTarget` / `ExitPolicy` / `DecisionIntent` | `TargetDecision` (signed weight of NAV; `0` = flat/close) |
| `Direction` / `SizingKind` / `DecisionAction` | sign + magnitude of the `TargetDecision` target |
| data/time exit as an exit object | explicit `target=0` decision |
| price-path exit inferred downstream | declared `RiskRule` on the `TargetDecision` |
| `foundation=None` / fail-open on breach | typed `result.feasibility` verdict, `succeeded=False` |
| `foundation_max_gross_exposure` `[output]` key | operator-frozen leverage budget (not agent-editable) |
| per-trade-sum "return" as the scored number | NAV-path total return (`result.foundation`) |
| alternate / `project_perp_ledger_v1` evaluation backend | one `netted_portfolio_book_v1` on every surface (`verdict_source="engine"`) |
