# Single Validation Paper Readiness Design

## Goal

Use one retained-candidate validation workflow to decide the highest advisory
status a strategy earns:

```text
hard_no
mechanical_pass
watchlist
paper_candidate
```

`paper_candidate` means the strategy is strong enough for Season to manually
review for a paper-trading experiment. It does not authorize paper trading,
live trading, or promotion.

## Current State

`quant-strategies run` executes one experiment config. Its `validate` mode uses
the internal smoke engine and applies simple gates: valid inputs, minimum one
trade, positive gross return, and positive net return.

`quant-strategies validate` validates researched packages. It already supports
multiple validation windows, VectorBT Pro backend execution, package manifest
checks, readiness metadata, decision validation, data audits, observation
lineage checks, and a scenario matrix per window.

Current package validation scenarios are:

- base with zero costs,
- configured realistic costs,
- doubled stressed costs,
- entry fill lag plus one bar,
- first numeric parameter down 10 percent as diagnostic,
- first numeric parameter up 10 percent as diagnostic.

Current final decisions are `hard_no`, `maybe`, and `mechanical_pass`. The
current `mechanical_pass` criteria are useful but not enough for paper
readiness.

## Design

Keep the public command unchanged:

```bash
conda run -n quant quant-strategies validate researched/<package>
```

Validation becomes a single ladder:

```text
hard_no
  Invalid or untrustworthy run. Examples: manifest mismatch, failed data audit,
  lookahead, backend failure, unsupported semantics, invalid metrics, or
  required scenario failure.

mechanical_pass
  Package is valid enough to backtest and compare. Data lineage passes, backend
  runs, and metrics are usable, but paper-readiness evidence is insufficient.

watchlist
  Strategy is inspectable but not paper ready. This includes promising
  strategies that miss at least one paper-candidate gate and inconclusive runs
  where an optional backend is unavailable.

paper_candidate
  Strategy passes mechanical validation plus v1 paper-readiness gates.
```

## Paper Readiness Config

Add optional validation config:

```toml
[paper_readiness]
enabled = true
min_windows = 2
min_total_trades = 30
min_positive_window_fraction = 0.5
max_stressed_net_loss = -0.02
max_fill_lag_net_loss = -0.02
```

If the section is absent, use these defaults. If `enabled = false`, validation
still returns `hard_no`, `watchlist`, or `mechanical_pass`, but never
`paper_candidate`.

## Gate Logic

Layer 1: integrity gates.

- package manifest/hash checks pass,
- strategy imports,
- params validate,
- data loads,
- decisions validate,
- observation lineage passes,
- no lookahead via `available_at`,
- backend completes required scenarios,
- required scenarios have no unsupported semantics.

Failure here returns `hard_no` when the evidence is invalid or negative.
Backend unavailable returns `watchlist` when package, data, and decision audits
are otherwise inspectable.

Layer 2: mechanical validation.

- required backend scenarios complete,
- backend metrics include valid numeric `net_return` and integer `trade_count`,
- total trade count is at least the existing package-validation mechanical
  minimum of 10 trades.

Passing this layer earns at least `mechanical_pass`.

Layer 3: paper-readiness gates.

- at least `min_windows` validation windows,
- at least `min_total_trades` across required realistic-cost scenarios,
- no required window has zero realistic-cost trades,
- aggregate realistic-cost net return is positive,
- at least `min_positive_window_fraction` of windows have positive
  realistic-cost net return,
- aggregate stressed-cost net return is not below `max_stressed_net_loss`,
- aggregate fill-lag-plus-one net return is not below `max_fill_lag_net_loss`.

Passing all paper-readiness gates returns `paper_candidate`. Passing mechanical
validation but missing paper-readiness gates returns `watchlist` when the
strategy has positive realistic-cost evidence. Passing mechanical validation
without positive realistic-cost evidence remains `mechanical_pass`.

Parameter +/-10 percent scenarios remain diagnostic in v1. They are reported
but do not block `paper_candidate`.

## Metrics

Use existing backend metrics first:

- `net_return`,
- `trade_count`,
- scenario status,
- warnings,
- unsupported semantics.

Add VectorBT Pro metrics when cleanly available:

- `max_drawdown`,
- `profit_factor`,
- `win_rate`.

These metrics may appear in artifacts before they are required by gates. Do not
add Monte Carlo, Deflated Sharpe, or portfolio-level gates in v1. Instead,
reserve explicit artifact fields:

```json
{
  "overfit_controls": {
    "trial_count": null,
    "deflated_sharpe": null,
    "monte_carlo": null
  }
}
```

## Artifacts

Keep the existing validation artifact set. Enrich:

- `validation_decision.json`: final ladder decision, passed gates, failed
  gates, reasons, and eligibility flags;
- `robustness_matrix.json`: per-window and per-scenario metrics,
  classification reasons, decision-generation status, and diagnostic flags;
- `validation_report.md`: concise human explanation of why the strategy earned
  its final status.

Eligibility flags remain false for every decision:

```json
{
  "promotion_eligible": false,
  "paper_trade_eligible": false,
  "live_eligible": false,
  "requires_manual_approval": true
}
```

## Out Of Scope

- automatic paper trading,
- live trading,
- moving strategies to `tested/`,
- portfolio allocation,
- cross-strategy correlation checks,
- capital sharing,
- Monte Carlo,
- Deflated Sharpe,
- backtest-overfitting probability,
- auto-research trial-count accounting.

These are later layers, not v1 requirements.

## Tests

Add focused tests for:

- one-window validation cannot return `paper_candidate`,
- insufficient total trades cannot return `paper_candidate`,
- negative realistic-cost aggregate blocks `paper_candidate`,
- stressed-cost collapse blocks `paper_candidate`,
- fill-lag collapse blocks `paper_candidate`,
- most windows positive can return `paper_candidate`,
- parameter diagnostics are emitted but non-blocking,
- backend unavailable or unsupported does not return `paper_candidate`,
- eligibility flags remain false for `paper_candidate`,
- old configs without `[paper_readiness]` use defaults.

## Rationale

This keeps the system simple: one validation command, one config, one artifact
directory, one final advisory decision. It avoids a separate paper-readiness
workflow while preserving useful distinctions between mechanically valid,
promising, and paper-candidate strategies.

The design also aligns with the auto-research workflow. Auto-research can
generate many candidates, retain a small set, and send each retained strategy
through the same validation ladder. Portfolio management can be added later
once enough individual paper candidates exist.
