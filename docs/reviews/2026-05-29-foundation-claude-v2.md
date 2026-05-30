# Foundation Review: `quant_strategies`

Date: 2026-05-29
Reviewer: Claude (senior quant-researcher lens + onboarding / architecture / senior-eng / adversarial sub-lenses)
Target: `/Users/Season_Yang/Personal/quant_strategies` (repo internals + seams with `quant_data` and `quant_autoresearch`)
Method: code-first, first-principles. Docs (`PRD.md`, `README.md`, `AGENTS.md`, `docs/`) treated as **claims to verify**, not ground truth. Five fresh-context lenses ran independently; the synthesis below is mine and I re-verified every headline finding against source. **I did not read `review-claude.md`** (per instruction).

---

## TL;DR — and direct answers to your three concerns

**Verdict: conditionally solid. The spine is genuinely good and worth keeping. Your effort is misallocated — heavy where it should be light, thin where it must be rigorous — and the single number the validation gate exists to produce is currently unsound.** This is fixable without a rewrite.

You gave me license to recommend rewrites. **The evidence says don't.** The bones — one pure strategy contract, one PnL kernel, one shared execution spec, honest metric naming, real two-direction lookahead replay — are the hard parts and they are right. The work is *re-placing* effort, not rebuilding.

Your three worries, answered from source:

| Your worry | Verdict | The precise truth |
|---|---|---|
| **(a) Over-engineering?** | **Partly — but you have the wrong target.** | The *architecture* is not over-engineered (no god-functions; one real kernel — every lens independently refuted that). The over-build is **localized**: a dead second ontology, a dead cross-check oracle, and **validation-grade rigor running on every disposable quick run**. Meanwhile the gate's headline number is *under*-engineered. So: ~6.4k LOC of ceremony wraps a 628-LOC kernel, **and** the one output that matters is unsound. The problem is *placement of effort*, not raw volume. |
| **(b) Too convoluted / too much vocabulary?** | **The mechanism is genuinely 2 steps. The vocabulary is real but mis-placed.** | A newcomer must hold **~34 terms** to use two steps; ~19 are gate/audit terms that **leak onto the quick-run surface** (16-field `RunResult`, 4 overlapping policy knobs whose values collide: `gate` mode vs `validate` subcommand vs `validation` row-contract). The words are mostly *honest and load-bearing* (`as_of_time`/`decision_time`/`available_at` is the minimum vocabulary for point-in-time correctness). Fix the **altitude**, keep the words. Then dedup: the "executable" ontology is **triplicated** across 3 files and there's a **dead** parallel ontology. |
| **(c) Poor design / legacy / artifact bias?** | **Design is good. Artifact *bias* is refuted. Real cruft is code + housekeeping.** | An independent lens **measured** `researched/`: 15 `strategy.py`/`strategy_snapshot.py` pairs, **zero byte drift**; `results/` is gitignored; `researched/` carries **no verdict files**. So stale artifacts are *not* silently driving conclusions. The genuine cruft is (i) **dead code** that biases the *reader's* mental model (the dead ontology + dead oracle) and (ii) **stale `results/`/`researched/` dirs from a strategy that no longer exists in the tree**, with no freshness/commit linkage to a live strategy. |

**The one-sentence reframe:** you are not drowning in over-engineering — you are paying validation-grade cost on the search path while the validation gate's decisive number compounds a quantity your own code documents as non-compoundable. Re-tier the rigor and fix the gate math, and most of the "too heavy / too convoluted" feeling dissolves without losing any integrity.

---

## Review Objective

I reviewed `quant_strategies` to determine whether it is a solid foundation for a small quant research lifecycle whose **primary consumer is the `quant_autoresearch` agent** (generate → quick-run → rank → iterate, with occasional validation) and whose secondary user is you. Success = stable runner/data contracts + low-ceremony iteration + a single strict validation gate; failure = over-engineering, vocabulary sprawl, convoluted workflow, artifact bias. Priority locked with you: **keep runs light/fast, concentrate rigor at the gate.** Change appetite: **evidence-led, rewrites on the table.**

### Clarified scope
- **In scope:** repo internals (`src/quant_strategies/{core,decisions,engine,runner,validation}` + 8 top-level modules), strategy contract, the quick-run and validation-run paths, tests, and the seams with `quant_data` (loaders) and `quant_autoresearch` (consumer).
- **Out of scope:** the internals of `quant_data` and `quant_autoresearch` (treated as black boxes at the seam); live execution against real market data; promotion process.
- **Assumptions:** primary user = the agent (machine contracts win on conflict); "between light-run/strict-gate and velocity-everywhere" → low ceremony throughout, strictness only where it must bite.

---

## Executive Verdict

