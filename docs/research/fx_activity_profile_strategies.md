# FX Activity-Profile Strategy Research

Date: 2026-06-09

Scope: FX only, focused on strategies that are realistic with the currently
available `quant-data` FX datasets. This is deliberately called
"activity-profile" research, not "true volume-profile" research, because the FX
bar `volume` field is tick count, not consolidated traded notional.

## Executive View

The usable FX edge is not "draw a classic futures volume profile on FX and
trade every POC touch." Our FX data supports a narrower and more defensible
family:

1. **Session activity-profile breakout/rejection** - highest priority. Build
   tick-count profiles over Asia or prior-session balance, then test London/NY
   acceptance or failure using bid/ask costs.
2. **Low-activity return reversal / high-activity continuation** - strongest
   literature link. FX volume research finds that abnormal volume changes the
   return continuation/reversal relationship, but our data is a tick-count proxy,
   so this must be tested as an activity proxy, not copied directly.
3. **Fix-window activity-spike exhaustion** - plausible and testable with
   1-minute data, but must use timezone-aware fixing windows and strict
   bid/ask execution.
4. **Triangular residual plus activity-profile filter** - useful because we
   already have liquid triangles such as `EURUSD`, `USDJPY`, `EURJPY`; activity
   and spread regimes can gate residual reversion.
5. **Activity-spread liquidity regime filter** - probably more valuable as a
   filter for other FX strategies than as a standalone alpha.

The first backtest should be the Asia-to-London activity-profile strategy. It
has the clearest match to our data: 1-minute OHLC tick-count bars, executable
quotes, high quote coverage, and a known FX session structure.

## What FX Data We Have

Live DB checks on 2026-06-09 and generated `quant-data` consumer docs show:

| Dataset | Symbols | Rows | Observed range | Clean/research window | Status | Use |
|---|---:|---:|---|---|---|---|
| `forex_1min` | 18 | 55,526,868 | 2018-01-02 to 2026-04-13 | clean from 2020-01-01 | usable with caveats | Raw OHLC tick-count bars. |
| `forex_1min_with_quotes` | 18 | 42,264,890 | 2020-01-02 to 2026-04-13 | 2020-01-02 to 2026-04-13 | usable with caveats | Preferred research table for execution-aware strategies. |
| `forex_quotes_1min` | 18 | 42,482,639 | 2020-01-02 to 2026-04-24 | 2020-01-02 to 2026-04-24 | usable with caveats | Quote diagnostics; raw crossed/locked caveat applies. |
| `forex_daily` | 18 | 92,619 | 2010-01-03 to 2026-04-13 | clean from 2013-01-01 | usable with caveats | Daily context only. |

Available FX pairs:

`AUDJPY`, `AUDNZD`, `AUDUSD`, `CADJPY`, `EURAUD`, `EURCAD`, `EURCHF`,
`EURGBP`, `EURJPY`, `EURUSD`, `GBPAUD`, `GBPJPY`, `GBPUSD`, `NZDJPY`,
`NZDUSD`, `USDCAD`, `USDCHF`, `USDJPY`.

Preferred loader direction:

- Use `load_fx_bars_with_quotes(..., strict=True)` for executable strategy
  research.
- Use `load_fx_quotes(..., research=True)` only for quote diagnostics.
- Use lower-level raw loaders only when investigating data problems.

## Core Data Caveats

### FX Volume Is Tick Count

`volume` in `forex_1min`, `forex_1min_with_quotes`, and `forex_daily` is tick
count, not notional traded volume. Treat it as a quote/update activity proxy.

Consequences:

- Do not compare FX tick count to crypto or equity volume.
- Do not call it "turnover" or "notional volume" in strategy docs.
- Do not infer capacity from it.
- Normalize by pair, session, and calendar bucket before using it.
- Use it to detect "market is active here" rather than "large notional traded
  here."

### Quotes Are Causal After The Minute

`forex_1min_with_quotes` has:

- `timestamp`: bar-open storage key.
- `available_at`: `timestamp + 1 minute`.
- `bid`, `ask`, `mid`, `spread`, `relative_spread`.
- `has_quote`.

For causal backtests, make decisions only after `available_at`. A strategy that
uses the current minute close, high/low, or quote fields at the bar-open
timestamp is lookahead-biased.

### Raw FX Quotes Need Filtering

