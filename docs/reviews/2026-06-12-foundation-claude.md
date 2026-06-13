# Foundation Review — 2026-06-12 (Claude, broad/blind)

**Reviewer:** Claude (Opus 4.8), independent broad foundation review.
**Scope (locked with Season):** root docs, `docs/`, and `src/`. Everything else
(`candidates/`, `researched/`, `results/`, `tests/`) is changeable/refactorable
context, read only as evidence of contract behavior.
**Weighting:** (1) strategy feasibility — *primary*; (2) engine
over-engineering — *secondary*; (3) stale docs — *tertiary*; plus consumer-API
stability. Quick-run end-to-end is the most important path (it is the
autoresearch iteration hot path); validation and evaluation are one-run filters.
**Method:** first-hand source trace of the quick-run spine + money model, two
independent fresh-context lens subagents (quant-feasibility+math, engine
over-engineering), and a docs-vs-code audit. The sibling
`2026-06-12-foundation-codex.md` was **not** read (perspective independence).

---

## 0. Disposition Update — 2026-06-12

This archive preserves the original review evidence and source anchors from the
reviewed state. Current live contracts remain in `FOUNDATION_LOCK.md`, `README.md`,
`docs/foundation-surfaces.md`, and `docs/consumer/`.

Implemented since review:

- **P1 / F1-F2:** implemented in `37bde41` (`Fix micro causality gate and type
  evidence quality`). Detected micro-causality violations now fail scoreability,
  and evidence quality is a typed value object instead of an untyped dict cascade.
- **P2 / F3-F6, F9:** implemented in `bd8c2e4` (`Clean up P2 foundation
  contracts`). Quick-run sample floor defaults to 20 with an explicit diagnostic
  override, `exit_lag_bars` is removed and rejected, chunked return stats use the
  single statistics path, loader DI is explicit lazy accessors, and consumer docs
  match current `RunOutcome`/failure-stage fields.
- **Core P3 / F7, F8, F11, F12, F14:** implemented in the current cleanup
  change. The validation backend registry and `EngineBackend` alias are removed,
  the happy-path quick-run manifest writes once, multi-symbol missing marks are
  covered by a fail-closed regression test, validation policy defaults no longer
  mutate a frozen model, and quick run/evaluation share `netted_portfolio_book_v1`.

Remaining open items are F10's FX financing/liquidity-model follow-on and F13's
artifact-free quick-run mode, which remains deferred until profiling justifies it.

---

## 1. Executive Verdict

**The foundation is trustworthy for its primary purpose.** On the one question
Season cares about most — *does every strategy that passes a quick run reflect a
genuinely live-tradeable portfolio, or can an untradeable setup be scored as if
real?* — the portfolio-book spine holds. I found **no fail-open counterexample**,
and the independent quant lens found none either. The specific failure that
motivated the portfolio rewrite — *stacking signals / summing per-trade PnL
instead of netting one financed book* — is now **structurally impossible**, not
merely discouraged:

- A strategy emits one signed weight-of-NAV target per instrument; the book
  trades the *delta* to that target (`portfolio_foundation.py:994`), so
  same-symbol exposure nets and cannot sum (`decisions/models.py:132`).
- There is exactly **one money model**. The NAV path is the only scored object;
  the per-trade ledger is a derived attribution view that reconciles with it
  (`economic_metrics.py:116-123`, `evidence_semantics.py:41-99`). The old
  per-trade linear-sum scorer is gone (`engine_runner.py:14-23`).
- The same walk (`_walk_book`) backs all three surfaces — quick run and
  validation via `build_portfolio_foundation`, evaluation via
  `walk_portfolio_book` (`validation/engine_backend.py:51`,
  `evaluation/spine_backend.py:176`). No divergent per-surface money path exists.
- The feasibility envelope is typed and **fail-closed**, never clamped: leverage
  budget, unfinanced leverage, unpriced short financing, capacity unpriced /
  unsupported / missing-volume / insufficient-ADV / participation-limit, zero-cost,
  and insufficient-sample all raise a typed `FeasibilityVerdict` that sets
  `succeeded=False` (`portfolio_foundation.py:1466-1585`, `runner/__init__.py:287-295`).

**The engine is largely right-sized, with complexity concentrated in two spots,
not spread everywhere.** It is not broadly over-engineered: the hot path is
dependency-light, the public surface is narrow, and the money model is singular.
The real weight sits at the **evidence-quality boundary** (an untyped dict
threaded through a 4×-duplicated 16-argument cascade) and in one 2249-line module.

**Docs are unusually current** — better than most repos at this stage. The
audit found only narrow drift in one consumer reference file.

**The one residual that touches the feasibility thesis** is not in the money
model but in causality: on the default `micro` mode, a quick run whose
lookahead probe *detects a violation* is still scored (`succeeded=True`,
flagged non-retainable), rather than being made non-scoreable. Because the
autoresearch loop climbs the quick-run NAV, this is the single place where a
non-causal — hence not-actually-tradeable — book can still produce a scored
climb signal. It is surfaced (not silent), but it deserves an explicit
decision (§7, F1).

