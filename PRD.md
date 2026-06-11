# PRD — `quant_strategies`

**Status:** Draft v1
**Owner:** Season Yang
**Last updated:** 2026-06-10
**Companion documents:** `README.md` (short current-state orientation),
`FOUNDATION_LOCK.md` (locked contracts and review disposition),
`docs/foundation-surfaces.md` (current command/API/artifact reference),
and `AGENTS.md` (agent operating contract).

This PRD is the source of truth for **why** `quant_strategies` exists and **what** it must
provide. `README.md` describes the current implementation; this PRD describes the target
behavior the implementation must converge to. When PRD and code disagree, the PRD describes
the work to be done.

Document responsibility is intentionally split: this PRD owns product intent,
goals, non-goals, and constraints. It should not duplicate command schemas,
artifact inventories, package facts, or agent workflow rules owned by the
companion documents.

---

## 1. One-Line Summary

`quant_strategies` is a **stateless research foundation** with three required
public jobs: diagnostic quick runs, mechanical evidence validation, and research
evaluation for supplied frozen candidates. Research
evaluation means stateless candidate evidence, not the stateful auto-research
loop.

**Foundational principle (north star).** The unit of simulation is **one causal,
single-account portfolio, not an isolated trade.** A strategy declares a complete
portfolio — a *target book* — and the foundation simulates it as one stateful book
under explicit frictions, treating that NAV path as the authoritative unit of
return. The foundation's contract with its consumer is two-sided: **enable** any
complete, tradeable portfolio strategy to be expressed in `strategy.py`, and
**guarantee** that a strategy which passes Train evidence is genuinely feasible to
trade — measuring it on one honest book and refusing to score what is not
tradeable. A kept result must mean a tradeable candidate, or the downstream loop is
optimizing fiction.

---

## 2. Background and Problem Statement

### What the project is

A disciplined Python library and CLI that:

1. Defines a **declarative strategy contract**: a pure function emitting a
  **target book** — a standing, signed target position per instrument over causal
  time, with optional declared price-path risk rules.
2. Provides a **mathematically explicit execution kernel** that simulates the
  target book as **one causal, single-account portfolio** (same-symbol netting,
  financing, mark-to-market) and treats that NAV path as the authoritative unit of
  return, with declared assumptions.
3. Provides a **diagnostic quick-run harness** that computes quick-run evidence,
  causality hygiene, and bounded behavior diagnostics for one strategy version.
4. Provides a **mechanical evidence validation harness** that runs a retained
  candidate across windows and scenarios with hidden-lookahead protection and
   mechanically auditable artifacts.
5. Provides **research evaluation evidence** for frozen candidates: portfolio,
  path, and economic evidence under explicit assumptions.
6. Exposes a **stable, minimal consumer surface** for `quant_autoresearch` to drive
  strategy iteration without touching internals.

### What the project is not

- Not a general-purpose backtesting framework where users compose arbitrary
pipelines. There is one foundation pipeline. Strategies are pure functions.
The research evaluation surface owns stateless historical evaluation evidence
for frozen candidates under explicit assumptions.
- Not a market-validation system. All outputs are advisory; promotion requires
human-led review.
- Not a data platform. Data acquisition, refresh, and repair are owned by `quant_data`.
- Not a paper-trading or live-trading harness.
- Not an auto-research process owner. Candidate generation, search memory,
ranking across variants, stopping rules, and iteration decisions are owned by
`quant_autoresearch`; `quant_strategies` evaluates supplied strategies and
configs.

### Foundation jobs

The product contract distinguishes three jobs:


| Job                            | Product requirement | Purpose                                                                            |
| ------------------------------ | ------------------- | ---------------------------------------------------------------------------------- |
| Quick run                      | Public job          | Fast causal diagnostics for one strategy version.                                  |
| Mechanical evidence validation | Public job          | Retained-candidate integrity checks across windows and scenarios.                  |
| Research evaluation            | Public job          | Stateless historical economic, path, and portfolio evidence for frozen candidates. |


Mechanical evidence validation verifies that evidence was produced honestly,
causally, reproducibly, and audibly under explicit config. It does not answer
whether a strategy has durable alpha, statistical significance, regime
robustness, benchmark-relative edge, capacity, or portfolio quality.
Research evaluation provides stateless frozen-candidate portfolio, economic,
and path evidence. No foundation job authorizes promotion, paper trading, or
live trading. Benchmark-relative metrics, when configured, are advisory
evaluation evidence only; they do not rank candidates or authorize promotion.

