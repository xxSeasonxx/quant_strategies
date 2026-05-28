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
| `**quant_autoresearch`** (autonomous agent)  | Generates and iterates strategies in a tight loop              | Stable, typed Python API; declarative strategy contract; deterministic artifacts; clear "good vs bad" ranking signals; small surface area to misuse |
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

**G1. Flexible strategy expression across the axes a real quant uses.**
The strategy contract MUST express, at minimum:

- **Direction / state**: long, short, flat.
- **Action / intent**: open, close, adjust (rebalance), roll.
- **Side of book**: buy, sell — distinct from net direction.
- **Instrument**: equity / ETF, FX pair, crypto perp, futures (with expiry + multiplier),
options (call / put with strike + expiry + multiplier + settlement style).
- **Multi-leg structures**: pair trades, spreads, calendars — one decision, multiple legs,
joint exit policy.
- **Sizing**: target weight, target notional, target contracts, and at least one
risk-targeted sizing (e.g., vol-targeted) — declared at the type level even if not all
are executed by every backend.
- **Exit**: time-based, threshold-based, expiry-based, event-based.

A strategy that needs any of the above MUST be expressible without monkey-patching the
foundation.

**G2. Math correctness adequate for paper-readiness research.**
Every numeric quantity emitted by the foundation MUST:

- Carry a declared **unit** and **base** (e.g., "fraction of entry notional", "percentage
points of signed trade activity", "NAV-path total return").
- Be reproducible by reading the artifact set without re-running the code.
- Match across backends within a declared tolerance, or declare the asymmetry explicitly.
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
- The public consumer surface is re-exported and Protocol-typed. Internals are private.
- Misusing the surface (returning the wrong shape, importing private modules, etc.)
produces a clear error, not a silent miscalculation.

**G5. Trade-level auditability for every result.**
For any reported metric, a reviewer MUST be able to trace it to:

- the strategy file snapshot,
- the input row set (hashed and reproducible),
- the decisions produced (timestamped, with `as_of_time` lineage),
- the fills and exits (with reason),
- the funding/cost contributions,
- the configuration that produced them.

### 4.2 Non-goals (explicit, durable)

**NG1.** Market validation. Mechanical and statistical checks are advisory only; no output
flips a `paper_trade_eligible` or `live_eligible` bit autonomously.

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
- **NFR-DETERMINISM.** Given the same code, config, and data, two runs produce
  byte-identical artifact hashes (modulo `run_id` timestamp and git identity).
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

- **Expressiveness.** A quant can express their intended strategy — across put/call,
  buy/sell, long/short/flat, single-leg and multi-leg — without monkey-patching the
  foundation.
- **Math correctness.** Every emitted metric is unit-tagged, reproducible from artifacts,
  named consistently with what it actually computes, and either agrees across backends
  within a declared tolerance or has the asymmetry declared explicitly.
- **Consumer integration.** `quant_autoresearch` drives iteration end-to-end using only
  the public surface; misuse fails fast and clearly.
- **Auditability.** Any reported number is back-traceable from artifacts alone to the
  decisions, fills, and config that produced it.
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
- **C-6.** Promotion between `untested/` → `tested/` → `researched/` is a separate human
  process. The foundation never auto-promotes.
- **C-7.** No network IO in the engine or kernel. All data comes from `quant_data`
  loaders called from the runner.
- **C-8.** No legacy compatibility shims. Contract changes require regenerating
  strategies and rerunning configs.

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
- Performance benchmarking and microsecond-latency optimization.
- A web UI, dashboard, or notebook integration.

---

## 9. Glossary

| Term | Definition |
|---|---|
| **Strategy** | A pure Python module exposing `generate_decisions(rows, params)` and optional `validate_params(params)`. |
| **Decision** | A `StrategyDecision` object emitted by a strategy. Carries instrument, intent, sizing, exit policy, observations, and timing. |
| **Intent** | The action+side pair (`open buy`, `close sell`, etc.) — distinct from net direction. |
| **Sizing** | Magnitude and kind (target weight, target notional, target contracts, target vol). |
| **Observation** | A causal lineage record: `(symbol, timestamp, field, source)` for a row that contributed to a decision. |
| **as_of_time** | The information-set cutoff a decision was made on. Must be ≤ `decision_time`. |
| **decision_time** | The wall-clock moment the decision becomes actionable (i.e., would be sent to a broker). |
| **Smoke engine** | The deterministic in-process screening engine. Linearized per-trade math; not a portfolio NAV. |
| **vbt backend** | The vectorbtpro-based validation backend. |
| **Kernel** | The shared execution primitives used by both runner and validation: strategy load, params validation, data load, freezing, decision execution, lookahead replay, observation audit. |
| **Runner** | The top-level orchestrator for a single screening or validation-gate run from one config. |
| **Validation harness** | The multi-window, multi-scenario advisory harness. |
| **Backend** | A PnL implementation conforming to the execution-model contract. |
| **Advisory** | Any output that does not authorize promotion, paper trading, or live trading. All foundation outputs are advisory. |
| **Mechanical pass** | Met all mechanical gates (data audit, required scenarios, valid metrics, minimum trades). Not statistical evidence. |
| **Search pressure** | Metadata about parameter search (candidate count, trial count, search space, selection rule, split ids). Consumed for deflation; not for blocking. |
| **Row contract** | The expected schema of rows for a given `data.kind`. Violations are reported back to `quant_data` via `quant_data_feedback`. |

---

## 10. Document Maintenance

- This PRD is updated when a Goal, Non-Goal, or Constraint changes.
- `README.md` describes current behavior. When PRD and `README.md` diverge, PRD wins for
  intent; `README.md` is a bug to be fixed.
- `AGENTS.md` governs how agents operate inside this repo and is consistent with this
  PRD; if they conflict, the more specific instruction wins (per `CLAUDE.md` global
  policy).

*End of PRD v1.*
