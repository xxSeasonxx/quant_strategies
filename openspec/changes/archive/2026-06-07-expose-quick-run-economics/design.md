## Context

The quick-run (Train) surface computes after-cost, per-trade economics on every run, but
returns them nowhere in-process. Concretely:

- `_evaluate_engine_request` (`runner/__init__.py:441`) calls the engine with
  `include_diagnostics=True` **hardcoded** — only `include_evidence` is gated on
  `artifact_profile`. So `engine_run.screen_summary` carries the full per-trade ledger on
  **every** completed run, independent of profile.
- The economics are then computed at `runner/__init__.py:476-484`, **inside**
  `_write_completion_artifacts`: `compact_engine_summary(..., include_diagnostic_trades=True)`
  → `trades_from_engine_summary` → `summary_metrics`. The result flows only into
  `summary.json`. The per-trade ledger is `pop`-ed off (line 486) before the non-diagnostic
  summary is written.
- The by-symbol / by-direction / by-exit-reason **slices** (`economic_metrics.diagnostic_slices`)
  are computed *only* under the `diagnostic` profile (`runner/diagnostics.py`).
- `RunResult` (`runner/__init__.py:66`) exposes only `outcome`/`evidence` — nothing economic.

A programmatic consumer (the `quant_autoresearch` simplified-loop, which climbs a robustness
number on Train via `run_config`) therefore has to scrape `results/*.json` every ~1s
iteration to read the after-cost return sample its `objective.py` slices into
subwindows/cells. The data already exists in memory; this change hands it back.

Precedent: `openspec/specs/evaluation-fold-returns/spec.md` already established this exact
pattern on the evaluation surface — one computation feeding both an on-disk trace and a
typed, in-process accessor on the result object, with no significance statistics.

## Goals / Non-Goals

**Goals:**
- Expose the quick-run after-cost economics in-process on `RunResult`: the **raw per-trade
  ledger** (so a consumer can slice by time and symbol) **and** the **summary scalars +
  slices** already computed.
- Populate the accessor on every completed run, **independent of `artifact_profile`**
  (including `summary`); reading it MUST NOT require writing artifacts.
- Keep the Train path **pure-Python and dependency-light** — no numpy/pandas/VectorBT Pro,
  no portfolio/dataframe build.
- Additive, non-breaking: `run_config` signature and `RunResult.succeeded` unchanged.

**Non-Goals:**
- A per-period / bar-level return series on Train. That is a portfolio-backend concept
  (evaluation only) and would require new economics + pull VectorBT Pro into the loop.
- The downstream climb math (`worst_subwindow`, `breadth_median`, `cv_mean`), gates, and the
  in-memory data cache — these live in `quant_autoresearch`.
- Significance statistics (PSR/DSR/PBO).
- Changing the validation surface or any on-disk artifact (`summary.json` etc. stay byte-stable).

## Decisions

### D1 — One computation, two sinks (the modularization)
Extract the economics computation (currently `runner/__init__.py:476-484`) into a standalone
builder over the in-memory engine result, e.g. `economic_metrics.build_run_economics(engine_run)
-> RunEconomics`. `run_config` calls it once after `_evaluate_engine_request` succeeds,
attaches the typed object to `RunResult`, and hands the **same** object (or its dict
projection) to `_write_completion_artifacts`, which keeps emitting the identical
`summary.json`. The economics become a first-class step over `engine_run`, not a side effect
of artifact writing.

*Alternative considered:* compute economics twice (once for the result, once for artifacts).
Rejected — duplicated logic and a drift risk between the in-process number and the on-disk
number. They must be the same computation.

### D2 — New public pure-Python value objects, not engine re-exports
Define the accessor types in the runner package (e.g. `RunEconomics` plus a per-trade
`RunTrade` record) as frozen dataclasses carrying plain floats, `str`, tz-aware `datetime`,
and a tuple of records. Do **not** re-export the internal `engine.models.Trade` — the engine
is internal (per `docs/consumer/reference.md`), and the public contract must not couple to it.
This mirrors evaluation defining its own `FoldReturnSeries`/`FoldScenarioMetrics` rather than
exposing backend internals.

