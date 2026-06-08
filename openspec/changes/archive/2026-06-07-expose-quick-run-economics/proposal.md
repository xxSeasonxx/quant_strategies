## Why

The quick-run (Train) surface already computes per-trade economics on every run, but
`run_config` returns them **nowhere in-process** — `RunResult` carries only causality and
row-contract evidence, while the economic numbers are computed *inside* the artifact writer
and emitted only to `summary.json`. A programmatic consumer (the `quant_autoresearch`
simplified-loop, which climbs a robustness number on Train via `run_config`) would have to
scrape `results/*.json` on every ~1s iteration to read after-cost returns. The data exists
and is thrown away from the in-process result; this change hands it back.

## What Changes

- Modularize the economic-metric computation out of the artifact-writing path
  (`_write_completion_artifacts`) into a standalone step over the in-memory engine result,
  feeding **two sinks**: the existing artifact writer (behavior unchanged) **and** a new
  field on `RunResult`.
- Add a new **additive** typed field on `RunResult` that exposes, in-process, both:
  - the **raw per-trade ledger** the engine already builds (per trade: `symbol`, `side`,
    `weight`, `decision_time`/`entry_time`/`exit_time`, `gross_return`, `funding_return`,
    `cost_return`, `net_return`, `exit_reason`) — so a consumer can slice the after-cost
    return sample by time and by symbol; and
  - the **summary scalars + slices** already produced by `runner/economic_metrics.py`
    (`trade_count`, hit-rate, profit factor, cost/funding share; by-symbol / by-direction /
    by-exit-reason groupings).
- Make the in-process accessor **independent of `artifact_profile`**: it MUST populate even
  under the `summary` profile (and any future no-artifact run). Reading it MUST NOT require
  writing files.
- Keep the Train path **pure-Python and dependency-light**: no numpy/pandas/VectorBT Pro,
  no portfolio/dataframe construction. The exposed objects are plain typed value objects
  (dataclasses) over data already in memory.
- Additive and non-breaking: existing `RunResult` fields and the `succeeded` property are
  unchanged; the public `run_config` signature is unchanged.

Out of scope (deliberately): a per-period / bar-level return series on Train (a
portfolio-backend concept that would require new economics and pull VectorBT Pro into the
loop); the downstream climb math (`worst_subwindow`, `breadth_median`, `cv_mean`), gates, and
the in-memory data cache (these live in `quant_autoresearch`); and any significance
statistics (PSR/DSR/PBO). The validation surface is not changed.

## Capabilities

### New Capabilities
- `quick-run-economics`: `run_config` exposes the quick-run after-cost trade-level economics
  (the raw per-trade ledger plus the summary scalars/slices) as typed, in-process value
  objects on `RunResult`, populated on every completed run independent of `artifact_profile`,
  with no new runtime dependency.

### Modified Capabilities
<!-- None. The sibling `evaluation-fold-returns` capability is the design precedent but its
     requirements are unchanged. `data-boundary` is unaffected. -->

## Impact

- **Code**: `src/quant_strategies/runner/__init__.py` (build the economics step over the
  in-memory engine result; attach to `RunResult`); `src/quant_strategies/runner/economic_metrics.py`
  (expose typed value objects, not just dict payloads for the artifact); the `RunResult`
  dataclass gains one additive field. The artifact-writing path keeps emitting the same
  `summary.json`.
- **Public API**: `run_config` signature unchanged; `RunResult` gains an additive,
  defaulted field — existing consumers and `succeeded` unaffected.
- **Consumers**: unblocks the `quant_autoresearch` loop from reading the Train after-cost
  return sample in-process (no artifact scraping).
- **Dependencies**: none added — Train path stays free of numpy/pandas/VectorBT Pro.
- **Docs** (on implementation): `docs/consumer/reference.md` (`RunResult` field table) and
  `docs/consumer/usage-guide.md` (Surface 1 — Quick run; programmatic-consumer section).
