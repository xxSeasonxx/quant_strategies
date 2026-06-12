# Foundation Review — `quant_strategies` (2026-06-11)

**Reviewer:** Claude (Opus 4.8), broad first-principles foundation review (Season-requested).
**Reviewed:** working tree at branch `main`, commit `2949f35` context.
**Scope:** root docs + `docs/` + `src/`, with **quick-run end-to-end** as the priority path.
**Method:** source-as-primary-evidence; docs treated as claims to verify. Five fresh-context,
read-only perspective lenses (onboarding/author-ergonomics, architecture/over-engineering,
senior-eng/perf, adversarial-feasibility via `the-fool`, quant-math) were dispatched with the
locked objective and **forbidden from reading `docs/reviews/`** so this review is uncontaminated
by sibling reviews. The main reviewer independently traced the spine, config, contract,
feasibility chain, and the micro-causality gate, and reconciled the lens findings rather than
copying them.

> **Disposition note.** This is a *broad* review (Season-requested), not a delta review. New
> findings below are unprefixed; where a finding intersects `FOUNDATION_LOCK.md` accepted debt or
> `TODOS.md`, the intersection is called out in the finding text. Triage into `FOUNDATION_LOCK.md`
> / `TODOS.md` is Season's to make; this artifact only recommends.

---

## 1. Executive Verdict

**The core money model is trustworthy. The gaps are at the edges — and they sit exactly where
your two stated worries live: feasibility realism and hot-path/over-engineering.**

The portfolio-book spine is genuinely good work: there is **one** causal, single-account, netted
NAV walk reached by all three surfaces; the per-trade ledger is a *derived* attribution view that
**reconciles to NAV** (numerically verified); the fail-closed feasibility machinery is real,
correctly wired, and tested; fill-side, funding-sign, and barrier-fill math are textbook-correct;
and the quick path has no eager heavy imports and a cached DB engine. The signal-stacking class of
infeasibility that motivated the target-book refactor is now **structurally inexpressible** (one
signed idempotent target per symbol). That is a sound foundation.

It is **not yet** true that "passes Train ⟹ feasible to trade," because the feasibility *envelope*
has holes the verdicts do not cover, and the default Train iteration path does not enforce the one
check most associated with non-tradeable backtests:

- **Shorts are free.** `unfinanced_leverage` fires only at `net > 1.0`, so a market-neutral or
  net-short **equity/FX** book pays **zero borrow/locate** and scores feasible. (F1)
- **The "operator-frozen" envelope has no realism floor.** Cost/leverage/capacity all live in the
  agent-authored `run.toml`; the foundation cannot tell an operator-frozen envelope from an
  agent-relaxed one, and nothing rejects `max_adv_participation = 1e9`, `impact_coefficient_bps = 0`,
  `max_gross_exposure = 50`, or `fee = 1e-7 bps`. "Frozen" is a TOML-section convention, not a bound. (F2)
- **`micro` causality — the documented Train mode — cannot fail on detected look-ahead.**
  `_prepare_micro_causality_evidence` returns a hardcoded `passed=True`; a run whose own replay
  detects hidden look-ahead still reports `succeeded=True`. (F3 — verified in source)

On over-engineering: the engine is **mostly right-sized, not bloated** — but the **DSR / deflated-
Sharpe / significance machinery lives in the quick-run hot path**, while the evidence surface
deliberately omits it and the locked methodology assigns significance to the consumer. That block
is both an over-engineering wart *and* a quant-math correctness risk (its skew/kurtosis are biased
anti-conservative). Removing it from the spine is the single highest-leverage simplification. (O1)

On stale docs: the active docs are unusually fresh and consistent — with one **load-bearing
contradiction**: root `README.md` still says `RiskRule` exits fill on the *end-of-bar close*,
the exact opposite of the shipped intrabar-barrier engine. (D1)

