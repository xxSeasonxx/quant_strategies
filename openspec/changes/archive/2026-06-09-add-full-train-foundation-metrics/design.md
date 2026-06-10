## Context

Quick run now builds a lightweight causal portfolio path for each foundation
scenario and slices that path into configured Train subwindows. Each subwindow
record carries enough return-statistic inputs for downstream PSR calculation,
but the artifact does not expose the corresponding full-Train record. Downstream
therefore cannot calculate:

```text
score = min(PSR(full_train_nav_returns), min_k PSR(subwindow_nav_returns_k))
```

without either reading raw returns or incorrectly reconstructing full-window
statistics from subwindow summaries.

The quick-run foundation must stay lightweight: no heavy evaluation imports, no
strategy replays per subwindow, and no default raw NAV or period-return traces.

## Goals / Non-Goals

**Goals:**

- Expose a compact `full_train` metric record per scenario.
- Compute `full_train` from the same Train scoring path used to produce
  subwindows.
- Add minimal economic and gate inputs that are already available from that path:
  total return, mean period return, period-return volatility, max drawdown,
  closed-trade count, and max symbol concentration.
- Keep the payload additive and compact.
- Preserve the downstream boundary: `quant_autoresearch` owns PSR, score, gate
  thresholds, keep rules, and failure-mode labels.

**Non-Goals:**

- Do not emit full NAV or period-return traces by default.
- Do not add parameter-neighborhood, leave-one-symbol, PBO, MinBTL, ES/CDaR, or
  drawdown-duration audits.
- Do not make DSR the keep-rule score.
- Do not change execution semantics, fill semantics, funding semantics, or
  subwindow assignment semantics.

## Decisions

1. Use one foundation metric record shape for full Train and subwindows.

   The existing `FoundationSubwindowMetric` shape already contains most gate and
   statistic fields. Refactor it into a general metric record used by both the
   scenario `full_train` field and each item in `subwindows`. This avoids two
   nearly identical payload implementations and keeps later gate fields from
   diverging.

   Alternative considered: add a separate `FoundationFullTrainMetric` class.
   That duplicates the same payload and statistics logic immediately, so it is
   worse for the current requirement.

2. Add mean and volatility to `ReturnStatistics`.

   `compute_return_statistics()` already computes mean and sample standard
   deviation before Sharpe. Publishing those values is effectively free and
   gives downstream economic-magnitude gate inputs without recomputing returns.
   The existing Sharpe denominator remains the sample standard deviation.

   Alternative considered: leave mean and volatility downstream. That would
   require raw traces or duplicate return aggregation outside the foundation,
   violating the ownership boundary.

3. Add `total_return` to the metric record, computed from the metric NAVs.

   Total return is a path-level economic magnitude input, not a return-sample
   statistic. It belongs next to max drawdown and concentration on the metric
   record. If a metric has no NAVs, `total_return` is `None`.

4. Keep PSR out of the foundation.

   The protocol hurdle Sharpe is a downstream policy input. The foundation emits
   `sharpe` and `sharpe_standard_error`; downstream computes PSR from those
   fields and its configured hurdle.

5. Keep compact summaries useful but not exhaustive.

   Scenario summaries should expose `full_train`, subwindow count, minimum
   trade count, max concentration, and warning counts. The diagnostic matrix
   should continue adding the per-subwindow records. Neither artifact should
   include period-return traces.

## Risks / Trade-offs

- Payload shape grows slightly in `summary.json` and `diagnostics.json` →
  Mitigation: only compact scalar fields are added; no per-period arrays.
- Consumers may currently key off DSR-centered summary fields →
  Mitigation: keep existing DSR fields additive and introduce full-Train fields
  without removal.
- Renaming the internal metric dataclass could disturb tests →
  Mitigation: this class is not imported outside `portfolio_foundation.py`;
  update tests through public payload behavior.
- Full-Train and subwindow returns must share timestamp semantics →
  Mitigation: derive both from the same scoring path and period-return values
  already produced by `_portfolio_path()`.
