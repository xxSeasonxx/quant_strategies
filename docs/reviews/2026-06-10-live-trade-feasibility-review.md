# Live-Trade Feasibility Foundation Review

**Date:** 2026-06-10
**Reviewer:** Claude (Opus 4.8), main reviewer, synthesizing five independent fresh-context lenses (onboarding, architecture, senior engineering, adversarial pre-mortem, quant execution-realism).
**Method:** Source code as primary evidence; docs treated as claims to verify. Lens subagents were forbidden from reading `TODOS.md` and `docs/reviews/*` to stay independent; the main reviewer read those *after* forming the code-based view, to label findings new-vs-known.
**Focus:** The quick-run portfolio foundation as the surface the downstream auto-research loop (`quant_autoresearch`) climbs, and whether a strategy that "passes" research here is realistic and feasible to trade live.

> ## ⚠️ STATUS — 2026-06-10: SHIPPED (read this first)
>
> **The root fix in this review has been implemented and archived** as the
> `portfolio-book-spine` OpenSpec change (branch `portfolio-book-spine`, commits
> `a53a1ad`…`968300d`; spec deltas applied to `openspec/specs/`; change archived at
> `openspec/changes/archive/2026-06-10-portfolio-book-spine/` with its proposal,
> design, and four review artifacts). The engine is now **one causal single-account
> netted NAV book**: strategies declare an idempotent **target book** (`TargetDecision`,
> signed weight-of-NAV; stacking inexpressible), the **NAV path is the single scored
> object**, an envelope breach is a typed **fail-closed `FeasibilityVerdict`**,
> statistics use **at-risk bars** (the F2 fix), and the trade-unit scorer + VBT + the
> perp-ledger are deleted (net ≈ −5,700 lines). Three independent reviews
> (code / quant-math / performance) validated the core and caught + fixed one
> validation-gate blocker (realized-Σ vs marked-NAV). Engine suite green; the enforced
> gate is `ruff` + `pytest`.
>
> **§1–§13 below are the ORIGINAL pre-refactor analysis, preserved as provenance —
> they describe the state *before* the refactor and must NOT be read as current.** The
> accurate, re-statused picture and all remaining work live in **§14**.
>
> **Remaining work for the next session (from §14):**
> - 🔴 **Open** — No. 11 (PIT `available_at ≥ timestamp` guard), No. 17 (relocate the
>   stale `researched/` artifacts), No. 20 (**rebuild the four candidate strategies on
>   the target-book contract** — clears the last deferred test).
> - ⏳ **Deferred follow-ons** (plug into the spine's market-model interface; several
>   need new `quant_data` fields) — No. 3 capacity/ADV (a `volume` field), No. 6
>   (tighten `off`/`micro` causality → non-scoreable), No. 7 (asset-class
>   financing/borrow/carry — guarded meanwhile by the `unfinanced_leverage` verdict),
>   No. 8 (intrabar OHLC stop fills + fill-price stress).
> - ✅ Everything else is **Done** (the §1A root + most P0/P1), now including **No. 18**
>   (the dead `foundation_enabled` knob removed — the book is mandatory) and **No. 19**
>   (VBT fully purged: build extras, `Makefile` smoke target, `evaluation/dependencies.py`
>   import, the `vectorbtpro` purity-ban entry, and all active docs/tests scrubbed).
>
> Both of Season's decisions are resolved (2026-06-10): No. 18 → **remove** the knob;
> No. 19 → **purge** all VBT (no scaffolding kept). Cross-repo `quant_autoresearch`
> edits are written up in `docs/consumer/MIGRATION-portfolio-book-spine.md`.

---

## 0. UPDATE (2026-06-10, post-review) — reconciled with the live score contract

After this review was drafted, Season provided `quant_autoresearch/docs/score_research.md` (dated 2026-06-10), the authoritative contract for what the loop climbs. It resolves the one open question flagged in §11 and re-weights several findings. **Net: the score *design* is good and removes the worst-case reading of one finding — but it makes the top finding (F2) more severe and more clearly quant_strategies' job to fix.**

**What is climbed (resolved):**
```
score = min( PSR(full_train),  min_k PSR(subwindow_k) )
PSR   = NormalCDF( (sharpe − psr_hurdle) / sharpe_standard_error )
```
- The loop climbs the foundation **`realistic_costs` NAV path**, reading the foundation's `sharpe` and `sharpe_standard_error` (full_train + K subwindows). It explicitly does **not** climb the engine trade-bag economics and does **not** recompute NAV/SE/effective-sample-size locally (`score_research.md:27-29, 90-113, 176-195`).
- The live score is **PSR, not DSR**. DSR, PBO, MinBTL, trial count, win-rate, profit-factor, and aggregate return are *explicitly excluded* from the keep-rule score (`:197-213`). Engine economics (`win_rate`, `profit_factor`, `avg_trade_net`, `cost_return_sum`) are **diagnostics only** (`:162-163`); foundation `closed_trade_count`/`total_return`/`max_drawdown`/`max_symbol_concentration` are **gates** (`:130-149`).
- **Correction to this review:** wherever later sections say the loop climbs "worst_subwindow **DSR**," read "worst_subwindow **PSR**." F2's *mechanism* is unchanged and in fact sharper (below); only the named final statistic was wrong.

**SHARPENS F2 — now unambiguously the #1 fix.** PSR = NormalCDF((sharpe − hurdle)/**SE**), and the foundation computes **SE = f(effective_sample_size, skew, kurtosis)**. The flat-bar (zero-return) padding inflates `effective_sample_size` (~50→~5000), collapsing SE and driving PSR→1.0 *independent of whether the Sharpe is real*. Two load-bearing consequences:
1. It directly inflates the **climbed score** — and PSR has *no* trial-count deflation to dampen it, so it is *more* sensitive to SE than DSR would have been.
2. `effective_sample_size` is *also* a **gate** ("minimum evidence: return samples and effective sample size", `:140`), so the same inflation lets a 99%-flat strategy **pass the min-evidence gate**.

The doc's stated intent is to "adjust for the effective number of return observations" (`:41, :50-51`) but it **delegates that quantity to quant_strategies** ("`quant_strategies` owns … effective sample size", `:180`) and instructs: *"If an upstream metric is … mathematically suspect, mark the run unavailable and fix the upstream contract"* (`:193-195`). **An effective sample size counted over a zero-padded calendar is exactly that suspect upstream metric — the whole conservatism of the probability-scale score rests on an honest upstream SE, and today it is not honest.** This is squarely quant_strategies' bug, and the downstream contract explicitly asks for the fix.

**RESOLVES / DOWNGRADES the two-PnL-path concern (§6.2, action No. 5).** The loop climbs the realistic NAV path *by deliberate design* — the doc says it switched to portfolio-foundation PSR precisely to capture overlapping positions, idle time, compounding, and exposure that the trade bag ignored (`:38-53`). So the worst case raised below — "the optimizer climbs the exposure-blind per-trade sum" — **does not occur.** The engine ledger is diagnostic/audit-only. Action No. 5 drops from "re-architect to make NAV authoritative" to "the NAV path already is authoritative — keep the ledger labeled diagnostic, add a consistency note."

**REFRAMES the fail-open (action No. 1).** Because the score climbs the foundation and the doc says *"Missing or malformed foundation evidence is a run failure, not a weak score to patch around"* (`:148-149`), a gross breach → `foundation=None` should make the **attempt fail** downstream — so over-leverage is *not* rewarded in the kept score (contrary to my earlier "stacks gross for free" worst case). The finding survives, reframed, on two grounds: (1) **contract mismatch** — quant_strategies returns `succeeded=True` with `foundation=None` on a breach, while the downstream treats missing foundation as a *failure*; safety currently depends on the loop reclassifying `None`, when quant_strategies should emit an unambiguous typed failure with a reason (exactly what `:193-195` asks). (2) **diagnostic destruction** — a gross breach, a benign data gap, and an internal bug all collapse to the same `None` + soft string, blinding the structural-edit loop whose failure-interpretation logic (`:216-235`) needs to know *why* a run failed; "you breached the gross budget, reduce stacking" is the most actionable feasibility signal and it is thrown away.

