## Why

The quick-run portfolio foundation now emits per-subwindow portfolio-return
statistics, but downstream cannot calculate the proposed Train score exactly
because the full-Train return statistics record is missing. The root fix is to
publish the same compact foundation metrics for the full Train path, without
making quick run write raw return traces or own downstream score policy.

## What Changes

- Add a full-Train metric record to each portfolio-foundation scenario, computed
  from the same scenario path used for subwindows.
- Include PSR-ready return-statistic inputs on the full-Train record:
  `return_sample_count`, `mean_return`, `return_volatility`,
  `effective_sample_size`, `sharpe`, `sharpe_standard_error`, `skew`,
  `kurtosis`, and `warnings`.
- Include minimal gate metric fields on the full-Train record:
  `max_drawdown`, `closed_trade_count`, `max_symbol_concentration`,
  and `total_return`.
- Keep PSR, final score calculation, gate thresholds, and keep/discard policy
  downstream-owned.
- Keep default artifacts compact; do not emit full period-return or NAV traces.
- Keep the change additive to the existing foundation payload. No breaking
  change is intended.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `quick-run-portfolio-foundation`: each scenario must expose a compact
  full-Train foundation metric record in addition to the existing subwindow
  records.

## Impact

- Affected code: `src/quant_strategies/core/portfolio_foundation.py`, quick-run
  artifact payload tests, and consumer documentation.
- Affected API/artifacts: `RunPortfolioFoundation.summary_payload()`,
  `RunPortfolioFoundation.matrix_payload()`, `summary.json["portfolio_foundation"]`,
  and `diagnostics.json["portfolio_foundation"]` gain additive full-Train fields.
- Dependencies: none. The quick-run foundation must continue avoiding heavy
  evaluation, pandas, numpy, and vectorbtpro imports.
