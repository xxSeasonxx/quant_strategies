# Performance Review — `crypto_perp_funding_crowding_reversal` (one run == one experiment)

Scope: wall-time / runtime cost of a single `runner.run_config(...)` on the attempt-0012
survivor (`researched/crypto_perp_funding_crowding_reversal/strategy.py`), and how to make
that cost cheaper for the downstream auto-research climb, where **every experiment is exactly
one `run_config` call**. Per `quant_autoresearch/program.md`, each attempt edits `strategy.py`'s
`generate_decisions` signal logic and the bounded `experiment.toml` params; the **data config**
(symbols, window, dataset, costs, fills, capacity, leverage) is protocol-frozen for the whole
lifecycle. That frozen data config — not a frozen strategy — is what makes the data-prep work
below invariant across attempts.

## How this was measured

- Driver: `runner.run_config` on a self-contained run config equal to the frozen Train
  protocol (`protocol.train.toml`) + attempt-0012 params (`experiment.toml`), `diagnostic`
  profile, `causality_check = "micro"`, `micro_probe_limit = 40`, `foundation_subwindows = 6`.
- Per-stage wall time comes from the runner's own `StageEmitter` `duration_ms` events; the
  function-level split comes from `cProfile`.
- Two windows: a **2-month** window (2025-03-01..05-01, 8 symbols, 1-min) for the profiled
  numbers below, and the **full 10-month** climb window observed live.
- Honest caveats:
  - The 2-month `run_config` wall (121 s) was measured while the live climb was running, so
    it is partly contended (an upper bound on quiet-machine wall).
  - `cProfile` inflates absolute time (~1.1B calls) and over-weights high-call-count
    functions, so treat the function-level **shares** as directional and the JSON/normalize
    share as an upper bound. The **stage-level** split is un-inflated and is the ground truth.
  - Full-window numbers are a ~5.4× row-count extrapolation, corroborated by the live climb's
    resident-set size.

## Headline

| Metric | 2-month window (measured) | Full 10-month climb window |
|---|---|---|
| Signal rows (strategy window) | 714,240 (89,280 × 8) | ~3.9M |
| Materialized rows incl. valuation mark frame | ~1.6M Python dicts | ~8M Python dicts |
| Peak process RSS | **6.8 GB** | **~30 GB** (live climb observed at 33–34 GB) |
| `run_config` wall (contended) | **121 s** | order **minutes** per experiment |

The dominant cost of a run is **data preparation, not the strategy or the P&L walk** — and
that preparation is byte-identical on every experiment in a lifecycle.

## Where the time goes

Stage-level wall (un-inflated, 2-month run):

| Stage | Wall | Share | What it does |
|---|---|---|---|
| `strategy_execution` | 85.7 s | 71% | load data + normalize (×2) + freeze rows + call `generate_decisions` |
| `causality_check` (micro) | 22.0 s | 18% | build a visible-row index + replay `generate_decisions` on 40 prefixes |
| `portfolio_foundation` | 10.9 s | 9% | base + cost-stress + 6 subwindow NAV walks + book-scale calibration |
| everything else | < 2 s total | < 2% | config, artifacts, readiness, observation audit |

Function-level decomposition (cProfile shares of the compute path):

| Work | ~Share | Root location |
|---|---|---|
| Row normalization **run twice** (execution window, then strategy window) | ~53% | `data_contract.py:184` `NormalizedRows.from_rows` |
| — of which: canonical-JSONL encode + sha256 of every row | ~33% | `data_contract.py:320` `_canonical_jsonl_lines_from_storage`; `core/serialization.py:12` `json_safe_value` (25.6M calls) + `json.dumps` (12M calls) |
| Deep-freeze every row for the purity boundary | ~15% | `boundary.py:42` `frozen_rows` → `_freeze_mapping`/`_freeze_value` |
| Micro-causality: 720k-candidate index build + 40 strategy replays | ~20% | `causality.py:268` `check_micro_causality`, `causality.py:1273` `_visible_row_index_from_normalized` |
| Foundation NAV walks + calibration (17 walks) | ~12% | `core/portfolio_foundation.py:1525` `_walk_book` |
| DB query + Polars→`list[dict]` materialize (signal + mark) | ~8% | `core/data_loader.py:60` `load_data`, `_rows_from_frame` |

