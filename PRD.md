# PRD — `quant_strategies`

**Status:** Draft v1
**Owner:** Season Yang
**Last updated:** 2026-05-28
**Companion documents:** `AGENTS.md` (agent contract), `README.md` (current state),
`docs/quant-autoresearch-consumer.md` (consumer contract).

This PRD is the source of truth for **why** `quant_strategies` exists and **what** it must
provide. `README.md` describes the current implementation; this PRD describes the target
behavior the implementation must converge to. When PRD and code disagree, the PRD describes
the work to be done.

---

## 1. One-Line Summary

`quant_strategies` is the **execution and paper-readiness foundation** for a small, focused
quant research lifecycle: a senior quant researcher (Season) and an autonomous research
agent (`quant_autoresearch`) iterate on strategies efficiently, with explicit position
semantics, mathematically correct PnL, hidden-lookahead protection, and auditable artifacts.

---

## 2. Background and Problem Statement

### What the project is

A disciplined Python library and CLI that:

1. Defines a **declarative strategy contract** (pure function → typed decisions).
2. Provides a **mathematically explicit execution kernel** that turns decisions into
  trade-level PnL with declared assumptions.
3. Provides an **advisory validation harness** that runs the strategy across windows and
  scenarios with hidden-lookahead protection and writes mechanically-auditable artifacts.
4. Exposes a **stable, minimal consumer surface** for `quant_autoresearch` to drive
  strategy iteration without touching internals.

### What the project is not

- Not a backtester users compose pipelines in. There is one pipeline. Strategies are pure
functions.
- Not a market-validation authority. All outputs are advisory; promotion requires a separate
human-led process.
- Not a data platform. Data acquisition, refresh, and repair are owned by `quant_data`.
- Not a paper-trading or live-trading harness.
- Not a research-loop driver. Auto-research is owned by `quant_autoresearch`.

---

## 3. Users and Stakeholders

### Primary users


| User                                         | Role                                                           | What they need                                                                                                                                      |
| -------------------------------------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `**quant_autoresearch`** (autonomous agent)  | Generates and iterates strategies in a tight loop; consumes runner artifacts for search ranking and validation verdicts for retained-candidate triage | Stable, typed Python API for both `runner.run_config` and `validation.run_validation`; declarative strategy contract; deterministic artifacts; clear "good vs bad" ranking signals from runner; advisory verdict labels from validation; small surface area to misuse |
| **Senior quant researcher (Season)**         | Designs strategies, audits research, makes promotion decisions | Math correctness; explicit ontology; ability to investigate any trade end-to-end; ability to add new strategy axes without rewriting the harness    |
| **Future strategy authors** (human or agent) | Write new strategy files                                       | One-page contract; obvious where to put thesis/observables/rule/falsifier; impossible to accidentally introduce lookahead                           |


### Secondary stakeholders

- `**quant_data`** (upstream): provides loaders; receives structured row-contract feedback.
- **Audit / review process**: consumes validation artifacts to support promotion decisions.

### Non-users (explicit)

- Live-trading systems. No API path leads from `quant_strategies` to order routing.
- End-user notebook explorers. The library is callable from a notebook, but ergonomics are
not optimized for ad-hoc exploration; that is `quant_autoresearch`'s domain.

---

## 4. Goals

### 4.1 Strategic goals

**G1. Default-narrow strategy expression with explicit extended ontology.**
The default strategy contract MUST express the executable v1 path clearly:

- **Direction / state**: long, short, flat.
- **Action / intent**: open.
- **Instrument**: equity / ETF, FX pair, crypto perp.
- **Sizing**: target weight.
- **Exit**: time-based plus declared optional threshold controls.

Extended vocabulary for futures, options, multi-leg structures, buy/sell book side,
close/adjust/roll actions, target notional, target contracts, and vol-targeted sizing
MUST live behind explicit opt-in imports. A strategy that needs those axes must be able
to express them without monkey-patching the foundation, but the default import path must
not imply that unsupported execution semantics are executable.

**G2. Math correctness adequate for paper-readiness research.**
Every numeric quantity emitted by the foundation MUST:

