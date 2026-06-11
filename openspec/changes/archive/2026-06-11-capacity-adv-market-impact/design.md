## Context

The shared netted portfolio book is now the single scored money model for quick
run, validation, and evaluation. It charges fee/slippage and crypto-perp funding,
but it does not ask whether an order delta is plausible at the assumed capital
scale. O15 exists because the required bar fields already reach the book for
supported datasets, while scoring remains capacity-blind.

The current book is normalized to `INITIAL_EQUITY = 100.0`. Target weights size
positions in normalized book dollars, so a capacity model needs one additional
operator-owned input: the real portfolio notional represented by that normalized
book. Without that scale, ADV participation and market impact cannot be computed
honestly.

## Goals / Non-Goals

**Goals:**

- Add an explicit capacity envelope that is frozen by the operator beside costs,
  fills, and leverage.
- Make scoreable non-flat runs capacity-priced by default: a traded book with
  capacity disabled is non-scoreable, not silently capacity-free.
- Compute turnover, bar participation, ADV participation, and impact cost from
  the same executed deltas that update the shared book's cash and NAV.
- Keep one money model across quick run, validation, and evaluation.
- Produce compact quick-run diagnostics and detailed evaluation traces from the
  same execution events.
- Fail closed, with typed reasons, when capacity inputs are missing, uncalibrated,
  or breached.

**Non-Goals:**

- No partial fills, order slicing, venue routing, intraday execution scheduler, or
  order-book simulation.
- No FX capacity pricing until FX volume semantics are calibrated as notional
  liquidity. Current FX `volume` is treated as tick-count activity.
- No external dependency or pandas/numpy import on the quick-run book path.
- No legacy compatibility for configs that omit the new capacity envelope.

## Decisions

### D1. Add a required operator-frozen `CapacityModelConfig`

Add `CapacityModelConfig` in `core.config`, and include it in quick-run,
validation, and evaluation configs plus scenario run objects. The table is
required, like the other protocol envelopes.

Proposed shape:

```toml
[capacity_model]
mode = "adv_impact"          # or "off"
portfolio_notional = 1000000 # required when mode = "adv_impact"
adv_lookback_bars = 3900
adv_min_observations = 390
max_bar_participation = 0.05
max_adv_participation = 0.01
impact_coefficient_bps = 10.0
impact_exponent = 0.5
```

`mode = "off"` is allowed for profiling and flat/no-trade runs, but a traded
book with capacity off receives a fail-closed `capacity_unpriced` verdict. This
keeps the escape hatch explicit without preserving silent capacity-free scoring.

Alternative considered: add capacity fields under `[output]`. Rejected because
capacity changes scored economics; agents must not be able to optimize against a
capacity-free score by editing a diagnostic block.

### D2. Represent capacity through execution events, not round trips

Add an `ExecutionEvent` trace to `BookWalkResult`. Each event corresponds to one
executed net delta: target-change entry/trim/close/reversal deltas and risk-rule
flatten deltas. Fields should include symbol, timestamp, event reason, side,
fill price, signed delta units, normalized executed notional, real executed
notional, base cost, impact cost, total cost, bar notional volume, ADV notional,
bar participation, ADV participation, and decision metadata when available.

Round trips are still the per-trade attribution view, but they are too coarse for
capacity: same-sign trims, additions, reversals, and stop exits can all produce
capacity-relevant deltas that do not map cleanly to a single closed round trip.

Alternative considered: derive capacity from completed round trips. Rejected
because it misses open-position deltas and misattributes reversal costs.

### D3. Charge impact in the localized fill/cost step

For each executed delta:

1. Compute normalized executed notional as `abs(delta_qty * fill_price)`.
2. Scale to real notional using
   `real_notional = normalized_notional * portfolio_notional / INITIAL_EQUITY`.
3. Compute bar notional volume as `volume * reference_price`, using positive
   `vwap` when present and otherwise the fill/mark price.
4. Compute ADV notional from prior rows for the same symbol, excluding the
   current fill row, over `adv_lookback_bars`, requiring
   `adv_min_observations`.
5. Compute `bar_participation = real_notional / bar_notional_volume` and
   `adv_participation = real_notional / adv_notional`.
6. Fail closed if either participation exceeds the frozen limit.
7. Charge
   `impact_fraction = bps_to_fraction(impact_coefficient_bps) *
   adv_participation ** impact_exponent`, and subtract
   `impact_cash = normalized_notional * impact_fraction` from cash.

Base cost remains the configured fee+slippage term. `cost_cash` on round trips
becomes total transaction cost; a new impact component exposes the split.

Alternative considered: fold impact into `slippage_bps_per_side`. Rejected
because a constant bps field cannot scale with order size or ADV and hides the
capacity evidence needed for review.

### D4. Fail closed on missing or unsupported capacity inputs

Capacity-enabled non-flat runs require valid notional volume inputs. Missing,
non-finite, negative, or zero volume on an executed bar is a row/capacity failure,
not a warning. Insufficient prior volume history for ADV is a capacity failure on
the first affected executed delta. `forex_with_quotes` is unsupported for
`adv_impact` because its `volume` is tick count/activity, not notional liquidity.

The feasibility vocabulary should add typed reasons such as:

- `capacity_unpriced`
- `capacity_unsupported_volume_semantics`
- `capacity_missing_volume`
- `capacity_insufficient_adv_history`
- `capacity_limit_breach`

Alternative considered: emit capacity warnings while still scoring. Rejected
because the foundation's north star is that Train evidence must be feasible to
trade.

### D5. Surface compact and detailed evidence from the same events

Quick-run foundation summaries should expose compact capacity diagnostics:
maximum and mean bar participation, maximum and mean ADV participation, total
turnover, total impact cost, and impact as a share of gross realized
attribution. Typed quick-run economics should expose impact return per round
trip, while preserving total cost return as the total cost component.

Evaluation should serialize execution events as a Parquet trace table. Existing
portfolio path and round-trip tables remain derived from the same book walk.

Alternative considered: add only evaluation traces. Rejected because
`quant_autoresearch` needs quick-run Train diagnostics without scraping heavy
artifacts.

## Risks / Trade-offs

- **Calibrated notional is arbitrary unless chosen deliberately** -> Require
  `portfolio_notional` in config and record it in artifacts so reviewers know the
  capacity scale.
- **ADV lookback may fail at the start of short windows** -> Use explicit
  `adv_min_observations`, encourage load buffers in configs, and fail closed
  rather than using future/current volume as history.
- **Simple impact is still an approximation** -> Keep the formula transparent,
  deterministic, and conservative; defer partial fills and venue-specific models.
- **More config churn across candidates** -> Cut over committed configs in the
  same change, per the no-legacy project rule.
- **Round-trip cost split remains approximate on reversals** -> Keep NAV exact
  through execution events; document round-trip attribution as derived.
