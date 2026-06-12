# Crypto Perp Volume-Profile Strategy Research

Date: 2026-06-09

Scope: crypto perpetual futures only. FX research lives in
`fx_activity_profile_strategies.md`.

## Executive View

The best crypto candidates are systematic auction-state signals built from
1-minute bars:

1. **Crypto perp LVN acceptance continuation** - highest data fit. Perps have
   real exchange-traded 1-minute volume and a 25-symbol universe. Trade
   continuation when price accepts through a low-volume node with volume/range
   expansion.
2. **Crypto perp funding-crowding value-area reversal** - strongest economic
   rationale. Combine profile rejection with realized funding extremes, so the
   signal is not just a chart pattern.
3. **Crypto perp POC migration trend** - useful as a trend/regime feature, but
   likely weaker as a standalone entry rule.
4. **Cross-sectional perp profile stretch** - promising as a portfolio signal if
   normalized by symbol and tested with strict multiple-testing discipline.

Do not build strategies that require footprint delta, order-book imbalance, or
intrabar volume-at-price precision. We do not have that data. The viable path is
to approximate volume-at-price from 1-minute OHLCV, keep the approximation
stable, and demand robust out-of-sample behavior.

## Data We Actually Have

Live DB checks on 2026-06-09 and generated `quant-data` consumer docs show:

| Dataset | Symbols | Rows | Observed range | Research window/status | Use |
|---|---:|---:|---|---|---|
| `crypto_perp_1min` | 25 | 58,362,453 | 2020-01-01 to 2026-04-13 | clean from 2020-03-01, usable with caveats | Core OHLCV profile research. |
| `crypto_perp_1min_with_funding` | 25 | 57,945,185 | 2020-03-01 to 2026-04-13 | usable with caveats | Profile plus realized funding/crowding research. |
| `funding_8h` | 25 | 130,575 | 2020-01-01 to 2026-04-13 | usable with caveats | Realized funding event stream. |

Perp symbols available:

`ADA-PERP`, `APT-PERP`, `ARB-PERP`, `ATOM-PERP`, `AVAX-PERP`, `BNB-PERP`,
`BTC-PERP`, `DOGE-PERP`, `DOT-PERP`, `ETH-PERP`, `FET-PERP`, `INJ-PERP`,
`LINK-PERP`, `MATIC-PERP`, `NEAR-PERP`, `OP-PERP`, `PEPE-PERP`, `RENDER-PERP`,
`SEI-PERP`, `SOL-PERP`, `SUI-PERP`, `TIA-PERP`, `UNI-PERP`, `WIF-PERP`,
`XRP-PERP`.

## Data Constraints

The provider stores Binance futures kline field `volume` (`kline[5]`), while the
Binance response also exposes quote-asset volume separately. Our stored `volume`
is therefore best treated as base-asset bar volume, not a directly comparable
USD turnover field across all contracts.

Implications:

- For per-symbol signals, use volume z-scores or percentiles within symbol.
- For cross-sectional signals, prefer `close * volume`, symbol-level ranks, or
  liquidity buckets. Be careful with aliased/multiplier symbols such as `PEPE`.
- We have `num_trades`, but no order-book, bid/ask, taker buy volume, or
  footprint delta. Do not design order-flow imbalance strategies.
- `vwap` is null for crypto in the current loader schema. If a strategy needs
  intrabar VWAP, it must compute an approximation from available bars or use a
  future richer data source.

## Volume-At-Price Approximation

Classic volume profile is volume by price level. We have volume by 1-minute bar.
Any profile is an approximation. The approximation can still be useful if it is
stable and tested honestly.

Recommended construction:

1. Define a price grid per symbol using a volatility-normalized bin size.
2. For each 1-minute bar, allocate bar volume across all bins overlapped by
   `[low, high]`.
3. Baseline allocation: uniform overlap weight.
4. Robustness allocation: close-only, typical-price-only, and triangular weights
   centered on `(high + low + close) / 3`.
5. Keep features only if their sign and rough magnitude survive all reasonable
   allocation choices.

Minimum profile features:

- `poc`: price bin with maximum allocated volume.
- `vah`, `val`: bounds containing 70% of allocated volume around POC.
- `hvn`: local volume maxima.
- `lvn`: local volume minima between HVNs.
- `distance_to_poc_atr`: `(close - poc) / rolling_atr`.
- `profile_width_atr`: `(vah - val) / rolling_atr`.
- `volume_z`: current bar volume relative to same symbol, same time bucket.
- `range_z`: current true range relative to same symbol/time bucket.
- `acceptance_count`: consecutive closes outside prior value area or beyond an
  LVN.
