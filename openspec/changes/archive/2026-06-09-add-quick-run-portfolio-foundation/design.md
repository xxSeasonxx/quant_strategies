## Context

Quick run currently executes a strategy once, runs causality checks, builds an
engine request, and exposes trade-level `RunEconomics`. That path is intentionally
dependency-light and is guarded by tests that prevent importing
`quant_strategies.evaluation`, `vectorbtpro`, `pandas`, or `numpy`.

The existing evaluation surface already computes per-period portfolio returns and
fold return accessors, but it does so through the evaluation backend boundary.
Using evaluation directly from quick run would make Train iteration heavier and
would blur the public distinction between quick-run diagnostics and
survivor-grade evaluation evidence.

The desired Train foundation is different from the existing trade ledger: it
needs causal after-cost portfolio return paths, subwindow-level return
statistics, DSR inputs, drawdown, concentration, and cost-stressed variants. It
should remain diagnostic by default.

## Goals / Non-Goals

**Goals:**

- Add a quick-run portfolio-return foundation that is diagnostic Train evidence,
  not validation, promotion, paper-trade, or live-trade authority.
- Keep quick run import-clean of evaluation/backend dependencies.
- Compute full Train portfolio paths once per configured scenario, then slice
  those paths into subwindows for metrics.
- Expose foundation metrics in-process on `RunResult` and in compact diagnostic
  artifacts.
- Preserve the existing trade-level `RunEconomics` contract.

**Non-Goals:**

- Do not call `run_evaluation` or `VectorBTProEvaluationBackend` from quick run.
- Do not make quick-run foundation metrics promotion-eligible or comparable to
  evaluation evidence.
- Do not write full per-bar return traces by default.
- Do not implement an optimizer score in `quant_strategies`; the score remains a
  consumer/autoresearch concern built from foundation metrics.

## Decisions

### Keep Foundation Separate From `RunEconomics`

`RunEconomics` remains the existing trade-level engine ledger. Add a separate
`RunPortfolioFoundation | None` field to `RunResult`.

Alternative considered: extend `RunEconomics` with portfolio returns and DSR.
Rejected because it would mix trade-unit diagnostics with portfolio-path
statistics and violate the established semantics of `RunEconomics`.

### Use a Core Lightweight Portfolio Module

Add a neutral pure-Python core module for portfolio-foundation construction,
rather than importing evaluation code into quick run. The module owns:

- prepared row indexing by symbol/time
- decision fill windows
- grouped NAV path construction
- scenario cost variants
- subwindow slicing
- return statistics and DSR inputs

Alternative considered: call the evaluation backend and consume its
`fold_returns`. Rejected because that imports the heavier evaluation stack and
changes quick-run performance/semantics.

### Compute Paths Once Per Scenario

Build one portfolio path for realistic costs and one for cost-stressed costs,
then slice each path into Train subwindows. Do not replay the strategy or
portfolio ledger once per subwindow.

This keeps performance roughly proportional to `scenario_count * row_count`
instead of `scenario_count * subwindow_count * row_count`.

### Diagnostic Defaults

Quick-run foundation metrics are enabled as diagnostic output by default for
completed quick runs. Default artifacts include compact metrics only. Full
period-return traces are not emitted unless a future explicit trace option is
added.

### Metric Semantics

Subwindow metrics use finite post-initial period returns from the causal
portfolio path. DSR is computed only when the necessary inputs are valid:

- at least two finite returns
- finite volatility
- finite effective sample size
- finite skew and kurtosis
- known attempted-trial count
- finite benchmark Sharpe threshold

When any required DSR input is missing, the DSR value is `None` and the payload
includes a warning reason. This avoids silently treating unknown search pressure
as one trial.

### Gate Input Semantics

- `min_trades_per_window` counts closed trades whose `exit_time` falls inside the
  subwindow.
- `max_symbol_concentration` uses maximum symbol share of absolute target
  exposure over the subwindow.
- `cost_stressed_dsr` is read from the cost-stressed scenario's subwindow DSR
  values.
- `complexity` is reported only when supplied by the caller/config or a local
  complexity counter is added; it is not inferred from unrelated metadata.

## Risks / Trade-offs

- Pure-Python portfolio path may drift from evaluation backend semantics.
  Mitigation: keep first implementation narrow, add parity tests against simple
  engine/evaluation fixtures, and label the surface diagnostic.
- Adding DSR to quick run revises an existing spec restriction.
  Mitigation: modify `quick-run-economics` explicitly and keep DSR outside
  `RunEconomics`.
- Portfolio paths can be expensive on large Train windows.
  Mitigation: compute once per scenario, keep scenario set small by default, and
  emit compact artifacts.
- DSR formulas are easy to misuse.
  Mitigation: expose the inputs alongside the result, return `None` on missing
  trial metadata, and keep score construction outside this package.