---

## 3. Users and Stakeholders

### Primary users


| User                                         | Role                                                                                                                                                                                                                  | What they need                                                                                                                                                                                                                                   |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `**quant_autoresearch`** (autonomous agent)  | Generates and iterates strategies in a tight loop; consumes quick-run diagnostics for one-version improvement, validation verdicts for retained-candidate triage, and evaluation evidence for frozen-candidate review | Stable, typed programmatic surfaces for quick runs, validation runs, and evaluation runs; declarative strategy contract; deterministic artifacts; bounded behavior diagnostics; advisory validation verdict labels; small surface area to misuse |
| **Senior quant researcher (Season)**         | Designs strategies, audits research, makes promotion decisions                                                                                                                                                        | Math correctness; explicit ontology; ability to understand behavior slices and investigate trades end-to-end; ability to add new strategy axes without rewriting the harness                                                                     |
| **Future strategy authors** (human or agent) | Write new strategy files                                                                                                                                                                                              | One-page contract; obvious where to put thesis/observables/rule/falsifier; impossible to accidentally introduce lookahead                                                                                                                        |


### Secondary stakeholders

- `**quant_data`** (upstream): provides loaders; receives structured row-contract feedback.
- **Audit / review process**: consumes validation artifacts to support promotion decisions.

### Non-users (explicit)

- Live-trading systems. No API path leads from `quant_strategies` to order routing.
- End-user notebook explorers. The library is callable from a notebook, but ergonomics are
not optimized for ad-hoc exploration; that is outside this foundation.

---

## 4. Goals

### 4.1 Strategic goals

**G1. Default-narrow strategy expression with explicit extended ontology.**
The default strategy contract MUST express the executable v1 path clearly as a
**target book**:

- **Target**: a signed weight of NAV per instrument (long `+`, short `-`,
  `0` = flat/close), **standing** until changed. Open, close, adjust, and rebalance
  are all expressed as *setting a target*; targets are **idempotent**, so
  same-symbol exposure nets and repeated signals cannot stack into hidden leverage.
- **Instrument**: equity / ETF, FX pair, crypto perp.
- **Risk rules**: optional declared price-path exits (stop-loss, take-profit,
  trailing) the engine enforces causally on the net position. Data- or time-based
  exits (signal reversal, fixed hold horizon) are expressed as explicit target
  changes, not risk rules.

Extended vocabulary for futures, options, multi-leg structures, target notional,
target contracts, and vol-targeted sizing MUST live behind explicit opt-in imports. A strategy that needs those axes must be able
to express them without monkey-patching the foundation, but the default import path must
not imply that unsupported execution semantics are executable.

**G2. Math correctness adequate for advisory research evidence.**
Every numeric quantity emitted by the foundation MUST:

- Derive the **scored statistics from the single portfolio NAV path**, which is the
one authoritative unit of return. The per-trade ledger is a *derived attribution
view* of that same book (for alpha / information-coefficient analysis), never an
independent scored quantity. There is one model of money.
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
- A single shared strategy execution kernel for import, params, data loading,
row normalization, decision generation, and causal-invariant replay checks.
- One causal single-account portfolio book is the authoritative model of money
and the source of NAV truth; the per-trade ledger is a derived attribution view of
it, not a parallel computation. A second backend (an independent re-implementation)
is permitted only as a cross-check that must agree, never as a divergent
money-model.
- A single declared freezing idiom for `params` / `rows` / `metadata`.
- Each module has one main reason to change. Orchestrator god-functions are forbidden.

**G4. Simple, hard-to-misuse consumer integration.**

