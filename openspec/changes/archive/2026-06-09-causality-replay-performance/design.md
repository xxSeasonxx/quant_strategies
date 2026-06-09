## Context

Quick run, validation, and evaluation all use hidden-lookahead replay, but they
serve different research decisions. Quick run is the fast iteration surface;
validation and evaluation are later evidence surfaces. Focused quick-run replay
currently blocks engine scoring when it fails or times out, which prevents
downstream autoresearch from logging the diagnostic economics needed to decide
whether a candidate deserves more expensive checks.

The current replay implementation also performs avoidable harness work:
focused planning enumerates row-grid candidates before selecting a tiny sample,
prefix construction refreezes rows per replay boundary, and baseline decisions
are rescanned by several boundary helpers. These costs are especially visible on
large multi-symbol panels.

## Goals / Non-Goals

**Goals:**

- Add a quick-run `micro` replay policy that is cheap by construction.
- Ensure quick-run `micro` replay never blocks scoring.
- Add shared replay-scope evidence so consumers can distinguish `micro`,
  `bounded`, `complete`, and `off` replay.
- Add explicit bounded replay configuration to validation and evaluation while
  keeping complete replay as the default.
- Improve replay harness efficiency without changing the strategy author API.

**Non-Goals:**

- No individual strategy rewrites or performance tuning.
- No replay parallelism in this change.
- No general-purpose strategy-state or indicator cache.
- No new runtime dependency.
- No change to promotion, paper-trading, or live-trading authority.

## Decisions

### Use `micro` for quick-run autoresearch iteration

Quick-run autoresearch should use `causality_check = "micro"`. Micro replay
selects a tiny probe set directly from normalized rows and emitted decisions. It
does not build or rank a full row-grid candidate set. Micro replay is diagnostic
evidence only and never blocks engine scoring.

Alternatives considered:

- Keep `focused` as the recommended mode. Rejected because focused replay still
  couples quick-run scoring to large-prefix strategy replay cost.
- Use `off` by default. Rejected because a cheap diagnostic replay can still
  catch obvious replay failures and provides useful metadata when it stays
  cheap.

### Keep complete replay as validation/evaluation default

Validation and evaluation keep complete replay as their default. They gain an
explicit `causality_replay = "bounded"` option for large-panel research runs.
Bounded replay still includes emitted-decision replay and caps only the
representative row-anchor probes. It is labeled evidence, and
result/provenance payloads record that the replay scope was bounded.

Alternatives considered:

- Make bounded replay the default everywhere. Rejected because validation and
  evaluation are later evidence surfaces, and changing their default evidence
  scope would be a larger semantic shift than needed to unblock quick-run
  iteration.

### Centralize replay preparation in a private workspace

Introduce a private replay workspace that owns visible rows, frozen row storage,
timestamps by symbol, baseline payloads, and decision indexes for one replay
check. `check_hidden_lookahead`, `check_micro_causality`, and bounded replay
helpers use this workspace internally. Public strategy APIs and public replay
entry points remain stable except for additive result fields.

Alternatives considered:

- Add caching hooks to strategy modules. Rejected because strategies must remain
  pure flat files and this change is a harness concern.
- Cache whole strategy outputs across prefixes. Rejected because replay prefixes
  are part of the test and broad output caching risks hiding behavior changes.

### Optimize prefix construction before considering parallelism

Store frozen rows in the visible row index and add a fast tuple-slice path when
availability filtering is not needed. Use filtering only when `available_at`
requires it. Keep replay-row caching by boundary identity, but make the cached
prefix cheaper to produce.

Parallel replay is deferred because process pools would add row-prefix
serialization, strategy import overhead, timeout complexity, and noisier failure
semantics before the obvious wasted work is removed.

## Risks / Trade-offs

- Micro replay can miss hidden lookahead that complete replay would catch.
  Mitigation: label `replay_scope = "micro"`, keep `causality_verified = false`
  on failure/timeout, and keep validation/evaluation defaults at complete
  replay.
- Bounded validation/evaluation can be misread by downstream consumers.
  Mitigation: expose replay scope and probe counts in result/provenance payloads
  rather than only warnings.
- Prefix fast paths can introduce subtle availability bugs.
  Mitigation: preserve the filtered path, add tests for rows where
  `available_at` differs from timestamp, and compare existing hidden-lookahead
  behavior.
- Retaining focused mode creates two quick-run bounded replay concepts.
  Mitigation: document `micro` as the recommended autoresearch policy and leave
  `focused` as advanced/legacy behavior unless a later cleanup removes it.

## Migration Plan

1. Add `micro` config support and replay evidence fields additively.
2. Update committed quick-run configs and consumer docs to recommend `micro`.
3. Add validation/evaluation bounded replay config fields with defaults that
   preserve current complete replay behavior.
4. Archive the OpenSpec change into living specs after implementation and tests.
5. Downstream `quant_autoresearch` can migrate templates from `focused` to
   `micro` after this repo ships the new surface.