**Bottom line:** the foundation is close. None of the findings require a rewrite; the heaviest is
a focused boundary fix. Closing F1/F2/F3 makes the G8 "passes ⟹ tradeable" promise honest;
O1 + O2 trim the hot path; D1–D4 restore doc trust. I would not let the autoresearch loop optimize
against the current quick-run number until F2/F3 are addressed, because the climb can be helped by
free shorts, a relaxed envelope, or undetected look-ahead.

---

## 2. Scope and Evidence Inspected

**Read in full or in depth (main reviewer):** `PRD.md`, `README.md`, `FOUNDATION_LOCK.md`,
`TODOS.md`, `docs/foundation-surfaces.md`, `docs/consumer/README.md` (+ heads of `reference.md`,
`usage-guide.md`, `MIGRATION-portfolio-book-spine.md`); `core/portfolio_foundation.py` (all 2346
lines), `core/config.py`, `runner/config.py`, `runner/__init__.py` (feasibility + causality gating
regions), `decisions/models.py`, the `simple_momentum` example and the
`crypto_perp_funding_crowding_reversal` candidate (+ both `run.toml`s); causality structure via
CodeGraph; `succeeded` gate via tests.

**Covered by lenses (read-only, fresh context):** full quick-run trace and contract surface
(onboarding); whole `src/` boundary/duplication map (architecture); quick-run perf with empirical
micro-benchmarks (senior-eng); the full feasibility envelope attacked for holes (adversarial); the
PnL/stat/funding/fill math with numeric verification of NAV↔ledger, Sharpe-SE, and DSR (quant-math).

**Not deeply inspected (per locked scope — eval/validation as one-run filters):** the internals of
`validation/_pipeline.py` and `evaluation/_pipeline.py` beyond confirming they route through the
**same** `build_portfolio_foundation` / `walk_portfolio_book` and the same feasibility verdict.
`docs/reviews/` siblings were deliberately not read. `quant_autoresearch` is a separate repo and
out of scope; several findings note where the risk depends on its behavior.

**Tooling caveat:** CodeGraph cross-module *edge* resolution was unreliable for this codebase
(`build_portfolio_foundation`/`run_config` returned no callers); call-tracing was grep/Read-verified.
Structural conclusions rest on direct reads.

---

## 3. Intended Foundation Model (north star, restated for this review)

The unit of simulation is **one causal, single-account portfolio, not an isolated trade.** A
strategy is a pure function emitting a **target book** — a standing signed weight-of-NAV per
instrument, idempotent so same-symbol exposure nets and cannot stack — with optional declared
price-path `RiskRule`s. The engine folds that book into one netted, financed, marked walk and
scores its **NAV path** (the single authoritative scored object); the per-trade ledger is a derived
attribution view. The contract is two-sided: **enable** any complete tradeable portfolio in
`strategy.py`, and **guarantee** that whatever passes Train evidence is genuinely feasible to trade.
An envelope breach is a typed **fail-closed** verdict, never clamped, never a silent `None`. The
strategy owns the portfolio; the foundation owns accounting, the market model, and the
operator-frozen envelope.

A minimal-but-sufficient foundation therefore needs exactly: (1) a pure target-book contract that
makes infeasible *shapes* inexpressible; (2) one money model; (3) a feasibility envelope whose
breaches fail closed **and whose realism the strategy author cannot relax**; (4) a causal-replay
gate that actually gates; (5) a fast quick-run path for iteration; (6) heavier one-run filters
(validation/evaluation) over the *same* model; (7) docs that state each contract once. The review
measures the code against this.

---

## 4. Project Ontology — Concepts, Contracts, Boundaries, Invariants

