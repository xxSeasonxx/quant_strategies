## Context

Quick run currently reports whether a run completed and whether the portfolio
book was feasible, but it does not separately say whether the evidence may be
retained for validation/evaluation. That distinction matters because micro replay
is intentionally fast Train evidence, while retention needs a stricter contract:
trusted envelope, acceptable causality state, and no unpriced financing.

The existing design already has the right foundation pieces:

- `RunResult.succeeded` reports completed execution with no failure stage.
- `RunEvidence` carries causality metadata.
- `FeasibilityVerdict` carries typed non-scoreable reasons.
- `CostModelConfig`, `CapacityModelConfig`, and `LeverageBudgetConfig` are
  operator-envelope configs.
- The single netted book owns market-model feasibility.

This change should connect those pieces without adding another backend or a
parallel scoring path.

## Goals / Non-Goals

**Goals:**

- Add a clear quick-run retainability contract for downstream consumers.
- Keep micro quick-run scoring useful for iteration while preventing detected or
  untrusted evidence from being retained.
- Enforce minimal envelope realism/provenance before evidence is retainable.
- Fail closed on unpriced short exposure in asset classes without modeled
  short/carry financing.
- Update the foundation review status when implementation is complete.

**Non-Goals:**

- No validation/evaluation parity work; that is Phase 2.
- No full borrow-rate, FX rollover, dividend, or margin financing model.
- No new search/ranking/promotion workflow.
- No compatibility aliases for retired result shapes.

## Decisions

### Decision 1: Add `RunResult.retainable`

`RunResult.succeeded` stays the terminal execution success check. A new derived
or stored `retainable` signal answers the narrower question: may the quick-run
evidence advance into retained-candidate validation/evaluation?

Retainability requires:

- `succeeded is True`;
- causality evidence is retention-admissible;
- envelope provenance and realism checks pass;
- no fail-closed feasibility verdict is present.

Alternative considered: redefine `succeeded`. Rejected because current docs and
callers use `succeeded` as a terminal success check; changing it would collapse
diagnostic scoring and retention into one concept.

### Decision 2: Treat micro replay as scoreable but not always retainable

Micro replay may still score quick-run evidence for fast iteration. If micro
detects violations, times out, skips probes, or otherwise records incomplete
retention proof, the run can complete but `retainable` is false with an
actionable reason.

Alternative considered: make every micro replay failure a `failure_stage`.
Rejected for this phase because existing TODOs explicitly frame micro as Train
annotation. This design preserves fast scoring while making the retention
boundary explicit.

### Decision 3: Enforce envelope trust at config/result boundary

Add minimal envelope trust fields and realism validation rather than trying to
detect who wrote the TOML indirectly. The practical root contract is explicit:
retained evidence needs a declared operator-frozen envelope.

Minimal fields:

- `[envelope] operator_frozen = true`

Minimal realism:

- scoreable retained runs need nonzero base costs;
- `adv_impact` needs positive impact coefficient;
- bar/ADV participation limits must be at most `1.0`;
- leverage remains part of the frozen envelope; omitting `[leverage_budget]`
  freezes the conservative default `1.0/1.0`, while explicit higher values remain
  subject to the book's budget verdict.

Alternative considered: infer envelope trust from file path or config ownership.
Rejected as fragile and not auditable.

### Decision 4: Add `unpriced_short_financing`

The book already raises `unfinanced_leverage` for net exposure above `1.0` when
financing is not modeled. Extend the same book-owned feasibility model: if a
non-financed data kind has intended short exposure, fail closed with
`unpriced_short_financing`.

Crypto perp funding remains exempt because funding is modeled in the book.

Alternative considered: wait for borrow/carry data. Rejected because scoring free
shorts is worse than blocking them until the model lands.

## Risks / Trade-offs

- **Existing configs fail until they declare envelope provenance** -> update
  checked-in candidate/example configs and tests in the same change.
- **Some useful exploratory runs become non-retainable** -> retainability is
  separate from `succeeded`, so iteration can continue.
- **Short-heavy ideas are blocked** -> this is intentional until borrow/carry is
  priced or explicitly modeled.
- **New result field can be ignored** -> docs and tests must make
  `retainable` the downstream retention check.
