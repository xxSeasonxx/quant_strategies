## 1. Core Foundation Model And Math

- [x] 1.1 Add pure-Python foundation dataclasses for scenarios, subwindow metrics, DSR inputs, portfolio path points, and compact payload serialization.
- [x] 1.2 Implement finite-return statistics: sample count, effective sample size from autocorrelation, Sharpe, Sharpe uncertainty inputs, skew, kurtosis, DSR, and null/warning handling.
- [x] 1.3 Implement Train subwindow splitting and closed-trade counting by trade exit time.

## 2. Lightweight Portfolio Path Builder

- [x] 2.1 Implement a dependency-light portfolio path builder from normalized quick-run rows and emitted decisions.
- [x] 2.2 Support realistic-cost and cost-stressed scenarios without rebuilding the path per subwindow.
- [x] 2.3 Compute max drawdown, per-period returns, closed trades, and max symbol concentration for each subwindow.

## 3. Runner Integration

- [x] 3.1 Add additive quick-run config settings for portfolio foundation diagnostics, subwindows, trial count, benchmark Sharpe threshold, and cost-stress multiplier.
- [x] 3.2 Add `RunResult.foundation` and build it after completed engine evaluation.
- [x] 3.3 Preserve failure semantics: failed quick runs leave foundation metrics unset.

## 4. Artifacts And Semantics

- [x] 4.1 Write compact foundation summaries into `summary.json` and diagnostic matrix details into `diagnostics.json`.
- [x] 4.2 Keep full per-period return traces out of default artifacts.
- [x] 4.3 Update public docs and OpenSpec-facing semantics to label the foundation as diagnostic Train evidence only.

## 5. Tests And Verification

- [x] 5.1 Add focused unit tests for statistics, DSR nullability, subwindow slicing, and concentration semantics.
- [x] 5.2 Add runner integration tests proving completed quick runs expose foundation metrics and failed quick runs do not.
- [x] 5.3 Add dependency-wall tests proving quick-run foundation does not import evaluation, VectorBT Pro, pandas, or numpy.
- [x] 5.4 Run formatting, targeted tests, and `openspec validate add-quick-run-portfolio-foundation --strict`.
