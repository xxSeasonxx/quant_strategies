# Foundation Review — `quant_strategies` (Claude, senior-quant lens)

**Date:** 2026-06-03
**Reviewer:** Claude (Opus 4.8), as senior quantitative researcher + math-correctness lens
**Method:** First-principles, code-as-primary-evidence foundation review. Objective taken
from `PRD.md` and locked with Season. Five independent fresh-context lenses
(onboarding, architecture, senior-engineering, adversarial/`the-fool`,
quant-math/`quant-math-code-review`) plus my own re-derivation of the core math.
**Independence:** I did **not** read `review-codex.md` (your prior Codex review) to keep this
uncontaminated. I treated `PRD.md`, `README.md`, `FOUNDATION_LOCK.md`, and
`docs/foundation-surfaces.md` as **claims to audit**, not binding constraints — per your
"challenge the design / don't be biased by existing output" instruction.
**Disclosed fallback:** the `the-fool` and `quant-math-code-review` lenses were run from prompt
criteria inside general-purpose subagents (the named skills were not loadable in-subagent).
**Lock disposition:** `FOUNDATION_LOCK.md` says "do not reopen accepted tradeoffs." I am
deliberately surfacing several of those anyway, tagged `[lock: accepted_debt]` /
`[lock: deferred]`, because your question is *"is the foundation good to begin running"* and
you explicitly asked me not to be anchored by prior dispositions. Nothing here is reopened
frivolously.

---

## 1. Executive Verdict

**GO. This is a sound foundation and it is good to begin running. I found no critical math
error and no blocker.**

I re-derived the core math from source and the quant-math lens confirmed it numerically against
a real VectorBT Pro install:

- Per-trade PnL `gross = direction·(exit−entry)/entry·weight`, `net = gross + funding − cost`
  — signs correct for long/short, costs round-trip, entry lag default 1 (no same-bar fill).
- Funding sign `Σ(−direction·rate)·weight`, window `entry < ts ≤ exit` — **long pays positive
  funding, short receives** — identical window in both the engine and the perp-ledger paths.
- Perp NAV marks **unrealized** PnL only (`cash + Σ units·(mark − entry_fill)`) — no notional
  double-count; fees/slippage directions correct.
- Risk metrics: `Sharpe = (mean/stdev)·√P`, geometric `annualized_return`, sample stdev (n−1),
  drawdown `(nav/peak)−1 ≤ 0`, zero-variance and <2-sample guarded to `None`. Annualization is
  **required explicit config**, not an inferred-frequency guess — this sidesteps the single most
  common quant stats bug.
- Engine↔vbt agreement: **deviation = 0.0 at machine precision** for long, short (rising and
  falling), and partial weights.

The discipline here is **above typical** for a research backtester: a single shared decision
kernel, a dual-direction lookahead replay (it catches both future-data-*changes-a-decision* and
future-data-*withholds-a-losing-trade* — most stacks never check the second), honest metric
naming (`sum_signed_trade_activity_*`, *never* called "return"), and per-metric unit/base tags.

