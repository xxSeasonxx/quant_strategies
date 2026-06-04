# Foundation Review — `quant_strategies`

- **Reviewer:** Claude (Opus 4.8), senior-quant-researcher lens + standard foundation lenses
- **Commit:** `a1c7236` (branch `main`)
- **Date:** 2026-06-04
- **Scope:** Whole foundation default path — `runner`, `core`, `engine`, `decisions`, `validation`, `evaluation`, plus the shared top-level modules. `extended_ontology` and `untested/` strategies were boundary-checked only, not deep-reviewed (per locked scope).
- **Mode:** Fresh independent verdict from source, then audited against `FOUNDATION_LOCK.md` / prior reviews / `TODOS.md`. Five fresh-context lens subagents (onboarding, architecture, senior SWE, adversarial, quant-math) were run blind to the prior reviews; the main reviewer owns the reconciliation below and did not adopt any lens conclusion without independent code verification.
- **Artifact status:** archived historical review; accepted cleanup findings are
  dispositioned by `FOUNDATION_LOCK.md` and current tests/docs.

---

## 1. Executive Verdict

**The foundation is sound and good to begin running. There are no critical math errors and no legacy/output bias. Start running with targeted configs.**

The three things you were most worried about resolve cleanly:

1. **Math correctness (the gate): PASS.** I read the execution kernel, the perp NAV ledger, funding, cost, drawdown, and the annualization stack line by line, independently of the math lens, and they agree: **0 critical, 0 high math errors.** Signs, units, timing, and metric naming are all correct and — importantly — *honestly labeled*. The engine emits `sum_signed_trade_activity_*`, never "return"; only the genuine compounded NAV path emits `total_return`. That is exactly the PRD-G2 discipline you wrote, actually enforced in code.

2. **Over-engineering / "layered of layered": mostly a naming artifact, not real duplication.** 68 files for three jobs *looks* heavy, but the dependency graph is acyclic, no surface imports another surface, `core` never imports a surface, and the "god-function" risk is absent — the `run_*` orchestrators are linear stage decomposition. The shared spine is real: all three jobs adapt into one `StrategyExecutionSpec` and call one `execute_strategy_run`. The genuine trims are small and listed below (a dormant module, a single-impl registry, duplicated vbt helpers, brittle doc-tests, and some confusing names).

3. **Legacy / existing-output bias: none.** `results/`, `validation_results/`, `evaluation_results/` are gitignored; there are **zero committed generated artifacts** (no goldens, no parquet, no summary.json), and **zero `legacy`/`compat`/`shim`/`deprecated` mentions in `src/`**. Nothing pins you to stale output. The "we can always rerun" claim is true in the code, not just the docs.

**Workflow simplicity: confirmed simple.** Three CLI verbs (`run` / `validate` / `evaluate`), one pure strategy contract, a three-function public API. A competent engineer traces a quick run end to end in ~5 hops / 10–15 minutes from source.

The single highest-value fix *before you lean on the numbers over time* is reproducibility hygiene, not correctness: **the numeric backend `vectorbtpro` is completely unpinned** (H1). Everything else is medium/low polish or expectation-setting. None of it blocks starting.

A note on honesty, since you asked for it: the adversarial lens returned a **CRITICAL "end-of-history lookahead" finding**. I chased it into the code and **it does not hold** — the replay correctly catches future-data use, and `as_of_time ≤ decision_time` is enforced. What survives is the in-sample/overfitting limitation, which no point-in-time replay can detect and which your PRD already scopes out. Reconciliation in §8. I'm flagging this explicitly so the "no critical errors" verdict is auditable rather than asserted.

---

## 2. Scope and Evidence Inspected

Read in full or in the relevant region (source, not docs):

