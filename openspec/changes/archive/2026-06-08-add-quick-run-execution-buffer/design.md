## Context

The quick-run path currently adapts one `RunConfig.data` window into the shared
`StrategyExecutionSpec`. `execute_strategy_run()` loads rows for that window,
passes those same rows to the strategy, runs causality replay on those rows, and
then gives those rows plus all emitted decisions to the engine.

That works when all exits fit inside the decision window. It breaks for
Train-loop research where entries near `data.end` are valid Train decisions but
need later rows to resolve `max_hold_bars` exits. The workaround of checking
future row availability inside strategy code is wrong because it makes decision
generation depend on future sample coverage.

## Goals / Non-Goals

**Goals:**

- Keep `data.start` / `data.end` as the strategy-visible decision and scoring
  window.
- Add an optional execution/load window for quick-run engine coverage.
- Ensure strategies and causality replay cannot see execution-buffer rows.
- Ensure engine request building can use execution-buffer rows to fill exits for
  decision-window entries.
- Preserve current behavior for configs that omit the buffer fields.
- Give downstream consumers enough artifact metadata to audit which rows were
  strategy-visible versus execution-only.

**Non-Goals:**

- Do not add preloaded-row or cached execution APIs.
- Do not change validation/evaluation window semantics in this change.
- Do not score buffer-only entries.
- Do not add strategy-level cutoff or future-horizon gates.
- Do not relax row-contract, observation-dependency, or data-readiness checks.

## Decisions

### Keep `start/end` as the Decision Window

The existing `[data].start` and `[data].end` fields remain the strategy-visible
window. That keeps current config meaning stable: a strategy receives only rows
inside this window and causality replay audits only this information set.

Alternative considered: reinterpret `end` as load end and add `score_end`. This
was rejected because it would be a breaking semantic change and would make old
configs ambiguous.

### Add Optional `load_start/load_end`

Add optional quick-run `[data].load_start` and `[data].load_end` fields. If
omitted, they default to `start` and `end`. If present, the load window must
cover the decision window: `load_start <= start <= end <= load_end`.

For the immediate autoresearch use case, only `load_end` is needed. The pair is
still cleaner because pre-window warmup is the same class of problem as
post-window exit coverage.

Alternative considered: add `execution_buffer_bars`. This was rejected for the
initial API because bars-to-calendar conversion depends on data cadence and
missing bars. Explicit load dates are deterministic and easier to audit.

### Split Execution Rows From Strategy Rows

The runner should load normalized rows over `load_start/load_end`, then derive a
strategy-visible `NormalizedRows` view over `start/end`. Strategy generation,
determinism replay, emitted replay, and strict replay operate on the
strategy-visible rows only.

Engine request construction receives the full loaded rows plus filtered
decision-window decisions, so exit fills can use buffer rows.

### Filter Entries By Decision Window

Only decisions whose `decision_time` is inside the decision window are eligible
for engine evaluation. Buffer rows are execution support, not a source of
buffer-only entries. Decisions outside the decision window should be excluded
from quick-run economics and artifacts rather than scored.

The first implementation can filter after strategy generation because the
strategy never receives buffer rows. That means all generated decisions should
already be in the decision window, but the explicit filter protects boundary
semantics and future extensions.

### Preserve Evidence Semantics

Data manifests and compact artifacts should expose both row ranges:

- decision/strategy rows: rows visible to strategy and causality replay
- execution/load rows: rows available to engine for fill/exit coverage

`normalized_rows_sha256` for existing artifacts should continue to identify the
strategy-visible input rows unless an artifact explicitly labels an execution
rows hash. This avoids silently changing the meaning of replayability and
strategy evidence hashes.

## Risks / Trade-offs

- Buffer rows could accidentally leak into strategy generation -> derive a
  separate strategy-visible row view and test that a strategy counting rows does
  not see buffer rows.
- Artifacts could confuse strategy evidence with execution support -> label
  strategy-visible and execution-buffer row counts/ranges separately.
- Date-only `load_end` can still be too short for long holds -> downstream
  protocols must choose a buffer long enough for configured hold/fill settings;
  runner should fail loudly if exits still exceed loaded bars.
- Filtering decisions outside the decision window can hide strategy behavior if a
  future extension lets strategies see wider rows -> artifact diagnostics should
  report excluded decision counts if any occur.

## Migration Plan

1. Add optional `load_start/load_end` fields to quick-run data config with
   validation that they cover `start/end`.
2. Extend the execution/data-load flow so quick-run can load the wider execution
   rows while preserving strategy-visible rows for generation and replay.
3. Update runner request build to use execution rows and decision-window
   decisions.
4. Update manifests/summary profile to include decision and execution row
   ranges/hashes.
5. Add tests proving strategies cannot see buffer rows, exits can fill from
   buffer rows, existing configs behave unchanged, and invalid load windows fail.
6. Update `quant_autoresearch` protocol materialization to set `load_end` and
   keep `require_exit_horizon = false`.

Rollback: omit the new fields from configs to return to existing single-window
behavior.

## Open Questions

- Should downstream `quant_autoresearch` set `load_end` explicitly as a date, or
  derive it from max configured hold/fill settings? The upstream API should
  support explicit dates first; downstream derivation can be a follow-up if it
  reduces operator burden.