Net: **a sound base to keep building on.** No rewrite warranted. The
recommendations are one feasibility decision, one maintainability refactor, and
a short tail of simplifications and doc fixes.

---

## 2. Scope and Evidence Inspected

**Read first-hand (source):** `core/portfolio_foundation.py` (full, 2249 LOC),
`runner/__init__.py` (full), `runner/economic_metrics.py`, `core/engine_runner.py`,
`evidence_semantics.py`, `decisions/models.py`, `decisions/__init__.py`,
`evaluation/__init__.py`, `validation/__init__.py`; targeted reads/greps across
`evaluation/spine_backend.py`, `validation/engine_backend.py`, `core/config.py`,
`runner/config.py`.
**Docs audited vs code:** `PRD.md`, `README.md`, `FOUNDATION_LOCK.md`,
`docs/foundation-surfaces.md`, `docs/consumer/{README,usage-guide,reference}.md`.
**Structure:** CodeGraph (151 files, 5084 nodes) for the map and call/blast queries.
**Lenses (independent subagents):** quant-feasibility+math; engine over-engineering.

**Verified claims (first-hand):** one money model on three surfaces;
`netted_portfolio_book_v1` exists (`evaluation/metrics.py:13`);
`examples/simple_momentum/` exists; `exit_lag_bars` never read; micro returns
`passed=True` unconditionally; `min_return_sample` hardwired to 2 on the quick path.

**Not verified (residual risk):** the test suite was not read in depth (the two
lenses flag specific tests to confirm before refactors — see §7 verification
columns); `quant_data` loader internals and real data coverage are upstream and
out of scope; `quant_autoresearch`'s actual consumption code is in another repo.

---

## 3. Intended Foundation Model (first principles)

A minimal, trustworthy version of this foundation must provide exactly:

1. **A declarative strategy contract** — a pure function emitting a *target book*
   (standing signed weight-of-NAV per instrument, idempotent, optional declared
   price-path risk). Nothing about accounting leaks into the strategy.
2. **One causal money model** — fold the book into a single netted, financed,
   marked, single-account NAV path under operator-frozen frictions; derive every
   scored statistic from that path; expose a per-trade ledger only as a derived
   attribution view that must reconcile.
3. **A fail-closed feasibility envelope** — anything the model cannot honestly
   price or execute (over-budget leverage, unfinanced leverage, unpriced shorts,
   over-capacity, zero-cost, degenerate sample, non-causal decisions) yields a
   typed non-scoreable verdict, never a clamp or a silent absence.
4. **Three thin evidence surfaces over that one model** — fast diagnostic quick
   run (the iteration hot path), mechanical validation, stateless evaluation —
   sharing one kernel and one book, differing only in evidence depth.
5. **A narrow, typed consumer surface** — one entry point per job, typed results,
   no stable promise about internals.
6. **Honest metric semantics** — every number unit/base-tagged, named for what it
   computes, with replayability declared.

The current code expresses all six. The judgments below are against this model,
not against the current names.

---

## 4. Project Ontology: Concepts, Contracts, Boundaries, Invariants

**Core concepts (well-modeled, one owner each):**

| Concept | Type / owner | Invariant that must never break |
|---|---|---|
| Target book | `TargetDecision` (`decisions/models.py:132`) | one signed weight per (symbol, time); idempotent; `as_of_time <= decision_time` |
| Declared risk | `RiskRule` (`decisions/models.py:104`) | price-path exits only; engine-enforced intrabar; latches flat on fire |
| Net position | `_NetPosition` (`portfolio_foundation.py:501`) | one running signed qty per symbol on a shared account; cannot stack |
| Money model | `_walk_book` (`portfolio_foundation.py:794`) | the sole PnL/NAV computation; NAV path is the only scored object |
| Attribution ledger | `RoundTrip`→`RunTrade` | derived; Σ realized PnL reconciles with NAV (D4); never independently scored |
| Feasibility | `FeasibilityVerdict` / `FeasibilityError` | typed, fail-closed; never clamped, never silent `None` |
| Evidence surfaces | `run_config` / `run_validation` / `run_evaluation` | one entry per job; same kernel + same book |

**Boundaries (clean):** strategy owns allocation/sizing/netting-intent/exits;
engine owns accounting/market-model/frozen-envelope; `quant_data` owns data;
`quant_autoresearch` owns the loop (ranking, memory, stopping, promotion). These
match `PRD.md` and `FOUNDATION_LOCK.md` and are honored in code.

**Invalid states are largely unrepresentable:** signed-weight target makes
stacking inexpressible; frozen strict Pydantic models reject unknown fields;
fail-closed verdicts prevent an infeasible book from being scored.

---

## 5. What Already Exists and Should Be Reused (Preserve)

These are right-sized and load-bearing — do not disturb them, and do not let any
future change erode them:

- **One money model, three surfaces** (`portfolio_foundation.py:447/381`;
  `validation/engine_backend.py:51`; `evaluation/spine_backend.py:176`;
  `economic_metrics.py:123`). The single most important property; verified in
  code. *Any* future "cross-check backend" must be a strictly-agreeing oracle,
  never a second money model routed by data kind (already locked as deferred).
- **Typed fail-closed verdicts, never clamped** (`portfolio_foundation.py:1466-1585`;
  surfaced via `runner/__init__.py:851-895`). Matches G8/D5 exactly.
- **Hot-path dependency discipline** — no top-level pandas/numpy/vectorbt on the
  quick-run path; pandas gated behind the evaluation extra; DB engine memoized;
  default `causality_check="micro"` with a bounded probe budget. Serves G6/G7.
- **Narrow, typed public API** — `runner.__all__`, `validation.__all__`,
  `evaluation.__all__` each expose one entry function + typed results. Serves G4.
- **Target-book ontology** (`decisions/models.py`) — idempotent, strict, frozen,
  content-hashed IDs, `as_of_time <= decision_time`. The cleanest expression of G1.
- **Intrabar `RiskRule`** — barriers on the completed bar's high/low, gap-through
  worsening, adverse-wins-ties, prior-extreme trailing (`portfolio_foundation.py:1381-1463`).
- **At-risk-bar statistics + honest metric semantics** (`evidence_semantics.py`);
  documented, confined approximations (the at-risk Sharpe sample asymmetry and
  reversal cost-attribution split are explicitly non-scored).
- **`extended_ontology` isolation** — zero consumers, excluded from the package
  surface; keep it quarantined per the multi-asset roadmap (do not expand until
  an executor/market model lands).

---

## 6. Architecture and Boundary Review

The quick-run spine (the hot path) is a clean staged pipeline; each stage
delegates to a helper and returns a typed early-failure. It is long by line count
(`run_config` ≈ 190 lines) but it is **not** a god-function — it is a sequence of
named `with events.stage(...)` blocks, not inline logic.

```
                 experiment.toml
                      │
        ┌─────────────▼──────────────┐
        │ run_config (staged pipeline)│   one public entry; typed RunResult
        └─────────────┬──────────────┘
   config_load → artifact_init → strategy_execution
        → observation_audit → causality(*) → request_build
        → data_readiness → portfolio_foundation ──► FeasibilityError? ──► typed
                                   │                                     fail-closed
                                   ▼                                     verdict
                  ┌────────────────────────────────┐                  (succeeded=False)
                  │  _walk_book  (THE money model)  │
                  │  net same-symbol → trade delta  │
                  │  → finance/funding → mark        │
                  │  → NAV path (scored) + ledger    │
                  └────────────────┬────────────────┘
                                   │  (same walk reused)
        ┌──────────────────────────┼───────────────────────────┐
        ▼                          ▼                            ▼
   quick run                  validation                   evaluation
   NAV scoring +          windows × scenarios            frozen candidate →
   derived economics      → advisory decision            portfolio/path + Parquet
                                                          (+ in-process fold returns)

 (*) causality gate: "off" → non-scoreable unless operator override.
     "micro" (default) → ALWAYS passed=True; a detected violation downgrades
     to non-retainable, NOT non-scoreable.  ◄── F1 (the one feasibility residual)
```

**Boundary verdict:** dependency direction is correct (surfaces adapt into one
kernel + one book; none owns another's path). The internal `engine` package is
correctly fenced off as non-public. The consumer API is narrow and hard to
misuse. The only boundary smell is the evidence-quality dict (F2), which defeats
typing across the whole runner.

---

## 7. Findings

Severity = impact on the locked objective. Action class per the review skill.
Disposition reconciles with `FOUNDATION_LOCK.md`'s protocol (New / Accepted-debt /
Deferred). Full action map with priorities in §11.
Finding bodies preserve original review evidence from the reviewed state; the
current status is owned by §0 and §11.

### F1 — Micro causality scores a book whose lookahead probe *detected* a violation
- **Severity:** High · **Action:** Refactor (or deliberate Add: document) · **Disposition:** New · **Root cause:** contract/boundary (gate semantics)
- **Evidence:** `_prepare_micro_causality_evidence` runs a real
  `check_micro_causality` (→ `check_hidden_lookahead`, `causality.py:268`) but then
  **unconditionally** returns `LookaheadCheckResult(passed=True, …)`
  (`runner/__init__.py:507-512`). The run-level gate `if not causality.passed`
  (`runner/__init__.py:250`) therefore can never trip in micro mode. A detected
  violation feeds only `evidence_quality` (→ `replay_warning`), which blocks
  *retainability* (`runner/__init__.py:1031-1033`) but not *scoreability*.