| Concept | Owner in code | Invariant that must never be violated |
|---|---|---|
| Target book | `decisions/models.py:TargetDecision` | one signed idempotent target per (symbol, decision_time); `as_of_time ≤ decision_time` |
| Risk rule | `decisions/models.py:RiskRule` | price-path-only exits; engine-enforced on net position; fractions of entry mark |
| Money model | `core/portfolio_foundation.py:_walk_book` | one netted cash/margin account; NAV path is the only scored object |
| Ledger | `RoundTrip` / `RunEconomics` | Σ realized_pnl == final_NAV − initial_equity (derived, never independently scored) |
| Feasibility | `FeasibilityVerdict` + `_check_intended_budget` / `_scenario_feasibility` | breach ⇒ typed fail-closed verdict ⇒ `succeeded=False`; never clamp, never silent `None` |
| Envelope | `core/config.py` (`Cost`/`Capacity`/`LeverageBudget`/`CausalityPolicy`) | operator-frozen; the strategy author cannot relax it |
| Causality | `causality.py` + runner gating | a usable scored run must have its look-ahead replay *gate*, not merely *annotate* |
| Data boundary | `core/data_loader.py` | `quant_data` owns acquisition/ordering/`available_at`; this repo never sorts/loads/caches |

The findings below are, in effect, the places where the **bolded invariants leak**: the envelope
invariant (F2), the feasibility-completeness invariant for shorts (F1), and the causality-gate
invariant on the default mode (F3).

---

## 5. What Already Exists and Should Be Reused (Preserve)

These are load-bearing and correct; **do not disturb them while fixing the findings.**

1. **One spine, verified.** Exactly three call sites of the book (`runner/__init__.py:794`,
   `validation/engine_backend.py:52`, `evaluation/spine_backend.py:158` via `walk_portfolio_book`).
   No forked money model by surface or data kind. (architecture lens)
2. **NAV ↔ ledger reconciliation has teeth.** `Σ round_trip.realized_pnl == final_NAV −
   INITIAL_EQUITY` verified numerically across costs/multi-symbol/funding/reversal, and asserted in
   `tests/test_portfolio_foundation.py:879`. (quant-math lens)
3. **Fail-closed verdict is real and tested.** `FeasibilityError(ValueError)` is caught *before* the
   generic `except (ValueError, RunnerError)` (`runner/__init__.py:811` vs `813`); leverage breach →
   typed `feasibility` failure_stage with `observed_gross` (`tests/test_runner_api_cli.py:2007`).
   No crash-as-pass, no silent `None`.
4. **Fill / funding / barrier math is correct.** Quote fills cross the correct side (no free
   half-spread); barrier fills gap-worsen and grant no favorable bonus; funding sign
   (`−signed_qty·mark·rate`) and window (`entry < funding_ts ≤ now`) are right; `entry_lag_bars ≥ 1`
   is enforced so same-bar fills are impossible. (quant-math lens; lag confirmed by main reviewer)
5. **Target-book contract makes signal-stacking inexpressible** by construction
   (`decisions/output_validation.py` one-target-per-(symbol,time); idempotent netting in
   `_apply_decision`). The motivating defect is structurally fixed.
6. **Hot path is import-disciplined.** No eager `pandas`/`numpy`/`pyarrow`/`quant_data` on
   `import quant_strategies.runner`; loaders are lazy proxies; DB engine cached, not per-run
   reconnected. (senior-eng lens)
7. **Artifact-profile honoring is tested** (`summary` writes no full artifacts, < 75 KB on 2000
   rows). Manifest hashing is deterministic and excludes self-referential files.
8. **Consumer docs (`docs/consumer/`) are model-grade for LLM authoring** — the "For AI agents"
   block, anti-patterns list, and pre-flight checklist are exactly right. (onboarding lens)
9. **Honest naming and honest purity lint** — no `validated_alpha`, no "return" for a linear sum;
   purity lint states plainly it is a best-effort AST denylist, not a sandbox.
10. **Right-sized abstractions to keep:** `extended_ontology.py` (cleanly staged, surface-excluded,
    roadmap-anchoring); `data_contract.py` (large but single-concept); per-surface
    `events.py`/`artifacts.py` thin adapters over `core/events.py`; one-impl `Protocol` backends as
    test seams. (architecture lens — do **not** "simplify" these away)

---

## 6. Architecture and Boundary Review (over-engineering concern)

**Verdict: mostly right-sized. One genuine misplacement, two clean extractions, the rest is fine.**