The single hottest primitives (cProfile `tottime`): `isinstance` (25 s / 330M calls),
`json_safe_value` (18 s), JSON `iterencode`/`dumps`/`encode` (~23 s combined),
`_freeze_value` (9 s), `abc.__instancecheck__` (7 s / 74M calls), `datetime.isoformat`
(4.7 s). Nearly all of this is spent turning millions of rows into, and validating, Python
dict objects — the same rows, every experiment.

## Root cause: invariant work repeated per experiment

The Train protocol freezes the **data config** (symbols, dataset, window), fills, costs,
capacity, leverage, objective, and gates for the whole lifecycle. Each attempt edits
`strategy.py`'s signal logic and the bounded params — but **not** the data config. The
load → normalize → sha256 → freeze pipeline is a pure function of the frozen data config
(verified: `required_row_fields` and the loaders read only `config.data` / `fill_model` /
`capacity_model`, never `strategy.py`). So the *decisions* change every attempt while the
*loaded / normalized / frozen rows* do not. Split the run accordingly:

- **Invariant across every attempt in a lifecycle** (~65–70% of the run), because it depends
  only on the frozen data config: DB load + Polars materialization, normalization +
  canonical-JSONL sha256 (both passes), and the deep-freeze of rows.
- **Changes every attempt** (~30–35%), because it depends on the edited signal logic and
  params: the `generate_decisions` output, the micro-causality check on the new decisions, and
  the foundation NAV walk on the new decisions.

So even though the strategy code itself changes every attempt, each attempt still recomputes
the invariant ~65–70% from scratch on byte-identical data.

(Separately, the strategy's own `_rows_by_symbol` grouping is data-derived but lives inside the
editable, purity-bound strategy, so the engine can't cache it across attempts; it is recomputed
on every one of the ~42 `generate_decisions` calls *within* a single run — main + 40 micro
replays — a per-run redundancy addressed by lowering `micro_probe_limit`, Tier 1 item 4.)

**Why it can't self-cache today:** the climb runs **one attempt per process** (this is exactly
why the `prepare_run_data` / `PreparedRunData` / `run_config(prepared=)` reuse seam was retired
— "production-dead, no consumer"). A fresh process cannot reuse another process's loaded,
normalized, frozen data. So the fixed cost is paid in full every attempt, and the ~30 GB data
footprint is re-allocated every process.

## Recommendations (root-cause, ordered by leverage)

### Tier 1 — Remove redundant work inside a single run
These help every experiment regardless of the process model; no new seam, no legacy path.

1. **Make the canonical-JSONL sha256 lazy or vectorized (biggest single lever, ~33% ×2).**
   `from_rows` unconditionally JSON-encodes every field of every row (`json_safe_value` +
   `json.dumps` per row) to produce `normalized_rows_sha256`, even under the `diagnostic`
   profile that never emits the per-row JSONL. Compute the hash lazily (only when an artifact
   consumer actually reads it), or replace the per-row Python encoder with a single vectorized
   hash over the already-materialized columnar frame. `data_contract.py:320,342`.

2. **Kill the double normalization (~½ of the ~53% normalize cost).** `from_rows` runs once on
   the execution/load window (in `load_data`) and again on the strategy-visible subset (in
   `execute_strategy_run`, `core/execution.py:139-142`). The strategy window is a timestamp
   prefix-subset of the execution window — derive it by **slicing the already-normalized
   storage** instead of re-normalizing and re-hashing from raw dicts.