- **Kernel / math:** `core/execution.py`, `engine/evaluation.py`, `engine/models.py`, `engine/executable.py`, `engine/bar_index.py`, `funding.py`, `core/config.py`.
- **Portfolio math:** `evaluation/vectorbtpro_backend.py` (perp ledger NAV loop, `_equity_at_mark`, `_perp_ledger_metrics`, `_sample_stdev`, `_downside_deviation`, fill helpers), `evaluation/metrics.py`, `runner/economic_metrics.py`.
- **Causality:** `causality.py` (full), `observation_dependencies.py`, `decisions/models.py`.
- **Pipelines/boundaries:** `validation/_pipeline.py` and `evaluation/_pipeline.py` audit/preflight ordering; `data_contract.py` (row hashing/order).
- **Claim docs audited against code:** `PRD.md`, `README.md`, `docs/foundation-surfaces.md`, `FOUNDATION_LOCK.md`, `TODOS.md`, `docs/reviews/README.md`.
- **Repo hygiene:** `.gitignore`, `git ls-files` over `runs/ untested/ examples/`, legacy/compat grep across `src/`.

Verified by execution (via the SWE lens, `conda run -n quant`): **full suite 958 passed, 1 skipped** (the intentional `RUN_VECTORBTPRO_SMOKE` gate), 38s, with `vectorbtpro 2026.4.7` / `pyarrow 23.0.1` / `pandas 2.3.3` installed so no tests were silently skipped.

**Not verified:** real `quant_data` runtime behavior (upstream; row-ordering determinism assumed, see M1); `extended_ontology` and `untested/` strategy internals; non-default `[[scenarios]]` matrices beyond reading the code path.

---

## 3. Intended Foundation Model (first principles)

The irreducible job: **turn a pure `generate_decisions(rows, params)` into trustworthy, causally-honest, unit-tagged evidence — and never let a number with unclear semantics drive a conclusion.** A minimal sound foundation needs exactly:

1. A typed, pure strategy contract (input rows → typed decisions).
2. One execution spine: load (via `quant_data`) → freeze → generate → **prove no lookahead**.
3. A trade-level PnL contract whose numbers are the numbers a human audits (quick run + validation).
4. A separate portfolio/NAV evidence path for frozen candidates (evaluation), not pretending linear trade sums are NAV.
5. Deterministic, immutable, auditable artifacts; advisory-only verdicts; no promotion authority.

The current code expresses all five. The boundaries match the ontology; the abstractions mostly earn their place.

---

## 4. Project Ontology: Concepts, Contracts, Boundaries, Invariants

- **Strategy** = pure `generate_decisions`; purity is a best-effort AST lint, the *real* guarantee is the causal replay. ✔ honest in docs and code.
- **Decision** (`StrategyDecision`, frozen, `extra="forbid"`, `strict=True`) carries `as_of_time ≤ decision_time` (enforced), instrument, target, exit policy, optional observations, content-hashed `decision_id`. ✔ invalid states are genuinely hard to represent.
- **Execution spec** (`StrategyExecutionSpec`) = neutral input all three surfaces adapt into. ✔ no surface owns another's path.
- **Engine result** = per-trade ledger + `sum_signed_trade_activity_*` (linear activity, **not** NAV). ✔ naming invariant holds.
- **Evaluation** = compounded NAV via vbt (non-funding) or `project_perp_ledger_v1` (perps). ✔ separate path, separate contract.
- **Invariants that must never be violated:** no decision uses data after its `as_of_time`; artifacts immutable; `*_eligible` always False. All three hold in code (§8 confirms eligibility flags are hard-coded, unflippable by config).

---

## 5. What Already Exists and Should Be Reused (Preserve)

These are right and should not be touched:

- The **causal replay** (`causality.check_hidden_lookahead`): bidirectional (subset check for decision-altering lookahead; strict suppression check for trade-withholding lookahead), with honest skipped-probe accounting that refuses to claim `strict_suppression_verified` when probes were skipped. This is the load-bearing correctness mechanism and it is well-built.
- The **engine PnL math** and **perp ledger** — correct signs, adverse slippage, fee-on-notional, mark-to-market NAV, funding window `entry < ts ≤ exit`, no double-count at shared boundaries, residual-open-position hard error.
- **Metric naming/units discipline** (`runner/economic_metrics.py`, `evaluation/metrics.py` semantics) — no silent zeroing; ratios/`profit_factor`/`sortino` return `None` (never `inf`); annualized family gated behind cadence + min-sample floor.
- **Determinism/immutability machinery** — identity hashes exclude runtime/env/git-dirty; re-runs go to new dirs; eval uses staging→atomic-rename.
- **Boundary signposting** — `engine/__init__.py`'s "not a public surface" docstring; tight `__all__` per public package; advisory `*_eligible=False` hard-coded constants.
- **Repo hygiene** — gitignored output roots, no committed goldens, no legacy code.