- **O1 — DSR/significance in the quick-run hot path is misplaced** (see §9 action map). The spine
  computes deflated-Sharpe, expected-max-Sharpe, autocorrelation-adjusted effective-N, skew, and
  kurtosis on *every* run for 2–3 scenarios × 6 subwindows — yet `evaluation/_spine_metrics.py:15`
  explicitly refuses to ("significance is the consumer's job") and `FOUNDATION_LOCK.md` says the
  quick-run DSR is "not survivor-grade." Significance is a property of a *search over many
  candidates*, which only the consumer knows. This is ~12 statistical functions earning their keep
  nowhere the spine owns. **Retire from the spine** (keep descriptive mean/vol/sharpe).
- **O2 — `portfolio_foundation.py` (2346 LOC) is two concepts on a clean seam.** Lines ~1–1569 are
  the causal walk + accounting + feasibility; lines ~1570–2346 are a self-contained
  return-statistics library operating on `Sequence[float]`. **Extract `core/return_statistics.py`**
  (pure move + import). This also gives evaluation a shared home for stats it currently duplicates.
- **O3 — Causality mode vocabulary is baroque.** Three literal types describe "what replay":
  `causality.py:ReplayScope` (7 values), `runner/config.py:CausalityCheck` (5), and
  `core/config.py:CausalityReplayScope` (2), with a dead `"complete"` scope value that *also*
  collides with a data-availability status string, and two disjoint dialects (runner:
  micro/focused; eval+validation: bounded/complete) over the *one* real engine
  `check_hidden_lookahead`. **Simplify to one reachable enum**; each surface advertises its subset.
  (This is the accreted residue of the O1–O10 focused-timeout pain in `TODOS.md` — real cause,
  baroque result.)
- **O4 — Stats helpers triplicated** (`_sample_stdev`/`_profit_factor`/`_downside_deviation`/
  win-rate across `portfolio_foundation.py`, `evaluation/_spine_metrics.py`,
  `runner/economic_metrics.py`). Collapse into O2's module. Net deletion.
- **O5 — Layering inversion:** `core/engine_runner.py:9` imports the runner DTO `RunEconomics`
  (`TYPE_CHECKING`-guarded, single caller in `runner/`). `core` must not name `runner`. **Move
  `engine_runner.py` into `runner/`.**
- **O6 — Config base duplicated:** `validation/config.py` / `evaluation/config.py` re-declare
  `model_config = ConfigDict(extra="forbid", frozen=True)` and duplicate path helpers instead of
  extending `core/config.py:SharedConfigModel`. Minor drift hazard; lift to one owner.

None of O1–O6 is a rewrite; all are focused, mostly-deleting refactors. The "one spine," the
three-surface adapter symmetry, and the `quant_data` boundary are right and should be preserved.

---

## 7. Engineering, Testability, and Operability Review (quick-run perf + robustness)

- **P1 — The default `causality_check = "strict"` is uncapped and O(rows²)** in strategy
  re-execution (`runner/config.py:102`; `strict_probe_limit` default `None`). Empirically ~4× per
  row-doubling; for the 1M-row G6 ceiling this is minutes, not seconds. The committed candidate
  `run.toml`s dodge it by setting `causality_check = "micro"`, and the convention documents micro for
  Train — but **defaults must be safe**, and an LLM/agent that omits the field silently goes
  quadratic. Compounding: `tests/test_performance_regressions.py:636` *claims* strict-default perf is
  covered by integration budgets — **that test does not exist** (the only runtime-bound replay test
  is `focused`). Change the default to a bounded mode (or require a `strict_probe_limit`), and add
  the missing strict perf-budget test. (senior-eng lens, empirically confirmed)
- **P2 — `adv_notional_before` is O(events × rows_per_symbol)** (`portfolio_foundation.py:641`):
  a full linear scan + per-row notional recompute on *every* execution event, despite `by_symbol`
  already being sorted. With capacity on (the candidate configs use `adv_impact`) and a high-turnover
  strategy this stacks a second quadratic. Fix: `bisect` the prefix end + a per-symbol prefix-sum of
  notional computed once in `_RowIndex.__init__`.
