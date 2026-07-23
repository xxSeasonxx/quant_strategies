# Crypto Price/Volume Structure: Volatility, Seasonality, and Trend

Date: 2026-07-22

Scope: crypto strategies built **purely from price/volume structure** —
volatility targeting/scaling, seasonality/calendar/time-of-day, intraday
mean-reversion, trend/breakout, volatility-breakout regime switching, and
inverse-vol multi-coin allocation. Buildable on our engine and data only
(1-min OHLCV + `num_trades`, `funding_8h`, spot-perp basis). Sibling briefs:
`crypto_perp_volume_profile_strategies.md`, `fx_activity_profile_strategies.md`.

## Executive Summary

The strongest, most cost-survivable ideas here are **overlays and low-turnover
portfolio construction, not fresh alpha sources.** (1) **Volatility scaling /
vol-targeting** is the single best-supported effect: inverse-realized-vol
position sizing reliably lifts Sharpe and cuts drawdowns for both single-asset
Bitcoin trend and cross-sectional crypto momentum, and our engine already has
`calibrate_vol` to express it cheaply (monthly-ish turnover). (2) **Trend /
time-series momentum** on daily-aggregated bars (10-40d MA family, Donchian
20/55) is robust across a decade and rebalances slowly, so it clears costs; it
is a regime harvester, not a predictor, and pays for it in whipsaw during
chop. (3) **Inverse-vol / risk-parity multi-coin allocation** is a near-free
baseline portfolio with monthly rebalance. Calendar/seasonality and 1-min
intraday mean-reversion are **fragile and mostly cost-fatal**: the honest
finding is that day-of-week and month effects have decayed to noise post-2017,
and genuine intraday structure (quarter-hour bursts, tea-time volatility)
lives at sub-minute horizons we cannot trade or dies to fees at 1-min. The one
seasonality effect worth a cautious, low-turnover test is the **overnight
22:00-23:00 UTC window** as an entry-timing filter, not a standalone strategy.
Costs are enforced by our engine, so treat every intraday/calendar claim as
guilty-until-proven and demand the edge clears realistic taker fees + slippage.

---

## Family 1 — Volatility targeting / vol-managed portfolios / vol-scaled momentum

### (a) Thesis + rationale
Scale exposure inversely to *predicted* realized volatility. Moreira & Muir
(2017) show that because changes in volatility are **not** offset by
proportional changes in expected return, cutting risk when vol is high and
adding when vol is low raises the Sharpe ratio and produces alpha. Crypto is an
ideal habitat: realized vol is highly persistent (clusters), forecastable from
recent realized vol, and momentum/trend books suffer violent crashes that
vol-scaling truncates. In crypto specifically the improvement comes as much
from **higher returns** as from lower risk (unlike equities, where it is mostly
downside mitigation) — crypto lacks the extended momentum-crash episodes that
make naive vol-scaling backfire in equity momentum.

### (b) Exact construction using our fields
- Realized vol per symbol: `rv_t = std(log(close_t / close_{t-1}))` over a
  trailing window of `N` 1-min bars, annualized. Use bar-count windows: 1 day =
  1440 bars, so a 30-day window = 43,200 bars; or aggregate to hourly/daily
  closes first (cheaper, less noisy) and compute vol on those.
- Target weight: `w_t = base_signal_t * (target_vol / rv_t)`, capped at the
  engine leverage ceiling. `base_signal_t` is the underlying book (e.g. a trend
  sign, or a long-only 1). This is exactly what the engine's `calibrate_vol`
  vol-targeting does — prefer expressing target vol through the operator rather
  than hand-rolling in `strategy.py`.
- Two flavors: (i) **vol-target overlay** on a fixed book (long-only BTC or a
  trend book), (ii) **vol-scaled momentum**: `sign(mom) * (target_vol / rv)`.

