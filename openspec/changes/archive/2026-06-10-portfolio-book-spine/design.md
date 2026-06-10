## Context

This change implements §1A of `live-trade-feasibility-review-2026-06-10.md`. The
review's verdict — confirmed by an independent senior-quant audit — is that the
engine's atomic unit is the **trade**, not the **portfolio**, and that this is the
root beneath signal-stacking, implicit leverage, the fail-open gross cap, and the
divergent PnL paths.

Current state, verified in source:

- **Input ontology** (`decisions/models.py`): a decision is an `open` ticket with
  a baked-in `ExitPolicy`. The strategy cannot declare a total intended position,
  cannot close on signal, cannot rebalance or net. `PositionTarget.size` has no
  upper bound.
- **Scored statistic** (`engine/evaluation.py:108-111`): `net_total = Σ` weighted
  per-trade fractional returns — a sum of isolated round-trips, equal to a NAV
  path only for a single trade (conceded by `validation/agreement.py`, whose
  oracle is single-trade-only).
- **Three money-models**: the engine linear sum; the foundation `_portfolio_path`
  (`core/portfolio_foundation.py:642`, pure-Python book keyed by `id(window)`, **no
  same-symbol netting**, gross cap that **raises into a fail-open `except`**); and
  the hand-rolled `project_perp_ledger` (`evaluation/project_perp_ledger.py:54`,
  near-identical pandas book). Funding is implemented three times.
- All three **replay fixed trade windows** whose entry/exit were chosen by the
  per-trade screen `_select_exit` **before any book exists**. The "portfolio"
  never *constructs* anything; it re-prices already-isolated round-trips.

The consumer (`quant_autoresearch/program.md`) edits `strategy.py` freely and
trusts "passes Train ⟹ tradeable." When a research move is blocked by engine
capability it must file an upstream limitation, **not** approximate in strategy
code (`program.md:119-121`). So the engine's expressiveness is a hard ceiling:
today's open-ticket contract structurally blocks the agent from building a
complete portfolio, and the fail-open accounting rewards untradeable books.

## Goals / Non-Goals

**Goals:**

- **Enable**: let `strategy.py` express a complete, live-shaped portfolio —
  allocation, sizing, rebalancing, signal-driven and risk-driven exits, side,
  hedging — without hitting a capability wall.
- **Guarantee**: simulate exactly one stateful portfolio under frozen real
  frictions and **refuse to score** anything not actually tradeable, so a kept
  Train candidate is genuinely a live-trade candidate.
- One causal, single-account, netted book as the single source of NAV truth;
  collapse three money-models (and three funding impls) into one.
- Preserve strategy **purity**, the **causality machinery**, **funding
  correctness**, and the **dependency-light import wall**.

**Non-Goals:**