- **Why it matters (feasibility):** a strategy that observes its own/future bar is
  not live-tradeable — its NAV is built on leaked alpha. On the *default,
  most-used* iteration mode, such a book still returns `succeeded=True` with a full
  scored `foundation` NAV/Sharpe. The autoresearch loop climbs that NAV; if it
  scores without also gating on `evidence.causality.verified` / `retainable`, it
  optimizes fiction until a later strict/validation gate catches it. This is the
  one remaining path by which a not-actually-tradeable book yields a scored climb
  signal on the hot path. It is *surfaced* (`assessment_status=quick_check_unverified`,
  non-retainable), so it is not a silent fail-open — but it is easy to misread.
- **Recommendation — decide explicitly:**
  - **(a) Fail-close on a detected micro violation:** thread `micro.passed` into the
    returned `passed` at `runner/__init__.py:506`. A *detected* leak makes the run
    non-scoreable; a *clean/timed-out/capped* micro stays scoreable. Cheapest correct
    fix; preserves micro as the cheap mode while closing the leak.
  - **(b) Keep advisory (if intended):** then document in `FOUNDATION_LOCK.md` and
    the consumer guide that a micro run scores **despite a detected violation** and
    that a climbing consumer MUST gate on `causality.verified`/`retainable`, not on
    `succeeded` alone.
  - I recommend (a): "detection ran and found a leak" should not coexist with a
    scored NAV, even on the cheap mode. (a) still lets micro score the common
    no-violation case.
- **Verification needed:** confirm no test asserts that a *failing* micro probe
  still yields `succeeded=True`; update tests with the chosen semantics.

### F2 — Untyped `evidence_quality` dict threaded through a 4×-duplicated 16-arg cascade
- **Severity:** High · **Action:** Refactor · **Disposition:** New · **Root cause:** missing value object at a contract boundary
- **Evidence:** the same ~16 causality fields are re-declared in four signatures —
  `evidence_semantics.causality_evidence_fields` (`:124`), `data_contract`
  `NormalizedRows.evidence_quality`, `runner/artifacts.evidence_quality`,
  `runner/artifacts.with_causality_verification` — then carried as a
  `dict[str, object]` and re-typed back into dataclasses with hand-written coercers
  (`runner/__init__.py:1364-1391`, used by `_run_evidence` `:1275`). A
  typed→untyped→typed round trip; every new causality field touches five places;
  the dict bag defeats the type checker across the runner.
- **Why it matters:** this is the single largest "complexity that doesn't earn its
  place." The data has a fixed shape — it should be one frozen value object
  constructed once and passed by value, serialized once at the artifact edge.
- **Recommendation:** introduce one frozen `CausalityVerification` (and a small
  `EvidenceQuality`) model; `causality_evidence_fields` becomes its constructor;
  the three wrappers collapse to passing the object; the coercion helpers in
  `runner/__init__.py` disappear. Clean cutover per NO-LEGACY (no shim).
- **Verification needed:** doc/manifest-structure tests likely pin exact
  `evidence_quality` keys / `data_manifest.json` shape — update them in the same
  change (project memory: these tests are brittle).

### F3 — Quick-run scoreability floor is 2 at-risk samples and not operator-tunable (evaluation uses 20)
- **Severity:** Medium · **Action:** Add (expose) / Refactor (share floor) · **Disposition:** New · **Root cause:** contract/data-model
- **Evidence:** `DEFAULT_MIN_RETURN_SAMPLE = 2` (`portfolio_foundation.py:27`);
  `PortfolioFoundationConfig.__post_init__` only enforces `>= 2` (`:78-79`);
  `scenario_feasibility` marks scoreable at `count >= min_return_sample`
  (`:1569`). The runner builds `PortfolioFoundationConfig(...)` **without**
  `min_return_sample` (`runner/__init__.py:824-830`) and `OutputConfig` doesn't
  expose it → hardwired to 2. Evaluation's `min_annualized_samples` defaults to 20.
- **Why it matters (feasibility):** a book at-risk for as few as 2 bars is
  "scoreable" and emits `sharpe`/`skew`/`kurtosis` — statistically degenerate, and
  exactly the "degenerate sample scored as if real" case. The same book would be
  nulled by evaluation's 20-sample floor, so a quick run can look scoreable on
  numbers a one-run filter would reject. Mitigation: `sharpe_standard_error` is
  emitted and significance gating is an explicit non-goal — so this is
  by-design-permissive, not a lie.
- **Recommendation:** raise the hot-path default to a non-degenerate floor and/or
  expose `min_return_sample` as an operator `[output]` knob so quick run and
  evaluation can share one floor. Keep it advisory (do not add significance
  gating — out of scope). At minimum, document that quick-run statistics below
  ~20 samples are diagnostic-only.

### F4 — `exit_lag_bars` is a dead config field — exit fill timing silently uncontrolled
- **Severity:** Medium · **Action:** Retire (delete) or Add (implement) · **Disposition:** New · **Root cause:** contract/config (input with no implementation)
- **Evidence:** `FillModelConfig.exit_lag_bars: int = Field(default=0, ge=0)`
  (`core/config.py:71`) is the **only** occurrence in `src/` — never read as an
  attribute. The book routes every decision (entries and `target=0` flats) through
  `_DecisionPlan` using `entry_lag_bars` only (`portfolio_foundation.py:707`);
  RiskRule exits resolve intrabar. By contrast `entry_lag_bars` is read in two
  places.