- **P3 — Row hashing JSON-serializes every row** (`data_contract.py:926`), ~15 µs/row → ~15 s at 1M
  rows, and runs **twice** when a load window differs (`data_loader.py:78` + `execution.py:138`).
  Hash from the already-sorted `storage` primitives instead of `json.dumps` per row; avoid the second
  full normalization.
- **P4 — Double marking per bar:** `_equity_at_mark` then `_exposures` each loop open positions and
  call `mark_at` (`portfolio_foundation.py:887-890`). Fold into one pass. (Low; constant factor.)
- **P5 — `include_diagnostics=True` is unconditional** even for the `summary` profile that discards
  the diagnostic trades (`runner/__init__.py:279` then pops them at `:887`). Gate on profile. (Trivial.)

**Tests are a genuine strength** (23k test LOC vs 16.8k src; reconciliation, feasibility verdicts,
at-risk gate, artifact profiles, and the `succeeded` derivation are all asserted, not smoke) — with
the one stale "covered elsewhere" comment in P1 as the exception.

---

## 8. Domain Lens — Quant-Math Findings

**Verdict: the scored number's accounting and the headline formulas are correct;** the one real
defect feeds the (misplaced) DSR.

- **Q1 (High) — Biased skew/kurtosis.** `_shape`/`_shape_from_chunks` center by the **sample** (n−1)
  stdev but divide the 3rd/4th moments by **n** — a mongrel that biases kurtosis low. It feeds the
  Lo/Mertens Sharpe SE → **understates SE → overstates DSR** (anti-conservative: heavy-tailed
  strategies look more significant than they are). **This is moot if O1 removes DSR from the spine;**
  otherwise use a consistent (population or Fisher-Pearson) convention.
- **Q2 (Medium) — DSR/Sharpe scoreable on a 2-sample.** `min_return_sample` default `2` lets a Sharpe
  (and a per-subwindow DSR) compute on `N_eff − 1 = 1`. Statistically meaningless and gameable by the
  climb. Raise the *scoring* floor and/or expose it as operator-frozen. (= F5; the spirit of G8's
  "statistically degenerate sample" verdict.)
- **Confirmed correct, preserve:** NAV↔ledger reconciliation, fill-side selection, barrier fills,
  long/short risk-rule symmetry, funding sign/window/dedup, Sharpe SE (Mertens), DSR threshold
  (Bailey–López de Prado expected-max-of-N), exposures (intended-weight budget is the right
  lookahead-free quantity), honest units/naming, downside-deviation normalization, and the documented
  `quant #4/#5/#6` accepted approximations (the at-risk entry/exit asymmetry is **not** a cost-timing
  leak — verified).

---

## 9. Prioritized Recommendations / Action Map

`Status`: `open` = new finding, not yet actioned. `Priority`: P0 (feasibility integrity + headline
stale doc) → P1 (high value) → P2 (cleanups). Action class per the review method:
Preserve / Refactor / Simplify / Add / Retire. Disposition vs `FOUNDATION_LOCK.md`/`TODOS.md` is in
the detail column.