- `quant_autoresearch` owns candidate workspaces and supplies explicit strategy
and configuration inputs for each public job. Quick-run iteration,
retained-candidate review, and frozen-candidate evaluation each use their own
explicit input contract.
- For quick runs, it uses the result object and structured artifacts to consume
computed diagnostics for one strategy version; downstream retention and iteration
decisions belong outside `quant_strategies`.
- For validation runs, it uses the result object and structured artifacts as advisory
retained-candidate triage.
- For research evaluation runs, it passes frozen candidate inputs and explicit
assumptions to obtain stateless portfolio, path, and economic evidence.
- The public consumer surface is intentionally narrow: one supported public
entry point per foundation job, typed result objects, and no promise that
private internals are stable. Exact command names, function paths, result class
names, and schemas are reference-document responsibilities, not PRD
responsibilities.
- User-facing foundation vocabulary MUST remain small. Surface language centers
on `quick run`, `validation run`, and `evaluation run`.
Validation verdicts remain advisory validation vocabulary only. Terms such as
screen/gate modes, artifact profile internals, replayability metadata, and
row-contract details are reference-level vocabulary, not the normal foundation
surface.

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
validation. Structured reasons carry qualifying context. Consumers ranking on
the label alone without reading those reasons are operating outside the
contract.

**G6. Good performance code — decent, not microsecond-optimal.**
The foundation is written with performance discipline. The code:

- MUST NOT eagerly import dependencies a code path does not use.
- MUST NOT do redundant work: deepcopying already-frozen data, hashing the same payload
twice, reconnecting to the database per run when the engine can be cached, walking row
lists more than once when one pass suffices.
- MUST NOT serialize or write artifacts the consumer did not request. Summary and
diagnostic quick runs do not produce full audit-replay artifacts.
- MUST use efficient formats for bulk per-row data (see C-6).

A typical diagnostic quick run (≤1M rows, single strategy, bounded diagnostics) completes
in seconds, not minutes. Micro-latency optimization (sub-100ms per run) and vectorized-
engine inner-loop tuning are explicitly out of scope (§8). The goal is good performance
code, not benchmark-chasing.

**G7. Research evaluation provides stateless frozen-candidate evidence.**
Research evaluation evaluates frozen candidates under explicit assumptions and
emits portfolio, economic, and path evidence. It accepts explicit candidate
inputs covering strategy identity, parameters, data selection, windows,
fill/cost assumptions, metrics assumptions, and output location.

It returns a typed evaluation result and writes auditable portfolio metrics,
scenario summaries, data provenance, evaluation provenance, and detailed trace
artifacts in an efficient format suitable for path and portfolio review. It
MUST NOT own candidate generation, search memory, ranking across variants,
stopping rules, promotion, paper-trading authorization, or live-trading
authorization.

Research evaluation evidence does not authorize promotion, paper trading, or
live trading. Benchmark-relative metrics, when configured, are advisory
evidence only and do not rank candidates.

A portfolio/NAV-specific **heavy** backend is appropriate when portfolio/NAV
semantics are the deliverable. That heavy backend remains out of the quick-run hot
path — the quick-run path computes its own dependency-light portfolio book (G8) —
and does not grant promotion authority.

**G8. Feasibility is a first-class, enforced contract ("passes ⟹ tradeable").**
A strategy that passes Train evidence MUST be genuinely feasible to trade. The
foundation scores it on one netted, financed, marked portfolio book under
operator-frozen frictions (costs, fills, the leverage ceiling, asset universe, and
window — the strategy author cannot relax these). A breach of the feasibility
envelope — intended gross/net over the frozen leverage budget, a zero-cost
scoreable run, or a statistically degenerate sample — MUST produce a typed,
actionable **fail-closed** verdict that makes the run non-scoreable. The foundation
MUST NOT clamp or normalize an infeasible book to fit the budget, and MUST NOT
collapse a breach into a silent absence of evidence. "Leverage allowed but capped"
means leverage *priced and bounded*, never free. The strategy owns the portfolio
(allocation, sizing, netting intent, rebalancing, exits, declared risk); the
foundation owns the accounting, the market model, and the frozen envelope.

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