**What keeps this from being an unqualified "ship it" for an autonomous tight loop** is not a
bug — it's the **thinness of the independent verification net on the paths that matter most**,
plus **vocabulary/representation accretion** at the result-interpretation layer (your "layered
on layered" instinct is partially right, but not where you'd expect). Concretely:

1. The verdict the consumer ranks on (`net_return`) is **self-certified for every multi-trade
   strategy** — the cross-backend oracle is single-trade-only and off by default. *The math is
   correct today; there is simply no tripwire to catch a future regression on the dominant path.*
2. The **`project_perp_ledger_v1`** NAV engine (the most intricate math in the repo) has **no
   cross-check and no numeric pin test** — only structural and zero-value tests.
3. Risk metrics are correct **given** `annualization_periods_per_year`, but nothing checks that
   the supplied value matches the data's actual bar cadence, and the NAV return series includes
   flat (no-position) bars — so a misconfigured loop can rank on a mis-scaled Sharpe.

None of these block first runs. All three are cheap to harden and worth doing **before
`quant_autoresearch` ranks thousands of candidates on these numbers.** Section 12 prioritizes.

**On your specific worries:**

| Your concern | Finding |
|---|---|
| Critical math error? | **None found.** Re-derived + numerically confirmed. Highest-confidence part of this review. |
| Over-engineering? | **Mostly no.** `causality.py`, `data_contract.py`, `funding.py`, the test suite are right-sized. Real accretion is narrow: 4 parallel verdict vocabularies + a live legacy `screen/gate` layer, and `evaluation/backend.py` doing three jobs. |
| Workflow simple? | **Yes to invoke** (3 CLI cmds → 3 APIs → 1 pure contract). **No to interpret** — the *result objects* carry 4 "did it work" vocabularies and leaked internals. |
| Layered on layered? | **Not in the call graph** (deps are clean, one shared kernel, `__init__` modules are cohesive pipelines, not god-functions). **Yes in the vocabulary/result surface.** |
| Legacy / compat / artifact bias? | **No back-compat shims** (NG5 honored). Artifacts are gitignored + disposable — safe to rerun. The only "legacy" is the conceptual `screen/gate/EvidencePacket/evidence v4` layer beneath the newer surface. |

---

## 2. Scope and Evidence Inspected

**In scope (locked):** this repo only — strategy contract, execution kernel, the three public
jobs, `decisions/purity` lint, public consumer surface. `quant_data` and `quant_autoresearch`
treated as external contracts (boundary audited, internals not).

**Evidence I read directly** (primary): `decisions/models.py`, `engine/models.py`,
`engine/evaluation.py`, `funding.py`, `core/execution.py`, `causality.py`,
`validation/agreement.py`, `runner/economic_metrics.py`, `evaluation/metrics.py`,
`decisions/purity.py`, `evaluation/backend.py` (perp ledger 489-661, metrics 761-905, stat
helpers 1185-1199, `_equity_at_mark` 724-742), plus `pyproject.toml`, structure/LOC,
`PRD.md`, `FOUNDATION_LOCK.md`, `docs/foundation-surfaces.md`.

**Verified numerically** (quant-math lens, real vbt): engine↔vbt agreement dev=0.0; 261
math-relevant tests pass.

**Not verified / residual risk:** multi-bar perp funding under price drift (perp tests hold
close flat); multi-symbol vbt basket NAV; how `quant_autoresearch` actually consumes result
fields (external); CI `conda run` behavior (environment-specific). Stated where relevant.

**Footprint:** ~12.8K LOC source / 62 files; ~20K LOC tests / ~50 files. Largest areas:
`validation/` 3.3K, `evaluation/` 3.1K, `runner/` 1.9K.

---

## 3. Intended Foundation Model (first-principles, before judging the code)

The irreducible job: **turn a pure strategy into trustworthy, advisory, auditable trade-level
evidence, without ever letting the future leak in, and without overstating what a number means.**
The minimal foundation needs exactly:

1. **A pure strategy contract** — `generate_decisions(rows, params) -> [StrategyDecision]`, no IO,
   no engine, no clock/RNG. Enforced by contract + a best-effort lint + review.
2. **One causal execution kernel** — import → param-validate → load (via `quant_data`) → generate
   decisions — shared by all jobs, with a lookahead invariant that holds at both decision time
   and fill time.
3. **A PnL/economics layer** with declared assumptions, honest names, and unit/base tags;
   per-trade and portfolio/NAV semantics kept distinct (a linear per-trade sum is not a return).
4. **Three thin job surfaces** (quick run / validation / evaluation) and **one narrow consumer
   API** that is hard to misuse.
5. **Determinism of identity** (source+inputs+decisions+artifacts; not wall-clock/env) and
   **write-once immutable artifacts**.
6. **Advisory-only** outputs; promotion is human-led; data and the research loop are owned
   upstream/downstream.

**The current code expresses all six.** Where it legitimately exceeds the minimum: a vbt
portfolio backend + a bespoke perp NAV ledger (justified by G7 portfolio evidence + funding),
and an opt-in cross-backend oracle. Where it adds friction beyond the minimum: the 4-way verdict
vocabulary, the leaked result fields, and `evaluation/backend.py` carrying three responsibilities.

---

## 4. Project Ontology: Concepts, Contracts, Boundaries, Invariants

**Core entities** (all `frozen`, `extra="forbid"`, strict Pydantic — invalid states are genuinely
hard to construct):

- `StrategyDecision` (pure output): `instrument`, `direction∈{long,short,flat}`, `target.size`
  (weight ≥0), `exit_policy` (max_hold + optional stop/TP/trailing bps), `decision_time`,
  `as_of_time`, `observations`. **Invariant `as_of_time ≤ decision_time`** enforced at the model.
- `Bar`: OHLC (+ optional bid/ask/mid, + optional funding event) with internal price-ordering
  and funding-completeness validators.
- `ExecutableDecision` → `Trade` (realized: entry/exit, gross/funding/cost/net, exit_reason) →
  `TradeResult` (`sum_signed_trade_activity_{gross,funding,cost,net}` — linear sums).
- `ValidationDecision` (advisory label) ; `PortfolioEvaluationResult` (NAV path + portfolio
  metrics + parquet traces).

**Contracts/invariants that must never be violated** and where they live:

| Invariant | Home | Status |
|---|---|---|
| Strategy purity | `decisions/purity.py` (lint) + contract + review | Honest best-effort; documented as not a sandbox ✔ |
| `as_of_time ≤ decision_time` | `decisions/models.py:168` | Enforced ✔ |
| No hidden lookahead (decision changes **and** suppression) | `causality.py` dual replay + determinism | Rigorous ✔ |
| Entry strictly after decision bar | `engine` fill (`entry_lag_bars` default 1) | Held at config; **not pinned in the kernel** (F7) |
| Single decision kernel | `core/execution.execute_strategy_run` | Real — all 3 jobs route through it ✔ |
| Honest names + unit/base tags | `engine/models.py`, `evaluation/metrics.py`, `*_metrics` | Exemplary ✔ |
| Deterministic identity (excl. env/time) | manifests + `decision_id` sha256 (sorted keys, `allow_nan=False`) | Held; one eval-manifest exception (F9) |
| Write-once artifacts | result dirs `mkdir` + suffix bump | Held ✔ |
| Advisory-only / data & loop owned elsewhere | boundaries + `FOUNDATION_LOCK` | Held ✔ |

**Dependency direction is clean:** `core`/`engine` never import the three surfaces; the surfaces
import the kernel. No upward imports. The "single causal kernel" PRD claim (G3) is **true** for
import/data/decisions/replay; the PRD *explicitly licenses* evaluation to branch to a NAV backend
— so the "one PnL path" reading is a misreading, not a violation.

---

## 5. What Already Exists and Should Be Reused (Preserve)

These are right and should not be churned:

- **`core/execution.execute_strategy_run`** — the genuine shared kernel. Preserve.
- **`causality.py`** dual-direction lookahead + determinism replay. This is the crown jewel;
  essential complexity, not over-engineering. Preserve.
- **`funding.py`** — single source of the funding window/dedup/sign, reused by engine + validation.
  Preserve.
- **`decisions/models.py`** — the decision schema; best single onboarding artifact. Preserve.
- **`data_contract.py`** (888 LOC) — large but **correctly scoped** boundary validator/normalizer
  + deterministic hash. The architecture lens explicitly rebutted the "over-built" hypothesis:
  this is boundary *validation/normalization* (legit for a non-owning consumer), not data
  acquisition (NG2). Preserve.
- **`validation/agreement.py`** — honest, narrow, correct cross-check (and honest about its
  narrowness). Preserve the comparator; widen coverage (F2).
- **Metric naming + `evaluation/metrics.py` semantics registry** — unit/base/cost_scope/null_when
  per metric. Preserve and extend (F3/F4 want two more disclosure lines).
- **Determinism/immutability machinery**, **typed-boundary error translation**
  (`StrategyExecutionError`, `BackendRunResult(status=...)` with `from exc`). Preserve.
- **`cli.py`** (148 LOC, 3 subcommands → 3 APIs, structured exit codes, no business logic). Preserve.

---

## 6. Architecture & Boundary Review

```
strategy.py  (PURE: generate_decisions(rows, params) -> [StrategyDecision];  validate_params)
      │
quant_data loaders ──► data_contract.NormalizedRows  (validate + normalize + sha256)
      ▼
core.execution.execute_strategy_run        ◄═══ THE single shared causal kernel
      (import → param-validate → load → generate decisions → causal replay)
      │
      ├───────────────┬────────────────────────────┐
      ▼               ▼                             ▼
  QUICK RUN       VALIDATION                    EVALUATION
  runner/         validation/                  evaluation/
  engine.screen   engine_backend.screen        ├─ vbt portfolio backend (NAV)
  (linear trade   + vbt AGREEMENT ORACLE        └─ project_perp_ledger_v1 (funding NAV)
   ledger)          (single-trade ONLY,            (BESPOKE; no oracle, no numeric test)
      │              off by default)                  │
      ▼               ▼                               ▼
  economic_metrics  policy.classify               metrics: Sharpe/DD/Sortino/...
  (trade stats,     (advisory verdict label)      (explicit-config annualization)
   no annualization)  │                               │
      ▼               ▼                               ▼
  summary/diagnostic  validation_* artifacts      evaluation_* + parquet traces
  (immutable, gitignored output roots — disposable, safe to re-run)
```

**Verification / trust map** — this is the load-bearing picture:

```
PnL path                         independent cross-check?
──────────────────────────────   ─────────────────────────────────────────────
engine linear sum, 1 trade        YES  — vbt oracle, dev=0.0 (numerically verified)
engine linear sum, ≥2 trades      NO   — engine is its own oracle            ◄ thin (F1)
validation funding                single shared fn (no 2nd impl to diverge)  ◄ ok
project_perp_ledger_v1 NAV+fund.  NO oracle, NO numeric pin test             ◄ thinnest (F1/F5)
vbt portfolio NAV                 rides on vbt's own engine (external)
```

**Findings (calibrated severity; F-numbers used in §12):**

- **F1 [HIGH · Add/Refactor · lock: accepted_debt+deferred] — The dominant-path verdict is
  self-certified; the perp ledger has no oracle at all.** For ≥2 trades the agreement oracle
  returns `skipped` by design (linear sum ≠ NAV), and it's `enabled=False` by default
  (`validation/config.py`). `project_perp_ledger_v1` has no oracle and no numeric test. *The math
  is correct now* (3 independent confirmations) — so this is a **missing regression tripwire**, not
  a present error. Root cause: verification strategy. Why it matters: a tight loop ranks on these
  numbers; a future arithmetic regression on the common path would emit a confident
  `mechanical_threshold_pass` with nothing disagreeing. Bounded by advisory-only + human promotion.
  Action: (a) stamp the verdict with `cross_checked: false` whenever the oracle was
  skipped/disabled so the consumer cannot mistake un-corroborated for corroborated; (b) add a
  cheap **per-trade** gross cross-check (comparable regardless of trade count — see F2);
  (c) add a numeric pin test for the perp ledger (F5). `FOUNDATION_LOCK` already lists the
  single-trade limitation as accepted debt and "rebuild around trade-ledger/path-level comparison"
  as deferred — I'm electing to surface it as the top hardening item because it gates autonomous
  trust, which is exactly your "begin running" question.

- **F2 [MEDIUM · Refactor] — Agreement oracle could be far more useful per-trade.** It compares
  only the aggregate in the single-trade regime; comparing the engine's **per-trade gross** against
  vbt per-trade would be valid for *any* trade count and would close most of F1 cheaply.
  Root cause: contract (oracle scoped to aggregate). Tradeoff: small reimplementation of the oracle
  loop; no behavior change to the verdict.

- **F3 [MEDIUM · Refactor or Doc] — PRD G3 sub-claim "single execution-model contract that any PnL
  backend implements" is unmet.** `validation/backends.py:ValidationBackend (Protocol) → BackendRunResult`
  vs `evaluation/backend.py:VectorBTProEvaluationBackend (no Protocol) → PortfolioEvaluationResult`
  are unrelated families. LSP holds *within* validation (engine/vbt/fake interchangeable), not
  across. Root cause: missing shared abstraction **or** an over-promising doc sentence. Fix: either
  introduce one thin `PnLBackend` Protocol over `{decisions, rows, cost_model} → trade ledger`, or
  **amend `PRD.md:150`** to scope that contract to the validation family. I lean toward amending the
  PRD — the NAV-vs-linear split is intentional and good; the sentence is just wrong. (Stale-doc rule.)

- **F4 [MEDIUM · Simplify · lock: accepted_debt] — `evaluation/backend.py` (1227 LOC) is three
  responsibilities in one file:** vbt portfolio backend, the bespoke perp NAV ledger, and ~30
  metric/frame helpers. The **most correctness-sensitive math in the repo (`_run_perp_ledger`) is
  buried in a file named after the *other* backend** — bad discoverability for exactly the code that
  most needs eyes. Fix: split into `evaluation/backend_vbt.py`, `evaluation/perp_ledger.py`,
  `evaluation/portfolio_metrics.py` behind the existing `PortfolioEvaluationResult`. Pure relocation,
  no behavior change. (`FOUNDATION_LOCK` calls large facades "not immediate blockers" — agreed, not a
  blocker; but this one hides the riskiest math, so it's worth doing.)

- **F6 [MEDIUM · Simplify] — Four parallel "did it work?" vocabularies + a live legacy layer.**
  `screen`/`gate` + `GatingReport`/`ScreeningResult`/`EvidencePacket(evidence/v4)` (engine) →
  `quick_check_*`/`assessment_status` (runner) → `mechanical_*` (validation) → `status`/
  `assessment_status` (evaluation). One question ("is this run good?") in four enums across four
  layers, with a non-obvious `quick_checks=True → engine "gate" → GatingReport.passed →
  assessment_status="quick_check_passed"` chain documented in no single place. This is the strongest
  evidence for your "layered on layered" instinct — but it's **representation/vocabulary** accretion,
  not deep abstraction towers. Root cause: ontology drift (the engine's `screen/gate` predates the
  quick-run/validation/evaluation surface and still leaks up). Fix: collapse the engine's internal
  `screen/gate` duality, keep the per-job verdict enums (they're audience-appropriate), and document
  the config→status map in one table. This does **not** require renaming public APIs (so it respects
  the lock's "don't rename" direction).

- **F8 [MEDIUM · Refactor — pending external check] — `RunResult` leaks internal evidence onto the
  public surface.** 17 fields including `emitted_replay_verified`, `strict_no_emission_verified`,
  `replayable_from_artifacts`, and an **untyped `row_contract: dict`**, mixed with the actual answer
  (`result_dir`, `assessment_status`). A consumer can't tell verdict from bookkeeping and is coupled
  to internal dict shape. Fix: split into a small verdict + a nested typed `evidence:` object;
  replace the raw dict with a typed summary. **Verify against `quant_autoresearch` usage before
  trimming** (external) — nest, don't delete, if fields are consumed.

- **F-arch-preserve — `runner/__init__.py` (652) and `validation/__init__.py` (983) are NOT
  god-functions.** Each is one public function + cohesive `_`-prefixed linear pipeline stages.
  *Discoverability* nit only: move `validation/__init__.py`'s body into `validation/runner.py`
  (mirror evaluation's layout) so `__init__` re-exports rather than houses the engine. Low priority.

---

## 7. Engineering, Testability & Operability Review

- **Tests are appropriate rigor, not over-engineering.** The 20K:12.8K test:source ratio is
  justified for a math-critical foundation, and the high-value tests pin **real invariants**
  (long/short sign, funding direction/window, entry-lag no-lookahead, dual replay, hash stability)
  — not snapshot-locked output. Two coverage holes matter:
  - **F5 [HIGH-value · Add] — perp ledger has no numeric pin test.** Perp tests assert structure and
    the *zero* funding case only (`funding_cashflow_total == 0.0`, empty frames). The
    compounding/funding/mark-to-market math is never checked against hand-computed numbers. Cheapest
    high-leverage fix in this review: one 1–2 trade scenario with a known funding event + price move,
    asserting `realized_pnl`, `funding_cashflow`, `net_pnl`, `total_return` to `approx`.
  - **F2b [Add] — engine↔vbt golden test covers only a single long.** Short and partial-weight
    equivalence is verified live (dev=0.0) but not pinned by a committed regression guard.
- **F9 [LOW · Simplify] — evaluation manifest is not byte-reproducible** (`generated_at_utc` embedded
  in payload), inconsistent with the validation manifest, which is reproducible. Data-artifact
  identity is unaffected (manifest self-excludes from its own hash map), so this is a
  provenance-vs-identity inconsistency, not a correctness break. Pick one convention.
- **F10 [MEDIUM · Refactor] — `_write_failure_artifacts` swallows all write errors** (`except
  Exception: pass`, `evaluation/runner.py`). The last line of failure diagnostics can vanish
  silently. Log/emit the secondary error before continuing (the staging-dir cleanup nearby does the
  right cleanup-then-`raise`). Elsewhere, broad `except Exception` around untrusted strategy/vbt/pandas
  code correctly translates to typed errors with `from exc` — good, not hidden failures.
- **F11 [LOW · Doc] — documented `conda run -n quant ...` may fail in non-interactive shells** (conda
  is a sourced shell function, not on PATH); env interpreter `.../envs/quant/bin/python -m pytest`
  worked (77/77 core tests, 6.5s). Environment-specific; add a CI-safe invocation note. Verify against
  your actual CI.
- **Performance discipline (G6):** JSON via `sort_keys=True, allow_nan=False`; result dirs write-once.
  No critical eager-import/redundant-work issues surfaced in the read; heavy deps (pandas/pyarrow/vbt)
  are confined to the evaluation/validation backends, not the quick-run hot path. Not exhaustively
  profiled.

---

## 8. Domain Lens — Quant Math (the part you care about most)

**No Critical or High math-correctness defect. Verdict: trustworthy for go/no-go.** Detail:

- **Per-trade engine PnL, funding, cost, net** — correct; signs verified; consistent base
  (fraction of entry notional) so `net = gross + funding − cost` is dimensionally clean.
- **Funding** — `Σ(−direction·rate)·weight`, window `entry < ts ≤ exit`, dedup w/ tolerance +
  conflict raise. Long pays positive funding, short receives. The engine path and the perp-ledger
  path use the **same window** (I verified the perp loop ordering funding→exit→entry yields
  `entry < ts ≤ exit`); they use **different bases by design** (entry-weight fraction vs mark
  notional) for two different jobs and are intentionally never reconciled — **F-M1 [MEDIUM · Add]:
  document the two bases** so an auditor doesn't expect them to match.
- **Perp NAV** — `cash + Σ units·(mark − entry_fill)` (unrealized PnL only); entry deducts fees not
  notional; slippage adverse on both sides. Correct perp/margin accounting. (Untested under
  multi-event price drift — see F5.)
- **Risk metrics** — `Sharpe=(mean/stdev)·√P`, geometric `annualized_return` (None if total ≤ −100%),
  sample stdev (n−1), target-semideviation Sortino, `Calmar=ann_return/|maxDD|`, drawdown sign
  correct, synthetic first return dropped, zero-variance/<2-sample → None. **Annualization is a
  required explicit config field (`gt=0`, no default)** — no inferred-frequency bug.
  - **F-M3 [MEDIUM · Add/Doc] — annualization correctness depends on the caller's `P` matching the
    bar cadence, and NAV returns include flat (no-position) bars.** So Sharpe is full-grid
    time-weighted (flat bars dilute mean/vol), and a misconfigured `P` silently mis-scales every
    risk metric a researcher ranks on. Within one config, *ordering is preserved* (uniform scale);
    *absolute thresholds and cross-config comparison* are corrupted. Add a cadence-consistency
    warning (infer spacing from the bar index; warn on mismatch) and document the full-grid return
    base. This is the practical sharp edge for the autonomous loop.
- **Aggregate `sum_signed_trade_activity_*`** — honestly named, **never annualized or compounded
  anywhere** (verified). Correctly *not* called a return.
- **Cross-backend agreement** — compares the same quantity on the same base to a declared tolerance,
  correctly restricted to single-trade; engine==vbt to machine precision. (Coverage = F1/F2.)

---

## 9. Unknown Unknowns & Assumption Risks

- **Biggest unstated assumption (adversarial lens):** *"the kernel's per-trade arithmetic is correct,
  therefore the dominant multi-trade path needs no independent corroboration."* True today; load-bearing
  and untripwired (F1).
- **`mechanical_threshold_pass` as a rankable label + self-attested overfit control (F12 [MEDIUM]).**
  The top label reads like "passed," and `prior_search` defaults such that an autonomous caller can
  declare "none" and dodge the search-pressure downgrade. The verdict is mechanical/in-sample with no
  statistical content (by design). Risk is consumer-side (quant_autoresearch ranking on the label),
  but the foundation enables it. Consider a less promotable top-tier name and requiring explicit trial
  counts from the research-loop caller. Partly out of scope (downstream), flagged for awareness.
- **Same-bar fill at the engine layer (F7 [LOW/MEDIUM · Refactor]).** `engine FillModel.entry_lag_bars`
  allows 0 (config surfaces force ≥1). Causality replay guards the *decision*, not the *fill bar* vs
  `as_of_time`. Off-contract direct-engine use by the agent could produce optimistic same-bar fills
  with no error. Cheap root-cause fix: push `ge=1` (or "reject fill bar ≤ as_of_time") into the kernel.
- **Timezone/instant aliasing (open).** `parse_aware_datetime` normalizes `Z`→`+00:00` but doesn't
  convert to UTC; equality is instant-based so dedup *probably* holds, but mixed-offset inputs from
  `quant_data` through dict-key/`==` matching are untested. Worth a targeted test; low confidence it
  bites.
- **DST/irregular spacing** compounds F-M3 (a 23/25-hour day violates the sample-count annualization
  assumption). Magnitude unverified.
- **External, unverifiable here:** which result fields `quant_autoresearch` consumes (affects F8 fix),
  CI conda behavior (F11), multi-symbol vbt basket NAV.

---

## 10. Overbuilt / Underbuilt / Right-Sized

| | Area | Note |
|---|---|---|
| **Right-sized** | `causality.py`, `funding.py`, `data_contract.py`, `decisions/models.py`, `cli.py`, test rigor, determinism/immutability | Don't let a "simplify" pass touch these. |
| **Mildly overbuilt / accreted** | 4 verdict vocabularies + legacy `screen/gate` (F6); `evaluation/backend.py` 3-in-1 (F4); `RunResult` 17 fields (F8) | Vocabulary/representation sprawl, not abstraction towers. Simplify. |
| **Speculative (deferred)** | `decisions/extended_ontology.py` — test-only, zero production imports (F13 [LOW]) | Per your multi-asset roadmap: **trim, keep** (don't retire). Ensure no shipping surface imports it (it doesn't). |
| **Underbuilt** | Independent verification net (F1/F2/F5); annualization cadence check (F-M3); failure-artifact observability (F10) | The few things to harden before the autonomous loop scales. |

---

## 11. Missing Docs / Decision Records

- **F3:** `PRD.md:150` "single execution-model contract any PnL backend implements" contradicts the
  code — amend or implement.
- **F-M1 / F-M3:** add to `evaluation/metrics.py` semantics and `docs/foundation-surfaces.md`:
  (a) perp funding base is mark-notional vs engine entry-weight (intentionally unreconciled);
  (b) evaluation returns are full-grid time-weighted incl. flat bars, and `P` must match bar cadence.
- **F6:** one table in `docs/foundation-surfaces.md` mapping each job's config knob → status enum.
- **No ADR for the perp-ledger vs vbt split or the single-trade-only oracle** beyond
  `FOUNDATION_LOCK` bullets — fine for now; capture the annualization/return-base convention as a
  short decision record since it shapes every risk metric.
- Docs I read (`README`, `foundation-surfaces`, `FOUNDATION_LOCK`) are **accurate to source** —
  notably not stale, which is rare and worth preserving.

---

## 12. Preserve / Refactor / Simplify / Add / Retire — Action Map & Priorities

**P0 — blocks "begin running": NONE.** Start running.

**P1 — harden before `quant_autoresearch` ranks many candidates on these numbers:**

| ID | Action | Item |
|---|---|---|
| F5 | **Add** | Numeric pin test for `project_perp_ledger_v1` (known funding + price move → hand-checked PnL/NAV). Cheapest, highest-leverage. |
| F1 | **Add** | Stamp verdict `cross_checked: false` when the oracle is skipped/disabled; don't let "uncorroborated" read as "corroborated." |
| F-M3 | **Add/Doc** | Warn when `annualization_periods_per_year` is inconsistent with observed bar cadence; document the full-grid return base. |
| F2 | **Refactor** | Make the agreement oracle compare **per-trade gross** (valid for any trade count) → closes most of F1. |

**P2 — clarity / maintainability (your "layered on layered"):**

| ID | Action | Item |
|---|---|---|
| F6 | **Simplify** | Collapse engine `screen/gate` internal duality; document config→status map. Keep per-job enums; don't rename public APIs. |
| F4 | **Simplify** | Split `evaluation/backend.py` → `backend_vbt` / `perp_ledger` / `portfolio_metrics`. Surfaces the riskiest math. |
| F8 | **Refactor** | Split `RunResult` into verdict + typed `evidence:`; type the `row_contract`. Verify vs consumer first. |
| F3 | **Doc/Refactor** | Amend `PRD.md:150` (or add a thin `PnLBackend` Protocol). |
| F10 | **Refactor** | Don't swallow failure-artifact write errors. |

**P3 — low / cosmetic (do not overweight):** F7 kernel `entry_lag_bars ge=1`; F9 manifest
reproducibility; F11 CI conda note; F2b short/partial golden test; `validation/__init__.py` →
`validation/runner.py` relocation; F12 label/overfit (mostly downstream); purity-lint
false-positive risk on generic `.remove()/.write()` names.

**Preserve:** everything in §5. **Retire:** nothing — there are no back-compat shims to remove;
`extended_ontology` is *trim-not-retire* per roadmap.

---

## 13. NOT in Scope

`quant_data` and `quant_autoresearch` internals; live/paper trading; promotion automation;
statistical gating beyond advisory; UI/notebook ergonomics; micro-latency; multi-asset extended
execution semantics (deferred). Absences of these are **not** findings.

---

## 14. What I Verified vs. Did Not

**Verified (read + re-derivation, plus numeric confirmation by the quant-math lens against real
vbt):** engine PnL/funding/cost/net signs & base; funding window equivalence engine↔perp;
perp NAV (unrealized-only) + fees/slippage; Sharpe/vol/Sortino/Calmar/drawdown/annualization
formulas; sample stdev n−1; dual-direction causality replay; metric unit/base tagging; purity
lint scope; agreement comparator + dev=0.0; 261 math tests pass.

**Did not verify:** multi-bar perp funding under price drift; multi-symbol vbt basket NAV;
`quant_autoresearch` field consumption; CI `conda` behavior; full timezone/DST edge behavior;
exhaustive review of all ~50 test files. Residual risk noted inline.

**No source files were modified** — this is a review artifact only (`review-claude.md`, +1 file).

---

*Bottom line: the math is correct, the causality discipline is excellent, the workflow is simple to
invoke, and there are no blockers — go. The work that remains is hardening the verification net
(F1/F2/F5), one annualization-cadence guard (F-M3), and trimming vocabulary/representation sprawl
(F6/F4/F8) before the autonomous loop scales. None of it requires a rewrite; all of it is
root-cause-local.*