- **Why it matters:** an operator/author can set `exit_lag_bars=3` (it validates)
  expecting exits to lag — it does nothing. Fill timing is a core determinant of
  executability; a knob that claims to control exit latency but is ignored
  misrepresents the executed contract.
- **Recommendation:** per NO-LEGACY, **delete** the field (and any doc/config that
  mentions it) unless lagged decision-exits are a real requirement, in which case
  implement it in `_DecisionPlan`. Deletion is the cleaner fix.

### F5 — Duplicated return-statistics implementation (scalar vs "from_chunks")
- **Severity:** Medium · **Action:** Simplify · **Disposition:** New · **Root cause:** premature micro-optimization → parallel code paths
- **Evidence:** parallel pairs computing identical quantities two ways in
  `portfolio_foundation.py`: `compute_return_statistics` (`:1588`) vs
  `_compute_return_statistics_from_chunks` (`:1630`); `_shape`/`_shape_from_chunks`;
  `_effective_sample_size`/`…_from_chunks`; `_sample_stdev`/`…_from_chunks`. The
  "from_chunks" family exists only to avoid concatenating ≤64 small subwindow lists.
- **Why it matters:** risk statistics are the scored output; two implementations of
  the most correctness-critical math is a divergence hazard (a fix to one
  skew/kurtosis path can miss the other) and doubles the audit surface. The
  motivating optimization is negligible at the ≤1M-row budget.
- **Recommendation:** delete the `_from_chunks` family; have
  `_metric_from_accumulator` pass `chain.from_iterable(return_chunks)` into the
  single `compute_return_statistics`. ~110 fewer lines, one audit target. Guard with
  a before/after equality assertion on an existing fixture; check
  `tests/test_performance_regressions.py` doesn't pin the chunked path.

### F6 — `_LazyLoaderProxy` is a heavyweight DI mechanism for 4 call sites + a test seam
- **Severity:** Medium · **Action:** Simplify · **Disposition:** New · **Root cause:** single-use abstraction for testability
- **Evidence:** `core/data_loader.py:15-53` — a custom proxy with an `_UNSET`
  sentinel, dynamic `setattr`, `importlib.import_module`, and a `resolve()`
  fallthrough, backing four upstream loaders resolved at four call sites; its
  documented purpose is "tests override via `setattr`."
- **Why it matters:** the real requirements — don't import `quant_data` at module
  import (purity) and let tests substitute a loader — are met by a plain
  module-level lazy-import accessor plus normal `monkeypatch.setattr`. No sentinel,
  no dynamic attributes, no proxy class.
- **Recommendation:** replace the proxies with thin lazy-import accessor functions;
  tests patch those names. Keep the engine memoization (`_default_engine`) — that
  part is correct. Migrate the loader tests' override style in the same change.

### F7 — Single-implementation backend Protocols + string registry
- **Severity:** Low-Medium · **Action:** Simplify (trim registry) / Preserve (the Protocol) · **Disposition:** New · **Root cause:** defensible test seam vs. speculative pluggability
- **Evidence:** `validation/backends.get_backend(name)` raises for anything but
  `"engine"` and returns the one `SpineBackend` (`:208`); `ValidationBackend`,
  `EvaluationBackend`, `PreparedEvaluationBackend` Protocols each have one
  production impl; `engine_backend.py:87` keeps an `EngineBackend = SpineBackend`
  alias.
- **Why it matters:** a Protocol with one impl is justified only as a test-fake
  contract or a concretely-planned second impl. Test-fake injection is legitimate —
  so this is not clearly wrong — but the string-dispatch factory and the alias add
  indirection beyond a test seam.
- **Recommendation:** keep the Protocols (they document the one-money-model
  invariant and the test seam); drop the `get_backend(name)` string indirection in
  favor of direct construction unless a config field actually selects a backend by
  name; drop the `EngineBackend` alias if only `SpineBackend` is referenced. Do not
  build more backend machinery.
- **Verification needed:** confirm no TOML field routes to `get_backend` (if one
  does, the registry earns its place and this drops to Low/Preserve).

### F8 — Redundant `data_manifest.json` write on the happy path
- **Severity:** Low · **Action:** Simplify · **Disposition:** New · **Root cause:** defensive write not de-duplicated against success path
- **Evidence:** `run_config` writes the execution data manifest at
  `runner/__init__.py:242` (before the causality gate) and **again** at `:307`
  (after scoring) with the same `(rows, normalized_rows, evidence_quality)` — the
  object is built once at `:241` and not mutated between. On the happy path the
  same file is serialized twice. (Independently flagged by the over-engineering
  lens and confirmed by me.)