**NG4.** Live trading-system features: order routing, execution, working-order
lifecycle, position keeping against a broker, broker integration, real-time market
data, alerts, dashboards. None of these belong here. Modeling financing, margin, a
leverage budget, and netting *inside the backtest book* is in scope as simulation
realism (see G8) and is distinct from operating live risk limits or an
order-management system: the book is evaluated end-of-bar on each printed bar (close
for marks, the completed bar's high/low for declared `RiskRule` barriers), not as a
working-order lifecycle.

**NG5.** Legacy-compatibility code paths. When the contract changes, strategies and configs
are updated and re-run. The foundation does not carry shims for old shapes.

**NG6.** A pluggable strategy IDE, notebook integration, or browser UI.

---

## 5. Non-Functional Requirements

- **NFR-RIGOR.** Math is correct first, fast second. Any optimization that changes
numerical results requires an explicit decision record.
- **NFR-DETERMINISM.** Given the same source, config, and data, deterministic
manifests keep research identity focused on source commit, inputs, decisions,
and artifact hashes. Runtime environment, installed package versions, git dirty
status, and tracked diff hashes are audit context only and are excluded from
manifest identity hashes.
- **NFR-IMMUTABILITY.** No artifact is mutated after write. Re-runs go to new
directories.
- **NFR-CAUSALITY.** The lookahead invariant is foundational: no run completes with
usable quick-run evidence if any decision violates it. Quick runs always compute
quick-run evidence and causality hygiene. Optional quick checks may classify the
quick-run result, but this is not validation.
- **NFR-SIMPLICITY.** New strategy authors can read one strategy interface and
one decision schema, then write a working strategy quickly. Researchers can
distinguish fast quick-run diagnostics, mechanical evidence validation, and
research evaluation without learning implementation vocabulary first.
- **NFR-ROOT-CAUSE.** When a bug is fixed, the fix lands at the boundary or contract that
produced it. Wrappers, guards, adapters, and "the new code path" are anti-patterns
unless explicitly justified.
- **NFR-NO-LEGACY.** Old strategies, configs, and artifacts that depend on retired
shapes are re-generated, not back-compat'd. Migration documents live in the relevant
decision records, not in code.
- **NFR-OBSERVABILITY.** Structured logging is emitted at stage boundaries. Stage names
match artifact taxonomy.
- **NFR-AGENT-FRIENDLY.** Strategy and config shapes are LLM-friendly (small,
typed, and documented at the interface boundary), so `quant_autoresearch` can
generate them reliably.

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
behavior diagnostics: aggregate trade-result metrics, compact economic metrics,
diagnostic-profile slices, cost/funding contribution, concentration,
holding-period summaries, and representative trade samples.
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
- **Code quality.** A single strategy ontology, one shared execution kernel,
explicit evidence-model contracts, and no orchestrator god-functions.

---

## 7. Constraints

- **C-1.** The foundation exposes Python developer surfaces and command-line
entry points for the public jobs. Exact runtime versions, command names,
function paths, and package dependencies live in reference documentation.
- **C-2.** `quant_data` is the only source of market data. The foundation does not load
CSVs, fetch APIs, or maintain caches.
- **C-3.** Generated artifacts are written under ignored output roots. Validation
and evaluation outputs remain candidate-local unless explicitly configured
otherwise; generated artifacts should not be written under source or input
directories, and example configs are templates.
- **C-4.** No network IO in the engine or kernel. All data comes from `quant_data`
loaders called from the runner.
- **C-5.** No legacy compatibility shims. Contract changes require regenerating
strategies and rerunning configs.
- **C-6.** Artifact production is tiered and format-disciplined. The consumer requests
a quick-run artifact profile: `summary` (compact aggregate quick-run evidence),
`diagnostic` (bounded behavior diagnostics for active strategy improvement), or
`full` (audit/replay artifacts). Replayability is emitted as derived metadata, e.g.
whether a run can be replayed from its artifacts alone; there is no separate
user-facing artifact tier. Bulk trace artifacts use efficient tabular formats;
control-plane artifacts remain deterministic and human-auditable. Exact file
names and serialization formats are reference-document responsibilities.

---

## 8. Out of Scope (explicit)

- Live trading, paper trading, order routing, broker integration.
- Real-time market data feeds.
- A general-purpose, user-composable backtesting framework. The execution kernel
produces quick-run and validation evidence; specialized backend integrations
may provide agreement checks or portfolio/path evidence, but no backend output
grants promotion authority. Research evaluation owns stateless historical
portfolio/path evidence for frozen candidates under explicit assumptions, but it
is not a free-composition backtester.
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
- `docs/foundation-surfaces.md` owns current command/API/artifact reference
details for quick run, validation run, and research evaluation. Keep those
details out of this PRD unless they define durable product intent.
- `AGENTS.md` governs how agents operate inside this repo and is consistent with this
PRD; if they conflict, the more specific instruction wins (per `CLAUDE.md` global
policy).

*End of PRD v1.*
