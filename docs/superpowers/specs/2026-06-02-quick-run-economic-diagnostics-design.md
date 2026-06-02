# Quick-Run Economic Diagnostics Design

- **Date:** 2026-06-02
- **Status:** Approved design; implementation planning should start after Season
  reviews this written spec.
- **Source context:**
  `docs/superpowers/specs/2026-06-01-foundation-mvp-roadmap-design.md`,
  `docs/superpowers/specs/2026-06-01-research-evaluation-surface-mvp-design.md`,
  `PRD.md`, `README.md`, `FOUNDATION_LOCK.md`, `TODOS.md`,
  `docs/foundation-surfaces.md`, and `docs/runner.md`.

## Purpose

Implement B from the foundation roadmap: improve quick-run economic diagnostics
with factual metrics derived from the existing internal engine trade ledger.

The work should answer:

```text
Given this completed quick run, what factual trade-level economic summaries did
the internal engine produce?
```

It should not answer whether a strategy should be kept, killed, ranked,
promoted, paper traded, or live traded.

## Product Boundary

B is a quick-run artifact improvement only. It does not add a new public surface,
does not call validation or evaluation, and does not change the strategy
contract.

Quick run remains:

```text
given: strategy + experiment config + data reference
return: deterministic quick-run evidence from the internal engine
```

The new metrics are derived summaries of engine trades and existing
`trade_result` fields. They are linear signed trade-activity diagnostics, not
portfolio/NAV/path returns and not research evaluation.

B must not:

- add ranking, keep/kill policy, thresholds, or gates;
- add `quant_autoresearch`-specific behavior;
- import VectorBT Pro or any evaluation dependency;
- relabel engine trade-activity sums as NAV, portfolio, or path returns;
- add annualization, drawdown, benchmark-relative, capacity, or robustness
  claims;
- change quick-run, validation-run, or evaluation-run CLI/API names.

## Artifact Shape

Use a split artifact surface.

Every completed quick run should write a compact `economic_metrics` block in
`summary.json`:

```json
"economic_metrics": {
  "schema_version": "quant_strategies.runner.economic_metrics/v1",
  "basis": "engine_trade_ledger",
  "trade_count": 12,
  "winning_trade_count": 7,
  "losing_trade_count": 5,
  "flat_trade_count": 0,
  "hit_rate": 0.5833333333333334,
  "average_trade_net": 0.0012,
  "average_win_net": 0.0041,
  "average_loss_net": -0.0028,
  "profit_factor": 1.7,
  "cost_share_of_abs_gross": 0.18,
  "funding_share_of_abs_gross": -0.04
}
```

Diagnostic-profile quick runs should additionally write richer grouped slices in
`diagnostics.json`:

```json
"economic_slices": {
  "schema_version": "quant_strategies.runner.economic_slices/v1",
  "basis": "engine_trade_ledger",
  "by_symbol": {},
  "by_direction": {},
  "by_exit_reason": {},
  "win_loss_distribution": {}
}
```

The existing `diagnostics.json` fields such as `by_symbol`, `by_direction`,
`by_exit_reason`, `holding_period`, `concentration`,
`cost_funding_breakdown`, and `sample_trades` can remain. The new blocks become
the clearer factual economic surface without requiring a breaking artifact
rename.

## Metric Definitions

All MVP metrics are simple arithmetic over completed engine trades and the
existing engine `trade_result` object.

`summary.json.economic_metrics` should include:

- `schema_version`: `quant_strategies.runner.economic_metrics/v1`.
- `basis`: `engine_trade_ledger`.
- `trade_count`: number of completed engine trades.
- `winning_trade_count`: trades with `net_return > 0`.
- `losing_trade_count`: trades with `net_return < 0`.
- `flat_trade_count`: trades with `net_return == 0`.
- `hit_rate`: `winning_trade_count / trade_count`, or `null` when no trades.
- `average_trade_net`: mean `net_return`, or `null` when no trades.
- `average_win_net`: mean positive `net_return`, or `null` when no winners.
- `average_loss_net`: mean negative `net_return`, or `null` when no losers.
- `profit_factor`: sum of positive `net_return` divided by the absolute sum of
  negative `net_return`, or `null` when there are no trades or no losses. Do not
  emit infinity.
- `cost_share_of_abs_gross`:
  `trade_result.sum_signed_trade_activity_cost /
  abs(trade_result.sum_signed_trade_activity_gross)`, or `null` when gross is
  zero.
- `funding_share_of_abs_gross`:
  `trade_result.sum_signed_trade_activity_funding /
  abs(trade_result.sum_signed_trade_activity_gross)`, or `null` when gross is
  zero.

`diagnostics.json.economic_slices` should use the same trade-level definitions
per group where practical:

- `count`;
- `winning_trade_count`;
- `losing_trade_count`;
- `flat_trade_count`;
- `net_sum`;
- `average_trade_net`;
- `hit_rate`;
- `average_win_net`;
- `average_loss_net`.