---

## 6. Architecture and Boundary Review

**Verdict: right-sized to begin running.** Acyclic, clean dependency direction (surfaces → core → engine → leaf modules), three jobs map 1:1 to `run_config`/`run_validation`/`run_evaluation` + CLI.

Genuine structural findings (all Medium/Low — none block running):

- **The "one execution kernel" claim is half true.** All three share the *decision* kernel (`execute_strategy_run`). The *price-path* forks by design: runner + validation use `engine.screen` (linear per-trade); evaluation uses the NAV backends and never touches `screen`. The README/architecture diagram overstates this as "one execution kernel." → fix the claim (M7).
- **Naming legibility, not layering.** `core/execution.py` (strategy-run orchestration) vs `core/engine_runner.py` (decisions→`EvaluationRequest` adapter) vs `engine/` (PnL kernel) are three sequential stages with generic names on the same peer level — they *read* like stacked wrappers but are not. → rename to intent (M7).
- **Speculative generality (trim targets):** `validation` `get_backend` registry resolves exactly one implementation (`engine`); `decisions/extended_ontology.py` has **zero production importers** (4 test files only). Both are dormant variability points. Keep `extended_ontology` quarantined per your multi-asset roadmap; collapse the single-impl dispatch (M8).
- **Two `vectorbtpro_backend.py` duplicate ~6 leaf vbt-frame helpers**, and the *project-owned* perp ledger lives inside the file named for the third-party vbt backend — a cohesion/naming smell. Hoist shared helpers; consider relocating/renaming the perp ledger (M9).
- **Minor upward edge:** `engine/models.py` aliases `core.config` cost/fill types, so the "innermost" kernel imports up a layer (types only, no cycle) (L5).

---

## 7. Engineering, Testability, and Operability Review

**Verdict: engineering-ready to run repeatedly.** All NFRs (determinism, immutability, observability, root-cause error handling, failure semantics) are met in code and proven by tests. Zero bare `except`, zero `except: pass`, zero TODO/FIXME in `src/`. Failures translate to structured `failure_stage` results with differentiated CLI exit codes (0/1/2/3).

Gaps to close early (not blockers):

- **H1 — unpinned numeric backend.** `vectorbtpro` has no version bound at all; `pandas>=2.2`/`pyarrow>=16` have no upper bound. Because the package version is (correctly) excluded from the identity hash, a silent `pip` upgrade can change validation/evaluation numbers with no determinism signal. This is the one finding that directly undermines "trust the numbers across time," and it is inconsistent with `quant-data` being bounded `>=0.1.0,<0.2.0`.
- **M1 — order-dependent identity hash.** `normalized_rows_sha256` hashes rows in the order `quant_data` returns them (`data_contract.py:310,335`); rows are never sorted. Same logical data in a different order → different identity. NFR-DETERMINISM silently depends on an upstream ordering contract the foundation never asserts.
- **M3 — no static type/lint gate.** Heavy annotations + strong-typing NFR, but no mypy/ruff configured or wired into `make check`; types are only enforced at runtime via pydantic.
- **L4 — one typing lapse:** evidence-quality / row-contract payloads flow as `dict[str, Any]` across stage boundaries and are re-parsed defensively.
- **L6 (over-built):** a cluster of tests assert on Makefile target ordering, exact `docs/reviews/README.md` row text, and review-file date-naming — brittle doc-drift guards that inflate the test count without testing behavior. Candidates to trim (relevant to your over-engineering concern).

Note: the 21.7k/13.7k test:source ratio is **justified**, not bloat — engine fills, causality replay, failure semantics, and byte-determinism all have real behavioral coverage. The only over-built sliver is the doc-assertion tests above.

---

