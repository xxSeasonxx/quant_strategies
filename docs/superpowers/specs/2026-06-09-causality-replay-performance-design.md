# Causality Replay Performance Design

Date: 2026-06-09

## Context

Quick-run causality replay has become a blocker for downstream
`quant_autoresearch` full-baseline runs. Recent focused causality runs timed out
before engine scoring even with small selected probe counts because each selected
probe can still replay strategy generation on a large row prefix. The observed
candidate probe count was over five million rows, and no diagnostic score was
logged because replay failed before scoring.

The root problem is structural: quick run is an iteration surface, but focused
causality currently acts as a pre-score gate. When replay costs minutes or times
out, it prevents the research loop from getting the score needed to decide
whether a candidate deserves stronger checks.

## Goals

- Let quick run produce diagnostic economics even when cheap causality replay
  fails or times out.
- Add a cheap quick-run replay mode that is bounded by construction and does not
  enumerate the full row grid.
- Improve replay harness efficiency for quick run, validation, and evaluation.
- Preserve clear evidence semantics so bounded replay is not confused with
  complete replay.
- Keep strategy files out of scope for this change.

## Non-Goals

- Do not rewrite or optimize individual strategy modules.
- Do not add a general strategy caching API.
- Do not add replay parallelism in this pass.
- Do not change promotion, paper-trading, or live-trading authority.
- Do not weaken evidence labels by implying bounded or micro replay is complete
  replay.

## Replay Vocabulary

Use neutral replay-scope vocabulary across surfaces:

- `complete`: deterministic replay, emitted-decision replay, and row-grid
  no-signal replay.
- `bounded`: deterministic replay, emitted-decision replay, and a bounded
  representative row-grid replay.
- `micro`: quick-run diagnostic replay with a tiny probe set and hard time
  budget.
- `off`: explicit no replay for profiling or debugging.

Expose `replay_scope` in result/artifact causality evidence where the current
flat flags are insufficient to distinguish these modes.

## Quick Run Behavior

Add `causality_check = "micro"` as the recommended autoresearch quick-run mode.

Micro replay:

- Never blocks engine scoring.
- Runs a tiny deterministic replay sample under a hard wall-time budget.
- Selects probes directly from normalized rows and emitted decisions.
- Does not enumerate or rank the full row grid.
- Records selected probe count, candidate count when cheap to know, elapsed
  seconds, timeout budget, timeout status, and any replay warning.
- If replay passes, records `replay_scope = "micro"` and verified micro replay
  evidence.
- If replay fails or times out, still returns scored quick-run economics and
  records `causality_verified = false` with the replay reason.

Existing quick-run modes remain available:

- `strict`: complete replay, still able to block scoring when selected
  explicitly.
- `emitted`: deterministic plus emitted-decision replay.
- `focused`: legacy or advanced source-oriented replay mode unless migrated to
  `micro` semantics in a later cleanup.
- `off`: no replay, explicitly unverified.

## Validation Behavior

Validation keeps `complete` replay as the default.

Add an explicit bounded replay option for large-panel runs. A bounded validation
run records:

- `replay_scope = "bounded"`.
- selected probe count.
- candidate count when available without full enumeration.
- elapsed seconds and timeout budget.
- timeout or replay warnings.

Validation remains advisory mechanical evidence. No promotion semantics change.

## Evaluation Behavior

Evaluation keeps `complete` replay as the default.

Add an explicit bounded replay option for large-panel research evaluation.
Evaluation metrics may still be produced under bounded replay when configured,
but provenance and result evidence must record `replay_scope = "bounded"` so
downstream consumers can rank, filter, or require complete replay as needed.

Evaluation remains evidence only and does not authorize promotion, paper
trading, or live trading.

## Harness Performance Design

Make performance improvements in the replay harness, not in strategy files.

### Micro Probe Selection

Micro replay should directly select a tiny probe set:

- first valid row boundary.
- middle valid row boundary.
- last valid row boundary.
- up to a small cap of emitted-decision boundaries.

It should not build millions of candidate boundaries, hash every candidate, or
use a heap over the full row grid.

### Replay Workspace

Extract a shared private replay workspace used by micro, bounded, and complete
replay:

- visible row index.
- frozen row storage.
- timestamps by symbol.
- baseline decision indexes.
- deterministic baseline payloads.
- frozen params.

The workspace should be built once per replay check and passed through internal
helpers. Public strategy APIs remain unchanged.

### Prefix Construction

Optimize replay prefix construction:

- Store frozen rows in the visible row index so replay does not repeatedly
  refreeze rows.
- Use a tuple-slice fast path when availability filtering is unnecessary.
- Use the existing filtered path only when `available_at` can differ from the
  timestamp visibility boundary.
- Preserve replay-row caching by `(as_of_time, decision_time)`, but make cached
  prefixes cheaper to build.

### Decision Indexes

Build decision indexes once:

- expected decisions by replay boundary.
- allowed decisions by `(as_of_time, symbol)`.
- emitted boundaries grouped by `(as_of_time, decision_time)`.

This avoids rescanning baseline decisions while constructing bounded or complete
replay boundaries.

## Why Not Parallelism First

Parallel replay is deferred. In Python, useful replay parallelism likely means a
process pool, which adds large row-prefix serialization costs, strategy import
overhead, timeout complexity, and more failure modes. Micro replay should be
small enough that parallelism is unnecessary. Bounded and complete replay should
first benefit from workspace reuse and direct probe selection.

## Evidence Fields

Add or normalize causality evidence fields where needed:

- `replay_scope`
- `candidate_probe_count`
- `selected_probe_count`
- `elapsed_seconds`
- `timeout_seconds`
- `timed_out`
- `replay_warning`

Existing low-level flags may remain for compatibility, but consumers should be
able to identify replay scope without inferring from multiple booleans.

## Testing Strategy

Add focused tests for behavior and performance:

- Large synthetic panel test proving micro replay does not enumerate the full
  row grid.
- Quick-run micro timeout test proving economics are still produced and
  causality evidence is marked unverified.
- Quick-run micro failure test proving scoring still completes with replay
  warning evidence.
- Validation config tests proving `complete` remains the default and `bounded`
  is explicit.
- Evaluation config tests proving `complete` remains the default and `bounded`
  is explicit.
- Replay workspace regression tests proving row visibility parsing and prefix
  freezing are not repeated per probe.
- Existing emitted, strict, and focused behavior tests should remain unless a
  later cleanup intentionally migrates focused into micro semantics.

## Open Implementation Decisions

- Exact micro defaults: start with `micro_probe_limit = 5` and
  `micro_timeout_seconds = 2.0`, then adjust only if tests show false utility or
  excess runtime.
- Whether bounded replay should share the same probe-selection helper as micro
  with larger caps, or use a separate deterministic row-grid sampler.
- Whether to retain `focused` indefinitely as an advanced quick-run mode or mark
  it deprecated after micro is implemented.