**Unchanged (still real; all feed the foundation returns/path that PSR and the gates consume, and the loop trusts them unchecked, `:193`):** F1 (cost floor + capacity — the cost-stress *gate* exists but only scales bps, so zero base cost ⇒ zero protection, and capacity/impact is still unmodeled), F4 (asset-class frictions), F5 (intrabar stop optimism), F7 (netting / live-MTM gross), F8 (PIT `available_at ≥ timestamp`).

**Re-sequenced P0 (onto the §14 action map):** **No. 2** (honest `effective_sample_size`/SE) → **No. 1** (typed foundation failure) → **No. 3** (cost floor + capacity) → **No. 4** (leverage gate / `size` bound). **No. 5 downgraded** to a consistency/labeling item.

---

## 1. Executive verdict

**The foundation's *workflow spine, boundary contracts, causality machinery, and funding math are genuinely sound* — that part of the 2026-06-04 codex review still holds. But the newer quick-run portfolio foundation (the surface that exists specifically to make Train results live-realistic) is *not yet trustworthy as the objective of an automated, no-human-in-the-loop climb.*** It is structurally inverted: the realism it computes lives in a **fail-open side-channel**, the number the optimizer climbs is computed on a **statistically distorted basis**, the repo's *real* risk gates (gross/leverage admissibility, strict look-ahead) sit on the **downstream validation/evaluation path — not on the quick-run path the loop actually uses**, and costs default to **zero** with **no capacity/impact model at all**.

Put bluntly, as a quant who has to trade the output: **a bounded climb on `RunResult.foundation` / `RunResult.economics` as they stand today is pointed at the most overfit, least tradeable corner of the search space.** It will reward (a) trading rarely and briefly to inflate a flat-bar Sharpe, (b) stacking gross exposure for free because the leverage penalty fails open, (c) high-turnover edges that evaporate under real spread/impact, and (d) equity-short / FX-carry P&L that is unfinanced. None of these require the strategy author to cheat — the *optimizer* finds them because the objective rewards them.

Season's stated concern — signal overstacking / portfolio gross exceeding 1 — is **real and already partly known** (`TODOS.md §2.3`, O14–O23). The point of this review is the *other* gaps, several of which are more dangerous precisely because they corrupt the optimized number itself rather than just one strategy's exposure:

- **The robustness statistic is computed on a per-minute return series that is ~99% zero-return flat bars** → inflated effective sample size, collapsed Sharpe standard error, flattered the climbed score *purely from sample count* (numerically reproduced by two lenses). This corrupts **`worst_subwindow` PSR** — the exact number the loop climbs (confirmed via `score_research.md`; see §0) — independent of any leverage issue. **This is the single most important "haven't-thought-of" finding.**
- **The gross-exposure guard fails *open*** — a leverage breach (a feasibility *signal*) is swallowed into the same `foundation=None` + soft-warning state as a benign data gap or an internal bug, and a test *encodes this as the accepted contract*. A constraint that vanishes when violated is not a constraint.
- **Two different PnL computations** (engine per-trade ledger vs foundation NAV path) disagree on the model of money, and it is unclear which one the loop climbs; the realistic one is the one that can disappear.
- **Costs default to 0.0 and aren't enforced by the foundation; there is no capacity/ADV/impact term anywhere**, and the leverage/causality gates that *do* exist are on the validation path, not the quick-run path.
- **Frictions are perp-shaped**: funding is modeled (correctly) for crypto perps, but equity borrow/dividends and FX rollover/carry are absent, and the cash model gives equities/FX *free leverage* — yet the stated objective spans all three asset classes.

This is **not a rewrite**. The math core, the decision schema, the funding invariants, and the boundary design are good and should be preserved. The fix is to make **feasibility a first-class, enforced contract on the quick-run scored path**, and to fix the statistic the loop optimizes. The root cause beneath almost every finding is one sentence: **"is this tradeable?" has no single owner on the path the optimizer climbs — it is delegated to operator convention (costs), scattered onto the wrong path (exposure), computed in a fail-open diagnostic (gross), and measured with a distorted statistic.** **And the reason it has no owner is deeper still (§1A): the *accounting* root is that the scored statistic is a per-trade sum, not a portfolio NAV (the codebase concedes it — `validation/agreement.py:91-109`); the *organizational* root is that no layer owns portfolio construction. Fix the accounting spine first (surgical, no strategy rewrites); the target-book ontology cutover follows.**

**Bottom line:** Do not let `quant_autoresearch` treat the current quick-run foundation as live-shaped evidence for an automated climb until at least the P0 items below are closed. The pieces to build on are already here; they are wired in the wrong order.

---

## 1A. Root cause — the unit is the trade, not the portfolio (fix this first)

*Added 2026-06-10 after Season confirmed this is the root and authorized breaking changes ("fine to break a lot, we can rerun; the foundation must be correct"). Almost every finding below is a surface of this one defect; fix it first and the others dissolve, collapse into the new spine, or merely get a clean home.*

**First principles.** A faithful backtest simulates **one stateful portfolio evolving causally through time under a market model.** The irreducible objects are a **book** (positions on a shared capital account) and a **market model** (fills, costs, financing, carry) that move the book bar by bar. Exposure, leverage, netting, financing, and a true NAV are all *properties of that one book* — they exist nowhere else.

**This foundation's atomic unit is the trade, not the portfolio** — two faces of one defect:
- **Input face (ontology):** a strategy can only emit independent `open` tickets with baked-in auto-exits (`decisions/models.py`: `action="open"` only). It cannot declare "my total intended position in X is w," cannot close, rebalance, or net. Portfolio construction is smushed into ticket emission and pushed onto every author as ad-hoc suppression logic.
- **Accounting face (engine + foundation):** the engine scores a **per-trade ledger** with no shared account and no netting (`economic_metrics.py` — no exposure/NAV concept); the portfolio NAV is **reconstructed afterward** from that trade bag as an *optional, fail-open side-channel* (`portfolio_foundation.py`), never simulated as the authoritative spine.

So the only object that has exposure/leverage/financing — the portfolio — is **never the thing being simulated** on the scored path; it is inferred late, optionally, and twice. That is *why* feasibility has no owner, *why* there are multiple disagreeing PnL paths, *why* gross fails open, and *why* there is nowhere clean to charge financing/borrow/carry. **Signal-stacking is not a strategy bug** — it is the output of a trade-unit system *with no shared-account construction layer*. (Correction from the audit below: a shared account can net and bound exposure *without* changing the emitted unit — mainstream engines do; the target-book ontology change buys *expressivity and pre-sim auditability*, not netting itself.)

### Target structure (the fix — still lightweight, pure-Python; *not* VBT)

Make a **causal, single-account, stateful portfolio the one spine**:
1. **Decision = a target book.** A decision declares, as of a causal time, a *target* for a symbol as a **(quantity, unit)** pair — unit ∈ {weight-of-NAV, notional, contracts/shares, risk-fraction}; `0` = flat/close. (Plain "target weight" is under-specified: the denominator differs across equity-NAV, perp-margin, and FX-base-currency — an open ADR question, per the audit.) "Open" becomes the special case `0 → target`; close/adjust/rebalance fall out for free. **Intended total exposure is now explicit, declared, bounded, and auditable from the decisions alone — before any simulation.**
2. **One stateful book, one capital account.** Walk bars causally; at each decision, trade = target − current (same-symbol **nets** automatically) against one shared cash/margin account. Gross/net exposure and capital-at-risk become first-class time series.
3. **One market model on the book.** Costs (size/impact-aware), financing on gross>1, borrow on shorts, carry/funding/dividends/rollover per asset class, realistic fills — charged **once**, at the book level.
4. **The book NAV is authoritative for the *feasibility* score** (`score_research.md` climbs PSR on the NAV path and already demotes per-trade economics to diagnostics). The per-trade ledger stops being an independent *scored* number — but per-bet / IC / breadth statistics stay **first-class for *alpha* research** ("is the signal predictive?", a different question that NAV-only would make inexpressible), not merely attribution.
5. **Feasibility is a verdict on the book.** Leverage-budget breach, zero-cost, unverified causality, degenerate sample → first-class **infeasible / non-scoreable** verdict that **fails closed**, never a swallowed `None`.