- **Recommendation:** keep the defensive pre-gate write for the failure branches;
  drop the `:307` re-write (completion artifacts supersede it). Verify no test
  asserts a mid-run manifest distinct from the final one.

### F9 — Stale fields in `docs/consumer/reference.md`
- **Severity:** Low (but consumer-facing) · **Action:** Retire/Add (fix doc) · **Disposition:** New · **Root cause:** doc drift
- **Evidence:** (1) `reference.md:316` documents `RunOutcome.promotion_eligible`
  — this field does **not** exist in `RunOutcome` (`runner/__init__.py:116-123`
  has only `completed`, `failure_stage`, `assessment_status`, `param_contract`) and
  appears nowhere in `src/`. A consumer coding to the doc hits `AttributeError`.
  (2) `reference.md:668-671` lists `engine_evaluation` as a quick-run
  `failure_stage` — it does not exist in `src/`; the real stages it omits are
  `observation_audit`, `data_readiness`, and `portfolio_foundation`.
- **Why it matters:** `reference.md` is the consumer contract; `promotion_eligible`
  actively misleads (the doc even self-describes "code wins"). The rest of the docs
  (`PRD`, `README`, `FOUNDATION_LOCK`, `foundation-surfaces`, `usage-guide`) are
  notably current — this is isolated drift.
- **Recommendation:** delete `promotion_eligible` from the `RunOutcome` row; fix
  the failure-stage list to the actual set; (optionally) add a tiny test asserting
  the documented `RunOutcome` fields match the dataclass.

### F10 — FX coverage gap: committed FX candidates are categorically unscoreable (fail-closed)
- **Severity:** Low · **Action:** Add (config hygiene) / Accepted-debt (engine financing) · **Disposition:** Accepted-debt / Documented diagnostic configs · **Root cause:** financing model is crypto-perp-only + capacity-off configs
- **Evidence:** `_FINANCED_DATA_KINDS = {"crypto_perp_funding"}`
  (`portfolio_foundation.py:36`); any short on a non-financed kind →
  `unpriced_short_financing` (`:1525-1539`); a traded book with capacity `mode=off`
  → `capacity_unpriced` on the first trade (`:1198-1205`). The committed FX
  candidate configs pair `forex_with_quotes` + `capacity_model.mode="off"` with
  short-emitting strategies, so they can never produce a feasible scored run.
- **Why it matters:** this is the *safe* direction (nothing infeasible is scored),
  and the financing coverage gap is already booked as accepted debt in
  `FOUNDATION_LOCK.md`. The committed FX configs now declare that FX quote runs
  are diagnostic only: `capacity_model.mode="off"` makes traded books fail closed
  with `capacity_unpriced`. FX ADV impact remains fail-closed with
  `capacity_unsupported_volume_semantics` until calibrated notional liquidity
  exists. `candidates/` is out of primary scope, so this is a hygiene note, not an
  engine defect.
- **Recommendation:** (engine) leave FX/equity financing as the named follow-on
  (upstream `quant_data` coverage-gated). (configs) keep the FX candidates marked
  known-unscoreable until calibrated notional liquidity can support a real
  `adv_impact` capacity envelope; ensure the verdict messages make "why this FX
  strategy fails" obvious.

### F11 — Multi-symbol missing-mark path is fail-closed but untested
- **Severity:** Low · **Action:** Add (test) · **Disposition:** New · **Root cause:** missing test coverage + implicit alignment contract
- **Evidence:** `_walk_book` iterates the union of all symbols' timestamps
  (`portfolio_foundation.py:817`) and marks every open position at every union bar;
  a held symbol missing a bar → `mark_at`→`row_at` raises `missing_mark`
  (`:625`), caught as a `portfolio_foundation` stage failure
  (`runner/__init__.py:834-847`). No test exercises ragged/non-aligned multi-symbol
  bars; the alignment guarantee is implicit (owned upstream).
- **Recommendation:** add one test that a held position with a missing mark yields a
  typed `portfolio_foundation` failure (not a raw crash), documenting the alignment
  contract the book relies on. No engine change needed if `quant_data` guarantees
  per-symbol-aligned bars over the window.

### F12 — Frozen-model mutation via `object.__setattr__` in validation policy
- **Severity:** Low · **Action:** Simplify · **Disposition:** New · **Root cause:** constants injected as mutable fields
- **Evidence:** `validation/policy.py:44-57` uses `object.__setattr__` on a
  `frozen=True` model to overwrite four constants from
  `validation_evidence_semantics()` post-construction.
- **Recommendation:** make them computed fields / class defaults sourced from
  `validation_evidence_semantics()`, removing the `object.__setattr__`. Low priority.

### F13 — `run_config` always materializes artifacts (no in-process artifact-free mode)
- **Severity:** Low · **Action:** Preserve / Defer · **Disposition:** Deferred-until-trigger · **Root cause:** single output mode for two consumers
- **Evidence:** `run_config` unconditionally creates the result dir and copies
  `config.toml`/`strategy_snapshot.py` (`runner/__init__.py:194-196`) and always
  writes notes/summary/manifest; no path returns a `RunResult` without disk I/O.