The consumer docs flag raw `forex_quotes_1min` crossed/locked rows. Use the
research-filtered quote loader or the joined `forex_1min_with_quotes` table for
strategy work.

### Provider Gaps Exist

The FX caveats include provider-source gaps and a specific NZD-cross gap from
2020-11-16 through 2020-12-11. Do not forward-fill missing FX days into profile
features. Profile windows must know when their source bars are incomplete.

## Actual Joined FX Data Shape

These metrics come from the live `market.forex_1min_with_quotes` table, joined
to `reference.instruments`, queried on 2026-06-09.

### Pair-Level Coverage And Average Costs

`avg_relative_spread_bps` is `AVG(relative_spread) * 10,000` on bars with valid
quotes. It is a crude average, not a trade-level effective spread estimate.

| Pair | Rows | Avg tick count | Has quote ratio | Avg relative spread bps |
|---|---:|---:|---:|---:|
| `AUDJPY` | 2,365,327 | 146.95 | 0.9985 | 2.08 |
| `AUDNZD` | 2,659,772 | 122.47 | 0.9980 | 6.68 |
| `AUDUSD` | 2,321,749 | 115.66 | 0.9870 | 1.66 |
| `CADJPY` | 2,380,677 | 130.70 | 0.9994 | 2.45 |
| `EURAUD` | 2,324,203 | 175.16 | 0.9985 | 1.85 |
| `EURCAD` | 2,295,224 | 161.55 | 0.9991 | 1.59 |
| `EURCHF` | 2,277,885 | 151.93 | 0.9940 | 2.14 |
| `EURGBP` | 2,308,865 | 165.66 | 0.9943 | 2.01 |
| `EURJPY` | 2,328,352 | 208.69 | 0.9895 | 1.19 |
| `EURUSD` | 2,303,892 | 131.84 | 0.9687 | 0.69 |
| `GBPAUD` | 2,359,921 | 168.80 | 0.9994 | 3.20 |
| `GBPJPY` | 2,325,664 | 179.67 | 0.9981 | 1.55 |
| `GBPUSD` | 2,284,530 | 147.14 | 0.9926 | 0.96 |
| `NZDJPY` | 2,628,432 | 110.85 | 0.9991 | 5.99 |
| `NZDUSD` | 2,252,489 | 99.14 | 0.9956 | 2.89 |
| `USDCAD` | 2,284,120 | 111.44 | 0.9939 | 1.31 |
| `USDCHF` | 2,285,447 | 120.75 | 0.9899 | 2.24 |
| `USDJPY` | 2,278,341 | 143.00 | 0.9826 | 0.56 |

Immediate implications:

- `EURUSD`, `USDJPY`, and `GBPUSD` are the cleanest starting points from a
  spread-cost perspective.
- `AUDNZD` and `NZDJPY` have much wider average relative spreads; they should be
  holdout or robustness pairs, not initial proof-of-concept pairs.
- Quote coverage is high overall, but `EURUSD` has the lowest `has_quote_ratio`
  in the joined table at about 96.9%. A strategy must filter `has_quote`.
- Raw average tick count is not comparable across pairs without normalization.

### UTC Session-Level Shape

Session labels used in the query:

- `asia`: 22:00 to 07:00 UTC.
- `london_morning`: 07:00 to 13:00 UTC.
- `ny_overlap`: 13:00 to 17:00 UTC.
- `late_us`: 17:00 to 22:00 UTC.

| Session | Rows | Avg tick count | Has quote ratio | Avg relative spread bps |
|---|---:|---:|---:|---:|
| `asia` | 15,808,493 | 107.92 | 0.9947 | 2.65 |
| `london_morning` | 10,508,143 | 175.70 | 0.9919 | 1.72 |
| `ny_overlap` | 7,059,008 | 214.53 | 0.9918 | 1.61 |
| `late_us` | 8,889,246 | 113.15 | 0.9940 | 3.15 |

Immediate implications:

- Activity and spread are strongly session-dependent in our data.
- A single global tick-count threshold is wrong. Use pair x session or pair x
  minute-of-week normalization.
- NY overlap has the highest average tick count and tight average spread.
- Late US has low activity and the widest average spread, so profile strategies
  should usually avoid initiating new trades there unless the edge specifically
  targets roll/illiquidity effects.

## External Research Context

The external literature is useful, but it must not be copied blindly because
most stronger FX volume papers use actual settlement/platform volume, not our
tick-count proxy.

### Market Structure