### How the other findings re-attach to this spine

| Finding | Fate under the new spine |
|---|---|
| Stacking, implicit leverage, **F3** (`size` unbounded, off-path gate), **F7** (no netting) | **Dissolved** — exposure is declared at the contract and netted by construction; you cannot stack a *target*. |
| Fail-open (**No. 1**), two PnL paths (**No. 5**), gross-utilization (**No. 16**) | **Collapse into the spine** — one book is authoritative; a breach is a verdict; gross is a first-class series. |
| **F2** statistic | **Structurally improved** — the book knows active vs flat, so the statistic is computed on at-risk returns (min-sample gate, No. 2, still needed as policy). |
| **F1** costs/capacity, **F4** borrow/dividend/rollover/financing, **F5** fills | **Get a home** — they become market-model terms on the one book (still must be *implemented* + data sourced: a `volume`/ADV field, borrow data, etc.). |
| **F6** causality, cost floor | **Gates/verdicts on the scored book.** |
| **F8** PIT guard, **No. 17** stale artifacts, dead-code cleanup | **Independent** — proceed in parallel; not reshaped by the spine (the rewrite removes the dead `_decision_windows` path naturally). |

### Blast radius (authorized; flagged honestly)

The decision contract is **shared by all three surfaces** — quick-run, validation, and evaluation all consume `StrategyDecision` via `StrategyExecutionSpec`. Changing the unit therefore touches: the decision model, the engine's interpretation, the quick-run foundation, the validation/evaluation backends, **every `strategy.py`**, **every config**, and most tests. Clean cutover, **no compatibility shim** (no-fallback principle): strategies are rewritten to declare target books and results are rerun. Large, but it is the root; building the realism terms (F1/F4/F5) before it would be wasted work on the wrong unit.

### Audit (independent senior-quant review, 2026-06-10)

A fresh-context senior-quant reviewer was tasked to *refute* this section. Verdict: **CONFIRM-WITH-CORRECTIONS** on both the root cause and the proposed structure. Corrections (already folded into the text above and the sequencing below):

1. **Two roots, separable.** **Root 1 — accounting (the must-fix):** the scored statistic is a *linear sum of weighted per-trade fractional returns* (`engine/evaluation.py:108-111`) that equals a NAV path **only for a single trade**. The project concedes this in its own code — `validation/agreement.py:91-109` restricts its cross-check oracle to single-trade scenarios *because* the linear sum and the compounded NAV "are different objects" for ≥2 trades. Three inconsistent money-models coexist (engine linear sum; VBT `cash_sharing=True` book, `vectorbtpro_backend.py:361`; hand-rolled perp ledger/foundation), and funding is implemented **three times** (`funding.py` vs `portfolio_foundation.py:729` vs `project_perp_ledger.py:84`). **Root 2 — organizational (deeper):** one layer (`StrategyDecision`) fuses *alpha signal* + *sizing* (`target.size`) + *execution* (`exit_policy`); portfolio construction has no home, so it leaks **up** into strategies (the candidate's hand-rolled `active_until_by_symbol` suppression) and **down** into three backends. "Trade-vs-portfolio" is the *accounting symptom* of the *missing-owner* root (which §1's verdict already named).
2. **"Inevitable" was too strong** (corrected above): a shared-account aggregation layer nets/bounds exposure without changing the emitted unit. The ontology change buys expressivity + pre-sim auditability, not netting.
3. **Primitive is (quantity, unit), not weight** (corrected above) — denominator per asset class is an open ADR question.
4. **NAV is authoritative for the *feasibility* score, not the *only* expressible statistic** (corrected above) — keep per-bet/IC first-class for alpha research.
5. **Honesty on cost:** the single-account sim across equity-cash + FX-multi-currency + perp-margin is *modeling + data-sourcing* (multi-currency NAV needs a base-ccy path; intraday financing/margin accrues on a schedule; borrow availability is data the repo lacks — no `volume`, let alone borrow), **not** "F4 = wiring."
6. **OMS guardrail:** evaluate the book **end-of-bar on printed marks**, no working-order lifecycle, keep construction **swappable** — a single causal netted account with a leverage budget is a *backtest book*, not an OMS. As written, §1A stays inside that line; the ontology step must not drift across it.

**Decisive sequencing correction (supersedes "fix the root, break everything, rerun"):** the *accounting* root is fixable **without touching the ontology or any strategy** — do that first, surgically; the *ontology* cutover (the only repo-wide breaking change) follows once the score is already honest:
- **0a (P0, surgical — no strategy/contract changes):** promote the existing NAV book (generalized perp ledger, or the foundation path) to the **single scored object**; **net same-symbol inside it**; **delete/demote the linear-sum scorer**; make a gross/leverage breach a **typed, fail-closed verdict** (not `None`). §0 concedes NAV is already the authoritative downstream score, so this is *mostly deletion + typing*, and it closes fail-open / F3 / F7 / two-PnL immediately.
- **0b (P0/P1):** add the explicit, swappable **portfolio-construction layer** + operator-frozen **leverage budget** (§9).
- **0c (P1, repo-wide blast radius):** migrate the **emitted ontology to a declared target book** — the ergonomics upgrade that retires hand-rolled suppression. Do this **after** the score is honest, so the P0 correctness fix isn't blocked on a cutover.

**Next artifact: an ADR / OpenSpec** that (i) specifies 0a's authoritative-book contract, and (ii) settles the `(quantity, unit)` denominator and the target-book ontology for 0c, before any code.

---

## 2. Scope and evidence inspected

**In scope (locked with Season):** realism-first, broad net — live-trade feasibility plus any foundation/contract/architecture flaw that threatens iterating toward tradeable strategies. Capital model: leverage allowed but capped, *not fully decided* → assess current assumptions and recommend. Realism baseline: asset-agnostic + equities/ETFs + FX + crypto perps.

**Verified directly by the main reviewer (read in full unless noted):**
`src/quant_strategies/core/portfolio_foundation.py`, `runner/__init__.py`, `runner/economic_metrics.py`, `core/config.py`, `decisions/models.py`, `data_contract.py`, `tests/test_portfolio_foundation.py`, `openspec/specs/quick-run-portfolio-foundation/spec.md`, `docs/foundation-surfaces.md`, `docs/consumer/reference.md` (partial), a real survivor candidate (`researched/crypto_perp_funding_crowding_reversal/.../attempt-99maxgross12/`: `strategy.py`, `experiment.toml`, `protocol.toml`, `quick_config.toml`) and the thesis-level `protocol.train.toml` / `experiment.toml`, plus `engine_runner.py` / `engine/models.py` via CodeGraph.

**Verified by lens subagents (with file:line, some with numeric repros):** `engine/evaluation.py` (fills/costs/exits/funding), `core/exposure.py`, `causality.py`, `funding.py`, `core/execution.py`, `evaluation/metrics.py`, `candidates/*/run.toml`. Two lenses reproduced the flat-bar Sharpe distortion and the DSR threshold values numerically.

**Reconciled against (read by main reviewer after independent analysis):** `TODOS.md`, `docs/reviews/2026-06-04-foundation-codex.md`.