*No numpy.* Unlike evaluation's dense per-period `FoldReturnSeries`, a trade ledger is
record-shaped and sparse; typed records + scalar floats are the natural foundation and keep
the path dependency-free. The consumer builds whatever arrays it wants.

### D3 — Source from the in-memory engine result; decouple slices from the diagnostic profile
Build the records from `engine_run.screen_summary` (trades always present per the hardcoded
`include_diagnostics=True`), so the accessor is profile-independent. Compute the by-symbol /
by-direction / by-exit-reason **slices unconditionally** from the in-memory ledger — today
they are only built under the `diagnostic` profile; the in-process object computes them every
run (a pure-Python grouping over a list already in memory; trivial cost).

`screen_summary` is a JSON dict, so trade timestamps are ISO strings; the builder parses them
to tz-aware `datetime` deterministically so the consumer slices by real time without parsing.

*Alternative considered:* retain the typed `ScreeningResult` (real `datetime`s) on `EngineRun`
to avoid parsing. Rejected for now — it widens the blast radius into `core/engine_runner.py`
and the `EngineRun` contract; parsing ISO strings is deterministic and keeps the change
confined to the runner package.

### D4 — Expose both the raw ledger and the summary scalars/slices
The raw per-trade ledger is the foundation (downstream slices it into subwindows/cells and
per-symbol cells); the scalars/slices are a convenience layer. Both ride on one
`RunEconomics` object. Per-trade fields mirror the engine `Trade`: `symbol`, `side`,
`weight`, `decision_time`, `entry_time`, `exit_time`, `entry_price`, `exit_price`,
`exit_reason`, `gross_return`, `funding_return`, `cost_return`, `net_return` (and
`decision_id`).

### D5 — Additive and non-breaking
`RunResult` gains one defaulted field (e.g. `economics: RunEconomics | None = None`). It is
`None` only when the run did not reach a completed engine evaluation (config/data/causality
failures); a completed run always populates it. `succeeded` and the `run_config` signature are
unchanged. Carry a schema/basis marker (parity with the artifact's `SUMMARY_SCHEMA_VERSION` /
`engine_trade_ledger` basis) for provenance.

### D6 — The dependency wall is the performance guard
The Train path stays import-clean of `vectorbtpro`/`pandas`/`numpy`/`quant_strategies.evaluation`
(verified today). The accessor adds only pure-Python object construction over data already in
memory. This is the concrete, testable form of "keep an eye on performance": a guard test
asserts the Train path imports none of those modules.

## Risks / Trade-offs

- **Slices now computed every run, not just under `diagnostic`.** → Pure-Python grouping over
  an in-memory list the engine already built; negligible cost, and artifacts are unchanged
  (the new computation feeds the in-process object; the diagnostic artifact path is unaffected
  or reuses the same builder).
- **Timestamp parsing from the JSON summary.** → Deterministic ISO→tz-aware parse; covered by
  a round-trip test on a known trade (typed record times equal the engine's). If parsing ever
  proves fragile, D3's rejected alternative (retain typed `ScreeningResult`) is the fallback.
- **Trade-unit, point-to-point semantics only.** → The exposed sample is per-trade net
  returns with engine economics, not period returns and not the portfolio-backend
  implementation the OOS gate uses. This is the deliberate scope wall, not a defect; a
  consumer needing period-level or OOS-comparable returns uses evaluation, and period-on-Train
  is a separate future change if ever justified. Recorded as a known limitation.
- **In-process number must equal the artifact number.** → Guaranteed by D1 (single
  computation). A test asserts `RunResult.economics` summary scalars equal `summary.json`'s
  `economic_metrics` for the same run.

## Open Questions

- Field/type names (`economics`, `RunEconomics`, `RunTrade`) — proposed above; final naming at
  implementation. 
- Whether validation should later expose the same accessor (it runs the same engine path) —
  explicitly deferred; out of scope here.