| No. | Status | Priority | Area | Finding (evidence) | Action | Class |
|---|---|---|---|---|---|---|
| 1 | open | P0 | Feasibility | **Shorts pay zero borrow and aren't fail-closed at `net ≤ 1`.** `unfinanced_leverage` keys on `net>1.0`; a L/S equity/FX book (gross≤budget, net≤1) finances shorts for free (`portfolio_foundation.py:1522`, `_FINANCED_DATA_KINDS:38`). *Disposition: `TODOS.md` O14 tracks the borrow **data** as coverage-blocked, but the **fail-closed gap for net≤1 shorts** is new — the accepted-debt framing only covers net>1.* | Fail-closed `unfinanced_short` verdict when an intended short exists on a kind with no modeled borrow (or a frozen flat-bps borrow charge). | Add |
| 2 | open | P0 | Feasibility | **No realism floor on the "operator-frozen" envelope.** `max_bar/adv_participation` only `gt 0` (accepts 1e9), `impact_coefficient_bps` `ge 0` (accepts 0), `max_gross_exposure` `ge 1` (unbounded), cost only the exact-zero floor (`1e-7 bps` passes) — `core/config.py:103-155`, `_scenario_feasibility:1552`. "Frozen" = TOML-section convention; the foundation can't tell operator-frozen from agent-relaxed. *Disposition: new; this is the general form of Season's feasibility worry.* | Add realism bounds in the two config validators (`participation ≤ 1.0`, `impact_bps > 0` under `adv_impact`, a `gross` soft-cap needing explicit override, a cost floor > epsilon); record envelope provenance. | Add + Refactor |
| 3 | open | P0 | Feasibility | **`micro` causality cannot fail on detected look-ahead.** `_prepare_micro_causality_evidence` returns hardcoded `passed=True` (`runner/__init__.py:483-490`); the real verdict is advisory-only, so `succeeded=True` even when micro detects hidden look-ahead / non-determinism. The default Train iteration mode therefore can't gate the #1 non-tradeable defect. *Verified in source. Disposition: tension with `FOUNDATION_LOCK.md` "causality scoreability gate."* | Return the real `micro` `passed`/`violations`, **or** if micro is intentionally advisory, narrow the PRD/LOCK claim and mark micro runs non-feasibility-bearing. | Refactor |
| 4 | open | P0 | Over-eng + Quant | **DSR/significance machinery in the quick-run hot path** (`portfolio_foundation.py:1694-2298`), which evaluation omits and the consumer owns; also carries the Q1 biased-moment risk. | Retire DSR/trial-count/benchmark-Sharpe from the spine; expose `compute_return_statistics` as a separate utility; keep descriptive stats. | Retire |
| 5 | open | P0 | Stale doc | **`README.md:135-139` says `RiskRule` exits fill "end-of-bar... not intrabar high/low"** — the exact opposite of the shipped engine (`portfolio_foundation.py:1390-1460`), `FOUNDATION_LOCK.md:37`, `foundation-surfaces.md:196`. Load-bearing contract, wrong in the canonical entry doc. | Replace with the intrabar-barrier semantics (or link to the `RiskRule` owning section). | Retire |
| 6 | open | P1 | Perf | **Default `causality_check="strict"` is uncapped O(rows²)** (`runner/config.py:102`), violating G6; the "covered by integration budgets" test doesn't exist (`test_performance_regressions.py:636`). | Default to a bounded mode (or require `strict_probe_limit`); add the missing strict perf-budget test. | Refactor |
| 7 | open | P1 | Ergonomics | **`available_at` — the causal linchpin — is absent from the code contract surface (`decisions/models.py`) and the root README;** only in `docs/consumer/`. Authors land on the types/README and gate on `timestamp` (the documented anti-pattern). | Document the row schema + "gate on `available_at`" at the import site and in README. | Add |
| 8 | open | P1 | Feasibility | **`min_return_sample` default `2`** lets a meaningless Sharpe/DSR be scoreable and gameable (`portfolio_foundation.py:27`; not exposed in `OutputConfig`). | Raise the scoring floor; expose as operator-frozen. | Refactor |
| 9 | open | P1 | Feasibility | **Non-aligned multi-symbol calendars fail as a raw `missing_mark` ValueError, not a typed verdict** (`_walk_book` iterates the union; `mark_at` raises — `portfolio_foundation.py:614,814,2040`). Fail-closed (good) but over-strict on the north-star multi-asset book and presented as a confusing data error. | Carry-forward last mark with a staleness bound + typed `stale_mark`, or a typed `nonaligned_calendar` verdict; document the calendar assumption. | Refactor |
| 10 | open | P1 | Over-eng | **Extract `core/return_statistics.py`** from the 2346-line spine (clean seam ~line 1570); dedupe the triplicated stats helpers into it. | Split + dedupe (net deletion). | Refactor + Simplify |
| 11 | open | P1 | Over-eng | **Collapse the 3 overlapping causality mode vocabularies** to one reachable enum; drop the dead/colliding `"complete"` scope. | Consolidate naming; keep the single `check_hidden_lookahead` algorithm. | Simplify |
| 12 | open | P1 | Stale doc | **`foundation-surfaces.md:346-348` claims the examples/candidates don't implement the target-book contract — they do** (`simple_momentum`, `crypto_perp_funding_crowding_reversal`). The caveat misleads authors away from the only correct references. | Delete the stale caveat. | Retire |
| 13 | open | P1 | Doc discipline | **North-star contract restated in 8 active docs; two "front door" READMEs; no `HISTORY.md`** despite migration/chronology living in active `docs/consumer/MIGRATION-portfolio-book-spine.md`. MECE violation (D1 was its first drift casualty). | One owning section + links; add `HISTORY.md`; move migration chronology there. | Simplify + Add |
| 14 | open | P2 | Feasibility | **Single-name concentration never gated** (computed at `_exposures:2064`, never compared to a limit). A 100%-one-name book passes. | Optional operator-frozen `max_symbol_concentration` → `concentration_breach`. | Add |
| 15 | open | P2 | Ergonomics | **Protocol says `rows`; all strategies name the param `bars`** (wrong for `forex_with_quotes`). | Rename to `rows` in examples/candidates. | Refactor |
| 16 | open | P2 | Ergonomics | **No minimal hello-world example;** the sole example is a 128-line re-arming machine. | Add `examples/minimal_target_book/`. | Add |
| 17 | open | P2 | Ergonomics | **`RunResult` nesting population rules are implicit** (`foundation`/`economics` `None` unless `succeeded`); easy `AttributeError` for an agent consumer. | Add gated accessors or field docstrings stating the precondition. | Add |
| 18 | open | P2 | Perf | **`adv_notional_before` O(events×rows)** and **JSON-per-row hashing (~15 s/1M, ×2 with load window)**. | `bisect` + prefix-sum; cheaper canonical hash; single normalization. | Refactor |
| 19 | open | P2 | Perf | **Double marking per bar** (`:887-890`) and **`include_diagnostics=True` for `summary`** (`:279`). | Single-pass marking; gate diagnostics on profile. | Simplify |
| 20 | open | P2 | Over-eng | **`core/engine_runner.py` imports a `runner` DTO** (layering inversion) and **config base duplicated** in validation/evaluation. | Move `engine_runner.py` into `runner/`; extend `SharedConfigModel`. | Refactor + Simplify |