BIS Triennial Survey data confirms the scale and OTC structure of FX. The 2025
release reports average OTC FX turnover of $9.6 trillion per day in April 2025
and emphasizes that the survey collects dealer-reported aggregates across
jurisdictions. This is the opposite of centralized futures-style volume: total
FX trading is distributed and not observable from one public exchange feed.

Strategy implication:

- Treat our tick count as an observable local activity measure.
- Do not claim it is total FX turnover.

### Volume Has Predictive Content, But Source Matters

Cespa, Gargano, Riddiough, and Sarno's FX volume work, and related summaries,
find that real OTC FX volume helps predict next-day currency returns. A key
finding is that low abnormal volume is associated with stronger return reversal,
while high abnormal volume weakens or can flip that reversal toward
continuation. Their dataset is CLS-style OTC volume coverage, not price-update
tick count.

Strategy implication:

- A low-activity reversal / high-activity continuation strategy is worth testing.
- The test must be framed as "does our tick-count proxy recover any of this
  behavior?", not "the paper proves our tick-count signal works."

### Intraday Seasonality Is Real

Academic and central-bank work on intraday FX markets documents strong
time-of-day effects in volatility, trading activity, turnover, and spreads.
London and New York overlap tends to be highly active, while low-activity hours
often have wider spreads. The live data query above shows the same broad shape:
NY overlap has higher tick count and tighter average spreads than Asia or late
US.

Strategy implication:

- FX activity features must be deseasonalized.
- Session anchors are economically meaningful, but should be stress-tested with
  DST-aware and shifted windows.

### Activity, Volatility, And Spreads Are Jointly Endogenous

Several FX microstructure papers find that volume/activity and volatility often
rise together, while spreads can tighten in active liquid sessions and widen in
stress or illiquid periods. This means high activity is not automatically good:
it can mean useful liquidity, informed flow, public news, or disorderly markets.

Strategy implication:

- Separate "active and liquid" from "active and stressed" using spread and range
  features.
- A raw high-tick-count breakout rule is under-specified.

## FX Feature Design

### Required Base Columns

From `forex_1min_with_quotes`:

- `symbol`
- `timestamp`
- `available_at`
- `open`, `high`, `low`, `close`
- `volume` as tick count
- `bid`, `ask`, `mid`
- `spread`, `relative_spread`
- `has_quote`

### Derived Activity Features

Use only information available by `available_at`.

Recommended features:

- `tick_count`: raw `volume`.
- `activity_z_pair_session`: robust z-score of tick count by pair and UTC
  session.
- `activity_z_pair_minute_of_week`: robust z-score by pair and minute-of-week,
  preferred once implementation is stable.
- `activity_percentile_60d`: rolling percentile of tick count within same pair
  and session bucket.
- `range_z_pair_session`: robust z-score of high-low or true range by pair and
  session.
- `spread_percentile_60d`: rolling percentile of `relative_spread` by pair and
  session.
- `liquid_activity`: high activity plus normal/tight spread.
- `stressed_activity`: high activity plus wide spread and high range.
- `quiet_balance`: low activity plus narrow range and normal spread.

Use robust statistics:

- Median and MAD, not mean/std, for intraday activity baselines.
- Rolling windows long enough to cover seasonality, e.g. 60 trading days.
- Separate baselines by pair and time bucket.

### Activity Profile Construction

Classic volume profile allocates traded volume by price. Our FX profile should
allocate tick count by price.

Baseline construction:

1. Choose an anchor window: Asia session, prior 24h, prior UTC day, prior
   London session, or rolling 5-day.
2. Define a symbol-specific price grid from rolling ATR or realized range.
3. For each 1-minute bar in the anchor, allocate tick count across bins
   overlapping `[low, high]`.
4. Compute POC, VAH, VAL, HVNs, LVNs, and profile width.
5. Store profile metadata: source rows expected/observed, quote coverage,
   average spread, and whether the window crosses a provider gap.

Robustness allocations:

- Uniform overlap across high-low.
- Close-only tick allocation.
- Typical-price allocation at `(high + low + close) / 3`.
- Triangular allocation centered on typical price.

Do not trust a profile signal unless it is directionally stable across these
allocations.

### Profile Quality Filters

Reject profile windows when:

- Any required day/session has missing bars beyond a threshold.
- `has_quote_ratio` inside the window is below a pair-specific floor.
- Average or median `relative_spread` is in the top decile for that pair/session.
- Profile width is too narrow relative to expected spread costs.
- The window overlaps known provider gaps unless the test explicitly models
  gaps.