- `rejection`: excursion outside value followed by close back inside value.

## Candidate 1: Perp LVN Acceptance Continuation

Priority: **High**

### Hypothesis

Low-volume nodes mark prices where the market previously moved quickly and did
little business. If price later crosses an LVN with abnormal volume and closes
beyond it for several bars, the market is accepting a new auction range. The
next high-volume node or value-area boundary becomes a natural target.

### Rule Skeleton

Universe: liquid perps, initially `BTC-PERP`, `ETH-PERP`, `SOL-PERP`,
`BNB-PERP`, `XRP-PERP`, then expand to all 25 symbols after proof of concept.

Profile window:

- Intraday: prior 24 hours, rolling every minute.
- Swing: prior 5 trading days / 7 calendar days for crypto.

Long setup:

1. Identify an LVN between two HVNs in the prior profile.
2. Current close moves from below to above the LVN.
3. At least `N` of the last `M` bars close above the LVN. Start with `N=3`,
   `M=5`.
4. Current volume z-score > 1.0 to 1.5 within symbol/time-of-day bucket.
5. Current range z-score > 0.5.
6. Optional: funding is not extremely positive, to avoid joining crowded longs
   at the end of a squeeze.

Short setup mirrors the long setup.

Exit:

- Primary target: next HVN, prior VAH/VAL, or profile measured move.
- Stop: close back inside the LVN region or 1.0 to 1.5 ATR.
- Time stop: exit after 4 to 12 hours if target not reached.

### Why It Could Work

The strategy is not betting that high volume always means continuation. It
waits for acceptance through a previously low-acceptance price zone, then uses
the profile to define where continuation should slow.

It should work best in crypto perps because:

- Volume is real exchange volume, not a tick proxy.
- Perp markets have frequent regime shifts and liquidation-driven continuation.
- The 25-symbol universe allows symbol holdout tests and cross-sectional
  robustness checks.

### Falsifiers

Reject the strategy if:

- Net expectancy is not positive after conservative fees/slippage.
- Performance disappears when bin size changes by +/-50%.
- Performance disappears under close-only vs uniform volume allocation.
- Out-of-sample results are materially worse than a simple Donchian breakout
  with the same holding period.
- More than 50% of total PnL comes from one symbol or one quarter.

## Candidate 2: Funding-Crowding Value-Area Reversal

Priority: **High**

### Hypothesis

Extreme funding identifies crowded positioning. A failed auction outside value
area identifies rejection. Combining them should be stronger than either one:
fade crowded longs only when price fails to accept above value, and fade crowded
shorts only when price fails to accept below value.

### Rule Skeleton

Long setup:

1. Funding percentile over prior 90 to 180 days is very negative, for example
   below the 10th percentile.
2. Price trades below prior 24-hour or 7-day `VAL`.
3. Price closes back inside the value area within `K` bars.
4. The rejection bar has high volume or high range, but does not close near the
   low.
5. Enter long on next bar.

Short setup:

1. Funding percentile is above the 90th percentile.
2. Price trades above prior `VAH`.
3. Price closes back inside value within `K` bars.
4. Rejection bar confirms failure.
5. Enter short on next bar.

Exit:

- Target 1: POC.
- Target 2: opposite value boundary.
- Stop: close outside rejected extreme or 1.0 to 1.5 ATR.
- Re-evaluate at actual funding event timestamps; do not assume a fixed 8-hour
  cadence.

### Why It Could Work

This has a clearer economic story than pure chart patterns:

- Funding extremes proxy for crowding/carry pressure.
- Failed acceptance outside value suggests the crowded side could not force a
  new auction range.
- The POC/value area provides a disciplined target and stop framework.

### Falsifiers

Reject if:

- The edge exists only when using future funding prints.
- Signal returns are worse after excluding the top 5 liquidation days per year.
- The strategy underperforms a simpler funding-mean-reversion rule without
  profile features.
- Drawdowns cluster exactly when funding is most extreme.

## Candidate 3: POC Migration Trend

Priority: **Medium**

Data fit: **Strong**, but likely better as a filter than a standalone strategy.

### Hypothesis

When POC migrates persistently in one direction and the value area follows,
market consensus is moving. This can identify trend regimes where pullbacks to
value should be bought/sold instead of faded.

### Rule Skeleton

Features:

- `poc_slope_6h`: rolling slope of POC over six hours.
- `poc_slope_24h`: rolling slope of POC over 24 hours.
- `value_overlap`: overlap between current and prior profile value areas.
- `price_vs_poc`: close relative to rolling POC.
- `volume_regime`: current rolling dollar-volume percentile.