---

## 10. Preservation Constraints / Right-Sized Boundaries

Keep these stable (no follow-up work; flagged so a future change does not "improve" them away):

- The **one-spine** money model and its three call sites; the `build_portfolio_foundation`
  (two-scenario+stats) vs `walk_portfolio_book` (single-scenario) split is the correct boundary.
- The **NAV-as-only-scored-object / ledger-as-derived** contract and its reconciliation test.
- The **fail-closed-before-generic-except** ordering and the typed `FeasibilityVerdict`.
- `extended_ontology.py` as **staged, surface-excluded** scaffolding (trim sizing axes if desired;
  do not delete — it anchors the multi-asset roadmap).
- `data_contract.py` as one cohesive concept; per-surface `events.py`/`artifacts.py` thin adapters;
  one-impl `Protocol` backends as test seams.
- The lazy `quant_data` loader boundary and the import-disciplined hot path.

---

## 11. Unknown Unknowns / Assumption Risks

- **Envelope provenance depends on `quant_autoresearch` (out of scope).** F2/F1/F3 are *foundation*
  gaps; whether they bite in practice depends on how the sibling repo templates configs and which
  causality mode it runs. The foundation cannot assume that repo is correct — which is the point.
- **Evaluation/validation causality default not fully traced.** F3 is confirmed for quick-run. Whether
  the downstream one-shot gate forces a *scoring* causality mode (making F3 quick-run-only) is the one
  cross-surface check to run before relying on validation/eval to catch look-ahead.
- **Evaluation's per-fold walk skips the `zero_cost`/`insufficient_samples` scenario gates** (only
  leverage/unfinanced/capacity apply in `walk_portfolio_book`). Intentional and documented, but it
  means the feasibility envelope is **not identical** across surfaces — worth stating explicitly in
  the contract so "same book everywhere" isn't over-read.
