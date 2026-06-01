# Foundation MVP Roadmap Design

- **Date:** 2026-06-01
- **Status:** Approved design for roadmap shape; implementation planning should start with A only.
- **Source context:** `docs/foundation-direction-2026-06-01-synthesis.md` and
  `docs/reviews/2026-06-01-foundation-direction-assessment-claude.md`
- **Roadmap order:** A -> C -> B

## Purpose

Clarify the next foundation MVP path without prematurely implementing or
over-specifying the missing evaluation layer.

The foundation direction is:

```text
A. Contract-first clarification
C. Research evaluation surface MVP
B. Quick-run economic diagnostics improvement
```

The immediate implementation plan should cover only A. C and B are included here
as scoped follow-ons so A can aim at the right destination.

## Current Read

`quant_strategies` should remain a stateless foundation engine:

```text
given: strategy + config + data reference
return: trustworthy evidence
```

It should not own idea generation, autonomous iteration, search memory,
candidate ranking, stopping rules, promotion policy, or paper/live readiness.
Those belong in `quant_autoresearch` and Season's human review process.

The current implementation has two public surfaces:

- `quick run`: fast causal diagnostic evidence for one strategy version.
- `validation run`: retained-candidate mechanical evidence validation.

The missing job is:

- `research evaluation`: stateless survivor evaluation for economic, path, and
  portfolio evidence under explicit assumptions.

The key correction is product-contract clarity. Current `validation` is mostly
mechanical evidence validation, not quant strategy evaluation.

## Approved Scope

This roadmap spec covers A, C, and B as ordered milestones, but only A is
implementation-ready.

### A. Contract-First Clarification

A is docs-only unless the docs reveal a broken public contract that requires a
tiny wording-compatible correction.

The deliverable is not another dated planning layer. The changed active docs
should become durable first-read state.

Target documents:

- `PRD.md`: define the three jobs and make clear that research evaluation is the
  missing next surface.
- `README.md`: add the concise mental model while keeping current commands
  factual.
- `FOUNDATION_LOCK.md`: amend the lock so C is an approved next direction, not
  an accidental reopening.
- `TODOS.md`: collapse the product-contract TODO into current open work for C
  and B.
- `docs/vectorbtpro.md` and `docs/quant-autoresearch-consumer.md`: touch only if
  they directly contradict the clarified contract.

Explicit exclusion:

- Do not update `docs/foundation-surfaces.md` in A. That document should remain
  the factual I/O reference for implemented surfaces and should be updated only
  when C is actually implemented.

Acceptance for A:

- A new session can read `PRD.md`, `README.md`, `FOUNDATION_LOCK.md`, and
  `TODOS.md` and understand the roadmap.
- `docs/foundation-surfaces.md` remains a current-state reference, not a
  speculative design document.
- No text implies that validation proves alpha, statistical significance,
  robustness, capacity, paper-trading readiness, live readiness, or promotion
  readiness.
- No code, CLI, package path, artifact name, or public API rename occurs in A.

### C. Research Evaluation Surface MVP

C is the missing product layer. This spec defines its boundary but does not yet
serve as its implementation plan.

The future evaluation surface should be stateless:

```text
given: frozen strategy/config/data references/evaluation assumptions
return: portfolio and economic evidence artifacts
```

It should not:

- drive the research loop;
- generate candidates;
- track search memory;
- rank variants across a trial ledger;
- define stopping rules;
- authorize promotion, paper trading, or live trading.

It should not be a renamed validation run. Validation remains mechanical
evidence validation. Evaluation answers portfolio, economic, and path questions.

VectorBT Pro belongs here when the question is portfolio/NAV evidence. Any
VectorBT Pro output must be labeled as NAV/path/portfolio evidence, not as the
project engine verdict and not as promotion authority.

Likely first MVP boundary:

- bars data;
- frozen candidate strategy and params;
- target-weight long/short decisions;
- explicit cost and slippage assumptions;
- benchmark optional or deferred;
- multi-asset support only if it is natural through VectorBT Pro and does not
  require a custom portfolio engine rewrite.

Expected evidence dimensions:

- total return or NAV-path semantics;
- drawdown;
- turnover or trade count;
- exposure and concentration basics;
- per-asset breakdown when multi-asset is supported;
- explicit warnings and non-claims.

### B. Quick-Run Economic Diagnostics Improvement

B should happen after A clarifies the contract and C establishes the evaluation
boundary.

Quick run should remain the fast, causality-controlled diagnostic surface on the
internal engine. It should not import VectorBT Pro, become a robustness
evaluator, or claim strategy quality.

The likely improvement is cheap keep/kill diagnostics from the existing engine
trade ledger, such as:

- hit rate;
- average trade net;
- win/loss distribution;
- cost and funding share;
- active exposure or concentration summaries.

These metrics should improve iteration feedback without turning quick run into
portfolio evaluation.

## Contract Decisions

1. Keep quick run as quick run.
   It stays on the internal engine and remains focused on causal diagnostics for
   one strategy version.

2. Rename by meaning before renaming APIs.
   In docs, describe current `validation` as mechanical evidence validation or
   evidence audit. Do not rename code paths, CLI commands, package names,
   artifact names, or public APIs in A.

3. Add research evaluation as a separate job.
   The project direction becomes conceptually three jobs, even while only two
   public surfaces are implemented today.

4. Do not reopen quick-run VectorBT Pro.
   VectorBT Pro belongs in evaluation where portfolio/NAV semantics are the
   deliverable.

5. Do not silently reinterpret metrics.
   Existing engine metric semantics remain linear per-trade activity sums. Any
   NAV/path/evaluation metric must be named separately and labeled as portfolio
   evidence.

6. No promotion authority.
   Quick run, validation, and future evaluation all return evidence only.

## Verification For A

Use focused documentation checks:

```bash
rg -n "paper readiness|paper-readiness|paper_candidate|promotion ready|live ready|live readiness|statistical significance|alpha" PRD.md README.md TODOS.md FOUNDATION_LOCK.md docs
rg -n "two foundation surfaces|two-surface|quick run.*VectorBT|VectorBT.*quick run" PRD.md README.md TODOS.md FOUNDATION_LOCK.md docs
git diff --check
```

No full test suite is required for A if it remains docs-only.

## Risks

- Updating speculative docs too early would make future implementation harder to
  trust. That is why `docs/foundation-surfaces.md` is excluded from A.
- Calling C "validation" would preserve the current ambiguity. Evaluation must
  be named separately at the product-contract level.
- Treating VectorBT Pro as the solution to quick-run weakness would put a heavy
  portfolio tool on the hot path and blur causality semantics.
- Reinterpreting existing linear engine metrics as returns would create false
  comparability. New NAV/path metrics need separate names and semantics.

## Implementation Handoff

After this spec is reviewed and approved, invoke the writing-plans workflow for
A only. The A plan should be a docs-focused implementation plan with stale
language checks and changed-line accounting. C and B should receive separate
implementation plans after A lands.