### (c) Target-book expression, cadence, turnover
Signed weight per instrument; `0` = flat. Rebalance the vol scalar on a slow
clock (daily or every 4-8h) — do **not** re-scale every minute or turnover and
cost drag explode. Turnover is low-to-moderate: the scalar moves smoothly with
persistent vol, so realized turnover is dominated by vol regime shifts, not
noise. Expected: single-digit-to-~20 round-trips/year for the overlay.

### (d) Required datasets
`crypto_perp_1min` (close) is sufficient. `funding_8h` folds in as financing on
the perp leg automatically. No basis, no spot needed.

### (e) Bounded param set for autoresearch
- `vol_lookback_bars` ∈ {daily-equivalent 10, 20, 30, 60 days}
- `target_annual_vol` ∈ {0.20, 0.40, 0.60, 0.80} (crypto runs hot)
- `rebalance_bars` ∈ {240 (4h), 480 (8h), 1440 (daily)}
- `vol_estimator` ∈ {close-to-close std, EWMA λ≈0.94}

### (f) Edge / decay / capacity
Robust and slow-decaying — it is a risk-transformation, not an anomaly, so it
does not get arbitraged away. Reported crypto results: risk-managed momentum
lifted weekly return ~3.18%→3.47% and annualized Sharpe ~1.12→1.42; other work
reports vol-scaling **nearly doubling** momentum Sharpe while cutting max
drawdown, skew, and kurtosis. Capacity is high (liquid majors, slow rebalance).
Main risk: vol-targeting is *pro-cyclical de-risking* — it can sell the bottom
after a vol spike and miss the sharp V-recovery crypto is famous for.