**Not verified / residual risk:**
- I did **not** execute the full pipeline against live `quant_data`, and did not inspect `quant_autoresearch` or `quant_data` source. **Which number the loop actually climbs (`economics` vs `foundation.*`) is therefore inferred** from `docs/consumer/reference.md`, the `[objective] kind = "worst_subwindow"` protocol, and the memory note — not confirmed in the consumer repo. Several severities hinge on this; where they do, I say so.
- The "shipped candidate configs use 0 bps / micro causality" claim comes from two lenses reading `candidates/*/run.toml`; I personally verified the *researched* survivor protocol uses 5+1 bps and `causality_check="off"`, and that `CostModelConfig` defaults to 0.0. Either way the foundation enforces no cost floor.
- Real per-window bar counts (materiality of the small-subwindow finding) were inferred from minute-bar cadence + hold lengths, not measured on the production panel.

---

## 3. Intended foundation model (first principles)

A research foundation whose output feeds an automated optimizer that must produce *live-tradeable* strategies has one non-negotiable property: **the number the optimizer climbs must be a faithful, conservative proxy for live risk-adjusted P&L net of every friction the strategy will actually pay.** If the proxy is optimistic in any dimension the optimizer can reach, the optimizer will find and exploit that dimension — that is what optimizers do. So the minimal honest foundation must, on the *scored* path:

1. **Account money once, as a portfolio**, on a shared capital base (compounding, netting, one NAV), not as a bag of independent per-trade returns.
2. **Charge every friction the live book pays**: realistic per-asset costs (with a non-zero floor), market impact/capacity at the intended size, financing for leverage, borrow for shorts, carry/funding/dividends/rollover per asset class.
3. **Enforce the risk contract as a hard, first-class verdict**: gross/net exposure caps, per-name caps — breaches are *findings about the strategy*, never silent absences of a diagnostic.
4. **Refuse to score** what it cannot make honest: zero-cost runs, look-ahead-unverified runs, statistically degenerate windows.
5. **Measure a statistic that corresponds to live risk-adjusted return** — on the cadence and unit a trader would recognize — not an artifact of how the calendar was padded.
6. **Be explicit about what it does not model**, so the optimizer (and Season) never mistake silence for safety.

The current foundation does (1)–(5) *partially* and only in a side-channel, and is strong on causality and funding correctness. The gaps below are measured against this model.

---

## 4. Project ontology — concepts, contracts, invariants (as built)

| Concept | Where | Note |
|---|---|---|
| Strategy (pure) | `decisions/*`, candidate `strategy.py` | `generate_decisions(rows, params)`; flat, pure; good purity discipline. |
| Decision | `decisions/models.py:150` | Frozen, strict, `extra=forbid`, deterministic `decision_id`, `as_of_time ≤ decision_time` ✓. **Only `action="open"`** — no signal-driven exits / rebalancing; each decision is an independent timed trade. |
| Position target | `decisions/models.py:111` | `target_weight` only; `size = Field(ge=0)` — **no upper bound** on per-name weight. |
| Exit policy | `decisions/models.py:127` | `max_hold_bars` + optional stop/TP/trailing, **sampled at bar close, not intrabar** (honest docstring). |
| Data row | `data_contract.py` | `available_at` **required** ✓ (PIT stamp), OHLC/quote order validated, dup keys rejected. Three `DataKind`s: `bars`, `crypto_perp_funding`, `forex_with_quotes`. **No `volume` field.** |
| Engine economics | `runner/economic_metrics.py:37` | Per-trade ledger: fractional `gross/funding/cost/net_return`, hit-rate, profit-factor, cost/funding share. **No portfolio/exposure/NAV concept.** |
| Portfolio foundation | `core/portfolio_foundation.py:177` | Re-simulates a NAV path from `executed_trades`: compounding equity, gross cap, funding, bps costs, subwindow Sharpe/DSR. **The only exposure-aware surface — and it is optional + fail-open.** |
| Feasibility / admissibility | — | **No first-class concept on the quick-run path.** Scattered: per-decision instrument/leverage guard (`engine/executable.py`), gross cap (foundation, fail-open), exposure admissibility (`core/exposure.py` — *validation path only*), free-text warnings. |

**Invariants that hold (good):** causality (`as_of_time ≤ decision_time`, `entry_lag_bars ≥ 1`, strict/focused/micro replay), funding sign/window (`entry < ts ≤ exit`, dedup, conflict-raise), structured no-raise failure results, the heavy-backend import wall on the quick-run path.

**Invariants that are missing or unenforced on the scored path:** a portfolio gross/net cap that *bites*; a non-zero cost floor; capacity vs liquidity; a minimum-sample gate before a subwindow statistic is scored; `available_at ≥ timestamp`; same-symbol netting.

---

## 5. What already exists and should be reused (preserve)

These are genuinely well-built and should **not** be touched except to extend:

- **Causality machinery** (`causality.py`, `core/config.py:68-71`): mandatory `entry_lag_bars ≥ 1`, strict/focused/micro replay, `_assert_fillable` up front. Best-in-class for a research engine. (Caveat: it can be turned *off* — see F6.)
- **Funding correctness** (`funding.py`, `_apply_funding` `portfolio_foundation.py:729`): sign and window verified by two lenses; long pays positive funding, short receives; dedup + conflict-raise. This is the **template** for the missing carry/borrow terms.
- **Decision schema** (`decisions/models.py`): frozen/strict/deterministic-id, causal time invariant — strong "make invalid states unrepresentable" design.
- **Boundary design**: `StrategyExecutionSpec` neutral kernel, no-raise structured `RunResult`, compact-by-default artifacts, the no-heavy-import wall on quick-run.
- **DSR/statistics core math** (`portfolio_foundation.py:1206-1239`): the Sharpe-SE formula `1 − skew·SR + ((K−1)/4)·SR²` with raw kurtosis is the standard Mertens/Lo form (algebraically identical to `0.5 + (K−3)/4`); DSR threshold z verified (trials 2→0.52, 12→1.67, 100→2.53). **Investigated and clean** — the kurtosis-convention worry one lens raised is *refuted*. The math is right; the *inputs* (flat-bar returns, F2) are the problem.
- **No cost/funding double-count** between economics and foundation (verified): the foundation re-derives gross PnL from raw fill prices and applies its own costs/funding, ignoring the engine's decomposition — a clean, intentional parallel model.
- **Validation/evaluation already enforce exposure admissibility and strict replay** (`core/exposure.py` via `validation/_pipeline.py`; evaluation strict preflight). The capability exists — it is simply not on the quick-run path.

---

## 6. Architecture & boundary review

### 6.1 The structural inversion (root cause)

```
                 quick-run path  (what the auto-research loop climbs)
  config.toml
      │
      ▼
  execute_strategy_run ──► decisions ──► causality check ─(can be "off"/weak "micro")
      │                                         │
      ▼                                         ▼
  engine screen ──► executed_trades ──► RunEconomics      ← per-trade ledger
      │                 │                 (NO exposure, NO NAV, NO capacity)
      │                 ▼
      │           build_portfolio_foundation  ← NAV path, gross cap, funding, costs
      │                 │                        (the ONLY exposure-aware surface)
      │                 ▼
      │         gross > cap?  ──raise──►  _build_portfolio_foundation
      │                                   except Exception → foundation=None + warning
      │                                   RUN STILL COMPLETES (succeeded=True)
      ▼
  RunResult(economics=…, foundation=…|None, evidence.warnings=[…])

  WHERE THE REAL RISK GATES LIVE (NOT on the path above):
    core/exposure.py  (gross/leverage admissibility)  ── called only by ──►  validation/_pipeline.py
    strict causality replay, scenario stress           ── live on        ──►  validation / evaluation
```

The realism-critical checks are on the **heavy downstream** path (validation/evaluation), while the **lightweight quick-run** path — the one the optimizer iterates thousands of times — has the per-trade ledger (exposure-blind) and a fail-open diagnostic. **The optimizer climbs the path with the fewest guards.**