- **Why it matters:** the autoresearch loop consumes the typed `RunResult`
  in-process but still pays directory creation + file copies + JSON writes every
  iteration.
- **Recommendation:** **do not add speculatively.** Flag for Season: if
  `quant_autoresearch` profiles artifact writes as a hot-path cost, add an artifact
  profile that returns the typed result and skips non-essential writes. Until
  measured, the single mode is the simpler choice.

### F14 — Two "one book" names (`quick_run_netted_portfolio_book` vs `netted_portfolio_book_v1`)
- **Severity:** Low (informational) · **Action:** Simplify (naming/doc) · **Disposition:** New · **Root cause:** artifact-basis id vs accounting-model id
- **Evidence:** the quick-run foundation emits basis
  `quick_run_netted_portfolio_book` (`portfolio_foundation.py:23`) while evaluation
  emits accounting-model `netted_portfolio_book_v1` (`evaluation/metrics.py:13`);
  docs say "one shared book `netted_portfolio_book_v1` on every surface." The *walk*
  is genuinely shared (verified), so this is naming, not a divergent model.
- **Recommendation:** optional — align the identifiers (or add one sentence in
  `foundation-surfaces.md` distinguishing the quick-run artifact basis from the
  shared accounting-model id) so the "one book" story isn't undercut at the
  artifact label.

---

## 8. Engineering, Testability, Operability

- **Error handling:** failures return typed structured results, not raised
  exceptions, across all three public entries (`reference.md` confirms; code
  matches). `FeasibilityError` is caught and mapped to a typed verdict, never
  escapes. Good.
- **Observability:** every stage is a `with events.stage(...)` block with an
  optional `event_sink`; stage names match artifact taxonomy. Good (NFR-OBSERVABILITY).
- **Determinism:** content-hashed decision IDs, hashed normalized rows, immutable
  artifact dirs. Matches NFR-DETERMINISM/IMMUTABILITY.
- **Type boundaries:** strong at the strategy/decision edge (frozen strict
  Pydantic) and the result edge (typed dataclasses) — *except* the
  `evidence_quality` dict (F2), which is the one place types are dropped.
- **Testability gap:** the missing-mark multi-symbol path (F11) is the one
  feasibility-relevant code path with no test. The two lenses both flagged that
  doc/manifest-structure and performance-regression tests are brittle and must be
  updated alongside F2/F5/F8 — confirm before those refactors.
- **Performance discipline:** allocation-free happy paths in the inner loop
  (`mark_at`/`bar_at` build `isoformat()` error strings only on failure); ADV
  prefix sums cached. The one wasted-work item is the duplicate manifest write (F8).

---

## 9. Unknown Unknowns and Assumption Risks

- **The loop's consumption contract is the real feasibility boundary.** The
  foundation correctly flags non-causal/degenerate/over-budget runs, but several
  flags live on `retainability`/`evidence`, not `succeeded` (F1, F3). The
  "passes ⟹ tradeable" guarantee holds **only if** `quant_autoresearch` climbs on
  the right signal and gates on `retainable`/`causality.verified`, not on a scored
  NAV alone. That contract is in another repo and unverified here. Recommend a
  one-paragraph "how to consume the score safely" note co-owned with the loop.
- **No independent accounting cross-check** (already accepted debt): the spine's
  correctness rests on the NAV↔ledger reconciliation test and the
  feasibility/at-risk test suite. A second agreeing implementation remains the bar
  before any cross-check is treated as verification. Reasonable for now.
- **Data alignment is assumed, not asserted locally** (F11): the book relies on
  `quant_data` delivering per-symbol-aligned bars; the failure path is safe but
  untested.
- **`micro` is the default and is advisory** (F1): the most-used mode is the
  weakest causal evidence by design. Acceptable *iff* the score-vs-retain
  distinction is loud enough that the loop never optimizes a leaked-alpha NAV.

---

## 10. Overbuilt / Underbuilt / Right-Sized

- **Right-sized (keep):** the money model, the fail-closed envelope, the three thin
  surfaces, the narrow public API, the target-book ontology, hot-path dependency
  discipline. See §5.
- **Overbuilt (localized, not systemic):** the `evidence_quality` dict cascade
  (F2); the `_LazyLoaderProxy` DI (F6); the single-impl backend registry/alias
  (F7); the duplicated statistics family (F5). None are architectural; all are
  contained refactors.
- **Large but accepted:** `portfolio_foundation.py` at 2249 LOC / 130 symbols mixes
  the book walk, return-statistics (~600 LOC), and feasibility. `FOUNDATION_LOCK.md`
  books "large facade modules" as accepted debt. An optional, low-risk split
  (`return_statistics.py`) pairs naturally with F5; not a blocker.
