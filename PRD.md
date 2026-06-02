# PRD — `quant_strategies`

**Status:** Draft v1
**Owner:** Season Yang
**Last updated:** 2026-06-01
**Companion documents:** `AGENTS.md` (agent contract), `README.md` (current state),
`FOUNDATION_LOCK.md` (locked foundation contracts),
`docs/quant-autoresearch-consumer.md` (consumer contract).

This PRD is the source of truth for **why** `quant_strategies` exists and **what** it must
provide. `README.md` describes the current implementation; this PRD describes the target
behavior the implementation must converge to. When PRD and code disagree, the PRD describes
the work to be done.

---

## 1. One-Line Summary

`quant_strategies` is a **stateless research foundation**: it has three
implemented public surfaces today — diagnostic quick runs, mechanical evidence
validation, and research evaluation for frozen candidates.

---

## 2. Background and Problem Statement

### What the project is

A disciplined Python library and CLI that:

1. Defines a **declarative strategy contract** (pure function -> typed decisions).
2. Provides a **mathematically explicit execution kernel** that turns decisions into
   trade-level PnL with declared assumptions.
3. Provides a **diagnostic quick-run harness** that computes quick-run evidence,
   causality hygiene, and bounded behavior diagnostics for one strategy version.
4. Provides a **mechanical evidence validation harness** that runs a retained
   candidate across windows and scenarios with hidden-lookahead protection and
   mechanically auditable artifacts.
5. Separates the **research evaluation** job from validation: evaluation is
   where frozen candidates receive portfolio, path, and economic evidence under
   explicit assumptions.
6. Exposes a **stable, minimal consumer surface** for `quant_autoresearch` to drive
   strategy iteration without touching internals.

### What the project is not

- Not a general-purpose backtesting framework where users compose arbitrary
pipelines. There is one foundation pipeline. Strategies are pure functions.
The research evaluation surface owns stateless historical evaluation evidence
for frozen candidates under explicit assumptions.
- Not a market-validation authority. All outputs are advisory; promotion requires a separate
human-led process.
- Not a data platform. Data acquisition, refresh, and repair are owned by `quant_data`.
- Not a paper-trading or live-trading harness.
- Not a research-loop driver. Auto-research is owned by `quant_autoresearch`.

### Foundation jobs

The product contract distinguishes three jobs:

| Job | Status | Purpose |
| --- | --- | --- |
| Quick run | Implemented public surface | Fast causal diagnostics for one strategy version. |
| Mechanical evidence validation | Implemented public surface through `quant-strategies validate` | Retained-candidate integrity checks across windows and scenarios. |
| Research evaluation | Implemented public surface through `quant-strategies evaluate` | Stateless historical economic, path, and portfolio evidence for frozen candidates. |

Validation is not research evaluation. It verifies that evidence was produced
honestly, causally, reproducibly, and audibly under explicit config. It does not
answer whether a strategy has durable alpha, statistical significance, regime
robustness, benchmark-relative edge, capacity, or portfolio quality.
Evaluation is now an implemented stateless surface for frozen-candidate
portfolio/economic/path evidence. Programmatic callers use
`quant_strategies.evaluation.run_evaluation` with a candidate-local
`evaluation.toml`; evaluation writes detailed trace artifacts as Parquet through
`pyarrow`. It remains separate from validation and does not authorize promotion, paper trading, or live trading. Benchmark-relative metrics are deferred.

---

## 3. Users and Stakeholders

### Primary users