### 6.2 Two PnL computations, two models of money

| Dimension | Engine `economics` (`engine/evaluation.py`, `economic_metrics.py`) | Foundation NAV (`portfolio_foundation.py:642`) |
|---|---|---|
| Unit | Σ per-trade fractional return, **isolated** | Compounded NAV path, shared cash |
| Cost basis | `(round_trip_bps/1e4)·weight`, flat, once | `\|notional\|·per_side_fraction`, entry+exit, scales with live equity |
| Exposure | none (trades never see each other) | portfolio gross cap (fail-open) |
| Funding | `Σ(−dir·rate)·weight` | `−signed_units·mark·rate` (marked notional) |
| Fails? | never | yes → swallowed to `None` |

These are two different simulators, not two views of one number. They diverge as trades overlap and as equity drifts from 1.0. **If the loop climbs `economics`, it climbs an exposure-blind, capital-unconstrained sum; if it climbs `foundation.*`, it climbs the realistic one — which can vanish.** There is no reconciliation test asserting they agree even in the trivial (single non-overlapping unit-weight, zero-funding) case.

### 6.3 Dead/abandoned path muddying the seam

`_decision_windows` (`portfolio_foundation.py:551`) and `_fill_price` (`:985`) are **dead** (zero callers — confirmed by three lenses via CodeGraph). The live path is trade-based (`_trade_windows`, `:600`), so `_build_scenario` receives `decisions` and `fill_model` and **discards them** (`_ = decisions, fill_model`, `:523`), while the whole call chain still threads them through. The signature lies about the dependency (foundation = f(executed_trades, rows, cost_model, data, config)), and the dead code encodes fill/lag logic that *looks* authoritative but never runs. This also hides a real coupling worth stating: **the foundation trusts the engine's fills entirely** — it cannot independently re-validate fill timing.

### 6.4 Other boundary notes
- `runner/__init__.py` is a ~1250-line module mixing orchestration, four causality modes, focused-causality file caching, and ~90 lines of evidence-dict→dataclass coercion — the load-bearing economics+foundation wiring is buried, and the fail-open is one `except` in a long file.
- `funding.py` is documented as the "single source" of funding invariants, but the foundation re-implements them by hand (different basis: weight vs marked notional) — duplication that will drift.
- Dependency direction is otherwise clean (no cycles; `engine` imports cost/fill models from `core.config`; import wall respected).

---

## 7. Engineering, testability & operability review

- **The fail-open is *tested as the accepted contract*** — `tests/test_runner_api_cli.py` asserts a foundation failure yields a completed run + a `portfolio_foundation_unavailable:` warning. Tightening it will look like a regression; the contract must be *deliberately* changed, with the test updated, not worked around.
- **No min-sample floor on the scored statistic.** `compute_return_statistics` only guards `sample_count < 2`; a subwindow with 2 returns emits a Sharpe/SE/DSR. The evaluation path has `min_annualized_samples` (default 20) + an annualization-cadence check; the quick-run foundation has neither. With default 6 subwindows over short windows, degenerate buckets dominate `min_dsr`.
- **Warnings are free-form strings**, not a typed/closed vocabulary; the unavailable warning interpolates the exception message, so consumers must substring-match and `warning_counts` won't aggregate cleanly. There is **no `foundation_available`/`foundation_status` field** — a consumer doing `result.foundation.scenarios[0]…` will `AttributeError` with only a buried warning as forewarning.
- **`_RowIndex` silently drops malformed rows** (non-str symbol / non-datetime timestamp) with no count/warning (`portfolio_foundation.py:461-465`); a dropped mark later resurfaces as a misleading `missing_mark` — then gets swallowed by the fail-open.
- **Foundation lacks the funding-timestamp alignment check the engine enforces** (`funding_timestamp_not_aligned`) — a cross-path friction inconsistency on malformed data.
- **`assessment_status="diagnostics_complete"` and `succeeded=True` regardless of strategy quality** (screen mode, `passed=None`): a zero-trade run and a great run report the same terminal status. Correct by design, but easy for an agent to misread; `promotion_eligible` is a dead field (always `False`).
- **Determinism is sound** (explicit sorts; `id(window)` keying is safe today but fragile); drawdown signs consistent; boundary attribution tested.

---

## 8. Quant execution-realism findings (the live-trade lens)

Ranked by expected live-dollar damage. "Known?" maps to `TODOS.md`/codex (see §10).

| # | Finding | Asset classes | Known? |
|---|---|---|---|
| F1 | **Costs default to 0.0; no capacity/ADV/impact; size-independent bps; 2× stress only scales bps.** Optimizer mints untradeable high-turnover edges. No `volume` field exists to size against liquidity. | all (worst: HF/turnover) | capacity **explicitly out-of-scope** in codex; zero-cost **new emphasis** |
| F2 | **Sharpe/DSR computed over flat zero-return bars** (full union-of-timestamps grid). Flat bars inflate effective sample size (~5000 vs ~50 real), collapse Sharpe SE (~0.014 vs ~0.14), flatter DSR z (~3.5) **from sample count alone**. Not annualized; no min-sample floor; tiny single-day subwindows. **Corrupts the climbed number.** | all (worst: sparse/minute) | **NEW** |
| F3 | **Gross/leverage admissibility is off the quick-run path** (`core/exposure.py` validation-only) **+ `PositionTarget.size` unbounded + foundation gross cap fails open.** Over-leverage unpenalized in the climbed number; financing for leverage never charged. | all | overstacking **known** (O14–O23); *path location* **new** |
| F4 | **Asset-class friction asymmetry**: funding modeled for perps ✓; **no equity borrow/dividend, no FX rollover/carry**; perp-style cash model = **free leverage** for equities/FX. | equities, FX | **NEW** (borrow/margin out-of-scope in codex) |
| F5 | **Stops/TP/trailing evaluated at bar close, ignore intrabar high/low; exit fills same bar; forced `max_hold` exits assume fillable printed price; `cost_stress` doesn't stress fill price.** Stops optimistic, gap risk invisible — worst for the crypto *crowding-reversal* thesis (everyone unwinds at once). | all (worst: crypto, stop-reliant) | **NEW** |
| F6 | **`causality_check` can be `"off"`; live default is weak `"micro"` (~5 probes, `strict_suppression_verified=False`)** and the run is still "scoreable." The well-built look-ahead defense is optional on the climbed path. | all | **NEW** |
| F7 | **No same-symbol netting**; gross cap on *static target* weights not live MTM; per-name concentration is a diagnostic not a cap; costs/funding charged per-ticket not net. A hedged (net-flat) book can trip the gross cap; an unwinding winner can exceed cap in MTM without tripping. | all | O18 partial (suppression ≠ bound); netting/MTM **new** |
| F8 | **PIT shallow**: `available_at` presence checked but **not `available_at ≥ timestamp`**; missing `available_at` treated as visible in replay; no survivorship/corporate-action certification consumed. | all | R4 residual partial; `≥timestamp` **new** |

**Clean (verified, not defects):** engine `_select_exit` is causal (returns at first trigger, running-max only for trailing logic); quote fills charge the bid-ask spread in the correct direction; funding sign/timing correct; no cost/funding double-count between the two paths; DSR threshold math correct.

---

## 9. The capital model — recommendation (Season's Q2: "leverage allowed, capped" + "assess & recommend")