- Carry a declared **unit** and **base** (e.g., "fraction of entry notional", "percentage
points of signed trade activity", "NAV-path total return").
- Be reproducible by reading the artifact set without re-running the code **when the
consumer requested an `audit_replayable` run**. `search_only` runs MUST be explicitly
marked as not reproducible from artifacts alone.
- Declare backend-specific comparability and asymmetry explicitly. If multiple
  production backends exist later, cross-backend comparisons need a declared tolerance.
- Be **named in a way that does not overstate what it computes** (no "paper_candidate"
without statistical evidence; no "return" for a sum-of-trade-activity figure).

**G3. Modular code with explicit ontology and the right abstractions.**

- A single ontology for strategy output. The engine consumes it directly; no parallel
representation in the math layer.
- A single execution-model contract that any PnL backend implements.
- A single causal-invariant kernel shared by runner and validation; validation does not
reach into runner internals.
- A single declared freezing idiom for `params` / `rows` / `metadata`.
- Each module has one main reason to change. Orchestrator god-functions are forbidden.

**G4. Simple, hard-to-misuse consumer integration.**

- `quant_autoresearch` writes exactly two files per candidate (`strategy.py`,
`experiment.toml`).
- It reads exactly one typed result object and structured artifacts.
- The public consumer surface is intentionally narrow:
  `quant_strategies.runner.run_config` returns
  `quant_strategies.runner.RunResult`, and no top-level facade is promised.
  Strategy generation and backend extension points are Protocol-typed;
  internals are private.
- Misusing the surface (returning the wrong shape, importing private modules, etc.)
produces a clear error, not a silent miscalculation.

**G5. Trade-level auditability when the consumer asks for it.**
For any reported metric in an `audit_replayable` run, a reviewer MUST be able to trace
it to:

- the strategy file snapshot,
- the input row set (hashed and reproducible),
- the decisions produced (timestamped, with `as_of_time` lineage),
- the fills and exits (with reason),
- the funding/cost contributions,
- the configuration that produced them.

`search_only` runs intentionally omit the trade-level chain. Consumers that need to
investigate a candidate rerun it under `audit_replayable`. The foundation never auto-
promotes a run to `audit_replayable`; the consumer chooses the tier.

Validation runs additionally emit a **verdict label** (`hard_no | mechanical_pass |
watchlist | mechanical_review_candidate`) summarizing mechanical and paper-readiness
gates. **Verdict labels are advisory inputs to human review**, not autonomous
promotion signals — they MUST NOT be used by downstream automation to flip
eligibility bits. The verdict's `reasons` field carries the qualifying context (e.g.,
`no_positive_realistic_cost_evidence`, `multiple_testing_not_corrected_advisory_only`,
`search_pressure_unknown_advisory_only`);
consumers ranking on the label alone without reading reasons are operating outside
the contract.

**G6. Good performance code — decent, not microsecond-optimal.**
The foundation is written with performance discipline. The code:

- MUST NOT eagerly import dependencies a code path does not use.
- MUST NOT do redundant work: deepcopying already-frozen data, hashing the same payload
twice, reconnecting to the database per run when the engine can be cached, walking row
lists more than once when one pass suffices.
- MUST NOT serialize or write artifacts the consumer did not request — `search_only`
runs do not produce audit-replay artifacts.
- MUST use efficient formats for bulk per-row data (see C-9).

A typical search-scale run (≤1M rows, single strategy, `search_only` tier) completes in
seconds, not minutes. Micro-latency optimization (sub-100ms per run) and vectorized-
engine inner-loop tuning are explicitly out of scope (§8). The goal is good performance
code, not benchmark-chasing.

### 4.2 Non-goals (explicit, durable)

**NG1.** Market validation. Mechanical and statistical checks are advisory only; no output
flips a `paper_trade_eligible` or `live_eligible` bit autonomously. The validation
verdict label (see G5) is itself advisory — it summarizes mechanical evidence, not
market-validated alpha. Downstream consumers (including `quant_autoresearch`) MUST
treat the verdict as an input to human review, never as a promotion signal.

**NG2.** Data acquisition, refresh, repair, source joining. These belong to `quant_data`.
The foundation gives `quant_data` structured feedback when row contracts are violated and
otherwise consumes its public loader API.

**NG3.** Owning the research loop. `quant_autoresearch` owns iteration. `quant_strategies`
provides primitives, not a search driver.

**NG4.** Trading system features: order routing, execution, position keeping, risk limits,
margin, broker integration, real-time market data, alerts, dashboards. None of these belong
here.

**NG5.** Legacy-compatibility code paths. When the contract changes, strategies and configs
are updated and re-run. The foundation does not carry shims for old shapes.

**NG6.** A pluggable strategy IDE, notebook integration, or browser UI.

---

## 5. Non-Functional Requirements

- **NFR-RIGOR.** Math is correct first, fast second. Any optimization that changes
  numerical results requires an explicit decision record.
- **NFR-DETERMINISM.** Given the same source, config, and data, deterministic
  runner and validation manifests keep research identity focused on source commit,
  inputs, decisions, and artifact hashes. Python build, installed package versions,
  git dirty status, and tracked diff hashes are audit context only and live in
  `environment.json`, which manifest artifact hashes exclude.
- **NFR-IMMUTABILITY.** No artifact is mutated after write. Re-runs go to new
  directories.
- **NFR-CAUSALITY.** The lookahead invariant is foundational: no run completes with
  `assessment_status` other than `runner_failed` if any decision violates it.
- **NFR-SIMPLICITY.** New strategy authors can read one Protocol + one decision schema
  and write a working strategy quickly.