## 8. Domain-Specific (Quant) Lens Findings

**Math gate: PASS — 0 critical, 0 high.** Detail of what was verified correct:

- **Signal timing / lookahead:** `entry_index = decision_index + entry_lag_bars` with `entry_lag_bars ≥ 1` (no same-bar entry); exit scan starts at `entry_index + 1` (no same-bar exit at the trigger detection); `as_of_time ≤ decision_time` enforced. No off-by-one.
- **Fill sampling:** stop/take-profit/trailing evaluated on `open`/`close`/`bid`/`ask` at bar timestamps, never `high`/`low` — matches the documented sampled-threshold model and is not optimistic-intrabar.
- **PnL signs:** `direction = +1 long / −1 short`; short profits when price falls. Slippage adverse in both engine and ledger.
- **Funding:** `Σ(−direction·rate)·weight`, window `entry < ts ≤ exit` — long pays positive funding, short receives. Consistent across engine and ledger; no double-count at shared boundaries.
- **Annualization:** sample stdev uses Bessel `n−1`; `volatility = stdev·√periods`; `sharpe = (mean·periods)/vol`; `calmar = annualized/|max_dd|`; drawdown `= nav/peak − 1`. Annualized/risk family nulls on cadence mismatch or `< min_annualized_samples`, and `sortino`/`profit_factor` return `None` (not `inf`) when there's no downside/loss.

Two math items worth a one-line doc note (Medium, not errors):

- **M4 — Sortino convention.** `_downside_deviation` divides by the *total* return count (target-semivariance, target=0), not the count of downside returns. Both conventions are accepted; pin it in the metric semantics so a reviewer comparing against a library using the other convention isn't surprised.
- **M5 — two funding bases.** Engine funding is fraction-of-*entry*-notional; ledger funding is mark-notional. Both correct, but not numerically equal once price moves, and the agreement oracle deliberately excludes funding. State this so the two are not expected to match.

### Reconciliation of the adversarial CRITICAL (S1) — downgraded to LOW

The adversarial lens claimed end-of-history / in-sample lookahead survives the replay and is "exploitable by construction." **I verified in code that it does not hold as a lookahead bug:**

- The replay truncates to rows with `timestamp ≤ as_of_time` and `available_at ≤ decision_time` (`causality.py:434,446-453`). For any decision with future bars, using data after `as_of_time` changes the truncated-replay output → caught by the subset check (`hidden_lookahead_detected`).
- A decision at the literal last bar can't be filled (`entry_lag ≥ 1` needs a later bar), and using all data *up to* `as_of_time` is causal by definition — there is no "future" to peek at.
- `as_of_time ≤ decision_time` is enforced (`models.py:168`), so a strategy cannot declare a late knowledge time for an early action to widen its visible prefix.