**What the foundation currently assumes (exposed):** It is *undecided and inconsistent*. The engine ledger assumes **no portfolio at all** (unbounded implicit leverage via overlapping tickets). The foundation assumes a **perp-style margin book** (cash pays only fees; PnL marks to equity) with a gross cap that **must be ≥ 1.0** (`PortfolioFoundationConfig.max_gross_exposure`, `ge=1.0`) and that **fails open** when breached. The gross ceiling lives in the agent/runner-editable `[output]` block (`foundation_max_gross_exposure`), **not** pinned in the operator protocol the way `[cost_model]`/`[fill_model]` are — so the one realism ceiling is *less protected than costs*. The real survivor (`attempt-99maxgross12`) runs at `weight 0.2 × 1.5 long × top_n 5` ≈ up to ~1.5 gross across symbols and sets `foundation_max_gross_exposure = 1.8` to avoid the raise — i.e. it leverages, financed only by perp funding, with the cap quietly relaxed.

**Recommended target model (sound, and consistent with "leverage allowed but capped"):**
1. **Make the NAV/portfolio path the single scored unit.** The per-trade ledger becomes an attribution view of that path, not an independent number. (Closes §6.2.)
2. **An explicit gross *and* net leverage budget, operator-frozen** alongside costs/fills (move `foundation_max_gross_exposure` into the protocol-owned, agent-immutable set). Allow gross > 1 *up to the cap* — but a breach is a **first-class infeasible verdict**, never a swallowed `None`.
3. **Charge the cost of leverage.** Perp funding already does this for crypto ✓. For equities/FX, add margin/financing on gross > 1, equity short-borrow + dividends, FX rollover — mirroring `funding.py`. "Leverage allowed" must mean "leverage *priced*," or the optimizer treats it as free.
4. **Net same-symbol exposure before measuring gross / charging costs.**
5. Keep per-name caps; make concentration a real gate if live mandates require it.

This makes a capped, financed, netted >1-gross book *admissible and honestly scored* (your "2"), while exposing and replacing the current fail-open/undecided behavior (your "4").

---

## 10. Known vs. new — directly answering "what haven't we thought of?"