| User                                         | Role                                                                                                                                                                | What they need                                                                                                                                                                                                                                     |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `**quant_autoresearch`** (autonomous agent)  | Generates and iterates strategies in a tight loop; consumes quick-run diagnostics for one-version improvement, validation verdicts for retained-candidate triage, and evaluation evidence for frozen-candidate review | Stable, typed Python API for `runner.run_config`, `validation.run_validation`, and `evaluation.run_evaluation`; declarative strategy contract; deterministic artifacts; bounded behavior diagnostics; advisory verdict labels from validation; small surface area to misuse |
| **Senior quant researcher (Season)**         | Designs strategies, audits research, makes promotion decisions                                                                                                      | Math correctness; explicit ontology; ability to understand behavior slices and investigate trades end-to-end; ability to add new strategy axes without rewriting the harness                                                                       |
| **Future strategy authors** (human or agent) | Write new strategy files                                                                                                                                            | One-page contract; obvious where to put thesis/observables/rule/falsifier; impossible to accidentally introduce lookahead                                                                                                                          |


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

**G2. Math correctness adequate for advisory research evidence.**
Every numeric quantity emitted by the foundation MUST:

- Carry a declared **unit** and **base** (e.g., "fraction of entry notional",
"percentage points of signed per-trade result", "NAV-path total return").
- Declare whether the reported metric is replayable from artifacts alone. Compact
quick-run profiles are not required to be replayable; full artifact output is.
- Declare backend-specific comparability and asymmetry explicitly. If multiple
production backends exist later, cross-backend comparisons need a declared tolerance.
- Be **named in a way that does not overstate what it computes** (no
`validated_alpha` labels without statistical evidence; no "return" for a linear
sum of per-trade results).

**G3. Modular code with explicit ontology and the right abstractions.**

- A single ontology for strategy output. The engine consumes it directly; no parallel
representation in the math layer.
- A single execution-model contract that any PnL backend implements.
- A single causal-invariant kernel shared by runner, validation, and evaluation
for import, data loading, decision generation, and replay checks; portfolio
evaluation then branches to VectorBT Pro rather than the engine PnL contract.
- A single declared freezing idiom for `params` / `rows` / `metadata`.
- Each module has one main reason to change. Orchestrator god-functions are forbidden.

**G4. Simple, hard-to-misuse consumer integration.**

- `quant_autoresearch` writes exactly two files per candidate (`strategy.py`,
`experiment.toml`).
- For quick runs, it uses the result object and structured artifacts to diagnose one
strategy version, explain behavior, compare against prior versions, and decide
whether the candidate is worth retaining.
- For validation runs, it uses the result object and structured artifacts as advisory
retained-candidate triage.
- For research evaluation runs, it passes frozen candidate inputs and explicit
  assumptions to the separate stateless evaluation surface through
  `quant-strategies evaluate candidate/evaluation.toml` or
  `quant_strategies.evaluation.run_evaluation`.
- The public consumer surface is intentionally narrow:
`quant_strategies.runner.run_config` returns
`quant_strategies.runner.RunResult`,
`quant_strategies.validation.run_validation` returns `ValidationRunResult`, and
`quant_strategies.evaluation.run_evaluation` returns `EvaluationRunResult`.
No top-level facade is promised. Strategy generation and backend extension
points are Protocol-typed; internals are private.
- User-facing foundation vocabulary MUST remain small. Current implemented
surface language centers on `quick run`, `validation run`, and `evaluation run`.
Validation verdicts remain advisory validation vocabulary only. Terms such as
`screen`, `gate`, artifact profile internals, replayability metadata, and `row_contract`
are reference-level vocabulary, not the normal foundation surface.
- Misusing the surface (returning the wrong shape, importing private modules, etc.)
produces a clear error, not a silent miscalculation.

**G5. Tiered artifacts, bounded diagnostics, and auditability when requested.**
Quick-run artifact production has three profiles:

- `summary`: compact aggregate quick-run evidence.
- `diagnostic`: bounded behavior diagnostics for active strategy improvement.
- `full`: audit/replay artifacts.

A `diagnostic` profile may still have `replayable_from_artifacts = false` unless it
writes enough evidence to replay the run from artifacts alone. Replayability is derived
metadata, not a separate user-facing workflow concept.