`quant_strategies` has a **sound, well-factored spine** that most "research harnesses" never achieve: a pure `generate_decisions(rows, params) → [StrategyDecision]` contract, **one** PnL kernel (`engine.screen()`) consumed by both steps, **one** neutral `StrategyExecutionSpec` seam, content-addressed decision identity, an unusually **honest metric vocabulary** that refuses to call its smoke score a NAV return, and a genuinely two-directional lookahead replay (catches both peek-to-change and peek-to-suppress). The two orchestrators are clean staged pipelines, **not** god-functions. That core is right-sized and should be preserved.

The foundation is **not yet trustworthy as a verdict producer**, for one structural reason and a cluster of placement reasons. Structural: the validation gate's decisive paper-readiness hinge **geometrically compounds the engine's `sum_signed_trade_activity_net` across windows** — a quantity the system's own `evidence_semantics` and `agreement` modules explicitly declare is **not** a NAV/period return — and the only independent cross-check that would catch a price-path error is **off by default and skips every multi-trade strategy**. Placement: the "light, disposable" quick run is forced to pay full validation-grade cost on **every** iteration (strict O(rows) suppression replay, an 888-LOC row contract, an observation audit, a git-shelling provenance capture, full metric-semantics serialization) with **no opt-out** — directly contradicting your stated priority and the PRD's own "rigor at the gate" intent. Net: **heavy on the light path, thin at the gate.** Both are fixable with focused refactor/simplify/retire moves; none requires a rewrite.

---

## The foundation, in one screen

```text
            experiment.toml / validation.toml
                        │
                        ▼
   pure strategy.py  ──  generate_decisions(rows, params) → [StrategyDecision]   ← ONE contract  (KEEP)
                        │
                        ▼
   StrategyExecutionSpec  (core/config.py)   ← ONE neutral seam, 2 producers/1 consumer  (KEEP)
        │ runner/config.to_execution_spec()         validation/config.to_execution_spec(window)
        ▼                                                  ▼
   runner/execution.execute_strategy_run()  ────────────────  (shared)   ← ONE execution path  (KEEP)
        │  import · validate_params · load rows (quant_data) · freeze · typed decisions
        ▼
   engine.screen()  ── per-trade ledger · funding · cost · net = gross+funding−cost   ← ONE PnL kernel  (KEEP, honest)
        │                                                   ▲
        ├── QUICK RUN  (runner.run_config → RunResult)      │ validation/engine_backend reuses build_request+screen
        │     but ALSO runs, every iteration, with no opt-out:
        │       • strict suppression replay  (causality, O(rows) re-executions)   ← MIS-PLACED RIGOR (H1)
        │       • observation-dependency audit                                     ← MIS-PLACED RIGOR (H1)
        │       • 888-LOC data_contract diagnostics                                ← MIS-PLACED RIGOR (H1)
        │       • git-shell provenance + full metric-semantics                     ← MIS-PLACED RIGOR (H1)
        │
        └── VALIDATION RUN  (validation.run_validation → ValidationRunResult)
              windows × {base, cost, cost_stress, fill_lag}  ← stress, NOT out-of-sample (M1)
              policy.classify_validation → verdict ladder
                 └─ compounded_realistic_net = Π(1+net_return) − 1   ← UNSOUND: compounds a non-NAV sum (C1)
              agreement_oracle (VBT)  ← OFF by default; skips trade_count≠1  → DEAD on real strategies (H2)
              promotion/paper/live_eligible := False  (pinned in a model_validator)  ← real guarantee (KEEP)
```

### Ontology fit

| Concept / boundary | Owns | Key invariant | Current fit |
|---|---|---|---|
| `StrategyDecision` (`decisions/models.py`) | the one strategy output | `as_of_time ≤ decision_time`; content-hashed `decision_id`; `extra="forbid"`, frozen | **Strong.** Crown of the ontology. KEEP |
| `engine.screen()` (`engine/evaluation.py`) | per-trade PnL | `net = gross + funding − cost`; metric named as activity-sum, not NAV | **Strong & honest.** KEEP |
| `causality.check_hidden_lookahead` | point-in-time replay | emitted ⊆ replay; scoped ⊆ allowed | **Right mechanism**, but fails open (H4) and mis-placed onto quick run (H1) |
| "executable decision" (what the kernel can run) | the kernel's true contract | one place defines it | **Distorted.** Re-derived in **3** files (H3) |
| Extended instruments (`decisions/extended_ontology.py`) | futures/options/multi-leg | schema-valid ⟺ executable | **Broken/dead.** Schema-valid but unexecutable; tests-only (H3) |
| Validation verdict (`validation/policy.py`) | advisory mechanical gate | the gated number means what it says | **Unsound at the hinge** (C1); advisory-pinning is solid (KEEP) |
| `data_contract.NormalizedRows` (888 LOC) | row contract + normalization | one cohesive boundary | Cohesive, but full diagnostics run on the search path (H1) |