- **Underbuilt:** nothing critical. The financing coverage (FX/equity) is a named,
  fail-closed follow-on, not a hole. The one missing test (F11) is the only
  underbuilt verification on a feasibility path.

---

## 11. Prioritized Action Map

Priority: P1 = address soon; P2 = should fix; P3 = nice-to-have / opportunistic.
Status reflects implementation progress through the Core P3 cleanup. Verify the
named tests before any remaining refactor.

| No. | Status | Priority | Action | Finding | Evidence anchor |
|---|---|---|---|---|---|
| F1 | Implemented (`37bde41`) | **P1** | Refactor | Micro mode scores a *detected* lookahead violation (non-scoreable vs non-retainable) | `runner/__init__.py:506-512,250` |
| F2 | Implemented (`37bde41`) | **P1** | Refactor | Untyped `evidence_quality` dict through a 4×16-arg cascade → typed value object | `evidence_semantics.py:124`; `runner/__init__.py:1275,1364-1391` |
| F3 | Implemented (`bd8c2e4`) | P2 | Add / Refactor | Quick-run `min_return_sample` hardwired to 2 (eval uses 20); expose/share floor | `portfolio_foundation.py:27,1569`; `runner/__init__.py:824-830` |
| F4 | Implemented (`bd8c2e4`) | P2 | Retire (delete) | `exit_lag_bars` dead config field | `core/config.py:71` |
| F5 | Implemented (`bd8c2e4`) | P2 | Simplify | Duplicated return-statistics (`*_from_chunks`) ~110 LOC | `portfolio_foundation.py:1588/1630,2107/2118` |
| F6 | Implemented (`bd8c2e4`) | P2 | Simplify | `_LazyLoaderProxy` heavyweight DI for 4 sites + test seam | `core/data_loader.py:15-53` |
| F7 | Implemented (Core P3) | P3 | Simplify / Preserve | Trim `get_backend` string registry + `EngineBackend` alias; keep Protocol | `validation/backends.py:208`; `engine_backend.py:87` |
| F8 | Implemented (Core P3) | P3 | Simplify | Redundant `data_manifest.json` write on happy path | `runner/__init__.py:242,307` |
| F9 | Implemented (`bd8c2e4`) | P2 | Retire/Add (doc) | `reference.md` stale: `promotion_eligible`, `engine_evaluation` stage | `docs/consumer/reference.md:316,668-671` |
| F10 | Accepted-debt / Documented diagnostic configs | P3 | Add (hygiene) | FX candidates categorically unscoreable (financing coverage + capacity-off) | `portfolio_foundation.py:36,1525,1198` |
| F11 | Implemented (Core P3) | P3 | Add (test) | Multi-symbol missing-mark fail-closed but untested | `portfolio_foundation.py:817,625` |
| F12 | Implemented (Core P3) | P3 | Simplify | Frozen-model `object.__setattr__` in validation policy | `validation/policy.py:44-57` |
| F13 | Deferred | P3 | Preserve (defer) | No in-process artifact-free run mode (don't build until profiled) | `runner/__init__.py:194-196` |
| F14 | Implemented (Core P3) | P3 | Simplify (doc/naming) | Two "one book" identifiers | `portfolio_foundation.py:23`; `evaluation/metrics.py:13` |

**Outcome:** P1, P2, and the selected Core P3 bundle are implemented. F10 remains
accepted debt for financing and FX liquidity modeling, with committed FX configs
marked diagnostic/unscoreable. F13 remains deferred.

---

## 12. Preservation Constraints (do not erode)

- One money model only; never reintroduce a per-trade linear-sum scorer or a
  per-surface money path. A future cross-check is a strictly-agreeing oracle only.
- Feasibility verdicts stay typed and fail-closed — never clamp, normalize, or
  collapse a breach into a silent `None`.
- The scored unit stays the NAV path; the per-trade ledger stays a derived,
  reconciling attribution view.
- The public surface stays one typed entry per job; the `engine` package stays
  internal.
- Targets stay idempotent signed weights (stacking inexpressible).
- Keep the quick-run path dependency-light (no eager heavy-backend imports).

---

## 13. NOT in Scope

- `candidates/`, `researched/`, `results/` content (changeable; touched only as
  evidence, except F10's diagnostic config comments).
- `quant_data` internals and real data coverage (upstream; out of scope by C-2/NG2).
- `quant_autoresearch` loop logic — ranking, search memory, stopping, promotion,
  significance statistics (PSR/DSR/PBO) — which the foundation correctly leaves to
  the consumer.
- Live/paper trading, order routing, micro-latency optimization (PRD §8 non-goals).
- Statistical-significance gating (advisory metrics only, by design).

---

*Reviewer's note on confidence:* the money-model and feasibility findings are
first-hand source-verified. The two lens subagents ran on independent fresh
context and were reconciled, not copied. The main unverified surface is the test
suite depth and the in-another-repo consumer contract (§9); F2/F5/F8 refactors
must update the brittle doc/manifest/perf tests in the same change.