**Already known (don't re-litigate, but they remain open):**
- Overstacking / overlapping tickets / implicit leverage / gross > per-ticket size — `TODOS.md §2.3` O14, O17, O20–O22.
- Trade-ledger completes while portfolio foundation is unavailable; two evidence classes; risk of misreading a completed quick run as live-shaped — O15, O16.
- Per-symbol suppression doesn't bound *total* portfolio exposure — O18.
- A candidate can pass Train diagnostics yet be live-inadmissible (exposure/NAV-drawdown/leverage not yet valid evidence) — O19, O23.
- `net_return` dual semantics; causality missing-`available_at` fallback — residuals R1, R4.
- (codex, validation/evaluation surfaces) version-bounding, duplicate date fields, zero-funding-event guard, scenario coverage, CLI exit codes — codex F1–F7. **Note the codex review (2026-06-04) predates the quick-run portfolio foundation (commit `7f7ffdb`) and explicitly put "capacity, execution venue realism, borrow/margin/risk limits" out of scope — so it did not cover §8 at all.**

**Genuinely new / under-appreciated (the answer to the question):**
1. **F2 — statistical inflation of the climbed DSR by flat zero-return bars** (most important; corrupts the objective itself).
2. **Fail-*open* as silent signal-loss** — TODOS knows the foundation can be unavailable, but not that a *risk breach* is indistinguishable from a benign failure *and a test locks it in*. The fix (typed admissibility verdict) is new.
3. **Two PnL paths with divergent money-models and no reconciliation test** — which one the loop climbs determines which fiction it sees.
4. **F6 — look-ahead defense is optional/weak (`off`/`micro`) on the scored path** while a run still reads as scoreable.
5. **F4 — asset-class friction asymmetry / free leverage for equities & FX** (the objective spans all three, but only perps are financed).
6. **F5 — intrabar stop optimism + frictionless forced-exit fills**, with `cost_stress` not stressing fill price.
7. **F1 capacity re-scoped IN** — previously out-of-scope, but first-order for an automated climb; no `volume` field exists to even diagnose it.
8. **F8 — missing `available_at ≥ timestamp` guard** (cheap, local PIT defense).
9. **The realism ceiling (`foundation_max_gross_exposure`) is agent-editable, not operator-frozen like costs/fills.**
10. **Risk gates (exposure admissibility, strict causality) live on the validation path, not the quick-run path the optimizer climbs** — the precise architectural location of the gap.

---

## 11. Unknown unknowns & assumption risks

- **Which number the loop climbs — RESOLVED (see §0).** `score_research.md` confirms the loop climbs the foundation `realistic_costs` NAV path as `min(full_train PSR, worst_subwindow PSR)`, using the foundation's `sharpe`/`sharpe_standard_error`; engine economics is diagnostic-only. This makes **F2 the top fix** (it inflates the PSR score *and* the min-evidence gate via `effective_sample_size`) and **downgrades the two-PnL scoring ambiguity** (the realistic path is climbed by design).
- **Zero-cost shipped configs**: lenses report `candidates/*/run.toml` at 0 bps + `micro`. If true, current iteration is effectively frictionless and look-ahead-unproven. Verify and set per-asset cost/causality floors.
- **`quant_data` integrity** (survivorship, corporate actions, point-in-time correctness of `available_at`) is trusted blindly; contractually upstream, but a survivorship-biased Train universe is textbook fake alpha. Add the cheap `available_at ≥ timestamp` guard and require a data certification in the manifest the run already writes.
- **Strategy expressivity**: `action="open"`-only + auto-exit means the unit of strategy is an independent timed trade, not a maintained target-weight book. Real rebalancing/signal-reversal strategies can't be expressed, and "feasible here" may not map to a managed live portfolio. This is a deeper modeling boundary worth a decision.
- Row-order is owned upstream (per docs); fine if `quant_data` guarantees it.

---

## 12. Overbuilt / underbuilt / right-sized

**Right-sized (keep):** three public surfaces; flat pure strategies; `StrategyExecutionSpec`; causality machinery; funding single-source intent; no-raise structured results; import wall; compact artifacts; DSR core math.

**Underbuilt (the review's substance):** feasibility/admissibility as a first-class scored contract; cost floor + capacity/turnover diagnostic; the scored statistic (active-bar returns, min-sample gate, annualization metadata); asset-class financing/borrow/carry; gross/net leverage budget that bites; typed `foundation_status` + closed warning vocabulary; PIT `≥timestamp` guard.

**Overbuilt / cleanup:** dead `_decision_windows`/`_fill_price`; discarded `decisions`/`fill_model`; `FoundationSubwindowMetric` alias; dead `promotion_eligible`; `_trade_field` duck-typing of a typed `RunTrade`; `runner/__init__.py` god-module; foundation re-implementing funding instead of reusing `funding.py`.

---

## 13. Missing docs / decision records

- **ADR: the scored unit of return** — per-trade ledger vs portfolio NAV; which gates, which the optimizer climbs, and the reconciliation invariant.
- **ADR: the capital model** (§9) — gross/net budget, financing/borrow/carry per asset class, where the ceiling is owned (operator-frozen).
- **ADR: feasibility/admissibility contract** — what makes a quick run *scoreable* (cost floor, causality strength, min sample) vs merely *completed*.
- Doc fix: `docs/consumer/usage-guide.md` claims a single audited PnL path; there are two. Clarify `succeeded` ≠ "good strategy."
- Foundation spec: state explicitly that the foundation inherits engine fills (no independent fill validation), and that funding is reimplemented vs `funding.py`.

---

## 14. Prioritized action map

`P0`/`P1`/`P2` were the original priorities. **Status legend (updated 2026-06-10): ✅ Done · 🟡 Partial · ⏳ Deferred follow-on · 🔴 Open.**

> **RESOLVED by the `portfolio-book-spine` change (2026-06-10).** The §1A root fix shipped as the `portfolio-book-spine` OpenSpec change (branch `portfolio-book-spine`, commits `a53a1ad`…`968300d`; archived) and was validated by three independent reviews (code / quant-math / performance, archived alongside the change) that also caught and fixed one validation-gate blocker (the gate used a realized-only trade sum that diverged from the NAV on non-flat folds → a real open-at-boundary winner was rejected; now gates on the marked NAV fold return). The per-row `Status` column below reflects the **original** assessment; **current status:**
>
> - **✅ Done** — 0a, 0b, 0c, 1, 2, 4, 5, 9, 10, 12, 13, 14, 15, 16: one causal single-account netted **NAV book** is the single scored object; idempotent **target-book** contract (stacking inexpressible); typed **fail-closed** `FeasibilityVerdict` (`succeeded` gated on it); **at-risk-bar** statistics + min-sample gate (the F2 fix); operator-frozen **`[leverage_budget]`** (gross+net); one **funding** home; per-trade ledger is a **derived attribution** view (NAV↔ledger reconciled); dead code removed; gross/net **utilization** emitted; docs/ADRs shipped.
> - **🟡 Partial** — No. 3: zero-cost is now a fail-closed verdict ✅; **capacity/ADV** modeling deferred (needs a `quant_data` volume field).
> - **⏳ Deferred follow-ons** (plug into the spine's market-model interface; several need upstream data): No. 6 (tighten `off`/`micro` causality → non-scoreable), No. 7 (F4 asset-class financing/borrow/carry — guarded meanwhile by the required `unfinanced_leverage` verdict), No. 8 (F5 intrabar OHLC stop fills + fill-price stress).
> - **🔴 Open** — No. 11 (PIT `available_at ≥ timestamp` guard), No. 17 (stale `researched/` artifacts), No. 20 (rebuild candidate strategies). **No. 18–19 now ✅ Done** (knob removed; VBT purged).

| No. | Status | Priority | Action class | Finding | Recommendation |
|---|---|---|---|---|---|
| 0a | ✅ Done | P0 | Refactor | **ROOT-1 / accounting (§1A): scored statistic isn't a portfolio** | Promote the existing NAV book (generalized perp ledger, or the foundation path) to the **single scored object**; **net same-symbol inside it**; **delete/demote the linear per-trade sum** (`engine/evaluation.py:108-111`); make a gross/leverage breach a **typed fail-closed verdict**, not `None`. **Surgical — no decision-contract or strategy changes.** Absorbs No. 1/5/16 and the F7 cluster; closes fail-open. §0 concedes NAV is already authoritative downstream → mostly deletion + typing. |
| 0b | ✅ Done | P0 | Add | **Portfolio-construction layer + leverage budget (§1A, §9)** | Insert an explicit, swappable construction layer (targets→netted book, sizing, leverage/concentration policy) between alpha and the accounting spine; operator-frozen gross/net budget; breach → 0a's verdict. |
| 0c | ✅ Done | P1 | Refactor | **ROOT-2 / ontology cutover (§1A): decision = declared target book** | Migrate the emitted unit from `open`-tickets to a declared **(quantity, unit)** target book (open/close/rebalance fall out); resolve the per-asset denominator in the ADR. **Repo-wide blast radius** (every strategy/config/test). Do **after** 0a so the P0 score fix isn't blocked. Dissolves stacking at the contract. |
| 1 | ✅ Done | P0 | Refactor | Fail-open foundation (§7, §6.1; test-locked) | Split failure taxonomy: gross/leverage breach → first-class **infeasible verdict** on `RunResult` (not `None`); narrow `except Exception` to benign data-contract errors with a *distinct* typed warning; let internal bugs surface. Update the contract test deliberately. |
| 2 | ✅ Done | P0 | Refactor | F2 flat-bar Sharpe/DSR distortion | Compute return stats over **active (capital-at-risk) bars**, or expose `active_fraction`; add a **min-return-sample / min-trade gate** per subwindow before a statistic is scoreable; record cadence/annualization metadata. |
| 3 | 🟡 Partial | P0 | Add | F1 zero-cost default + no capacity | **Mandatory non-zero cost floor** (per `DataKind`) for any scoreable run; plumb a `volume`/ADV field and emit turnover + notional/ADV diagnostics, **or** contract the absence of capacity modeling explicitly on `RunResult`. |
| 4 | ✅ Done | P0 | Add | F3 leverage gate off the scored path; `size` unbounded | Run `core/exposure.py` admissibility on the **quick-run** path as a hard gate (or cap `PositionTarget.size`); make gross-budget breach the infeasible verdict from No. 1. |
| 5 | ✅ Done | P0 | Refactor | §6.2 two PnL paths | Make the **NAV path the single scored unit**; engine ledger becomes attribution; add a reconciliation invariant test (unit weight, non-overlapping, zero funding ⇒ equal within tolerance). Confirm with `quant_autoresearch` which number it climbs. |
| 6 | ⏳ Deferred | P1 | Add | F6 causality can be off / weak micro | Make `off`/`micro` runs **structurally non-scoreable** (stamp `assessment_status`/`param_contract`); the objective must gate on `evidence.causality`. |
| 7 | ⏳ Deferred | P1 | Add | F4 asset-class friction asymmetry | Add financing-on-leverage, equity borrow + dividends, FX rollover — mirror `funding.py`, gated by `DataKind`; or contract coverage per kind on `RunResult` so unfinanced P&L isn't scored net-of-cost. |
| 8 | ⏳ Deferred | P1 | Refactor | F5 intrabar stop optimism / frictionless exits | Evaluate stop/TP against intrabar low/high and fill at the level (or next-bar open); add a **fill-price stress** scenario (today `cost_stress` only scales bps). |
| 9 | ✅ Done | P1 | Add | §9 capital model | Move `foundation_max_gross_exposure` into operator-frozen protocol; allow gross>1 to cap; define gross **and net** budget; net same-symbol before cap/cost (F7). |
| 10 | ✅ Done | P1 | Add | §7 observability | Add typed `foundation_status`/`foundation_feasibility` to `RunResult`; promote warnings to a closed enum with detail in a separate field; count/warn on dropped malformed rows. Consider the enumerated `score_admissibility` shape from the Codex review (§17): `run_completed / causality_admissible / portfolio_foundation_admissible / cost_stress_admissible / score_allowed`. |
| 11 | 🔴 Open | P1 | Add | F8 PIT | Add cheap `available_at ≥ timestamp` row-contract assertion; require survivorship/corporate-action certification in the data manifest. |
| 12 | ✅ Done | P2 | Retire | §6.3 dead code | Delete `_decision_windows`/`_fill_price`; drop discarded `decisions`/`fill_model` params; delete `FoundationSubwindowMetric` alias and dead `promotion_eligible`; document that the foundation inherits engine fills. |
| 13 | ✅ Done | P2 | Refactor | §6.4 duplication/structure | Reuse `funding.py` window/dedup in the foundation; add the engine's funding-timestamp alignment check; extract causality-cache + evidence-DTO mapping out of `runner/__init__.py`. |
| 14 | ✅ Done | P2 | Refactor | M2 type boundary | Type `executed_trades` as `Sequence[RunTrade]` (or a shared Protocol); drop the mapping/`getattr` fallback. |
| 15 | ✅ Done | P2 | Add | §13 docs/ADRs | Write four ADRs (scored unit, capital model, scoreable-contract, open-ticket→target-state/rebalance ontology); fix usage-guide single-PnL claim and `succeeded` semantics. |
| 16 | ✅ Done | P1 | Add | Risk-budget utilization not reported (Codex F3, §17) | Emit `max_gross_exposure`, `mean_gross_exposure`, a gross-exposure time-integral, and `return_per_unit_gross` on full_train + subwindow records. The climbed Sharpe/PSR is leverage-invariant, but the `total_return` and `max_drawdown` **gates** are leverage-sensitive yet gross-blind, and capital efficiency can't be assessed without gross. |
| 17 | 🔴 Open | P1 | Retire | Stale research artifacts in the active repo (Codex F7, §17) | Move generated `researched/`/`candidates/` artifacts (`summary.json`/`diagnostics.json`/`artifacts/`) out of the active tree, or mark `researched/` frozen-and-excluded from agent context; add a repo-boundary test. Prevents an autonomous agent reading passed/causality-off stale artifacts as current evidence. (The repo-boundary test exists and currently fails on the untracked `researched/` dirs.) |
| 18 | ✅ Done | P1 | Refactor | **`foundation_enabled=False` → infeasible** (surfaced by the build) | **Resolved (2026-06-10): the dead knob is removed.** The portfolio book is mandatory — a run is either feasible-and-scored or a typed `feasibility` failure; there is no disabled, non-scored mode. Deleted `OutputConfig.foundation_enabled`, the runner guard, `PortfolioFoundationConfig.enabled` (read nowhere), and the disabled-foundation test. |
| 19 | ✅ Done | P2 | Retire | **Stale VBT build references** (surfaced by the build) | **Resolved (2026-06-10): purged, no scaffolding kept.** Removed the `pyproject.toml [vectorbtpro]`/`[evaluation]` extras' VBT entries, the `constraints/evaluation.txt` pin, the `evaluation/dependencies.py` VBT optional-import (dead `require_evaluation_dependencies` + `EvaluationDependencies`), the `Makefile check-vectorbtpro-smoke` target, the `vectorbtpro` purity-ban root, and the `environment.json` package entry; scrubbed the brand name from all active docs/tests/specs (deleted `docs/vectorbtpro.md`). The `vectorbtpro`/`VBT` token now appears only in git history, this review pair, and the `openspec/changes/archive/**` provenance. |
| 20 | 🔴 Open | P1 | Add | **Rebuild candidate strategies on the target-book contract** (surfaced by the build) | The four `candidates/*/strategy.py` (and `examples/simple_momentum`) still import the retired open-ticket contract (`StrategyDecision`/`ExitPolicy`); their tests are deleted and `test_committed_run_configs_use_decision_strategy_contract` is the deferred-red failure. Re-author them as `TargetDecision` target books + rerun; this clears the last deferred test. Season-owned (separate from the engine refactor). |

---

## 15. Preservation constraints (do not regress)

- Keep `run` / `validate` / `evaluate` as the only public surfaces; keep all adapting into `StrategyExecutionSpec`.
- Keep the causality machinery, funding correctness, decision schema, and the heavy-import wall on quick-run.
- Keep the foundation's parallel friction model (own costs/funding from raw fills) — fix *which path is authoritative*, don't merge the math into a double-count.
- Keep `quant_autoresearch`/`quant_data` ownership boundaries (objective, search memory, data materialization stay out of this repo). The fixes above are about *enforcing realism contracts*, not pulling in those responsibilities.

---

## 16. NOT in scope

- Strategy alpha / regime robustness / benchmark edge.
- `quant_autoresearch` and `quant_data` internals (only their contract with this repo).
- Building live OMS/broker/real-time infrastructure.
- The validation/evaluation-specific codex findings (F1–F7 there) except where they intersect the quick-run realism (cost floor, funding coverage, causality).
- Large refactors without a touched root cause.

---

## 17. Cross-check against the parallel Codex review (`LIVE_FEASIBILITY_FOUNDATION_REVIEW.md`)

A second independent foundation review (Codex, local lenses) ran on the same objective. **The two converge strongly on the core** — fail-open foundation as a P0 score-admissibility gap, causality-off/micro being scoreable, vacuous zero-cost stress, capacity/borrow/venue outside the model, open-ticket vs rebalance semantics, and "missing gates/contracts at the loop boundary, not a rewrite." Independent convergence raises confidence. What Codex *adds*:

**New findings adopted (action map No. 16–17):**
- **Risk-budget utilization is not reported (No. 16).** The foundation emits `max_symbol_concentration` but **no gross-exposure metric** (`portfolio_foundation.py:112`); concentration is *share of* gross by top symbol, not gross itself (`:1017`); the consumer reference lists no gross field (`reference.md:357`). Two candidates both admissible under the cap — one at 0.2 gross, one at 1.0 — look identical to the scorer. **Sharper than Codex's framing:** the climbed **Sharpe/PSR is leverage-invariant** (scaling positions by *k* scales mean and vol equally), and per-notional cost drag actually *penalizes* higher gross — so "more gross" does **not** inflate the climbed PSR. The real leak is (a) the leverage-sensitive **gates** `total_return` and `max_drawdown` both scale with gross but are gross-blind, so a higher-gross variant clears the return floor / risks the drawdown gate for reasons unrelated to signal quality; and (b) there's no way to compute **return-per-unit-gross** (capital efficiency). Fix: emit max/mean gross, a gross time-integral, and `return_per_unit_gross`.
- **Stale research artifacts tracked in the active repo (No. 17).** Codex reports git tracks ~351 paths under `researched/` — generated `summary.json`/`diagnostics.json`/`artifacts/` — many `quick_check_result: passed` with `causality_check="off"`, while `README.md:220` says archives don't live in active foundation context. For an autonomous agent this is **context contamination**. Boundary-hygiene, not core-number realism, but directly relevant to a loop reading the repo.

**Concrete in-the-wild evidence (upgrades my inferred findings to *observed*):**
- **Fail-open, observed:** `researched/crypto_perp_funding_crowding_reversal/candidates/survivors/attempt-99new/artifacts/summary.json` shows `quick_check_result: passed` while `portfolio_foundation_unavailable:…portfolio_target_weight_exceeds_one…1.2` is only a warning — a real survivor kept with the gross breach swallowed. Confirms No. 1.
- **Causality-off, observed:** the same artifact has `causality_check="off"`, `causality_verified=false`, *and* positive quick-check gates; and the active Train protocols' comments say "focused replay" while the setting is `causality_check="off"` (crypto `protocol.train.toml:95`, fx `:90`) — a comment/behaviour mismatch. Confirms F6.
- **Zero-cost candidate configs, confirmed:** `candidates/crypto_perp_funding_crowding_reversal/run.toml:36`, `…/crypto_perp_multivote_trend_following/run.toml:51`, `…/fx_triangular_residual_reversion/run.toml:42` all set zero fee/slippage — this **confirms** the lens-reported claim I had flagged unverified (F1, §2). A test pins committed candidates to `causality_check="micro"` (`tests/test_runner_config.py:170`), so micro is a *committed contract*, not just a default.

**Refinements:** adopt Codex's enumerated `score_admissibility` shape for the typed verdict (folded into No. 10); elevate open-ticket→target-state to a real ADR before any "live-shaped" claim (folded into No. 15).

**Superseded by `score_research.md` — do NOT adopt as a score fix:** Codex Finding 4 (require `foundation_trial_count` / no-score without it) is moot for the *live score* — the contract explicitly **excludes** DSR, PBO, MinBTL, effective-trial-count, and attempt count from the keep-rule score (`score_research.md:197-213`); selection pressure is a *process monitor*, not the candidate score. Trial-count/DSR stay as diagnostics/finalist audits. (Codex did not have `score_research.md`; this review does — §0.)

---

### What I verified vs. did not
**Verified:** the fail-open path and its test; the gross-cap raise; the zero-cost defaults and unbounded `size`; the two PnL bases; the flat-bar return construction (and two lenses reproduced the DSR inflation numerically); the dead code (CodeGraph, three lenses); funding/causality correctness; the real survivor's leverage (~1.5 gross, cap relaxed to 1.8); the DSR/SE math (clean). **Not verified by me directly:** production per-window bar counts; live `quant_data` integrity. **Resolved since drafting:** the climbed number (foundation NAV PSR — §0); the 0-cost candidate configs (confirmed by the parallel Codex review with file:line — §17); the fail-open and causality-off paths (observed in a real survivor artifact — §17). **Residual risk:** the gross-utilization leak (No. 16) is via the gates, not the Sharpe; and whether `quant_autoresearch` already reclassifies `foundation=None` as a run failure is asserted by `score_research.md:148` but unverified in its code.