## Strategy 1: Asia-To-London Activity-Profile Acceptance/Rejection

Priority: **Highest**

### Thesis

The Asia session often defines an overnight balance area. London/Europe then
tests whether that balance is accepted, rejected, or repriced. A tick-count
profile over Asia can identify accepted prices and thin price zones. Breakouts
through thin zones with high liquid activity can continue; failed breaks back
into value can revert to POC.

### Data Fit

Strong for our FX data:

- Requires only 1-minute OHLC tick-count bars.
- Uses quotes and spreads for execution filters.
- Session dependence is visible in our own data.
- Does not require true notional volume.

Initial pairs:

- `EURUSD`
- `USDJPY`
- `GBPUSD`
- `AUDUSD`
- `USDCAD`

Holdout/expansion pairs:

- `EURJPY`, `EURGBP`, `GBPJPY`, `EURCAD`, `EURAUD`
- Use `AUDNZD`, `NZDJPY`, `NZDUSD`, and wide-spread crosses as robustness tests.

### Rule Variant A: Acceptance Breakout

Anchor:

- Build an Asia profile from 22:00 to 07:00 UTC.
- Compute Asia POC, VAH, VAL, HVNs, LVNs.

Decision window:

- 07:00 to 10:00 UTC for London open/morning.

Long setup:

1. Price starts inside or below Asia value.
2. Price crosses above Asia VAH or a meaningful LVN above POC.
3. At least 2 of the next 3 closes remain outside/above the boundary.
4. `activity_z_pair_session > 1.0` or `activity_percentile_60d > 70`.
5. `spread_percentile_60d < 70`.
6. `has_quote` is true on entry and recent bars.
7. Enter long at next available ask.

Short setup mirrors long setup below VAL or lower LVN.

Exit:

- First target: next HVN or 0.75 to 1.0 Asia range.
- Second target: measured move equal to Asia value width.
- Stop: close back inside Asia value or 0.5 to 1.0 ATR.
- Time stop: exit by 13:00 UTC if neither target nor stop is hit.

### Rule Variant B: Failed Break/Rejection

Long setup:

1. Price breaks below Asia VAL during 07:00 to 10:00 UTC.
2. Break fails: close returns inside Asia value within 15 to 60 minutes.
3. The rejection has high activity, but spread has normalized.
4. Enter long toward Asia POC.

Short setup mirrors long setup above VAH.

Exit:

- Target 1: Asia POC.
- Target 2: opposite side of Asia value.
- Stop: outside rejected extreme.
- Time stop: exit by NY overlap if POC is not reached.

### Why This Could Work

It combines three independently plausible facts:

- FX activity is session-structured.
- Activity and spreads vary by session in our own data.
- Failed auctions around prior balance levels are mechanically testable with
  bid/ask costs.

### Falsifiers

Reject or demote this strategy if:

- It does not beat a plain Asia range breakout/reversal baseline.
- It only works at mid and fails at bid/ask.
- It is not stable when session boundaries shift by +/-30 minutes or +/-1 hour.
- It fails on `EURUSD`, `USDJPY`, and `GBPUSD` but works only on high-spread
  crosses.
- Profile features add no value beyond prior high/low and range width.

## Strategy 2: Low-Activity Reversal / High-Activity Continuation

Priority: **High**

### Thesis

FX volume literature suggests that return continuation/reversal depends on
abnormal volume. In our data, tick count may proxy for market activity. The
testable hypothesis is:

- After a directional move on low activity, returns are more likely to reverse.
- After a directional move on high liquid activity, returns are more likely to
  continue.
- After a directional move on high stressed activity, the behavior is ambiguous
  and should be separately modeled.

### Data Fit

Moderate. The hypothesis maps well to our bars, but our `volume` is tick count,
not CLS or platform notional volume.

### Rule Skeleton

Horizon variants:

- Intraday: 1h return predicts next 1h to 4h return conditional on activity.
- Session: Asia return predicts London morning return conditional on Asia
  activity.
- Daily: prior 24h return predicts next 24h return conditional on activity.

Features:

- `past_return`
- `past_activity_z`
- `past_range_z`
- `past_spread_percentile`
- `past_return * past_activity_z`

Signal:

- If `past_return` is positive and activity is low, short for reversal.
- If `past_return` is negative and activity is low, long for reversal.
- If `past_return` is positive and liquid activity is high, long for
  continuation.
- If `past_return` is negative and liquid activity is high, short for
  continuation.
- If stressed activity is high, either skip or model separately.

### Why This Could Work

This is the most direct way to test whether our tick-count proxy contains some
of the information documented in real FX volume literature. It also avoids
overfitting complex profile shapes before proving that activity has predictive
content.

### Falsifiers

Reject if:

- The interaction term between return and activity is unstable across pairs and
  time periods.
- Low-activity reversal does not beat plain short-horizon reversal.
- High-activity continuation does not beat plain momentum.
- Results are dominated by one pair or by 2020 stress windows.
- Results vanish when activity is normalized by minute-of-week rather than
  session.

## Strategy 3: Fix-Window Activity-Spike Exhaustion

Priority: **Medium**

### Thesis

FX fixing windows concentrate benchmark-related trading and hedging flows.
Activity spikes around fixes can generate short-lived volatility and sometimes
post-fix reversal. Our 1-minute data can test whether tick-count spikes plus
spread normalization identify exhaustion around fixes.

### Windows To Model

Use timezone-aware calendars:

- Tokyo fix around 09:55 Tokyo time.
- Frankfurt/ECB-style window around European afternoon.
- London 4pm fix around 16:00 London time.
- US macro-release windows around common 08:30 and 10:00 New York times as
  separate event windows, not the same as fixes.

Do not hard-code all of these as static UTC times without DST handling.

### Rule Skeleton

For each pair and event window:

1. Estimate normal activity and spread for the same event minute bucket.
2. Identify activity spike: tick count > 90th or 95th percentile.
3. Classify price move into the event as extended or normal.
4. Require spread to normalize after the event before entering.
5. Fade post-event exhaustion toward pre-event POC or mid-window POC.

Candidate pairs:

- London fix: `EURUSD`, `GBPUSD`, `USDJPY`, `EURGBP`.
- Tokyo fix: `USDJPY`, `EURJPY`, `AUDJPY`, `NZDJPY`.
- US macro windows: `EURUSD`, `USDJPY`, `GBPUSD`, `USDCAD`.

### Why This Could Work

The strategy targets scheduled liquidity concentration rather than generic
chart levels. Activity spikes are expected around these windows; the edge, if
any, is whether extreme activity plus failed continuation predicts reversal.

### Falsifiers

Reject if:

- Results are not materially better than a simple time-of-day reversal.
- Entry before spread normalization is required for profitability.
- DST-correct windows and static UTC windows give contradictory signs.
- The effect disappears after excluding known macro-release windows.

## Strategy 4: Triangular Residual With Activity-Profile Filter

Priority: **Medium**

### Thesis

Triangular FX residuals can mean-revert when price relationships stretch, but
not every residual is tradable. Activity and spread profiles can identify when
the residual is likely to close versus when a leg is repricing on real flow.

### Data Fit

Good. We have multiple tradable triangles:

- `EURUSD`, `USDJPY`, `EURJPY`
- `GBPUSD`, `USDJPY`, `GBPJPY`
- `AUDUSD`, `USDJPY`, `AUDJPY`
- `EURGBP`, `GBPUSD`, `EURUSD`

### Rule Skeleton

Base residual:

- Compute synthetic cross from two legs and compare to direct cross.
- Use mid for signal construction, bid/ask for execution/cost modeling.

Activity filter:

- If residual widens on low or normal activity and normal spread, favor
  reversion.
- If residual widens on high liquid activity concentrated in one leg, skip or
  allow continuation.
- If residual widens on high stressed activity and wide spreads, skip.

Profile filter:

- Direct cross outside prior session value while synthetic legs remain inside
  value: mean-reversion candidate.
- All legs accept outside value in coherent direction: skip reversion.

### Why This Could Work

This is not pure volume-profile trading. It uses activity profiles to improve a
relative-value signal that already has an economic constraint.

### Falsifiers

Reject if:

- Activity filters reduce trade count but not net expectancy.
- The residual signal is profitable without activity filters and filters add no
  incremental value.
- Results require crossing three bid/ask spreads too frequently.
- PnL depends on synthetic prices that are not executable after realistic costs.

## Strategy 5: Activity-Spread Liquidity Regime Filter

Priority: **Medium as a filter, Low as standalone alpha**

### Thesis

The same activity spike can mean different things depending on spread:

- High activity + tight spread: liquid information flow, breakout trades are
  more plausible.
- High activity + wide spread: stress or thin liquidity, avoid naive breakout
  entries.
- Low activity + wide spread: avoid trading.
- Low activity + tight spread: range/reversion more plausible.

### Rule Skeleton

Build a regime classifier by pair/session:

| Regime | Activity | Spread | Use |
|---|---|---|---|
| Liquid active | high | normal/tight | Allow continuation and acceptance trades. |
| Stressed active | high | wide | Avoid or demand wider stops; test reversal separately. |
| Quiet liquid | low | normal/tight | Allow mean reversion, not breakout. |
| Illiquid quiet | low | wide | Avoid initiating trades. |

Apply this filter to:

- Asia-to-London profile trades.
- Short-horizon momentum/reversal tests.
- Triangular residual trades.

### Falsifiers

Reject if:

- The filter only removes trades and does not improve net expectancy,
  drawdown, or cost-adjusted Sharpe.
- Regime labels are unstable across pairs.
- Spread percentiles are contaminated by quote gaps or provider artifacts.

## Lower-Priority Ideas

### Prior-Day POC/Value Reversion

Use prior-day or prior-session tick-count profile levels and fade first tests of
POC/VAH/VAL when spreads are normal.

Reason to keep it low priority:

- Major FX pairs are efficient.
- This may reduce to ordinary range reversion.
- It must beat a simple prior-day high/low/close baseline.

### Multi-Pair USD Activity Shock

Compute a USD-wide activity shock from USD pairs and trade lagged responses in
crosses. This may be interesting later, but it is too easy to overfit before
the simpler pair/session effects are tested.

## What Not To Build

Do not build:

- True FX notional volume-profile strategies. We do not have consolidated
  notional volume.
- Footprint delta, order-flow imbalance, or aggressive-buyer/seller strategies.
  We do not have signed trades.
- Sub-minute scalping systems from 1-minute bars.
- Raw tick-count threshold strategies without pair/session normalization.
- Strategies that assume `EURUSD` tick count is comparable to `AUDNZD` tick
  count.
- Strategies that require mid-price fills to be profitable.

## Recommended First FX Backtest

### Asia-To-London Activity-Profile Acceptance/Rejection

Reason: best data fit and cleanest falsification.

Minimum viable configuration:

- Pairs: `EURUSD`, `USDJPY`, `GBPUSD`, `AUDUSD`, `USDCAD`.
- Data: `forex_1min_with_quotes`, strict loader.
- Profile: Asia session 22:00 to 07:00 UTC.
- Decision window: 07:00 to 10:00 UTC.
- Entry variants:
  - Acceptance breakout through VAH/VAL or LVN.
  - Failed breakout back into value.
- Cost model:
  - Long entry at ask, long exit at bid.
  - Short entry at bid, short exit at ask.
  - Require `has_quote`.
- Filters:
  - Activity z-score by pair/session.
  - Spread percentile by pair/session.
  - Profile completeness.

Baselines:

- Plain Asia range breakout.
- Plain Asia range failed-break reversal.
- Same rules without activity profile.
- Same rules with prior high/low instead of VAH/VAL/LVN.

Success threshold:

- Positive net expectancy after bid/ask costs in validation and holdout.
- Beats the plain Asia range baselines.
- Stable under session boundary shifts of +/-30 minutes and +/-1 hour.
- Stable under profile bin width changes.
- Not dependent on wide-spread crosses.

## Backtest Contract

### Splits

Use the joined quote dataset's research window:

| Split | Dates |
|---|---|
| Development | 2020-01-02 to 2022-12-31 |
| Validation | 2023-01-01 to 2024-12-31 |
| Holdout | 2025-01-01 to 2026-04-13 |

Pair holdouts:

- Major USD holdout: leave out one of `EURUSD`, `USDJPY`, `GBPUSD`.
- Commodity pair holdout: leave out `AUDUSD` or `USDCAD`.
- Cross holdout: leave out `EURJPY` or `EURGBP`.

### Required Cost Handling

For every trade:

- Long entry: ask.
- Long exit: bid.
- Short entry: bid.
- Short exit: ask.
- Skip if `has_quote` is false.
- Apply extra slippage sensitivity as a fraction of spread.

Reject any strategy that only works at mid.

### Required Robustness Tests

For every FX candidate:

- Session windows shifted by +/-30 minutes and +/-1 hour.
- DST-aware windows versus fixed UTC windows where relevant.
- Activity normalization by session versus minute-of-week.
- Profile bin width: 0.5x, 1.0x, 1.5x, 2.0x.
- Profile allocation: uniform overlap, close-only, typical price, triangular.
- Exclude known provider-gap windows.
- Exclude top macro-event days if a macro calendar is later added.
- Pair holdout and year holdout.

### Metrics

Primary:

- Net return after bid/ask and slippage assumptions.
- Net Sharpe and Sortino.
- Max drawdown and time under water.
- Average trade expectancy.
- Profit factor.
- Trades per pair/session.

FX-specific:

- Entry spread percentile.
- Average spread paid per trade.
- Performance by pair and session.
- Performance by activity-spread regime.
- Profile completeness rate.
- POC hit rate for rejection trades.
- Next-HVN hit rate for acceptance trades.

## Implementation Notes For `quant_strategies`

Keep the strategy module pure:

- No data loading inside the strategy file.
- No artifact writing inside the strategy file.
- No autonomous loops.
- Put thesis, observables, rule, and falsifier in the module docstring.
- Run experiments through `src/quant_strategies/runner/` with TOML configs under
  `runs/`.

Suggested implementation order:

1. Prototype feature generation in runner/evaluation-side code, not inside a
   strategy module.
2. Implement a baseline Asia range breakout/reversal.
3. Add activity normalization and spread filters.
4. Add activity-profile VAH/VAL/LVN features.
5. Only then promote a pure strategy module.

Potential strategy module name:

- `fx_session_activity_profile_rejection.py`

Required docstring fields:

- Source/provenance: this research note plus the FX volume/activity papers in
  the source notes.
- Market rationale: session-structured FX liquidity and activity.
- Required observables: OHLC, tick count, bid/ask, relative spread, `has_quote`,
  `available_at`.
- Executable rule: acceptance/rejection around session value.
- Proxy/data assumptions: tick count is activity, not notional volume.
- Falsifier: must beat Asia range baseline after bid/ask costs.

## Open Questions

Before implementation, decide:

- Should the first prototype use fixed UTC session windows or timezone/DST-aware
  market windows? Recommendation: fixed UTC for first proof, DST-aware as a
  required robustness check.
- Should profile bins be ATR-based or pip-based? Recommendation: ATR-based
  first, pip-based as a robustness check.
- Should we add a macro/fix calendar before first backtest? Recommendation: no
  for Asia-to-London; yes before serious fix-window research.
- Should we include all 18 pairs at once? Recommendation: no. Start with the
  five lower-spread majors, then expand.

## Source Notes

Local sources:

- `quant-data/docs/consumer/readiness-snapshot.md`
- `quant-data/docs/consumer/reference.md`
- Live SQL probes run from `/Users/Season_Yang/Personal/quant-data` on
  2026-06-09.

External sources:

- BIS, "OTC foreign exchange turnover in April 2025":
  https://www.bis.org/statistics/rpfx25_fx.htm
- Cespa, Gargano, Riddiough, and Sarno, "Foreign Exchange Volume":
  https://ideas.repec.org/a/oup/rfinst/v35y2022i5p2386-2427..html
- Sarno et al., "The value of volume in exchange rates":
  https://www.norges-bank.no/contentassets/619c8b75e1ed4ba691e8ad6a006855e6/21-sarno-the-value-of-volume-in-exchange-rates.pdf
- Ito and Hashimoto, "Intra-day Seasonality in Activities of the Foreign
  Exchange Markets":
  https://www.nber.org/system/files/working_papers/w12413/w12413.pdf
- Reserve Bank of Australia, "Intraday Currency Market Volatility and Turnover":
  https://www.rba.gov.au/publications/bulletin/2007/dec/pdf/bu-1207-1.pdf
- Federal Reserve IFDP, "Transmission of Volatility and Trading Activity in the
  Global Interdealer Foreign Exchange Market":
  https://www.federalreserve.gov/pubs/ifdp/2006/863/ifdp863.htm
- Galati, "Trading volumes, volatility and spreads in FX markets":
  https://www.bis.org/publ/bppdf/bispap02k.pdf

Bottom line: real FX volume has documented information content, but our local
FX field is tick-count activity. The realistic strategy path is to use activity
profiles plus executable quotes, not to pretend we have centralized futures-like
volume-at-price.