### (g) Falsifiers
- OOS Sharpe of the vol-scaled book ≤ the unscaled book (the ScienceDirect
  "On the performance of volatility-managed portfolios" critique found many
  factors' timing gains vanish OOS — test this directly).
- Turnover-adjusted return after enforced costs < the static book.
- Drawdown not reduced vs unscaled in the crypto sample.

### (h) Citations
- Moreira, A. & Muir, T. (2017). *Volatility-Managed Portfolios.* Journal of
  Finance. NBER WP 22208: https://www.nber.org/system/files/working_papers/w22208/w22208.pdf
  · SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2659431
- Cederburg, S. et al. (2020). *On the performance of volatility-managed
  portfolios.* Journal of Financial Economics:
  https://www.sciencedirect.com/science/article/abs/pii/S0304405X2030132X
- *Cryptocurrency market risk-managed momentum strategies* (2025). Finance
  Research Letters: https://www.sciencedirect.com/science/article/abs/pii/S1544612325011377
- *Cryptocurrency momentum has (not) its moments* (2025). Financial Markets and
  Portfolio Management: https://link.springer.com/article/10.1007/s11408-025-00474-9

---

## Family 2 — Seasonality / calendar / time-of-day (incl. funding-settlement hour)

### (a) Thesis + rationale
Recurrent calendar structure (day-of-week, weekend, time-of-day, turn-of-month)
should exist because crypto liquidity is tethered to traditional-finance
working hours (London/NY sessions) despite 24/7 trading, and because 8h funding
settlements create mechanical order flow at fixed UTC stamps. Behavioral story:
retail/institutional attention and TradFi liquidity cycles imprint on a market
that never closes.

### (b) Exact construction using our fields
All timestamps are UTC. Derive from the bar index only — no extra data:
- **Time-of-day**: `hour = floor(minute_of_day / 60)`. Long the historically
  strong hour window (**22:00-23:00 UTC**), flat otherwise.
- **Day-of-week / weekend**: `dow = weekday(timestamp)`; weekend flag for
  Sat/Sun. Tilt exposure by realized dow return sign (in-sample dangerous —
  see falsifiers).
- **Funding-settlement hour**: settlements at **00:00 / 08:00 / 16:00 UTC**
  (from `funding_8h` stamps). Documented microstructure spikes ~2h *after*
  each settlement (02:00 / 10:00 / 18:00 UTC). Build a filter: reduce/flatten
  exposure into the 10-min window around settlement, or fade the post-settlement
  spread spike (research-only; likely sub-minute).
- **Turn-of-month**: flag last-2 / first-3 calendar days.

### (c) Target-book expression, cadence, turnover
Time-of-day = 1 entry + 1 exit per day = ~500 round-trips/year on a 2h hold.
That is **high turnover for a tiny per-trade edge (~0.07%/hr)** — cost realism
is the whole game. Day-of-week/weekend tilts are low turnover (weekly). Prefer
using calendar effects as **entry-timing filters layered on a book that already
has an edge**, not standalone books.

### (d) Required datasets
`crypto_perp_1min` (timestamps + close); `funding_8h` for settlement stamps.

### (e) Bounded param set
- `entry_hour_utc` ∈ {21, 22, 23} ; `hold_hours` ∈ {1, 2, 3}
- `settlement_flat_window_min` ∈ {5, 10, 15}
- `weekend_scalar` ∈ {0.0, 0.5, 1.0}

### (f) Edge / decay / capacity — **be candid: mostly fragile**
- **Day-of-week / Monday effects: decayed.** A significant positive Monday
  effect does not persist post-2015; "the evidence on seasonality is not
  robust." At hourly frequency, weekly patterns *evaporate* except one spike
  (Sunday 23:00-00:00 UTC, a US-reopen artifact).
- **Weekend effect: weak.** No reliable return gap; only lower weekend vol/volume.
- **Time-of-day**: 22:00-23:00 UTC is the most economically significant window;
  a long-only overnight book returned ~33%/yr, Sharpe 1.58, MaxDD -34% over
  2015-2021 — but **long-only and fails in bear markets**, and no costs reported.
- **Turn-of-month / January**: real in-sample, conditional and unreliable OOS;
  now swamped by ETF/macro flows. Deprioritize.
- Capacity fine (majors), but the edges are small and attention-decaying.

### (g) Falsifiers
- The hour/day effect is insignificant or flips sign in a held-out later
  sub-sample (e.g. 2023-2026) — strong evidence of decay.
- Edge disappears after enforced taker fees + slippage on the required turnover.
- Effect concentrates in one coin or one year (not pervasive → likely mining).

### (h) Citations
- *Bitcoin and the day-of-the-week effect* (Caporale & Plastun). Finance
  Research Letters: https://www.sciencedirect.com/science/article/abs/pii/S1544612317307894
- *Revisiting seasonality in cryptocurrencies* (2024). FRL:
  https://www.sciencedirect.com/science/article/pii/S1544612324004598
- *Calendar effects on returns, volatility and higher moments: Evidence from
  crypto markets* (2025): https://www.sciencedirect.com/science/article/pii/S1062940825000816
- *Bitcoin's Weekend Effect: Returns, Volatility, and Volume (2014-2024)*:
  https://ojs.bbwpublisher.com/index.php/PBES/article/view/11691
- Padyšák, M. & Vojtko, R. *Seasonality, Trend-following, and Mean reversion in
  Bitcoin.* SSRN 4081000: https://ssrn.com/abstract=4081000 (via Quantpedia:
  https://quantpedia.com/strategies/intraday-seasonality-in-bitcoin)
- *Are Day-of-the-Week Effects in Cryptocurrencies Real? Intraday Evidence*
  (mlquants): https://mlquants.substack.com/p/are-day-of-the-week-effects-in-cryptocurrencies
- *Temporal Dynamics of Market Microstructure in Crypto Perpetual Futures*
  (MDPI 2026): https://www.mdpi.com/2227-7072/14/5/103

---

## Family 3 — Intraday mean-reversion / range strategies on 1-min bars

### (a) Thesis + rationale
Short-horizon overreaction: price that stretches far from a rolling mean snaps
back as liquidity providers fade the move. Range/opening-range analogs: fade
excursions outside a recent high-low band. Economic basis is inventory/liquidity
provision, which is real — but the *compensation* for it is thin and accrues to
whoever is fastest and cheapest.

### (b) Exact construction using our fields
- **Z-score reversion**: `z = (close - SMA_n) / std_n` on 1-min or resampled
  bars; enter short when `z > +k`, long when `z < -k`; exit on `z → 0`.
- **Bollinger touch**: fade a touch of the `m`-sigma band back toward the mean.
- **Range fade (24/7 opening-range analog)**: define a rolling `w`-hour
  high/low; fade breaks that fail to hold, target the midpoint.
- Optional confirmation: `num_trades` or volume z-score (avoid fading a
  genuine volume-backed breakout).

### (c) Target-book expression, cadence, turnover
**Very high turnover** — the killer. On true 1-min signals this is dozens to
hundreds of round-trips/day. Our engine fills at `close` with
`entry_lag_bars >= 1`, so you eat at least one bar of adverse selection plus
enforced taker fee + slippage on every trade. Prefer coarser bars (15m-4h) to
cut turnover; the honest literature verdict is that 1-min reversion is
**dominated by microstructure noise and dies after costs**.

### (d) Required datasets
`crypto_perp_1min` (OHLC, volume, num_trades). No extra data.

### (e) Bounded param set
- `bar_agg` ∈ {1m, 5m, 15m, 60m} ; `sma_lookback` ∈ {20, 50, 100} bars
- `entry_z` ∈ {1.5, 2.0, 2.5, 3.0} ; `exit_z` ∈ {0.0, 0.5}
- `vol_filter` ∈ {off, ADX<20 / low-vol regime only}

### (f) Edge / decay / capacity — **honest: mostly cost-fatal at 1-min**
A 0.4-0.5% bounce routinely *vanishes* after entry fee + exit fee + spread +
slippage. Practitioner backtests show z-score/Bollinger reversion is profitable
**only in ranging regimes** (profit factor ~1.6 at ADX<20) and strongly
negative in trends (PF ~-0.7 at ADX>30) — so it *requires* a regime filter
(Family 5). Capacity is limited by the small per-trade edge vs cost. Genuine
sub-minute predictability exists (quarter-hour bursts) but concentrates in the
first 10 seconds and at 15-min frequency — **not capturable on 1-min bars with
`entry_lag_bars >= 1`.**

### (g) Falsifiers
- Post-cost Sharpe ≤ 0 at 1-min (expected); only survives at ≥15m + regime filter.
- Edge vanishes once `entry_lag_bars` and realistic slippage are applied.
- Profitability is entirely explained by a ranging-regime subsample.

### (h) Citations
- Kim, C. & Hansen, P. R. (2026). *The Quarter-Hour Effect: Periodic
  Algorithmic Trading and Return Predictability in Cryptocurrency Futures.*
  arXiv 2607.09426: https://arxiv.org/html/2607.09426v2
- *Decomposing cryptocurrency high-frequency price dynamics into recurring and
  noisy components* (2023). arXiv 2306.17095: https://arxiv.org/pdf/2306.17095
- *Bollinger Band mean reversion* (crosstrade.io):
  https://crosstrade.io/learn/trading-strategies/bollinger-mean-reversion
- *Mean Reversion Trading: How I Profit from Crypto Overreactions* (stoic.ai):
  https://stoic.ai/blog/mean-reversion-trading-how-i-profit-from-crypto-market-overreactions/

---

## Family 4 — Trend / breakout / moving-average / Donchian

### (a) Thesis + rationale
Time-series momentum: assets that have risen keep rising over weeks-to-months,
driven by under-reaction to information and herding, and crypto is the highest-
volatility, most retail-driven, most trend-persistent liquid market available.
Channel breakout (Donchian) is the same edge expressed as "new `n`-bar high →
go long." Crypto's 24/7 tape is an *advantage*: no weekend gaps you cannot
trade — signal and entry arrive together.

### (b) Exact construction using our fields
- **MA crossover**: aggregate 1-min → daily closes; long when
  `SMA_fast > SMA_slow`, flat/short otherwise. Grayscale's robust pair is
  ~10-30d fast vs ~40-100d slow.
- **Time-series momentum**: `sign(close_t / close_{t-k} - 1)`, `k` in days.
- **Donchian breakout**: long when `close > max(high, last n bars)`; exit on
  `close < min(low, last m bars)` (Turtle 20/55 or 20/20).
- Pair with Family 1 vol-scaling for position sizing (best-documented combo).

### (c) Target-book expression, cadence, turnover
Signed weight, `0` = flat. **Low turnover** — daily/weekly rebalance, a handful
to a few dozen signal flips per year → clears costs comfortably. This is the
most cost-friendly active family here.

### (d) Required datasets
`crypto_perp_1min` (close/high/low). `funding_8h` as financing. Multi-coin
version uses the 25-perp universe for cross-sectional momentum ranking.

### (e) Bounded param set
- `fast_days` ∈ {10, 20, 30} ; `slow_days` ∈ {50, 100, 200}
- `donchian_entry` ∈ {20, 55} ; `donchian_exit` ∈ {10, 20}
- `tsmom_lookback_days` ∈ {30, 60, 90} ; `allow_short` ∈ {true, false}

### (f) Edge / decay / capacity
Robust across a decade and multiple bull/bear cycles. Grayscale: a 20/100 daily
crossover returned ~116%/yr, Sharpe 1.7, vs buy-and-hold ~110%/yr, Sharpe 1.3 —
the win is **drawdown reduction and Sharpe, not raw return**. Donchian 20/55
positive through 2017/2020-21 bulls and 2018/2022 bears; win rate only 30-40%
with winners 3-5x losers (fat right tail). Capacity high on majors. Decay risk:
as crypto institutionalizes, trend persistence may compress; and **no reliable
intraday trend edge exists for BTC spot** — keep the trend clock at daily+.
Cross-sectional momentum reportedly fits crypto better than pure time-series.

### (g) Falsifiers
- Whipsaw in a chop-heavy held-out window drives post-cost Sharpe below
  buy-and-hold.
- Performance concentrated in one mega-trend (2020-21) and absent elsewhere.
- Intraday (sub-daily) trend variants show no edge (expected).

### (h) Citations
- Grayscale Research. *The Trend is Your Friend: Managing Bitcoin's Volatility
  with Momentum Signals:*
  https://research.grayscale.com/reports/the-trend-is-your-friend-managing-bitcoins-volatility-with-momentum-signals
- *A Decade of Evidence of Trend Following Investing in Cryptocurrencies* (2020).
  arXiv 2009.12155: https://arxiv.org/pdf/2009.12155
- *Dynamic time series momentum of cryptocurrencies* (2021). North American
  Journal of Economics and Finance:
  https://www.sciencedirect.com/science/article/abs/pii/S1062940821000590
- Rohrbach, J., Suremann, S. & Osterrieder, J. *Momentum and Trend Following
  Trading Strategies for Currencies and Bitcoin.* SSRN 2949379:
  https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID2949379_code2672176.pdf?abstractid=2949379

---

## Family 5 — Volatility breakout / regime switching (trend in high vol, revert in low vol)

### (a) Thesis + rationale
The market alternates between trending and mean-reverting regimes; a single
static rule loses in the wrong regime. A realized-vol / trend-strength filter
selects which sub-model to run: **trend-follow when volatility/trend-strength is
high, mean-revert when it is low.** This is the meta-layer that rescues Family 3
(reversion only in low-vol/ranging) and de-risks Family 4 (trend only when
trending). Volatility breakout proper: enter on a range expansion (today's move
> `k` × recent ATR).

### (b) Exact construction using our fields
- **Regime signal**: realized vol z-score, or ADX-style trend strength, or the
  ratio `|close_t - close_{t-n}| / sum(|Δclose|)` (efficiency ratio) over `n`
  bars. High ratio → trending; low → ranging.
- **Switch**: `if regime == trend: book = Donchian/MA book; else: book =
  z-score reversion book`. Or a soft blend of the two signed books.
- **Vol breakout**: long when `close > open + k*ATR_n` (and symmetric short).

### (c) Target-book expression, cadence, turnover
Turnover = the union of the two sub-books, gated by regime → **moderate**,
dominated by regime-flip frequency. Rebalance the regime label on a slow clock
(daily/4h) to avoid flip-flopping and cost churn.

### (d) Required datasets
`crypto_perp_1min` (OHLC for ATR + vol). No extra data.

### (e) Bounded param set
- `regime_lookback_days` ∈ {10, 20, 30}
- `regime_threshold` (ADX or efficiency-ratio) ∈ {2-3 discrete cuts}
- `atr_k` ∈ {1.0, 1.5, 2.0} ; `blend` ∈ {hard switch, soft}

### (f) Edge / decay / capacity
Conceptually strong and it is the correct home for reversion, but **added
degrees of freedom = overfitting risk**; the regime threshold is the most
tempting parameter to curve-fit. Practitioner blends (50/50 momentum + reversion)
report Sharpe ~1.71 / ~56%/yr, but that is in-sample and pre-cost. Treat the
regime switch as a *filter that must earn its complexity*: it should beat both
pure sub-books OOS or be cut.

### (g) Falsifiers
- The regime-switched book does not beat the better of {pure trend, pure
  reversion} out-of-sample after costs → complexity unjustified.
- Result is sensitive to the exact `regime_threshold` (unstable → overfit).

### (h) Citations
- *Systematic Crypto Trading Strategies: Momentum, Mean Reversion & Volatility
  Filtering* (Plotnik, Medium):
  https://medium.com/@briplotnik/systematic-crypto-trading-strategies-momentum-mean-reversion-volatility-filtering-8d7da06d60ed
- *Market Regimes Explained: Build Winning Trading Strategies* (LuxAlgo):
  https://www.luxalgo.com/blog/market-regimes-explained-build-winning-trading-strategies/
- Moreira & Muir (2017), as above (vol-timing is the theoretical anchor).

---

## Family 6 — Risk parity / inverse-vol multi-coin allocation (baseline portfolio)

### (a) Thesis + rationale
Weight each coin by the inverse of its recent volatility so every asset
contributes equal risk, rather than letting the most volatile coin dominate.
Optimal if assets share similar Sharpe and similar pairwise correlations — a
reasonable prior across a basket of large-cap perps. This is the natural
**baseline portfolio** and a benchmark every active idea above must beat.

### (b) Exact construction using our fields
- Per-coin realized vol `rv_i` over trailing `N` days (daily closes).
- Weight `w_i = (1/rv_i) / Σ_j (1/rv_j)`, long-only (or apply a shared trend
  sign per coin for a directional version). Scale the whole book to a target
  portfolio vol via the engine.
- Universe: liquid subset of the 25 perps (exclude thin/aliased names or handle
  multipliers like PEPE carefully).

### (c) Target-book expression, cadence, turnover
Signed weights summing across the basket; `0` for excluded coins. **Monthly (or
weekly) rebalance → very low turnover → near-free of cost drag.** The cleanest,
most capacity-friendly construction in this brief.

### (d) Required datasets
`crypto_perp_1min` (closes for all universe coins). `funding_8h` financing.

### (e) Bounded param set
- `vol_lookback_days` ∈ {20, 30, 60, 90}
- `rebalance_days` ∈ {7, 14, 30}
- `universe_size` ∈ {top 8, 15, 25 by liquidity}
- `target_portfolio_vol` ∈ {0.20, 0.40, 0.60}

### (f) Edge / decay / capacity
Not an alpha source — a **risk-normalized beta** that historically improves
risk-adjusted return vs equal-weight or cap-weight by avoiding BTC/SOL vol
domination. Robust, high capacity, slow decay. Main risk: crypto correlations
spike toward 1 in crashes, so "risk parity" gives less diversification exactly
when you need it; and inverse-vol overweights stablecoin-like low-vol names if
any sneak into the universe.

### (g) Falsifiers
- Inverse-vol basket does not beat equal-weight basket on risk-adjusted return
  OOS after costs.
- Diversification benefit collapses in the crash subsamples (correlation → 1),
  making it no better than concentrated BTC on a drawdown basis.

### (h) Citations
- QuantPedia. *Risk Parity Asset Allocation:*
  https://quantpedia.com/risk-parity-asset-allocation/
- S&P Dow Jones Indices. *Indexing Risk Parity Strategies:*
  https://www.spglobal.com/spdji/en/documents/research/research-indexing-risk-parity-strategies.pdf
- ReSolve Asset Management. *Risk Parity: Methods and Measures of Success:*
  https://investresolve.com/inc/uploads/pdf/risk-parity-methods-and-measures-of-success.pdf

---

## Cross-cutting cost/engine reality check

- Our engine **enforces costs** (a zero-cost run is rejected) and fills at
  `close` with `entry_lag_bars >= 1`. Any minute-frequency claim must clear
  realistic taker fee + slippage on its true turnover. This alone kills most
  1-min mean-reversion and 2h overnight-seasonality books unless the per-trade
  edge is unusually large.
- Genuine intraday structure documented in the literature (quarter-hour trade
  bursts in the first 10 seconds; tea-time 16:00-17:00 UTC volatility/illiquidity
  peak) lives **below our 1-min granularity and inside the entry lag** — we
  cannot harvest it. Report it, do not build on it.
- Prefer **daily-clocked, low-turnover** expressions (trend, inverse-vol,
  vol-scaling). Use calendar/regime signals as **filters on an already-profitable
  book**, never as standalone alpha.
- `vwap` is NULL and there is no order book, taker volume, OI, or tick data —
  every construction above deliberately uses only OHLCV, `num_trades`,
  `funding_8h` stamps, and (optionally) `basis_pct`.

## Consolidated citations
- Moreira & Muir (2017), *Volatility-Managed Portfolios*, NBER 22208 / SSRN 2659431.
- Cederburg et al. (2020), *On the performance of volatility-managed portfolios*, JFE.
- *Cryptocurrency market risk-managed momentum strategies* (2025), FRL.
- *Cryptocurrency momentum has (not) its moments* (2025), FMPM.
- Caporale & Plastun, *Bitcoin and the day-of-the-week effect*, FRL.
- *Revisiting seasonality in cryptocurrencies* (2024), FRL.
- *Calendar effects on returns, volatility and higher moments* (2025).
- *Bitcoin's Weekend Effect (2014-2024)*, PBES.
- Padyšák & Vojtko, *Seasonality, Trend-following, and Mean reversion in Bitcoin*, SSRN 4081000.
- Kim & Hansen (2026), *The Quarter-Hour Effect*, arXiv 2607.09426.
- *Temporal Dynamics of Market Microstructure in Crypto Perpetual Futures* (2026), MDPI.
- *Decomposing cryptocurrency high-frequency price dynamics* (2023), arXiv 2306.17095.
- Grayscale, *The Trend is Your Friend*.
- *A Decade of Evidence of Trend Following in Cryptocurrencies* (2020), arXiv 2009.12155.
- *Dynamic time series momentum of cryptocurrencies* (2021), NAJEF.
- Rohrbach, Suremann & Osterrieder, *Momentum and Trend Following for Currencies and Bitcoin*, SSRN 2949379.
- QuantPedia / S&P DJI / ReSolve — risk parity references.