---

## The central diagnosis: effort is misallocated

This is the lens that makes your three worries cohere. Plot each subsystem by *how much it costs per iteration* vs *how much research integrity it actually protects*:

- **High cost, low/false protection (fix or cut):** strict suppression replay on every quick run (H1); the VBT oracle (H2, dead on real strategies); the 888-LOC `data_contract` diagnostics on the search path (H1); the dead `extended_ontology` + triplicated executable-ontology checks (H3).
- **Low cost, high protection (keep):** `engine.screen()`, `funding.py`, `decisions/models.py`, `evidence_semantics.py` (the honesty layer), the advisory-eligibility pinning, the `decisions/purity.py` lint.
- **The dangerous quadrant — the gate's *headline number* (C1):** it is what a human reads as "did this make money," it gates the verdict, and it is **mathematically unsound**. This is *under*-engineering in the one place that most needs rigor.

So "are we over-engineering?" has a precise answer: **you over-invested in uniform rigor and dead infrastructure, and under-invested in the verdict's economic meaning.** The volume of code is a symptom; the disease is placement. Re-tiering the quick run and fixing the gate removes most of the perceived bloat *and* makes the foundation trustworthy at the same time.

---

## Findings — Correctness & Trust (the ones that change conclusions)

### C1 — [CRITICAL · Refactor] The validation gate compounds a non-NAV metric as if it were a return
- **Evidence:** `validation/policy.py:391` `compounded_realistic_net = _compounded_return(net_return per window)`; `policy.py:492` `_compounded_return = math.prod(1+r) − 1`. Each window's `net_return` is the engine's `sum_signed_trade_activity_net` — a **linear sum over per-trade signed returns** (`engine/evaluation.py:112`), declared in `evidence_semantics.py:78-84` as `linear_trade_activity_sum`, `"not comparable to NAV-path total return"`. The gate `compounded_realistic_net_positive` is the **hard_no ↔ watchlist hinge** (`policy.py:423,469-483`).
- **The codebase contradicts itself:** `validation/agreement.py:84-100` *documents the correct rule* — "the linear per-trade sum equals a NAV path **only for a single trade**; for two or more trades the linear sum and vbt's compounded NAV are different objects" — and uses it to **skip** the oracle on multi-trade cases. The same multi-trade `net_return` that `agreement.py` refuses to treat as NAV, `policy.py` geometrically compounds across windows.
- **Why it matters (first principles):** the whole point of a strict gate is that its number means something economically. Compounding `Π(1 + Σ_trades)` treats a sum-of-trade-activity as a period return — valid only for sequential, non-overlapping, full-capital-recycling trades. For overlapping or fractional-`target_weight` trades (i.e. every real strategy here), it has **no clean financial meaning** and can flip a verdict's sign. This violates the PRD's own G2 ("named in a way that does not overstate what it computes").
- **Root cause:** data-model / contract — metric semantics not honored by its own consumer.
- **Fix:** either (a) **sum** the linear activity across windows (consistent with `evidence_semantics`), or (b) compute a true per-window NAV path in the backend and compound *that*. Do **not** ship a compounding gate over a non-compoundable metric. Rename the gate so no reader infers NAV.
- **Confidence:** High on the defect (verified in source, and contradicted by the repo's own `agreement.py` docstring). The *magnitude* of resulting verdict error is reasoned-from-source, not measured against live PnL (no `quant_data` rows loaded).

### H1 — [HIGH · Simplify] The "light" quick run is forced to pay validation-grade cost every iteration, with no opt-out
- **Evidence:** `runner/__init__.py:run_config` unconditionally runs, per call: strict suppression replay (`_prepare_causality_evidence:273` → `causality.check_hidden_lookahead` with **default `mode="strict"`**, which re-executes `generate_decisions` at **every row-grid boundary**, `causality.strict_replay_boundaries:195`); observation-dependency audit (`_audit_observation_dependencies:503`); 888-LOC `data_contract` normalization/diagnostics; git-shell provenance (`provenance.git_identity` → `git status` + `git diff --binary HEAD`); full metric-semantics serialization (even on failure paths, `_failure_result:566`). `runner/config.py` exposes **no causality-mode knob** — only `mode`, `artifact_profile`, `row_contract`. The one asymmetry that exists (`row_contract` SEARCH=warn vs VALIDATION=error, `data_contract.py`) is **data-availability strictness, not causal-check cost**.
- **Why it matters:** for an autoresearch agent running thousands of disposable ranking iterations, strict replay is O(distinct-timestamps × strategy-cost) — potentially O(n²) in rows for intraday data — paid on **every** iteration. This is the direct cause of the "too heavy" feeling, contradicts your locked priority ("light runs, rigor at the gate"), and sits in tension with PRD G6 ("typical search-scale run completes in seconds").
- **Root cause:** ontology/abstraction — cost placement; the SEARCH vs GATE tiering exists for data strictness but was never extended to the expensive correctness checks.
- **Fix:** make strict suppression replay + the heavy `data_contract` diagnostics + provenance/observation audit **gate-only**. In quick-run, run at most the cheap emitted-boundary subset check and set `causality_verified=false` (the field already exists and `evidence_semantics.causality_evidence_fields` already models "not fully verified"). This is the highest-leverage velocity fix and your change appetite explicitly allows it.
- **Confidence:** High (traced in source; no mode knob confirmed).

### H2 — [HIGH · Retire or Refactor] The only independent cross-check is off by default and dead on every multi-trade strategy
- **Evidence:** `validation/agreement.py:96` returns `status="skipped"` whenever `trade_count != 1`; `validation/config.py:43` `enabled: bool = False`. The gate requires `_MIN_VALIDATION_TRADES = 10` (`validation/__init__.py:95`) and `min_total_trades` default 30 (`policy.py:366`). So the oracle (a) never runs unless explicitly enabled, and (b) even then **skips every strategy that can reach the gate**. It guards ~425 LOC (`vectorbtpro_backend.py`) + `agreement.py` + plumbing + a 106-symbol test file.
- **Why it matters:** the engine is therefore **self-certifying** for every realistic run — the verdict PnL and its "oracle" are the same kernel. The comfort of "we cross-check against VBT" is illusory exactly for multi-trade NAV correctness, which is the thing an oracle is for. Combined with C1, the gate's number is both unsound *and* unchecked.
- **Root cause:** abstraction ROI — infrastructure protecting a non-existent regime.
- **Fix:** either **retire** the VBT path until it can validate multi-trade NAV, or **rebuild** it to compare the engine's per-trade ledger (now emitted) against VBT **trade-by-trade**, regardless of count. Don't carry 500+ LOC that protects a case production never hits.
- **Confidence:** High (skip condition + default both verified in source).

### H4 — [HIGH · Refactor] The lookahead guard fails *open* in two ways
- **Evidence:** (a) `causality.py:110-128` — on `SystemExit`/`Exception` at a *suppression-probe* boundary (no `expected_decision_ids`), the code `continue`s; the probe is **skipped, not failed**, yet `strict_suppression_verified` can still end `True`. (b) No determinism probe anywhere: replay-equality is only meaningful if `generate_decisions` is deterministic, and purity is a **best-effort AST lint** (`decisions/purity.py`, "not exhaustive" per `AGENTS.md`). (c) `causality.py:331-338` `_row_available_for_boundary` returns `True` (visible) on missing/invalid `available_at`.
- **Why it matters:** lookahead is the #1 way backtests lie, and *suppression* lookahead (peek-to-skip-a-loser) is the subtle half. A guard that downgrades "couldn't test" to "verified" gives **false confidence** — and the primary consumer is an agent that optimizes *against the checker*, not the contract.
- **Root cause:** contract/implementation — fail-open on the adversarial path; an unverifiable invariant (determinism) is assumed.
- **Fix:** fail-closed — count skipped suppression probes and set `strict_suppression_verified=False` + surface `strict_suppression_incomplete`; add a determinism double-run (same full input twice → identical output, else refuse with `nondeterministic_strategy`); make invalid `available_at` an evidence-quality failure in one place instead of silently relaxing visibility.
- **Confidence:** High on the code paths; the *exploitability* (a strategy that both suppresses and is prefix-fragile, or is nondeterministic past the lint) is reasoned, not demonstrated.

---

## Findings — Architecture & Boundaries

### H3 — [HIGH · Refactor + Retire] One ontology, claimed; two ontologies + a triplicated check, actual
- **Evidence:** the kernel's *real* contract — "what `screen()` can execute" — is independently re-derived in **three** places: `engine/evaluation.py:256` `_executable_decision`, `runner/engine_runner.py:219-229` `_decision_symbol` (same checks, different error type), `validation/vectorbtpro_backend.py:147-164` `_structural_unsupported_semantics`. Separately, `decisions/extended_ontology.py` defines futures/options/multi-leg + `close/adjust/roll` + extra sizings that are **schema-valid but unexecutable** and imported **only by tests** (grep: `tests/test_decision_models.py`, `test_runner_engine_runner.py`, `test_vectorbtpro_backend.py`, `test_readme_contract.py`; **zero `src/` importers**).
- **Why it matters:** the single most safety-critical invariant (what PnL the kernel will produce) has no owning abstraction — adding one instrument requires editing three files in lockstep or risk a stale rejection (DRY/OCP violation at the worst seam). And a wide type surface the agent can instantiate but the kernel rejects is a **footgun for the primary consumer**: a generated `FutureRef` passes Pydantic and dies at screen time, costing an iteration. This is the strongest counter to the README's "one ontology."
- **Root cause:** ontology / contract.
- **Fix:** promote one `ExecutableDecision` adapter (owned by `engine`) that validates+projects a `StrategyDecision` and returns typed unsupported-reasons; `runner` and `vbt` consume it. **Retire** `extended_ontology` until a backend executes it (or make it a documented, queryable capability seam so schema-valid ⟺ executable). Either way, give it the module docstring the repo's own rules require.
- **Confidence:** High (import graph + Literal types are conclusive).

### M-arch — [MEDIUM/LOW · Refactor] Naming and cohesion slips that feed the "too much vocabulary" feeling
- `boundary.py` contains only `FrozenMapping`/`frozen_params`/`frozen_rows` — **immutability helpers**, not a domain "boundary"; the real temporal boundary (`ReplayBoundary`) lives in `causality.py`. A reader hunting the trust boundary opens the wrong file. **Rename → `frozen.py`.** (Root: naming.)
- Causality is split: the *mechanism* is in `causality.py` but the *policy* (`causality_evidence_fields`) lives in `evidence_semantics.py:113`. Move it to `causality.py` or document the split. (Root: cohesion.)
- `runner/execution.StrategyExecutionResult` carries `loaded_rows`, `normalized_rows`, `frozen_rows`, plus a hash and `evidence_quality` already derivable from `normalized_rows` — three views of the same rows invite "which is canonical?" Consider derived properties. (Root: data-model; verify `loaded_rows` provenance use before trimming.)

**Architecture refuted, explicitly:** no god-functions (`run_config` ~140 LOC and `run_validation` ~110 LOC are linear stage pipelines over `_ValidationContext`/`_ValidationState`); `core/events.py` observability is DRY (one `StageEmitter` base, 4-line subclasses); `funding`/`provenance`/`datetime_utils`/`observation_dependencies` each earn their place as small shared pure contracts; the `quant_data` seam is lazy, public-API-only, correct direction; VBT correctly demoted to oracle. **Do not collapse the spine.**

---

## Findings — Engineering, Tests & Operability

### M5 — [MEDIUM · Simplify] Pydantic used as config-injection / ceremony in places
- `validation/policy.py:40-54` — `ValidationPolicyDecision` declares `evidence_class`, `promotion_eligible`, `paper_trade_eligible`, `live_eligible`, `requires_manual_approval` as fields, then a `model_validator` **unconditionally overwrites all five** from a global. They look settable but are constants — the model surface lies. Make them `@computed_field`/`property`. (The *intent* — pinning eligibility false — is correct and worth keeping; the *mechanism* is the smell.)
- `evidence_semantics` metric-semantics dicts are serialized on **every** run including failure paths — validation-grade metadata on the light path (ties to H1).

### L4 — [LOW · Refactor] Tests are proportionate in volume but brittle in style
- Ratio ≈ **1.66:1** (14,621 test LOC / 8,794 src) across 561 functions — *proportionate* for a tool whose product is auditable verdicts; **do not cut volume.** The issue is closed-world assertions: `read_summary` asserts `set(summary) == SUMMARY_KEYS` (30 keys) and exact **prose strings** (`tests/test_runner_api_cli.py:20-50,183-253`). Any additive field breaks every completed-run test at once. Centralized in ~3 helpers, so the blast radius is the helper. **Fix:** superset (`SUMMARY_KEYS <= set(summary)`) + value spot-checks; drop prose-string equality.
- Genuinely good: `test_validation_backends_and_policy.py` (943 LOC) uses **zero** monkeypatching; CLI exit-code tests mock only at the `run_validation` seam; runner monkeypatching is overwhelmingly `load_data` substitution at the `quant_data` boundary. This is behavioral testing, not internal over-mocking.

### L1/L2/L3 — [LOW · Add] Failure-path robustness gaps (the F19 family)
- **L1 (F19 residual):** mid-pipeline success-path writes (`runner/__init__.py:106-128`; validation `_write_window_rows`/`_write_scenario_*`) can raise `OSError` to a **direct API caller** — the *primary* consumer — breaking the otherwise-total `failure_stage` contract. The CLI backstops it; the agent does not. **Root-cause fix is one outer guard** in `run_config`/`run_validation` converting any escaping `OSError` to `failure_stage="artifact_write"`, not wrapping each call site (matches the repo's "don't add a layer per call" rule).
- **L2:** `validation/__init__.py:705-725` `_failure_result` swallows `OSError` silently — a `hard_no` can leave no/partial audit trail indistinguishable from a run that never happened. Mark the incompleteness.
- **L3:** `provenance.git_identity:110-122` returns `commit=None` silently on timeout/error — an `audit_replayable` artifact can be written with null provenance yet look complete. The gate should fail when `commit is None`.

**Operability is genuinely good:** two subcommands (`quant-strategies run` / `validate`), principled exit codes (0/1/2/3), optional `--events-jsonl`. KEEP.

---

## Findings — Quant-domain (math, lookahead, statistics)

- **M1 — [MEDIUM · Refactor] `windows × scenarios` is cost/fill *stress*, not out-of-sample evidence; and multiple-testing control is optional.** `matrix.py:37-72` produces 4 scenarios/window (base, cost, cost_stress, fill_lag) over the **same decisions on the same window** (`_scenario_decision_outcome:817` reuses, never regenerates). The only genuine OOS variation is `[[windows]]`, default floor **2** (`config.py:117`). The `_has_search_pressure` → `watchlist` downgrade (`policy.py:78-82`, appending `multiple_testing_not_corrected_advisory_only`) **only fires if the agent populates `[search_pressure]`** — nothing forces it. So an undeclared parameter search reaches `mechanical_review_candidate` on thin, correlated crypto data, with the C1 number. **Fix:** make `[search_pressure]` mandatory at the gate (mirror the existing `validate_params`-required rule), and raise the window floor for any verdict above `watchlist`. Note the multiple-testing handling is *acknowledge-but-don't-correct* — no deflated metric / Bonferroni / DSR; for a search-agent consumer that is statistically weak.
- **M2 — [MEDIUM · Add] Exit fills use close/quote, never high/low; default `exit_lag_bars=0` fills the same bar that reveals the breach.** `engine/evaluation.py:213-238`: a stop triggers only when the *close* has crossed it and fills at that close, not the stop level — optimistic on gaps; intrabar stop-outs are invisible. Internally consistent and not lookahead, but it **flatters stop-heavy strategies** (e.g. the ATR-trailing ensemble) and is **not** surfaced in `evidence_semantics`. **Fix:** declare the fill convention as a named assumption now; optionally add high/low-aware triggering later.
- **Verified clean (KEEP):** funding sign/timing (`funding.py:15-44`, `Σ(−direction·rate)·weight` over `entry < ts ≤ exit`, long pays / short receives, deduped, single shared impl); gross PnL (`gross = direction·((exit−entry)/entry)·weight`); round-trip cost (`2·(fee+slippage)`, applied once, no double-count); the two-direction lookahead *mechanism*; content-addressed `decision_id` + `as_of ≤ decision_time`. **Blind spots to document, not bugs:** survivorship/universe selection (symbol list fixed in config, never audited) and data *restatement* (trusts loader `available_at`; only timing is replayed, not whether the value was the as-of-true value).

---

## Findings — Onboarding & Velocity

- **M3 — [MEDIUM · Simplify] Gate vocabulary leaks onto the quick-run on-ramp.** ~**34** terms to use two steps; contract+config (15) are fine and example-backed, but 4 overlapping policy knobs (`mode` `screen|gate` vs `row_contract` `search|validation` vs `artifact_profile` `full|summary` vs `artifact_trust_tier` `search_only|audit_replayable`) have colliding values, and `RunResult` carries **16 fields** (~9 trust/evidence metadata). Hide trust-tier/replay vocabulary from the quick-run path; trim or document `RunResult` tiers.
- **M4 — [MEDIUM · Add] No runnable on-ramp for either step as-is.** Every `runs/*.toml` needs a live `quant_data` backend, so the only thing a newcomer can execute end-to-end is a **unit test**, not `quant-strategies run`. And step 2 has **no committed `validation.toml`** anywhere in tracked source — the only one (`results/notebook_configs/...validate.toml`) sets a non-existent `mode` key and has no `[[windows]]`, so it **cannot load**. **Fix:** add a synthetic/fixture demo run (the `_LazyLoaderProxy` override seam already exists) and a committed multi-window `runs/<name>_validation.toml`; delete the broken one.
- **L5 — [LOW · Refactor] Doc drift vs enforced contract.** README:64 teaches a `thesis` docstring heading, but `tests/test_strategy_docstrings.py` enforces `Market rationale:` (no file uses "thesis"); the contract says `rows` but every strategy (incl. the example) names the param `bars`; top-level `__init__.py` is empty (zero discoverability). Align docs to the enforced contract; add a "start here" package docstring (no re-export needed).

---

## What already exists and should be reused (Preserve)

| Existing | What it does | Why keep |
|---|---|---|
| `decisions/models.py` | the one `StrategyDecision` ontology | frozen/strict, content-hashed id, `as_of ≤ decision_time`; minimal & correct |
| `engine/evaluation.py` | the one PnL kernel | careful fills/exits/funding/cost; honest metric naming |
| `funding.py` | shared funding cashflow | correct sign/timing, single source, tested |
| `evidence_semantics.py` | metric honesty layer | the thing that stops the smoke score from lying (PRD G2) — repo's crown jewel |
| `causality.py` (mechanism) | two-direction PiT replay | materially stronger than typical backtest hygiene (fix fail-open + placement) |
| `core/config.StrategyExecutionSpec` | neutral shared seam | one execution model for both steps |
| advisory pinning (`policy.py:40-54`) | `*_eligible := False` | "never auto-promotes" enforced in code, not just docs |
| `core/events.py`, CLI | observability + 2-subcommand UX | DRY, principled exit codes |

---

## Overbuilt / Underbuilt / Right-sized

- **Overbuilt (cut/shrink):** VBT oracle stack (dead on real strategies, H2); strict replay on the quick run (H1); 888-LOC `data_contract` diagnostics on the search path (H1); `extended_ontology` + triplicated executable checks (H3); some Pydantic-as-config ceremony (M5).
- **Underbuilt (add rigor):** the gate's economic number (C1); independent multi-trade verification (H2); multiple-testing correction + out-of-sample window discipline (M1); a determinism guarantee + fail-closed lookahead (H4); on-ramps for both steps (M4).
- **Right-sized (preserve):** the entire spine listed above.

---

## Unknown unknowns & assumption risks

| Assumption baked into the foundation | Why it may be wrong | Smallest de-risk |
|---|---|---|
| `net_return` (activity sum) ≈ portfolio return when compounded | False for overlapping/fractional-weight trades (C1); repo's own `agreement.py` says so | Compute a real NAV path for one multi-trade case; compare to `Π(1+net_return)` |
| `generate_decisions` is deterministic | Nothing verifies it; purity lint is best-effort; agent optimizes against the checker | Determinism double-run (H4) |
| Strict replay verifies "no lookahead" | Fails open on prefix-fragile strategies + bad `available_at` (H4) | Count skipped probes; fail-closed |
| `available_at` from the loader is point-in-time-true | Only *timing* is replayed; restatement/survivorship invisible | Document blind spots in `validation.md`; consider a restatement check upstream in `quant_data` |
| The agent declares search pressure | Optional today; undeclared search dodges the multiple-testing downgrade (M1) | Make `[search_pressure]` mandatory at the gate |
| `researched/`/`results/` are inert | Measured zero-drift today, but no enforced snapshot==source or freshness/commit link | Add CI snapshot check + engine-commit stamp on score artifacts |

---

## Documentation & decision gaps

- **PRD is strong and self-aware** (it preaches the exact minimalism the code partially violates) — use it as the standard. But it should **explicitly mandate the SEARCH-vs-GATE cost asymmetry** for correctness checks (not just data strictness), mirroring the asymmetry that already exists, so H1 can't recur.
- **Missing ADR:** the `net_return` aggregation semantics (sum vs compound) — C1 exists because no decision record pins how the gate may aggregate the metric.
- **Stale/contradictory docs:** README `thesis` heading vs enforced `Market rationale`; `rows` vs `bars`; the non-loadable example validation config.

---

## Preserve / Refactor / Simplify / Add / Retire

| Action | Items | Rationale |
|---|---|---|
| **Preserve** | strategy contract + `decisions/models.py`; `engine.screen()`; `funding.py`; `evidence_semantics.py`; `causality` mechanism; `StrategyExecutionSpec`; advisory pinning; CLI/events; behavioral tests | the right-sized spine; the hard parts done well |
| **Refactor** | C1 gate math (sum or true-NAV); H3 one `ExecutableDecision` adapter; H4 fail-closed lookahead + determinism; M1 mandatory search-pressure + window floor; M5 computed eligibility fields; L4 superset test assertions | keep capability, fix the boundary/contract that produces drift or wrong numbers |
| **Simplify** | H1 tier rigor (strict replay + heavy `data_contract` + provenance → gate-only); M3 hide gate vocabulary + trim `RunResult` from quick-run on-ramp | remove per-iteration cost the search path never needed |
| **Add** | M2 fill-convention disclosure; M4 synthetic demo run + committed validation example; L1 one outer artifact-write guard; L2/L3 honest failure/provenance signals; ADR for metric aggregation | trustworthiness requires these |
| **Retire** | H2 VBT oracle (until multi-trade-capable) or rebuild as ledger diff; H3 `extended_ontology` (until executable); `boundary.py` name (→ `frozen.py`); stale `results/`/`researched/...stateful_rebalance`/`.DS_Store` | preserving them misleads the reader or guards a non-existent regime |

---

## Prioritized recommendations

| Priority | Action | Recommendation | Why now | Verify |
|---|---|---|---|---|
| **P1** | Refactor | **C1** — stop compounding `sum_signed_trade_activity_net`; sum it, or gate on a real per-window NAV; rename the gate | the gate's decisive number is unsound; everything downstream inherits it | add a test: a multi-trade fixture where `Σ` and `Π(1+·)` disagree in sign → gate uses the sound one |
| **P1** | Refactor | **H4** — fail-closed lookahead (skipped-probe → not verified) + determinism double-run | false "verified clean" is worse than no check; agent optimizes against it | regression: prefix-fragile + nondeterministic fixtures must not report `causality_verified` |
| **P1** | Simplify | **H1** — make strict replay + heavy `data_contract` + provenance gate-only; quick-run does emitted-check + `causality_verified=false` | restores the "light run" you asked for; biggest velocity win | benchmark a quick run before/after on the ensemble strategy; assert verdict-parity at the gate |
| **P2** | Retire/Refactor | **H2** — delete or rebuild the VBT oracle to a trade-by-trade ledger diff | removes ~500 LOC of dead comfort; restores a real cross-check | grep: no `skipped:not_single_trade` on any gated run |
| **P2** | Refactor | **H3** — one `ExecutableDecision` adapter; retire/quarantine `extended_ontology` | single source of truth for the kernel's contract; removes agent footgun | `codegraph_impact` shows one owner; agent can't instantiate an unexecutable decision silently |
| **P2** | Refactor/Add | **M1** — mandatory `[search_pressure]` at the gate; raise OOS window floor | thin correlated data + undeclared search currently reaches `mechanical_review_candidate` | gate refuses agent candidate without declared trial count |
| **P3** | Add/Simplify | **M2/M3/M4/M5** — fill-convention disclosure; trim quick-run vocabulary & `RunResult`; demo + validation example; computed eligibility | clarity + onboarding + honesty; low risk | new dev runs both steps offline in minutes; docstring/README contract aligned |
| **P3** | Add/Retire | **L1/L2/L3/L5 + cruft sweep** — outer artifact-write guard; honest failure/provenance; doc alignment; prune stale dirs | closes the F19 family for the API consumer; removes reader-misleading cruft | API caller never sees a raw `OSError`; `git status` clean of stale results |

---

## NOT in scope

- Internals of `quant_data` and `quant_autoresearch` (reviewed only at the seam). The restatement/survivorship blind spots (M-quant) are partly **`quant_data`'s** responsibility — give them the structured feedback the PRD already promises.
- Live-data correctness / actual PnL materiality of C1 and M2 — needs a run against real rows (not executed here).
- The promotion process (`untested` → `tested`) — human-led, out of this code.
- Micro-latency tuning — explicitly out per PRD §8.

---

## Verification Summary

- **Verified by my own source reads:** the spine (`runner/__init__.py`, `validation/__init__.py`, `engine/evaluation.py`, `decisions/models.py`, `causality.py`, `funding.py`, `evidence_semantics.py`, `observation_dependencies.py`, `provenance.py`, `boundary.py`, `runner/config.py`, `validation/policy.py`, `validation/agreement.py`); C1 (compounding) traced end-to-end and cross-checked against the repo's own `agreement.py` docstring; H1 (no causality-mode knob; strict default); H2 (oracle skip `trade_count!=1` + `enabled=False`); H3 (grep: `extended_ontology` has zero `src/` importers); structure/LOC via codegraph (97 files, 2177 nodes).
- **Reasoned-from-source (not executed):** magnitude of the C1 verdict error; exploitability of the H4 fail-open paths; real-world materiality of the M2 stop-fill optimism. No `quant_data` rows were loaded; the test suite was not run; VBT Pro not importable here.
- **From independent lenses, spot-checked by me:** the `researched/` zero-drift measurement (15 snapshot pairs), the 1.66:1 test ratio, the 34-term vocabulary count, the triplicated executable-ontology sites.
- **Residual risk:** the heaviest correctness risk (C1) is proven as a *defect* but its *impact* on any specific strategy is unmeasured until run against live data; the windows×scenarios statistical strength (M1) is assessed from code because **no loadable validation config exists** in the repo to observe a real run.

---

*Bottom line: keep the spine, fix the gate's number (C1), make the quick run light again (H1), make the lookahead guard honest (H4), and cut the dead oracle and second ontology (H2/H3). That is a focused refactor — not a rewrite — and it converts a well-built harness into a trustworthy one.*