`diagnostic` quick runs MUST explain strategy behavior without dumping every raw row or
trade by default. Diagnostics SHOULD include aggregate slices, cost/funding contribution,
concentration, holding-period summaries, and bounded trade samples sufficient for a
researcher or agent to improve the current strategy version.

For any reported metric in a `full` run, a reviewer MUST be able to trace it from
artifacts alone to:

- the strategy file snapshot,
- the input row set (hashed and reproducible),
- the decisions produced (timestamped, with `as_of_time` lineage),
- the fills and exits (with reason),
- the funding/cost contributions,
- the configuration that produced them.

Compact quick-run profiles intentionally omit the full trade-level chain. Consumers that
need complete audit replay rerun under the `full` profile. The foundation never
auto-promotes a run to full audit output; the consumer chooses the artifact profile.

Validation runs additionally emit an advisory verdict from a small closed vocabulary.
The vocabulary SHOULD distinguish:

- failed required mechanical checks,
- mechanically executable but not review-ready,
- positive evidence with caveats,
- manual-review candidate.

Verdict labels MUST be self-explanatory without implementation history and MUST NOT
imply promotion, paper trading, live trading, statistical significance, or market
validation. The verdict's `reasons` field carries qualifying context (e.g.,
`no_positive_realistic_cost_evidence`, `multiple_testing_not_corrected_advisory_only`,
`search_pressure_unknown_advisory_only`). Consumers ranking on the label alone without
reading reasons are operating outside the contract.

**G6. Good performance code — decent, not microsecond-optimal.**
The foundation is written with performance discipline. The code:

- MUST NOT eagerly import dependencies a code path does not use.
- MUST NOT do redundant work: deepcopying already-frozen data, hashing the same payload
twice, reconnecting to the database per run when the engine can be cached, walking row
lists more than once when one pass suffices.
- MUST NOT serialize or write artifacts the consumer did not request. Summary and
diagnostic quick runs do not produce full audit-replay artifacts.
- MUST use efficient formats for bulk per-row data (see C-9).

A typical diagnostic quick run (≤1M rows, single strategy, bounded diagnostics) completes
in seconds, not minutes. Micro-latency optimization (sub-100ms per run) and vectorized-
engine inner-loop tuning are explicitly out of scope (§8). The goal is good performance
code, not benchmark-chasing.

**G7. Research evaluation is a separate stateless evaluation surface.**
The implemented evaluation surface evaluates frozen candidates under explicit
assumptions and emits portfolio, economic, and path evidence. It accepts a
candidate-local `evaluation.toml`, strategy reference, params, data config,
windows, fill/cost assumptions, metrics config, and output root. Programmatic
callers use `quant_strategies.evaluation.run_evaluation`.

It returns `EvaluationRunResult` and writes portfolio metrics, scenario summary,
data manifest, evaluation manifest, and detailed trace artifacts as Parquet
through `pyarrow`. VectorBT Pro is required for evaluation. Detailed traces have
no JSONL fallback path. It MUST NOT own candidate generation, search memory,
ranking across variants, stopping rules, promotion, paper-trading
authorization, or live-trading authorization.

Evaluation is not validation. It does not authorize promotion, paper trading, or live trading. Benchmark-relative metrics are deferred.

VectorBT Pro is appropriate here when portfolio/NAV semantics are the
deliverable. It remains out of the quick-run hot path and validation authority.

### 4.2 Non-goals (explicit, durable)

