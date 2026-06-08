## Context

Quick run currently exposes low-level replay modes (`off`, `emitted`, `strict`)
directly to consumers. That made sense as an evidence foundation, but it is the
wrong abstraction for autoresearch. The strategy-writing loop needs one answer:
is this source variant causally hygienic enough to score, or should it be
rejected? It should not spend minutes selecting replay modes or waiting on
full-window replay before it can write research results.

Validation and evaluation already remain the stronger trust gates. They run data
audit and strict causality before mechanical validation or portfolio evaluation.
The focused gate therefore does not need to prove promotion-grade causality; it
needs to prevent obvious lookahead and nondeterminism from polluting the
research loop quickly and reproducibly.

## Goals / Non-Goals

**Goals:**

- Add a focused causality gate suitable for autoresearch source-change checks.
- Keep the gate bounded by deterministic probe and runtime limits.
- Reject a strategy source variant when the focused gate fails or times out.
- Cache focused pass/fail evidence by source hash and focused profile so
  repeated parameter scoring does not rerun replay.
- Hide emitted/strict replay decisions from the strategy-writing LLM and the
  autoresearch inner loop.
- Preserve strict validation/evaluation behavior for survivor/audit workflows.

**Non-Goals:**

- Prove that a strategy is profitable or robust.
- Replace validation/evaluation strict causality.
- Add a fourth public surface beyond quick run, validation, and evaluation.
- Add a new runtime dependency or a distributed job system.
- Guarantee that one focused source-hash pass covers every possible parameter
  branch. Survivor validation remains responsible for stronger checks.

## Decisions

### Decision 1: Add a high-level focused policy instead of making agents choose replay modes

The runner will support a focused causality policy for Train/autoresearch
iteration. Autoresearch-facing templates and docs will use this focused policy;
they will not require the LLM to choose `emitted` or `strict`. Existing low-level
`off` / `emitted` / `strict` modes remain available for explicit debug and audit
callers, but they are not the default research-loop vocabulary.

Alternatives considered:

- Always use emitted replay: rejected because downstream already shows emitted
  replay can consume minutes and gigabytes on autoresearch-scale loops.
- Disable causality in quick run entirely: rejected because agents can introduce
  obvious lookahead and the loop needs an early hygiene gate.
- Add a separate CLI command: rejected because the project intentionally keeps
  three public jobs (`run`, `validate`, `evaluate`).

### Decision 2: Cache focused evidence by source-oriented key

The focused gate result will be keyed by strategy source hash, strategy id,
data kind, normalized strategy-row hash, validated parameter hash, focused
profile version, probe cap, and timeout budget. This keeps the hot path from
rerunning focused replay for the same evidence request while preventing a pass
from one window, parameter branch, or probe budget from being reused for a
different request. The cache payload will record the selected probes, status,
timeout budget, source hash, and profile version.

Alternatives considered:

- Key only by source hash: faster, but too broad for a data-derived gate because
  one window or parameter branch could certify another.
- Ignore caching: simple, but still makes every score pay causality cost.

### Decision 3: Focused replay uses deterministic sampled probes with hard caps

The focused policy will derive a deterministic subset of replay probes from the
loaded strategy-visible rows and baseline decisions. The sample should include
representative emitted-decision probes when available, no-signal probes, early /
middle / late row-grid probes, and first / last symbol coverage. If emitted
decisions exceed the probe budget, they are selected deterministically using a
seed derived from the cache key.

The gate has a wall-time budget, defaulting to 60 seconds. Where the host
supports an interrupting timer, focused replay is interrupted at the deadline;
otherwise elapsed time is checked before and after replay. Failure, timeout,
skipped sampled probes, or unhandled strategy error rejects the source variant
for scoring. Infrastructure or data-load failures remain ordinary run failures
rather than silent rejects.

Alternatives considered:

- Pure random probes: rejected because results would be hard to reproduce.
- Full strict grid replay: rejected because it is exactly the non-quick path.

### Decision 4: Validation and evaluation remain the robust gates

Focused causality evidence is Train/autoresearch hygiene evidence. Validation
and evaluation continue to run strict causality as their preflight gate. Survivor
promotion and serious research conclusions should rely on validation/evaluation,
not focused quick-run evidence alone.

## Risks / Trade-offs

- Focused sampling can miss branch-specific lookahead. → Mitigation: label the
  evidence as focused, cache by profile version, and keep strict validation /
  evaluation as survivor gates.
- Cache keys can over-trust mismatched evidence if they omit data or focused
  profile inputs. → Mitigation: include row hash, parameter hash, probe cap, and
  timeout budget in the cache key.
- Timeouts can reject complex but causal strategies. → Mitigation: rejection is
  intentional for the autoresearch loop; complex survivors can still be audited
  through explicit validation/evaluation workflows.
- Existing users may still rely on low-level replay modes. → Mitigation:
  preserve existing explicit modes and update docs to separate research-loop
  focused policy from advanced/audit policy.

## Migration Plan

1. Add focused causality result types, probe derivation, timeout handling, and
   cache-key helpers.
2. Extend runner config and evidence artifacts with focused gate status while
   preserving existing causality fields.
3. Update autoresearch/consumer docs to use focused policy for Train iteration
   and validation/evaluation for survivor gates.
4. Add focused tests for pass, fail, timeout, cache hit, evidence payloads, and
   non-regression of explicit emitted/strict modes.
5. Rollback is straightforward: explicit `off` / `emitted` / `strict` modes
   remain supported, so reverting focused policy does not remove the existing
   replay implementation.

## Open Questions

- The initial focused gate will use a 60-second default wall-time budget. If
  empirical runs show the common focused path is not under 20 seconds, tighten
  probe counts before broad use.
