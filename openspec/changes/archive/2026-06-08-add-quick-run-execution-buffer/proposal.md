## Why

Quick-run currently uses one `[data].start/end` window as the strategy-visible
decision window and as the engine execution window. Sparse strategies can emit
causal Train entries near the end of the decision window, but the engine needs
later bars to resolve exits; forcing strategies to check future exit coverage is
non-causal and blocks `quant_autoresearch`.

## What Changes

- Add an additive quick-run execution-buffer contract: callers can request a
  wider load/execution window while keeping the strategy-visible decision window
  unchanged.
- Preserve existing behavior when no buffer fields are configured.
- Ensure strategy generation and hidden-lookahead replay see only decision-window
  rows.
- Ensure engine request building can use buffer rows to fill entries/exits for
  decision-window entries.
- Ensure quick-run economics and artifacts distinguish decision-window evidence
  from execution-buffer rows.
- Update `quant_autoresearch` integration expectations so Train iteration can
  use emitted replay plus an execution buffer instead of future-horizon strategy
  gates.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `quick-run-economics`: Public `run_config` quick runs gain explicit
  decision-window versus execution-window behavior so Train entries can be
  scored while exits are resolved from buffer rows.
- `data-boundary`: Quick-run data loading gains optional strict execution-buffer
  window fields while preserving strict upstream loading, row order, and
  strategy-visible row-contract semantics.

## Impact

- Affected code: runner config parsing, shared execution spec/data loading,
  strategy execution row selection, causality replay inputs, engine request
  construction, data manifests/artifact summaries, and runner tests.
- Public config: additive `[data]` fields such as `load_start` / `load_end` or
  equivalent execution-buffer fields.
- Downstream consumer: `quant_autoresearch` can materialize a post-Train
  execution buffer and remove strategy-level future exit-horizon checks.
- Compatibility: existing configs without buffer fields keep the current single
  window behavior.