**NG1.** Market validation. Mechanical and statistical checks are advisory only; no output
flips a `paper_trade_eligible` or `live_eligible` bit autonomously. The validation
verdict label (see G5) is itself advisory — it summarizes mechanical evidence, not
market-validated alpha. Research evaluation metrics are also advisory evidence,
not promotion authority. Downstream consumers (including
`quant_autoresearch`) MUST treat the verdict as an input to human review, never
as a promotion signal.

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
usable quick-run evidence if any decision violates it. Quick runs always compute
quick-run evidence and causality hygiene. Optional quick checks may classify the
quick-run result, but this is not validation.
- **NFR-SIMPLICITY.** New strategy authors can read one Protocol + one decision schema
and write a working strategy quickly. Researchers can distinguish fast quick-run
diagnostics, mechanical evidence validation, and research evaluation without
learning implementation vocabulary first.
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
tolerance or has the asymmetry declared explicitly. Each run declares whether its
reported metrics are replayable from artifacts alone.
- **Consumer integration.** `quant_autoresearch` drives iteration end-to-end using only
the public surface; misuse fails fast and clearly.
- **Diagnostic usefulness.** A quick run explains one strategy version with bounded
behavior diagnostics: aggregate metrics, slices, cost/funding contribution,
concentration, holding-period summaries, and representative trade samples.
- **Auditability.** Any reported number in a `full` run is back-traceable from artifacts
alone to the decisions, fills, and config that produced it. Compact quick-run profiles
intentionally omit the full trade-level chain.
- **Surface simplicity.** A user can distinguish quick run, mechanical evidence
validation, and research evaluation without knowing implementation vocabulary
such as screen/gate modes or replayability metadata. Current docs must also make
clear which of those jobs are implemented today.
- **Performance.** Typical diagnostic quick runs complete in seconds, not minutes. Overhead
the strategy did not request (eager imports, redundant deepcopies, per-run database
reconnects, unwanted artifact writes) does not dominate wall-clock time.
- **Code quality.** A single ontology, a single execution-model contract, a single shared
kernel between runner and validation, and no orchestrator god-functions.

---

## 7. Constraints

- **C-1.** Python ≥ 3.12; pydantic ≥ 2.10; `quant-data` for data loading.
`vectorbtpro` is used for the explicitly enabled single-trade agreement check
and is required for the implemented evaluation surface; it is not a validation
backend or verdict source. Evaluation trace artifacts are Parquet and require
`pyarrow`.
- **C-2.** Conda environment `quant`. All Python commands run via `conda run -n quant`.
- **C-3.** `quant_data` is the only source of market data. The foundation does not load
CSVs, fetch APIs, or maintain caches.
- **C-4.** Strategy files live flat under `untested/` or `tested/` directories or inside
candidate workspaces driven by consumers. No nested strategy "framework" hierarchies
inside strategies.
- **C-5.** Runner results are written under ignored `results/` directories (per
config). Validation outputs remain candidate-local; generated artifacts should
not be written under source or input directories, and example configs are
templates.
- **C-6.** Promotion into `tested/` from `untested/` or `researched/` is a separate
human process. The foundation never auto-promotes.
- **C-7.** No network IO in the engine or kernel. All data comes from `quant_data`
loaders called from the runner.
- **C-8.** No legacy compatibility shims. Contract changes require regenerating
strategies and rerunning configs.
- **C-9.** Artifact production is tiered and format-disciplined. The consumer requests
a quick-run artifact profile: `summary` (compact aggregate quick-run evidence),
`diagnostic` (bounded behavior diagnostics for active strategy improvement), or
`full` (audit/replay artifacts). Replayability is emitted as derived metadata, e.g.
`replayable_from_artifacts = true | false`; there is no separate user-facing artifact
tier. V1 audit row, decision, and trade-ledger artifacts use deterministic JSONL;
control-plane artifacts (manifest, summary, config, evidence, diagnostics) stay
sort-keys JSON. Evaluation trace artifacts are separate: they are Parquet only
through `pyarrow`; quick-run and validation JSONL audit artifacts do not define
the evaluation trace format.

---

## 8. Out of Scope (explicit)

- Live trading, paper trading, order routing, broker integration.
- Real-time market data feeds.
- A general-purpose, user-composable backtesting framework. The execution kernel
produces quick-run and validation evidence; the optional VectorBT Pro agreement
integration is only a single-trade agreement check, not a validation backend or
verdict source. Research evaluation owns stateless historical portfolio/path
evidence for frozen candidates under explicit assumptions, but it is not a
free-composition backtester.
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
