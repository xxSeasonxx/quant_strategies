## Why

Quick-run Train iteration currently exposes only trade-level engine economics, so
autoresearch cannot compute portfolio-return foundation metrics such as
serial-correlation-aware Sharpe inputs, DSR inputs, drawdown, and concentration
without either scraping evaluation artifacts or running the heavier evaluation
backend. This change adds a diagnostic, dependency-light portfolio-return
foundation directly to quick run for fast Train scoring.

## What Changes

- Add an optional quick-run portfolio foundation surface that is diagnostic by
  default and remains Train/autoresearch evidence only.
- Build causal after-cost portfolio return paths in quick run without importing
  `quant_strategies.evaluation`, `vectorbtpro`, `pandas`, or `numpy`.
- Compute per-Train-subwindow foundation metrics for realistic-cost and
  cost-stressed scenarios:
  - return sample count and effective sample size
  - Sharpe and serial-correlation-aware uncertainty inputs
  - skew and kurtosis
  - DSR inputs and DSR value when trial-count metadata is available
  - max drawdown, closed-trade count, and symbol concentration
- Expose the foundation metrics in-process on `RunResult` and in compact
  diagnostic artifacts.
- Keep full return traces out of default artifacts; any trace-level output must
  be explicitly gated by an artifact/profile option.

## Capabilities

### New Capabilities

- `quick-run-portfolio-foundation`: Diagnostic quick-run portfolio-return
  foundation metrics for Train scoring without the evaluation backend.

### Modified Capabilities

- `quick-run-economics`: Allow quick run to expose a separate diagnostic
  portfolio-return foundation while preserving the existing trade-level
  economics contract and the heavy-dependency import wall.

## Impact

- Affected source:
  - `src/quant_strategies/core/` for shared lightweight portfolio/return math
  - `src/quant_strategies/runner/` for config, result objects, artifact payloads,
    and orchestration
  - OpenSpec specs and user-facing docs that describe quick-run Train evidence
- Affected APIs:
  - `RunResult` gains an additive foundation-metrics field.
  - quick-run config gains additive foundation settings.
- Dependencies:
  - No new runtime heavy dependency in the quick-run path.
  - The quick-run dependency-wall guard must continue to reject imports of
    `quant_strategies.evaluation`, `vectorbtpro`, `pandas`, and `numpy`.