- **Perf numbers are micro-benchmarks on synthetic rows** (no production DB); they establish
  complexity classes, not absolute wall-clock on real data shapes.
- **`min_return_sample` for the evaluation surface** was not traced; if it also defaults to 2, Q2/F5
  extends to the gate that matters most before paper.

---

## 12. Architecture & Lifecycle Diagrams

```text
QUICK-RUN PIPELINE (priority path)                         feasibility gate (fail-closed)
─────────────────────────────────                         ──────────────────────────────
 experiment.toml ─┐                                         _check_intended_budget (mid-walk)
 strategy.py ─────┤                                            ├─ gross/net > budget → leverage_budget_breach
        │  load_config (RunConfig)                             └─ net>1 & !financed → unfinanced_leverage
        ▼                                                    _capacity_execution_event (per trade)
 execute_strategy_run                                          ├─ mode=off & traded → capacity_unpriced
   import → validate_params → load rows (quant_data)           ├─ forex+adv     → ..unsupported_volume_semantics
   → freeze → generate_decisions → TargetDecision[]            ├─ missing vol   → capacity_missing_volume
        │                                                      ├─ short ADV hist→ ..insufficient_adv_history
        ▼                                                      └─ part. > limit → capacity_limit_breach
 observation audit ──► causality_check ──┐                  _scenario_feasibility (post-walk)
        │              (micro=ANNOTATE,   │                    ├─ scoreable & cost≤0 → zero_cost
        │               strict/focused=   │                    └─ sample<min       → insufficient_samples
        │               GATE — see F3)    │
        ▼                                 ▼                  GAPS (this review):
 build_portfolio_foundation ── FeasibilityError? ──► fail   ✗ short borrow at net≤1 (F1)
   _walk_book ×{realistic, stress[, fill_stress]}           ✗ envelope realism floor (F2)
     funding → riskrule(intrabar) → decisions → mark NAV    ✗ micro look-ahead gate (F3)
        │                                                   ✗ concentration (F4/#14)
        ▼                                                   ✗ nonaligned calendars→raw error (F6/#9)
 RunResult{outcome, evidence, economics, foundation, feasibility}
   succeeded = completed & failure_stage is None & feasible
        │
        ├──────────────► validation run  ┐  same book + same verdicts,
        └──────────────► evaluation run   ┘  heavier replay + scenarios (one-run filters)
```

---

## 13. NOT in Scope

- Implementation of any finding (this is a review artifact; Season triages into
  `FOUNDATION_LOCK.md`/`TODOS.md` and decides the policy calls flagged in #2/#3/#8/#14).
- `quant_autoresearch` internals (separate repo); deep validation/evaluation pipeline internals
  (treated as one-run filters per the locked scope, confirmed to share the spine).
- `candidates/`, `researched/`, `tests/`, generated `results/` as review *targets* — they are
  changeable and were read only as evidence.
- Re-litigating accepted debt in `FOUNDATION_LOCK.md` (independent netted-book cross-check,
  asset-class financing realism beyond crypto perp) except where a finding newly intersects it (#1).

---

## 14. Verification Statement

**Verified:** the spine, config, contract, feasibility chain, and the F3 micro-causality gate were
read directly in source; NAV↔ledger reconciliation, Sharpe-SE, and DSR were numerically checked by
the quant lens; the strict-default quadratic was empirically reproduced by the senior-eng lens;
`entry_lag_bars ≥ 1` and the D1/D2/D3/D4 doc states were confirmed by the main reviewer.
**Not verified:** absolute wall-clock on production data; evaluation-surface causality default and
`min_return_sample`; `quant_autoresearch` config behavior. **Residual risk:** the P0 feasibility
findings (F1/F2/F3) mean the current quick-run `succeeded` does **not** yet fully back the
"passes ⟹ tradeable" promise; until they are closed, treat a passing quick run as "feasible within a
trusted, realistic envelope and a gating causality mode," not as an unconditional guarantee.