- Asset-class friction realism beyond crypto-perp funding (equity borrow/dividends,
  FX rollover, margin financing), capacity/ADV/impact, and intrabar OHLC stop
  fills. These are real **modeling + data** work that plug into the spine's
  market-model interface as Open/Closed extensions; they are named follow-ons, not
  this change. (Crypto-perp funding is already modeled, so the spine is complete
  for today's asset class.)
- Realized-state-feedback strategy policies (drift-triggered rebalance,
  realized-NAV vol targeting, "cut my worst live performer"). Out of scope for v1;
  a pure intended-book escape hatch is reserved but not built.
- A working-order lifecycle / OMS. The book is evaluated **end-of-bar on printed
  marks**; it is a backtest book with a leverage budget, not an execution system.
- Migrating existing `candidates/` / `researched/` strategies (they will be
  redeveloped) and any backward-compatibility shim.

## Decisions

### D1 — The decision is a standing, signed, weight-of-NAV target book

`generate_decisions(rows, params)` returns a causal stream of `TargetDecision`s.
Each declares, as of `as_of_time` and effective at `decision_time`, the target in
one instrument as a **signed weight of NAV** (`+` long, `−` short, `0` =
flat/close). A target is **standing**: it holds until the next decision for that
symbol changes it. Targets are **idempotent** — re-emitting the current target
trades nothing.

- *Why weight-of-NAV*: it is the portfolio mental model the consumer must think in
  ("20% here, 15% there, 60% gross"), keeps candidates cross-comparable, and the
  foundation already sizes `signed_notional = signed_weight × equity`. Asset-class
  denominator nuance (perp margin, FX base-ccy) is pushed into the market model.
- *Why standing (not per-bar snapshot)*: live-faithful (a position persists until
  you trade), terse, and natural for event-driven rebalancing. A per-bar snapshot
  was considered (absent symbol = flat) — simpler exit semantics but verbose and
  it re-emits constantly.
- *Why idempotent targets matter*: re-emitting "long 0.2" while already at 0.2 is a
  no-op, so **signal-stacking is structurally inexpressible** and the agent is
  forced to reason about the whole book. This is the anti-stacking mechanism *and*
  the portfolio enabler in one primitive.
- A target sets a **quantity at the decision bar** (`qty = signed_weight × equity /
  fill_price`) and is then **held as quantity** until the next decision; weight
  drifts between decisions. Holding *constant weight* requires explicit periodic
  rebalancing decisions. This avoids the continuous-rebalance fiction and keeps
  turnover/costs realistic.
- Rejected: `(quantity, unit)` pluralistic units at the contract (contracts/shares/
  notional/risk-fraction). More literal but breaks cross-comparability and the
  scorer needs a common denominator anyway. Revisit only if a follow-on asset class
  needs it.

### D2 — Data/time-derivable exits are decisions; price-path exits are a declared RiskRule

The principled line: **anything derivable from data or time → an explicit
`target → 0` (or new) decision (pure); anything derivable only from the realized
price path → a declared `RiskRule` enforced by the engine.**

- A causal strategy **may not read future prices** in `rows` to place its own stop
  — that is lookahead, which the causality machinery forbids. The engine, walking
  the book causally, *can* evaluate "did the mark cross the level" at the bar it
  happens. So a protective stop **must** be an engine-enforced overlay; this is the
  only causal way to express it, not a convenience.
- `RiskRule` carries `stop_loss` / `take_profit` / `trailing` only. `max_hold` and
  signal-driven exits are **explicit target decisions** (the strategy knows its own
  decision times and the bar grid, so it can emit a paired `target → 0` purely).
  This keeps the overlay minimal and the responsibility line crisp.
- **Re-entry latch**: when a `RiskRule` fires and flattens a symbol, the symbol is
  **latched flat until the strategy emits a new (different) target** for it.
  Otherwise a standing target would immediately re-enter next bar and the stop
  would be useless. This moves the hand-rolled `active_until_by_symbol` suppression
  the old candidate carried **into the engine**, where it belongs.
- Rejected: all exits as decisions (cannot express causal stops); all exits as
  overlay rules (less expressive, conflates alpha and risk); a stateful callback
  (loses purity — see D7).

### D3 — One causal, single-account, netted book is the only spine

A single bar-by-bar walk replaces all three money-models:

```
for each bar t:
  1. apply decisions effective at t        → desired target weights
  2. net + size: per-symbol running QUANTITY; target_qty = f(weight, equity, mark)
  3. orders = target_qty − current_qty     → trade only the DELTA
  4. market model: fills, costs on |delta notional|, funding/financing on NET held
  5. mark-to-market on one cash/margin account → NAV[t]; gross/net exposure series
```

- Positions are keyed **per symbol** as a running signed quantity — not per window.
  Same-symbol exposure **nets by construction**; you trade and finance only what you
  actually hold/trade. This is the economically correct netting (F7) and it is the
  precise reason this is **not** a "surgical add" to the window-replay book — real
  netting *requires* the quantity-delta model. The de-risked "net inside the old
  book" intermediate (review 0a) is therefore skipped: it would be a new patch, and
  Season has authorized the strategy rewrite that the unified build needs.
- **Gross/leverage measured two ways**: (a) the **intended target gross** at a
  decision (the strategy's declared intent) is the **hard, fail-closed** check
  (D5); (b) **live mark-to-market gross** each bar is a reported utilization series
  (review No.16) — a winner drifting above the ceiling is a risk signal, not an
  infeasibility (you are not forced to delever intrabar in a backtest book).

### D4 — NAV path is the single scored object; the per-trade ledger is a derived view

The book walk produces one NAV path; **all scored statistics derive from it**
(Sharpe/PSR inputs, drawdown, exposure). The per-trade ledger is **reconstructed
from the same walk** as an attribution / information-coefficient view — kept
first-class for *alpha* research ("is the signal predictive?", a question NAV-only
cannot answer) but never an independent scored number. This aligns with
`score_research.md`, which already climbs the foundation NAV path and demotes
trade economics to diagnostics. It removes the two-PnL ambiguity (review §6.2) by
construction: there is one model of money.

### D5 — Envelope breach is a typed, fail-closed feasibility verdict; never clamp

The run carries a typed **feasibility verdict**. A breach — intended gross/net over
the operator ceiling, zero-cost on a scoreable run, or a degenerate sample — makes
the run **infeasible / non-scoreable** with an actionable reason
(`leverage_budget_breach` + observed gross, `zero_cost`, `insufficient_samples`).
`RunResult.succeeded` is gated on the verdict.

- *Why fail-closed, never clamp*: clamping/normalizing the book to fit the budget
  hides infeasibility and re-frees leverage — two strategies (target 1.5 vs target
  5.0 clamped to 1.5) would look identical, exactly the leak we are closing. In
  live trading you do not silently get your intent scaled; your risk limit binds.
  The consumer must learn to build within the budget — that *is* part of being
  tradeable, and the typed reason is the actionable training signal.
- *Why not fail-open* (current): a breach, a benign data gap, and an internal bug
  all collapse to `foundation=None` + a soft string, and a test locks it in. The
  most actionable feasibility signal is destroyed.

### D6 — Frozen-vs-free boundary: strategy owns the book, operator owns the envelope

- **Free (consumer-editable, in `strategy.py`)**: the entire target book —
  allocation, sizing, netting intent, rebalancing, explicit exits, declared
  `RiskRule`s. The strategy's *chosen* gross is theirs (and may be exposed as a
  bounded `experiment.toml` param the agent tunes).
- **Frozen (operator-owned, in `protocol.toml`)**: the leverage **ceiling**, cost
  floor, costs/fills, data kind, asset universe, train window, objective, gates —
  matching `program.md`'s frozen set verbatim. The engine enforces limits and
  prices reality; it never *allocates*.
- This relocates the overfit guard from *expressiveness* to the *envelope*:
  forbidding portfolio logic would force the signal-only strategies that are not
  tradeable. The complexity gate (declared components / bounded params) keeps a
  portfolio-rich strategy auditable.

### D7 — Strategies stay pure and emit the whole timeline up front

`generate_decisions` remains a pure function of `(rows, params)` returning the full
decision timeline. The consumer loop reacts **between** runs (edit → run → read
trades → edit), never within a backtest, so up-front emission costs no
expressiveness for v1 (`program.md`'s allowed moves are all data/signal/exit/
risk-shape). This preserves the AST purity lint, determinism, and the causality
machinery. Realized-state feedback (D-non-goal) would need book state mid-walk; the
reserved escape hatch is to pass the strategy its own *intended* prior book (still
pure), never a stateful callback.

### D8 — Localize frictions in the book now; publish a market-model interface only when F4 adds the second term

Costs, fills, and funding are applied at one **localized friction step** inside the
book's causal walk, with crypto-perp funding (already correct in `funding.py`) as
the **single** funding home — the two duplicate impls are deleted. This change does
**not** introduce a `MarketModel` abstraction as a deliverable: only one friction
term exists today (perp funding), so an interface now would be speculative
generality (the review flagged it as over-engineering; NFR-ROOT-CAUSE / "don't
over-engineer"). The Open/Closed moment is **F4**, when equity borrow / FX rollover
/ margin financing add the *second* term — the interface is extracted then, against
two real implementations. What this change must guarantee is that frictions are
*localized to one call site in the book* (not scattered across three money-models),
so extracting the interface later is a local refactor. That locality — not the
premature existence of an interface — is what makes deferring F4 "not doing it
again."

### D9 — One pure-Python spine book on every surface; retire the evaluation backends

The scored spine stays pure-Python (no `pandas`/`numpy`/`vectorbtpro`/`evaluation`
on the quick-run path) to keep the ~1s Train path and the import wall. **The same
spine is the single book for quick-run, validation, and evaluation**; evaluation
adds only artifact serialization (pandas/pyarrow) *around* the pure book at its own
layer. The VectorBT Pro and `project_perp_ledger` evaluation backends are
**retired**: VBT cannot model funding (so it cannot honestly evaluate the
crypto-perp asset class), and the agreement oracle is single-trade-only
(`validation/agreement.py`), so the second backend provides no real multi-trade
verification today. One model of money everywhere is the simplest correct,
no-legacy outcome.

An *independent cross-check* (a second re-implementation that must agree with the
netted book) is genuinely valuable but is a **follow-on**: it first requires
generalizing the agreement oracle from single-trade to the netted book. Building it
now is the over-engineering the review flagged.

**Decision (locked, 2026-06-10):** retire the VBT Pro + `project_perp_ledger`
evaluation backends and run the one spine book everywhere. Accepted tradeoff: no
independent cross-check of the spine's accounting until a follow-on generalizes the
agreement oracle to the netted book; the spine's correctness is guarded instead by
the NAV↔ledger reconciliation test and the at-risk-bar / verdict test suite.

## Risks / Trade-offs

- **Large blast radius** → It is the root; the contract is shared by quick-run,
  validation, and evaluation. Mitigation: clean cutover, no shim; rerun; strategies
  redeveloped against the new contract (Season authorized).
- **The fail-open contract is tested as accepted** (`test_runner_api_cli.py`) →
  Intentionally invert that test with the verdict change; document the contract
  flip so it does not read as a regression.
- **More runs return "infeasible"** under the fail-closed verdict → That is the
  correct signal; the verdict is typed and actionable so the loop's
  failure-interpretation can respond ("reduce intended gross"). Not a regression.
- **Standing-target + RiskRule interaction is subtle** (re-entry latch) → Specify
  and test the latch (D2) explicitly; it is a named scenario in the spec.
- **Weight→quantity uses equity at the decision bar** (a self-referential mark) →
  Size all same-bar entries against **one equity snapshot taken before any of that
  bar's entries**, so Σ|target weight| equals the measured intended gross exactly,
  independent of fill order (the spec now requires this); test the ordering.
- **Deferring asset-class financing** leaves equity/FX leverage unpriced *if those
  asset classes are used before the follow-on lands* → A **required**
  `unfinanced_leverage` fail-closed verdict per `DataKind` makes an unpriced-leverage
  book non-scoreable (crypto-perp exempt — funding is modeled), so deferring F4
  cannot silently mint free-leverage PnL.

## Migration Plan

1. Land the new `TargetDecision` / `RiskRule` contract and the unified book behind
   the existing public entry points (`run` / `validate` / `evaluate`); remove the
   open-ticket translation layer (`engine/executable.py`, `assert_supported_decisions`)
   and the isolated `_select_exit` exit engine.
2. Delete the per-trade linear-sum scorer, `_portfolio_path`'s window-replay,
   `project_perp_ledger`, the VBT/perp-ledger evaluation routing + model-name + the
   `_REQUIRED_COMPLETED_FUNDING_MODELS` gate, and the duplicate funding impls; route
   all NAV through the one spine book on every surface.
3. Move the leverage budget (gross **and** net) out of agent-editable `[output]`
   into the protocol-frozen set; make `RunResult.foundation` authoritative and add
   the typed feasibility verdict (incl. `unfinanced_leverage`); gate `succeeded` on
   it (a breach sets a `failure_stage`); invert the fail-open contract test.
4. Re-home return statistics onto at-risk bars + min-sample gate; remove dead
   `promotion_eligible` and the `FoundationSubwindowMetric` alias; keep DSR as a
   diagnostic recomputed on the at-risk statistics.
5. Update consumer docs and the `score_research.md` / `program.md` contract
   descriptions of the scored unit and feasibility.
6. Redevelop `candidates/` strategies against the new contract; rerun.

Rollback: revert the change set; there is no data migration (artifacts are
regenerated evidence, not state).

## Open Questions

- **Denominator when F4 lands**: how `weight-of-NAV` maps to a base-currency NAV
  for FX and to margin for perps under multi-currency financing — settle in the F4
  follow-on, not here.
- **Evaluation backend — RESOLVED (2026-06-10)**: retire VBT + `project_perp_ledger`;
  run the one spine book on every surface (see D9). An independent cross-check via a
  netted-book agreement oracle is a follow-on.
- **Causality in the verdict**: this change surfaces a `causality_admissible`
  dimension reading existing evidence; whether `off`/`micro` should make a run
  non-scoreable is a downstream-coupled policy tightening (F6 follow-on).