3. **Cheapen the purity freeze (~15%).** `frozen_rows` deep-freezes every field of every row
   into `MappingProxyType`, a second full copy after normalization. `NormalizedRows._storage`
   is already immutable tuples; hand the strategy a read-only view over that storage instead of
   re-freezing. `boundary.py:42-54`.

4. **Right-size the micro-causality probe count (~20%).** `micro_probe_limit = 40` triggers 40
   full `generate_decisions` replays plus a ~720k-candidate visible-row index build, per
   experiment. For a fast climb, a smaller limit (~8–12) keeps most causality coverage at a
   fraction of the cost — it is already a protocol knob (`[output].micro_probe_limit`). Also,
   the visible-row index is data-derived and can be shared with the main execution rather than
   rebuilt inside the check.

### Tier 2 — Compute the invariant work once per lifecycle (largest absolute win)

5. **Adopt a persistent-worker / batch-experiment model in the downstream climb.** Instead of
   one process per attempt, keep a worker that loads + normalizes + freezes the protocol-frozen
   data **once** (cache keyed on the frozen data config, which no strategy edit invalidates),
   then re-imports the edited `strategy.py` each attempt — a cheap module import + one
   `generate_decisions` call — and runs it against the cached rows. Per-attempt cost then
   collapses to the ~30–35% that depends on the signal edit (decisions + causality + NAV walk),
   and the ~30 GB footprint is paid once rather than per attempt. This is precisely what the
   retired data-reuse seam enabled; re-introducing it is justified **iff** the climb consumes it
   (otherwise it is dead code again and violates the no-legacy rule). The decision to move the
   climb off one-attempt-per-process is Season's; this repo would expose the prepared-data entry
   point only once there is a consumer.

### Tier 3 — Shrink the invariant footprint itself (strategic)

6. **Stop exploding the columnar frame into `list[dict]`.** `_rows_from_frame` copies each
   Polars frame into millions of Python dicts (twice: `to_dicts()` then `dict(row)`), and
   normalize / freeze / projection each re-copy. This dict-of-Python-objects representation is
   the source of both the ~30 GB RSS and most of the `isinstance`/`abc`/JSON CPU. An
   array-backed row representation (columnar or per-field numpy) would cut memory ~10× and CPU
   substantially. Deeper refactor (data contract + strategy input shape); flag as direction,
   not a quick fix. (Distinct from the memory guidance against pulling VBT onto the Train path —
   this is about not materializing the frozen data as Python objects.)

7. **Verify the valuation mark frame is needed for `crypto_perp_funding`.** `load_data` loads a
   second full universe frame (`crypto_perp_1min` for all symbols) purely for valuation repair
   (`core/data_loader.py:177`), doubling the load + materialize. If the signal frame already
   carries a usable `close`, the mark frame may be redundant for this kind.

## Notes / risks

- The working-tree change to `core/data_loader.py` (raising `_UNIVERSE_MARK_MAX_ROWS` to 20M)
  sits directly on this hot path — it is what lets the wide universe's mark frame materialize
  at all, and it doubles the row count that Tier-1/Tier-3 items act on.
- A stale-data warning surfaced during the probe: `crypto_perp_1min live data end 2026-04-13 is
  84d stale (threshold 2d); strict=True does not enforce freshness unless max_lag_days is set`.
  Not a performance issue, but relevant to the mark loader's freshness policy.
- The recorded per-experiment cost (minutes, dominated by fixed data prep) is far above the
  "~1s Train path" expectation; the gap is the invariant data-prep work, not the strategy.
- Verified: measurements are from the attempt-0012 survivor only; other candidates share the
  same runner path so the cost structure generalizes, but absolute times were not re-measured
  per candidate.

## Appendix — probe artifacts

- Probe scripts: session scratchpad `perf_probe.py` (8-run), `perf_probe2.py` (2-month profiled),
  `perf_probe3.py` (full-window timer). Temp run config and `results/perf_probe/` outputs are
  ephemeral and gitignored.
- Raw 2-month numbers (stage table + cProfile top-40 cumulative and top-25 tottime) are the
  basis for the tables above.