What genuinely remains is **in-sample parameter fitting** (fitting a threshold on the whole historical window) — a research-methodology / overfitting concern that *no* point-in-time replay can detect, and which the PRD already scopes out ("validation does not answer durable alpha, statistical significance, regime robustness"). So this is an **expectation-setting note (L1)**, not a code defect: make explicit that "no lookahead" means point-in-time causality, not freedom from in-sample bias. (S3 — "observation audit is opt-in" — collapses into this: the replay is the real gate and it's sound; observations are lineage.)

The adversarial lens also independently **failed to break** the advisory-eligibility boundary (hard-coded `False`, unflippable), decision-id determinism, metric coercion (no silent zeroing), purity-with-replay-backstop, and committed-artifact bias. Those are real strengths.

The one adversarial finding that *is* a genuine new gap: **M2 — silent zero funding for a `crypto_perp_funding` window containing no funding events.** The engine returns `0.0` with no warning; the evaluation path at least reports `funding_event_count=0` (detectable). Real perp data always carries funding, so this bites only on degenerate/mis-loaded data — but the foundation should warn or fail rather than silently drop carry.

---

## 9. Unknown Unknowns and Assumption Risks

- **Upstream row-order determinism (M1):** the whole determinism story assumes `quant_data` returns a stable row order. Unverified here; the foundation doesn't assert it.
- **Numeric backend drift (H1):** results' reproducibility over time depends on a `vectorbtpro` version that is currently unpinned.
- **Perp datasets always carry funding (M2):** assumed, not enforced.
- **In-sample bias (L1):** the foundation certifies causality, not statistical validity — correct by design, but easy to over-trust.

---

## 10. Overbuilt / Underbuilt / Right-Sized

- **Overbuilt (trim):** `extended_ontology.py` (0 prod users — keep dormant), single-impl `validation` backend registry, duplicated vbt-frame helpers, doc-assertion tests.
- **Underbuilt (add):** backend version pins (H1), row-order normalization (M1), type/lint gate (M3), typed input-row contract (M6), perp zero-funding guard (M2).
- **Right-sized (preserve):** causal replay, engine/ledger math, metric semantics, determinism/immutability machinery, public/internal boundary, repo hygiene.

---

## 11. Missing Docs / Decisions

- The "one execution kernel" framing in `README.md` should become "one *decision* kernel + a price-path that forks (engine screen vs NAV backend), cross-checked by the agreement oracle" (M7).
- Sortino convention (M4) and dual funding bases (M5) belong in the metric semantics.
- An explicit "what 'no lookahead' does and does not mean" note (L1).
- `core/` and root modules lack one-line module docstrings (L3); `engine/__init__.py` is the template to copy.

---

## 12. Architecture / Lifecycle Diagram (as-built)

```
 experiment.toml / validation.toml / evaluation.toml
        |
        v
 pure strategy.py  generate_decisions(rows, params) -> [StrategyDecision]
        |
        v
 StrategyExecutionSpec  (neutral; runner/validation/evaluation all adapt into it)
        |
        v
 execute_strategy_run        <-- THE shared DECISION kernel (core/execution.py)
   load via quant_data -> freeze -> validate params -> generate -> validate output
        |
        +--> audit_decision_rows + check_hidden_lookahead   (causal preflight; both validation & evaluation)
        |
        v
   frozen rows + typed decisions + causal proof
        |
        |------------------------- price path forks here -------------------------|
        v                                                                          v
 engine.screen (core/engine_runner.py -> engine/)                      evaluation NAV backends
   per-trade ledger, sum_signed_trade_activity_*                         vbt (non-funding)
        |                                                                 project_perp_ledger_v1 (perps)
        +--> quant-strategies run    (quick run: diagnostic evidence)            |
        +--> quant-strategies validate (windows x scenarios -> advisory)         +--> quant-strategies evaluate
                |   `-.opt-in single-trade.-> vbt agreement oracle                     (portfolio/path/economic evidence)
                v
        human promotion review  (outside the code; *_eligible always False)
```

---

## 13. Action Map (Preserve / Refactor / Simplify / Add / Retire)

`Status` is for your tracking. `Disp` = disposition vs `FOUNDATION_LOCK.md`/`TODOS.md` (new / accepted_debt / deferred).

| No. | Status | Sev | Action | Finding | Where | Disp |
|----|--------|-----|--------|---------|-------|------|
| H1 | open | High | Add | Pin `vectorbtpro` (and upper-bound `pandas`/`pyarrow`); a silent upgrade changes the numbers invisibly | `pyproject.toml` | new |
| M1 | open | Med | Add | Sort normalized rows by `(symbol,timestamp)` before hashing, or assert upstream order; identity is order-dependent | `data_contract.py:310,335` | new |
| M2 | open | Med | Add | Warn/fail when `crypto_perp_funding` window has zero funding events instead of silent 0 carry | `engine/evaluation.py:274`, `data_contract.py` | new |
| M3 | open | Med | Add | Wire a `mypy`/`ruff` gate into `make check`; types are only runtime-enforced today | `Makefile`, `pyproject.toml` | new |
| M4 | open | Med | Add | Pin Sortino denominator convention (total-N / target-semivariance) in metric semantics | `evaluation/metrics.py:88-97` | new |
| M5 | open | Med | Add | Document engine-funding (entry-notional) vs ledger-funding (mark-notional) base difference | `evaluation/metrics.py`, `funding.py` | new |
| M6 | open | Med | Add | Give strategy authors/agents a typed input-row contract (TypedDict per `data.kind`) or document it on the `StrategyGenerator` protocol; today each strategy re-implements field validation | `decisions/strategy_loader.py` | new |
| M7 | open | Med | Refactor | Fix "one execution kernel" doc claim (it's one *decision* kernel + forked price path); rename `core/execution.py` / `core/engine_runner.py` to intent | `README.md`, `core/` | new (facade size = accepted_debt) |
| M8 | open | Med | Simplify | Collapse single-impl `validation` `get_backend` dispatch; keep `extended_ontology` dormant/quarantined (zero prod importers) | `validation/backends.py`, `decisions/extended_ontology.py` | new / roadmap |
| M9 | open | Med | Simplify | Hoist ~6 shared vbt-frame helpers; relocate/rename `project_perp_ledger_v1` out of the vbt-named file | `validation/` + `evaluation/vectorbtpro_backend.py` | new |
| L1 | open | Low | Add | Doc note: "no lookahead" = point-in-time causality, not in-sample/overfitting protection; observation audit is lineage, replay is the gate | docs + `causality.py` | new (replaces adversarial S1/S3) |
| L2 | open | Low | Preserve | Quick-run `assessment_status` is always `diagnostics_complete` by design; structured evidence carries real flags | `runner/artifacts.py:376` | new |
| L3 | open | Low | Add | One-line module docstrings on `core/` and root modules (copy `engine/__init__.py`) | `core/`, root modules | new |
| L4 | open | Low | Refactor | Replace `dict[str,Any]` stage-boundary payloads with a frozen type/`TypedDict` | `runner/__init__.py`, `core/execution.py` | new |
| L5 | open | Low | Refactor | Move cost/fill config into `engine`, or document the engine→core upward edge | `engine/models.py` | new |
| L6 | open | Low | Simplify | Trim brittle doc/structure-assertion tests (Makefile ordering, README row text, review-file naming) | `tests/test_repository_boundaries.py`, `tests/test_evaluation_docs.py` | new |
| — | n/a | — | accepted_debt/deferred | VBT agreement single-trade scope; mid-pipeline I/O `OSError`; candidate-local output paths; `net_return` dual semantics; `_is_true_flag` coercion | per `FOUNDATION_LOCK.md` / `TODOS.md` | not re-raised |

---

## 14. Prioritized Recommendations

1. **Before relying on numbers across time:** H1 (pin the numeric backend). Cheap, high leverage for reproducibility.
2. **Cheap correctness hygiene:** M1 (row-order hash) and M2 (perp zero-funding guard) — both small, both close real unguarded assumptions.
3. **Documentation truth-in-labeling (one sitting):** M4, M5, M7, L1 — make the metric and kernel claims match the code so consumers don't over-trust.
4. **Maintainability gates:** M3 (mypy/ruff), M6 (typed row contract). Improve agent-friendliness and catch drift.
5. **Trim, when convenient (your over-engineering concern):** M8, M9, L6, L3, L5. None urgent.

You can start running today. The math is right, the workflow is simple, and you are not biased by old output. Treat the list above as polish during early runs, with H1 first.

---

## 15. NOT in Scope

- Deep review of `extended_ontology` and `untested/` strategy internals (boundary-checked only).
- `quant_data` upstream behavior and real row-ordering guarantees.
- VectorBT Pro internals beyond the project's usage boundary.
- Promotion/live/paper-trading concerns (explicitly out of the foundation per PRD).
- Re-litigating items already dispositioned as accepted_debt/deferred in `FOUNDATION_LOCK.md` (listed, not re-raised).

---

### Method note / deviations

Per the skill's hard gate, the objective was locked with you before inspection. One intentional deviation: I read `PRD.md` and `docs/reviews/README.md` during the gate (they are the designated objective/convention source you pointed me to) before locking. The `quant-math-code-review` and `the-fool` skills were not installed in subagent context; those lenses ran from explicit criteria and the fallback is disclosed here. The adversarial lens's CRITICAL was independently re-verified in code and downgraded with evidence (§8) rather than adopted.