Required groups for the MVP:

- `by_symbol`;
- `by_direction`;
- `by_exit_reason`;
- `win_loss_distribution`.

`win_loss_distribution` should be bounded and factual. A simple MVP shape is
enough:

- `largest_win_net`;
- `largest_loss_net`;
- `median_trade_net`;
- `sum_positive_net`;
- `sum_negative_net`;

No bucket tuning or policy labels are required.

## Code Shape

Add one small runner-owned helper module, likely:

```text
src/quant_strategies/runner/economic_metrics.py
```

The helper should contain pure functions that accept the completed engine
trade list plus the compact trade-result summary and return JSON-safe
dictionaries:

```text
summary_metrics(trades, trade_result) -> dict
diagnostic_slices(trades) -> dict
```

Data flow:

```text
engine_runner.evaluate_request(...)
  -> artifacts.compact_engine_summary(...)
  -> extract completed engine trades before artifact-profile trimming
  -> economic_metrics.summary_metrics(trades, trade_result)
  -> summary.json.economic_metrics

diagnostic profile only:
  -> economic_metrics.diagnostic_slices(trades)
  -> diagnostics.json.economic_slices
```

Keep the core engine model unchanged. These metrics are runner artifact
summaries, not new engine primitives.

Summary-level aggregates must be computed from the complete in-memory engine
trade ledger for the completed run. They must not be computed from bounded
sample trades, and the implementation must not persist full trade records in
summary-profile artifacts just to compute these aggregate metrics.

## Error Handling

Completed quick runs with zero trades should produce explicit zero/null metrics,
not failures.

If persisted diagnostic trades are absent because the artifact profile is not
`diagnostic`, summary metrics should still be derived from the complete
in-memory engine trades before those trades are omitted from compact artifacts.
If implementation planning finds that the completed engine trades are not
available at the artifact-writing boundary for all completed quick runs, stop
and resolve that design issue before weakening the artifact contract.

The implementation should not add gates, recovery wrappers, or policy fallbacks.
Malformed completed engine summaries should be treated as implementation bugs
covered by tests.

## Documentation Updates

Implementation of B must update active docs that describe quick-run artifacts:

- `README.md` if the high-level quick-run description changes;
- `PRD.md` if success criteria or metric vocabulary changes;
- `TODOS.md` to remove or collapse the completed B item;
- `docs/foundation-surfaces.md`;
- `docs/runner.md`;
- `docs/quant-autoresearch-consumer.md` only if the stable consumer artifact
  contract changes.

Docs must preserve these statements:

- quick run is factual diagnostic evidence only;
- quick-run trade metrics are engine trade-activity summaries, not NAV/path or
  portfolio returns;
- quick run does not rank, keep, kill, validate, evaluate, promote, paper trade,
  or live trade a strategy;
- VectorBT Pro remains outside the quick-run hot path.

## Tests

Focused implementation tests should cover:

- summary metrics for no trades;
- summary metrics for all winners;
- summary metrics for all losers;
- summary metrics for mixed wins, losses, and flat trades;
- profit factor emits `null`, not infinity, when losses are absent;
- cost/funding shares emit `null` when gross is zero;
- positive and negative funding share semantics;
- `summary.json.economic_metrics` exists for completed quick runs;
- `diagnostics.json.economic_slices` exists for diagnostic-profile runs;
- summary and diagnostic profile boundaries remain intact;
- docs-language checks prevent quick-run economic metrics from drifting into
  NAV/path/portfolio/evaluation or promotion language.

## Non-Goals

B does not include:

- a new evaluation or validation surface;
- annualized metrics;
- drawdown or NAV paths;
- benchmark-relative metrics;
- exposure path or concentration-over-time metrics;
- capacity, liquidity, or market-impact modeling;
- user-defined diagnostic metric sets;
- VectorBT Pro or pandas/pyarrow artifact dependencies;
- `quant_autoresearch` ranking guidance;
- strategy promotion policy.

## Risks

- Metric names can imply more authority than the quick-run surface has. The
  artifact keys and docs must consistently say engine trade-activity evidence.
- Putting too much into `summary.json` would blur artifact profiles. The summary
  block should stay compact; grouped slices belong in `diagnostics.json`.
- Deriving summary metrics from diagnostic-only trade samples would be wrong.
  The implementation must use the completed engine trade ledger, not bounded
  representative samples, for factual aggregate metrics.
- Adding quick-run economic metrics after evaluation exists can blur the
  product boundary. B must keep portfolio/path evidence in evaluation and
  trade-ledger summaries in quick run.

## Implementation Handoff

After Season reviews and approves this written spec, invoke the writing-plans
workflow for B. The plan should start by confirming where completed engine
trades are available for all completed quick-run artifact profiles, then add the
pure metrics helper, targeted artifact wiring, tests, and documentation updates.