Long setup:

1. POC slope is positive over 6h and 24h.
2. Current value area is above prior value area or has low overlap.
3. Price pulls back to POC/VAL without breaking trend structure.
4. Volume contraction on pullback, expansion on resumption.

Short setup mirrors long setup.

### Falsifiers

Reject if:

- POC migration adds no incremental value over price momentum and volatility
  filters.
- The signal is profitable only with very wide stops.
- Rebalancing every minute creates turnover that costs overwhelm.

## Candidate 4: Cross-Sectional Profile Stretch

Priority: **Medium to Low** until simpler perp strategies are tested.

### Hypothesis

In a 25-symbol perp universe, distance from weekly POC or value area can identify
relative stretch. Whether stretch should continue or revert depends on volume
acceptance and funding/crowding.

### Rule Skeleton

For each symbol:

- Build a weekly rolling profile.
- Compute `distance_to_weekly_poc_atr`.
- Compute `outside_value_bars`.
- Compute `volume_acceptance_z`.
- Compute `funding_percentile`.

Portfolio variants:

1. **Reversion basket**: fade symbols far outside weekly value when volume
   acceptance is weak and funding is crowded in the move direction.
2. **Momentum basket**: follow symbols far outside weekly value when volume
   acceptance is strong and POC is migrating in the same direction.

### Falsifiers

Reject if:

- Market-neutral or beta-neutral returns are flat.
- Performance collapses when BTC and ETH are excluded.
- Rank correlation is unstable across years.
- The model needs many handcrafted exceptions by symbol.

## Backtest Contract

Loader choices:

- Use `load_crypto_perp_bars_with_funding(..., strict=True)` when funding is
  part of the signal.
- Use `load_strategy_bars(..., dataset="crypto_perp_1min")` for pure profile
  baselines.
- Add conservative fee/slippage sensitivity because current data does not carry
  order-book spread.

Causality:

- Treat all 1-minute close-derived features as available at `timestamp + 1
  minute`.
- Use `available_at` from strict derived loaders whenever present.
- Funding fields are realized event observations, not forecasts.
- No feature may use the current bar's high/low/close until the next decision
  timestamp.

Suggested split:

| Split | Dates |
|---|---|
| Development | 2020-03-01 to 2022-12-31 |
| Validation | 2023-01-01 to 2024-12-31 |
| Holdout | 2025-01-01 to 2026-04-13 |

Robustness tests:

- Bin width: 0.5x, 1.0x, 1.5x, 2.0x baseline.
- Allocation: uniform overlap, close-only, typical price, triangular.
- Anchor: 24h rolling, UTC day, 7-day rolling.
- Entry delay: 1 bar, 2 bars, 5 bars.
- Execution price: optimistic, base, conservative.
- Symbol holdout and year holdout.
- Compare against Donchian breakout, moving-average trend, range reversion, and
  funding-only reversal baselines.

## Recommended Next Crypto Backtests

### Backtest 1: Perp LVN Acceptance Continuation

Reason: best data fit and simplest falsification.

Minimum viable rule:

- Universe: `BTC-PERP`, `ETH-PERP`, `SOL-PERP`, `BNB-PERP`, `XRP-PERP`.
- Profile: rolling prior 24h.
- Volume allocation: uniform overlap.
- LVN: local minimum below 35th percentile of profile-bin volume between two
  local maxima above 65th percentile.
- Entry: 3 of 5 closes beyond LVN plus volume z-score > 1.5.
- Exit: next HVN or 1.25 ATR stop or 8h time stop.

Success threshold:

- Beats Donchian breakout with same holding period after costs.
- Stable across bin widths.
- Net positive in validation and holdout.

### Backtest 2: Funding-Crowding Profile Reversal

Reason: strongest economic story.

Minimum viable rule:

- Universe: all perps with full funding coverage.
- Profile: rolling prior 7 days.
- Funding extreme: rolling 180-day percentile above 90 or below 10.
- Entry: failed auction outside VAH/VAL and close back inside value.
- Exit: POC, opposite value boundary, stop outside rejected extreme.

Success threshold:

- Beats funding-only reversal.
- Does not rely on future funding values.
- Works outside obvious crypto crash windows.

## Source Notes

Local source references:

- `quant-data/docs/consumer/readiness-snapshot.md`
- `quant-data/docs/consumer/reference.md`
- `quant-data/src/quant_data/providers/binance_futures.py`
- Live SQL probes run from `/Users/Season_Yang/Personal/quant-data` on
  2026-06-09.

External context used:

- Binance USD-M Futures API, "Kline/Candlestick Data":
  https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data