- **NFR-ROOT-CAUSE.** When a bug is fixed, the fix lands at the boundary or contract that
  produced it. Wrappers, guards, adapters, and "the new code path" are anti-patterns
  unless explicitly justified.
- **NFR-NO-LEGACY.** Old strategies, configs, and artifacts that depend on retired
  shapes are re-generated, not back-compat'd. Migration documents live in the relevant
  decision records, not in code.
- **NFR-OBSERVABILITY.** Structured logging is emitted at stage boundaries. Stage names
  match artifact taxonomy.
- **NFR-AGENT-FRIENDLY.** Strategy and config shapes are LLM-friendly (small, typed,
  documented in module docstrings + Protocols), so `quant_autoresearch` can generate
  them reliably.

---

## 6. Success Criteria

A consumer should be able to say "yes" to all of these without qualification.

- **Expressiveness.** A quant can use the default executable ontology without ambiguity,
  and can opt into extended vocabulary for put/call, buy/sell, long/short/flat,
  single-leg and multi-leg research without monkey-patching the foundation.
- **Math correctness.** Every emitted metric is unit-tagged, named consistently with
  what it actually computes, and either agrees across backends within a declared
  tolerance or has the asymmetry declared explicitly. `audit_replayable` runs are fully
  reproducible from artifacts; `search_only` runs are explicitly marked as not
  reproducible.
- **Consumer integration.** `quant_autoresearch` drives iteration end-to-end using only
  the public surface; misuse fails fast and clearly.
- **Auditability.** Any reported number in an `audit_replayable` run is back-traceable
  from artifacts alone to the decisions, fills, and config that produced it.
  `search_only` runs intentionally omit the trade-level chain.
- **Performance.** Typical search-scale runs complete in seconds, not minutes. Overhead
  the strategy did not request (eager imports, redundant deepcopies, per-run database
  reconnects, unwanted artifact writes) does not dominate wall-clock time.
- **Code quality.** A single ontology, a single execution-model contract, a single shared
  kernel between runner and validation, and no orchestrator god-functions.

---

## 7. Constraints

- **C-1.** Python ≥ 3.12; pydantic ≥ 2.10; `quant-data` for data loading. Optional
  `vectorbtpro` for one validation backend.
- **C-2.** Conda environment `quant`. All Python commands run via `conda run -n quant`.
- **C-3.** `quant_data` is the only source of market data. The foundation does not load
  CSVs, fetch APIs, or maintain caches.
- **C-4.** Strategy files live flat under `untested/` or `tested/` directories or inside
  candidate workspaces driven by consumers. No nested strategy "framework" hierarchies
  inside strategies.
- **C-5.** Results are written under ignored `results/` directories (per config). No
  results land in `src/` or in version-controlled trees.
- **C-6.** Promotion into `tested/` from `untested/` or `researched/` is a separate
  human process. The foundation never auto-promotes.
- **C-7.** No network IO in the engine or kernel. All data comes from `quant_data`
  loaders called from the runner.
- **C-8.** No legacy compatibility shims. Contract changes require regenerating
  strategies and rerunning configs.
- **C-9.** Artifact production is tiered and format-disciplined. The consumer requests
  either `search_only` (statistics + manifest, default) or `audit_replayable` (full
  audit chain) per run. Bulk per-row artifacts in `audit_replayable` runs (input rows,
  trades, fills) use an efficient columnar format (parquet). Control-plane artifacts
  (manifest, summary, config, evidence) stay sort-keys JSON. JSONL is reserved for
  human-streaming debug, not for primary audit data.

---

## 8. Out of Scope (explicit)

- Live trading, paper trading, order routing, broker integration.
- Real-time market data feeds.
- A general-purpose backtesting framework. The smoke engine is a *screening primitive*;
  the vbt backend is a *validation primitive*. Neither is a backtester for free
  composition.
- Strategy generation. (Owned by `quant_autoresearch`.)
- Data acquisition / repair / join. (Owned by `quant_data`.)
- Promotion automation. (Human-led process.)
- Statistical gating beyond advisory metrics.
- Micro-latency optimization (sub-100ms per run) and vectorized-engine inner-loop
  tuning. Performance discipline (no eager imports, no redundant work, no unrequested
  artifact writes) is in scope under G6; benchmark-chasing is not.
- A web UI, dashboard, or notebook integration.

---

## 9. Document Maintenance

- This PRD is updated when a Goal, Non-Goal, or Constraint changes.
- `README.md` describes current behavior. When PRD and `README.md` diverge, PRD wins for
  intent; `README.md` is a bug to be fixed.
- `AGENTS.md` governs how agents operate inside this repo and is consistent with this
  PRD; if they conflict, the more specific instruction wins (per `CLAUDE.md` global
  policy).

*End of PRD v1.*
