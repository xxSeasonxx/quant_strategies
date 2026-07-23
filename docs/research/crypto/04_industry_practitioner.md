# Industry & Practitioner Survey: Systematic Crypto Strategies Buildable from OHLCV + Funding + Basis

**Scope.** What crypto quant funds, prop desks, exchanges, and data vendors *actually
publish* about systematic strategies, filtered hard to what we can build from **only**
1-min OHLCV (perp + spot), realized 8h perp funding, and 1-min spot-perp basis. Every
idea is scored for buildability against our engine and flagged where it secretly needs
order book, open interest (OI), on-chain, options, or market-cap data we do not have.

## Executive summary

- The **single most-published, best-documented, best-data-fit** crypto systematic edge is
  **funding carry** — either as a *delta-neutral cash-and-carry* (long spot / short perp,
  collect funding) or as a *cross-sectional funding factor* (long low-funding coins, short
  high-funding coins). Both are directly buildable from `funding_8h` + spot/perp OHLCV, and
  the funding leg is what our engine already models as financing. Honest sources agree the
  edge is real but **decaying**: annualized yields have compressed from 30-50% (2020-21) to
  ~5-15% today.
- **Cross-sectional momentum** (rank coins by trailing return, long winners / short losers)
  is the second-most-published factor. The most credible source (a real crypto quant fund)
  publishes it *with its out-of-sample collapse shown* — a rare honest disclosure and a
  strong prior that raw price momentum is regime-dependent and cost-fragile.
- **Time-series trend / moving-average** on BTC (and the majors) is the most *marketed*
  idea (Grayscale et al.) and the easiest to curve-fit; treat single-MA-pair backtests as
  the canonical overfit trap.
- **Funding-extreme crowding reversal**, **spot-perp basis mean-reversion**, and
  **short-horizon cross-sectional reversal** are legitimate secondary ideas, all buildable.
- **Avoid / not buildable:** market-making and cross-exchange funding arb (need order book /
  latency / multi-venue), OI-weighted "composite" carry (need OI), on-chain flow signals
  (Glassnode/Coin Metrics), options/IV carry (Deribit), and BTC-dominance / "altseason"
  rotation (needs market cap). The buildable proxy for the last is relative-strength vs BTC.

**Buildability legend:** ✅ fully buildable from our fields · 🟡 buildable as a *proxy* of the
published version (we lack the exact inputs) · ❌ needs data we do not have.

---

## Idea 1 — Delta-neutral funding carry (cash-and-carry basis) ✅ TOP

**(a) Source & publisher / bias.** The canonical, most-published crypto systematic trade.
Documented by exchanges (**Kraken Learn** — sells perp futures, so promotional), data
vendors (**Amberdata** "Ultimate Guide to Funding Rate Arbitrage" — sells the funding data,
pure marketing, *zero* backtest evidence), and education/practitioner shops (**Quantt**,
**Hyperdash**, **BloFin Academy**). Academic backing: **BIS Working Paper 1087, "Crypto
carry."** Every party publishing this has an incentive to make it look easy (fees, data
sales, course sales) — discount the return claims, trust the *mechanism*.

**(b) Claimed edge & evidence.** When the perp trades above spot, longs pay shorts each 8h
funding interval; a long-spot / short-perp book earns that funding while its price exposure
cancels (delta-neutral). Kraken frames a representative +0.10%/8h → ~10.95% annualized on
notional. Quantt gives the honest arc: **30-50% annualized (2020-21) → 5-15% today**; BIS
finds the carry return is *mostly the funding rate*, ~8% mean with strikingly low ~0.8% vol
in-sample. No published source gives a clean net-of-cost, capacity-adjusted live track.

**(c) Exact construction from our fields.** For each basis-ready symbol with *both* spot and
perp (ADA, ATOM, BTC, DOGE, DOT, ETH, FET, LINK, RENDER, SOL, TIA, UNI, XRP):
- Signal = trailing realized funding from `funding_8h` (e.g. mean of last `k` funding
  events, annualized ×3×365). Optionally gate on `crypto_spot_perp_basis_1min.basis_pct`
  (only enter when basis/funding is favorably positive).
- Hold **long spot + short perp** of equal notional when carry is positive; optionally the
  reverse (long perp / short spot) when funding is persistently negative.
- Funding is realized on the perp leg (our engine models perp funding as financing), so the
  scored NAV *is* the carry P&L minus costs — no separate accrual bookkeeping needed.

**(d) Target book & cadence.** Per selected symbol X: `{spot_X: +w, perp_X: -w}` with
`w` scaled so the netted book hits the risk budget; `0` when carry below entry threshold.
Idempotent netting means the two legs sit as one financed book. **Rebalance daily**
(funding prints every 8h; daily re-selection is enough and cost-frugal).

**(e) Datasets.** `crypto_spot_1min`, `crypto_perp_1min`, `funding_8h`,
`crypto_spot_perp_basis_1min` (13 basis-ready symbols; spot history from 2021-01-01).

**(f) Bounded params for autoresearch.** funding lookback `k` ∈ {1,3,7,14} events; entry
threshold on annualized carry ∈ {5%,10%,15%}; exit/flatten threshold; optional basis gate
on/off; number of symbols carried (top-N by carry) ∈ {3,5,8,13}.

**(g) Capacity / decay / crowding.** Highest-capacity crypto edge (majors are deep), but the
most crowded and openly decaying — every desk and every "delta-neutral yield" product runs
it. Real-world risks the sim must respect: funding flips negative in stress, basis
compression, and (in live trading) exchange counterparty / liquidation of the perp leg. Our
sim cannot model exchange default; treat reported Sharpe as an upper bound.

**(h) Falsifiers.** (1) Net-of-cost carry after realistic fees is ≤ short-rate over the
Train window. (2) The book's NAV is not actually delta-neutral (residual BTC beta > small
threshold), meaning the "carry" is disguised directional exposure. (3) Return concentrates
entirely in 2020-21 and vanishes 2023→.

**(i) URLs.** Kraken; Amberdata; Quantt; Hyperdash; BloFin; BIS WP1087 (see Sources).

---

## Idea 2 — Cross-sectional funding-carry factor 🟡→✅ TOP

**(a) Source & publisher / bias.** **unravel.finance / aperiodic.io** ("Cross-Sectional
Alpha Factors in Crypto: 2+ Sharpe Without Overfitting") — a research/infra firm that
publishes *established* factors while keeping proprietary ones; incentive is to license
tooling, so published Sharpes are demonstrably real but the *best* variants are withheld.
Also **BIS WP1087** (soft cross-sectional carry) and general practitioner consensus.

**(b) Claimed edge & evidence.** "Soft" carry: **short the highest-funding coins, long the
lowest/most-negative**, *without* explicit hedging — returns come from the funding spread
plus the tendency of over-funded (over-crowded-long) coins to underperform. unravel reports
their momentum+carry blend reaches **Sharpe ≈ 2** (footnote concedes the headline is
generous; proprietary variants higher). BIS: the cross-sectional carry return is dominated
by the funding component.

**(c) Exact construction from our fields.** Across the perp universe (25 symbols): each day,
rank symbols by trailing realized funding (annualized, from `funding_8h`). Long the bottom
quantile (cheapest/most-negative funding), short the top quantile (most expensive). Equal- or
inverse-volatility-weighted within each leg; **dollar-neutral** across legs.
- 🟡 **Proxy caveat:** industry uses an **OI-weighted composite funding across venues**. We
  have single-source *realized* funding only — no OI, no cross-venue composite. Our version
  is the single-venue proxy; document this as a known deviation.

**(d) Target book & cadence.** Signed weights across all perps summing to ~0 net dollar (and
ideally ~0 net BTC-beta): `perp_i: -w` for top-funding, `+w` for bottom-funding, `0`
otherwise. **Daily** rebalance.

**(e) Datasets.** `funding_8h` (all 25 perps), `crypto_perp_1min` (returns for weighting +
beta-neutralization).

**(f) Bounded params.** funding lookback ∈ {1,3,7,14} events; quantile fraction ∈
{10%,20%,33%}; weighting {equal, inverse-vol}; beta-neutralize-to-BTC {on,off};
turnover-smoothing half-life.

**(g) Capacity / decay / crowding.** Medium capacity — the short leg lands on high-funding
alts that are often the *least* liquid, so capacity is set by the least-liquid shorted name.
Crowded among quant desks. Decays as funding markets get more efficient.

**(h) Falsifiers.** (1) After a BTC-beta neutralization the factor return disappears (it was
just short-beta in a bull market). (2) P&L is entirely the funding accrual with negative
price selection (i.e. you're paid to hold losers). (3) Turnover costs on the alt short leg
exceed the spread.

**(i) URLs.** unravel/aperiodic; BIS WP1087.

---

## Idea 3 — Cross-sectional price momentum (long/short) ✅ TOP (with honest caveats)

**(a) Source & publisher / bias.** **Starkiller Capital** ("Cross-Sectional Momentum in
Cryptocurrency Markets") — an *actual systematic crypto fund* (Leigh Drogen, Corey Hoffstein,
Kevin Otte). Uniquely credible because they **explicitly disclose hindsight bias and show the
strategy's out-of-sample collapse**. Also **unravel/aperiodic** (momentum as a core factor).
Bias: they run this money, but the write-up is unusually candid.

**(b) Claimed edge & evidence.** Rank by trailing return, hold the top group. Starkiller,
30-day lookback, weekly rebalance, long-only top quintile of a market-cap universe:
- In-sample (Apr 2018-Mar 2021): **+69% ann** (top quintile) — but *underperformed BTC's +97%*.
- **Out-of-sample (Mar 2021-Nov 2022): −2.35% ann** (BTC −37.8%) — momentum survived the bear
  better but the raw edge over holding BTC did not persist.
- Full period long/short: top +37.8% vs bottom −33.8% ann.
- **Costs bite hard:** at 50bps, in-sample dropped ~30pts; at **125bps the edge vanishes**.
unravel run it long/short (top vs bottom 20%, ~30-day formation, daily) and note crypto
momentum decays *faster* than equities, "sometimes reversing within months."

**(c) Exact construction from our fields.** Daily, rank the perp universe by trailing
`close`-to-`close` return over the formation window (from `crypto_perp_1min`). Long top
quantile, short bottom quantile (or long-only top for a directional variant). Inverse-vol
weight within legs; dollar- and optionally BTC-beta-neutral.

**(d) Target book & cadence.** `perp_i: +w` (winners) / `-w` (losers) / `0`, ~net-neutral.
**Weekly or daily** rebalance (weekly is more cost-robust given the 125bps sensitivity).

**(e) Datasets.** `crypto_perp_1min` only (returns + vol). No funding/basis needed.

**(f) Bounded params.** formation window ∈ {14,30,60,90} days; skip-most-recent ∈ {0,1,3}
days (short-term-reversal guard); quantile ∈ {10%,20%,33%}; rebalance {daily,weekly};
weighting {equal,inverse-vol}; long-only vs long/short.

**(g) Capacity / decay / crowding.** Capacity limited by the least-liquid ranked name; the
*bottom* (short) quintile is the binding constraint. Heavily crowded (most-published factor
after carry). Starkiller's own OOS shows the raw edge is not durable — this is a regime bet.

**(h) Falsifiers.** (1) Long/short net return < 0 after 50-100bps costs on Train. (2) Edge is
purely long-BTC-beta (dies after neutralization). (3) OOS window shows the same collapse
Starkiller reported — treat that as the null to beat.

**(i) URLs.** Starkiller Capital; unravel/aperiodic.

---

## Idea 4 — Time-series trend / moving-average (BTC + majors) ✅ but overfit-prone

**(a) Source & publisher / bias.** **Grayscale Research** ("The Trend is Your Friend:
Managing Bitcoin's Volatility with Momentum Signals") — a large asset manager whose incentive
is to keep clients *invested in* BTC products, so their trend framing is really a
drawdown-management pitch. Also ubiquitous in retail practitioner content (Coinmonks, Medium
CTA posts) — the single most *marketed* and most *curve-fit* idea in crypto.

**(b) Claimed edge & evidence.** Grayscale: a **20d/100d moving-average crossover** on BTC
returns ~116% ann / **Sharpe 1.7** vs buy-and-hold ~110% / 1.3 (2012→), with best Sharpes
when the fast MA is ~10-30 days. **Heavy caveat:** this is a two-parameter grid over a single
asset on a monotonically-up sample — the textbook overfit setup. Quantt explicitly lists
trend-following as *degraded*: "high whipsaw risk, strong negative skew on big trends."

**(c) Exact construction from our fields.** Per instrument: signal = `sign(MA_fast − MA_slow)`
of `close` (or price vs single MA, or breakout of N-day high/low). Apply across BTC/ETH and
optionally the full liquid universe as a diversified trend book (a proper CTA), not just BTC.

**(d) Target book & cadence.** `perp_i: +w · sign(trend_i)` (long/flat, or long/short),
vol-scaled by the engine's built-in vol targeting. **Daily** signal, rebalance on flip.

**(e) Datasets.** `crypto_perp_1min` only.

**(f) Bounded params.** fast MA ∈ {10,20,30}; slow MA ∈ {60,100,150}; or breakout window;
long-only vs long/short; per-asset vs portfolio vol target.

**(g) Capacity / decay / crowding.** High capacity on majors. But *most susceptible to
overfitting the MA pair* and to whipsaw in the current lower-vol, more-efficient regime.

**(h) Falsifiers.** (1) Performance is not robust across neighboring MA pairs (a single lucky
cell). (2) A diversified multi-asset trend book Sharpe ≤ buy-and-hold BTC after costs. (3)
Negative skew so severe that a few whipsaw clusters erase the trend premium.

**(i) URLs.** Grayscale Research; Coinmonks/Medium CTA posts; Quantt.

---

## Idea 5 — Funding-extreme crowding reversal ✅ (already a live in-house topic)

**(a) Source & publisher / bias.** **Kraken Learn**, **quantjourney (Substack)**, Phemex,
Altrady, and general desk lore. Kraken/exchanges want you trading; Substack authors want
subscribers. This is the thesis behind our own `crypto_perp_funding_crowding_reversal`
candidate — treat prior in-house results as the real prior, not the blog claims.

**(b) Claimed edge & evidence.** Extreme positive funding = crowded, over-leveraged longs →
vulnerable to a fast liquidation-driven unwind → **fade it (short)**; extreme negative
funding = capitulation → **fade it (long)**. Kraken: historical peaks of 0.15-0.20%/8h
"preceded 10-30% corrections"; −0.15% marked the March-2020 capitulation low. quantjourney
gives concrete thresholds: long when annualized funding < **−20%**, short when > **+40%**,
with ±0.3%/interval BTC caps as the extreme markers, and insists funding be combined with
volume/OI/basis to avoid false positives. **No published net-of-cost backtest** — all
anecdotal.

**(c) Exact construction from our fields.** Signal = annualized realized funding
(`funding_8h`) per symbol, optionally z-scored over a trailing window per symbol. When it
exceeds an upper extreme → target short; below a lower extreme → target long. Gate on
`volume` (from OHLCV) and `basis_pct` to filter false positives (no OI available — that's a
🟡 deviation from the blog recipe).

**(d) Target book & cadence.** `perp_i: −w` (funding too high) / `+w` (funding too low) /
`0`; can be run cross-sectionally (net-neutral) or per-symbol directional. Signal on each 8h
funding print, rebalance **daily**; short hold (blogs cite 24-72h reversion), so a
time-based or funding-normalization exit fits.

**(e) Datasets.** `funding_8h`, `crypto_perp_1min` (volume, price), `crypto_spot_perp_basis_1min`.

**(f) Bounded params.** funding z-score window; upper/lower thresholds (abs annualized {±20%,
±40%, ±60%} or z ∈ {2,2.5,3}); hold horizon {8h,24h,48h,72h}; volume/basis gate on/off.

**(g) Capacity / decay / crowding.** The extremes cluster in smaller alts (thin), so capacity
is low and the short side is the crowded-liquidation zone precisely when it's hardest to
trade. Real liquidation cascades are the return *source* but also the tail risk our sim can't
fully capture (no liquidation feed — only the funding/vol footprint).

**(h) Falsifiers.** (1) Reversal P&L is entirely explained by short-term price reversal (Idea
7), i.e. funding adds nothing over price alone. (2) Costs on thin alts exceed the reversion.
(3) Signal only works in the 2021 leverage-mania sample.

**(i) URLs.** Kraken; quantjourney; Phemex; Altrady.

---

## Idea 6 — Spot-perp basis mean-reversion / basis momentum 🟡✅

**(a) Source & publisher / bias.** Framed by **Amberdata**, **Kraken**, Deribit Insights
(basis/carry framing) and CoinAPI. Vendors selling basis data; mostly descriptive, little
hard evidence. Deribit's framing is options-centric but the *basis* concept transfers.

**(b) Claimed edge & evidence.** Basis (perp − spot, or `basis_pct`) oscillates around ~0 and
mean-reverts; extreme basis marks positioning stress. Closely related to carry (Idea 1) but
traded as a *timing* signal on the basis itself rather than a static carry hold. Evidence is
qualitative.

**(c) Exact construction from our fields.** Directly use `crypto_spot_perp_basis_1min.basis_pct`
(13 basis-ready symbols). z-score basis per symbol over a trailing window; when basis is
extreme-wide, put on the convergence trade (short the rich leg / long the cheap leg — same
two-legged spot+perp book as Idea 1 but *entered on deviation, exited on reversion*). A
"basis momentum" variant instead ranks symbols by change-in-basis and trades continuation.

**(d) Target book & cadence.** `{spot_X: ∓w, perp_X: ±w}` convergence pairs, `0` when basis
near mean. Signal on 1-min basis, rebalance **hourly/daily** (basis moves intraday but keep
turnover bounded).

**(e) Datasets.** `crypto_spot_perp_basis_1min`, `crypto_spot_1min`, `crypto_perp_1min`,
`funding_8h` (basis and funding are mechanically linked — model both).

**(f) Bounded params.** basis z-window; entry/exit z thresholds; mean-reversion vs
basis-momentum sign; symbol count.

**(g) Capacity / decay / crowding.** Same 13 deep-ish symbols as carry; medium capacity.
Highly related to carry and to funding-reversal, so watch for redundancy — it may be the same
edge in a different coordinate system.

**(h) Falsifiers.** (1) After netting funding, basis-MR P&L is indistinguishable from static
carry (Idea 1) — no *timing* alpha. (2) Basis "extremes" are just proxies for funding
extremes (Idea 5). (3) Reversion horizon is shorter than tradeable at 1-min+costs.

**(i) URLs.** Amberdata; Kraken; CoinAPI; Deribit Insights.

---

## Idea 7 — Short-horizon cross-sectional reversal ✅

**(a) Source & publisher / bias.** **Quantt** explicitly lists "cross-sectional momentum /
reversion" and "time-of-day patterns" among the *stat-arb families that still work*;
**unravel/aperiodic** discuss short-horizon reversal as a distinct factor. Education/infra
bias, but this is a well-known low-capacity quant staple.

**(b) Claimed edge & evidence.** Over very short horizons (1-3 days), crypto cross-section
*reverses* (yesterday's biggest gainers underperform). Quantt notes these still work while
"long-horizon factor strategies" and "naive cointegration" do not, attributing the shift to
reduced retail flow. Evidence is asserted, not tabled.

**(c) Exact construction from our fields.** Daily, rank the perp universe by *very recent*
return (e.g. prior 1-3 days from `crypto_perp_1min`). **Long the losers, short the winners**
(opposite sign to Idea 3), dollar/beta-neutral, inverse-vol weighted.

**(d) Target book & cadence.** `perp_i: −w·rank(recent_return)`, net-neutral. **Daily**
rebalance (this is the whole point — it's a high-turnover, short-hold factor).

**(e) Datasets.** `crypto_perp_1min` only.

**(f) Bounded params.** reversal window ∈ {1,2,3} days; quantile; weighting; beta-neutralize.

**(g) Capacity / decay / crowding.** **Lowest capacity** here — high turnover means costs
dominate and it's the most cost-fragile idea. Crowded among HFT-adjacent desks. Only viable
if our cost model is honest.

**(h) Falsifiers.** (1) Dies entirely under realistic per-rebalance costs (very likely the
binding test). (2) It's just the microstructure bounce, gone by the time a 1-min bar closes.

**(i) URLs.** Quantt; unravel/aperiodic.

---

## Idea 8 — Volatility targeting / risk-parity portfolio overlay ✅ (construction, not alpha)

**(a) Source & publisher / bias.** VanEck, XBTO, and academic portfolio-construction work
("Simple and Effective Portfolio Construction with Crypto Assets") — asset managers and
allocators. Bias: they want you allocated. This is **portfolio construction / risk
management, not a standalone signal.**

**(b) Claimed edge & evidence.** Scale exposure by inverse realized volatility (or full risk
parity with an EWMA covariance) rather than dollar/market-cap weights → steadier risk,
smaller drawdowns. Academic version: daily risk-parity rebalance with a 10-day half-life EWMA.

**(c) Exact construction from our fields.** Realized vol from `crypto_perp_1min` returns per
symbol; weight ∝ 1/vol (or full risk-parity). **This is what our engine's built-in
vol-targeting / risk-budget operator already does** — so this is best used as the *weighting
layer* on top of Ideas 2/3/5/7, not a separate candidate.

**(d) Target book & cadence.** Overlay: multiply any signal's target book by inverse-vol
weights; rebalance daily. **(e)** `crypto_perp_1min`.

**(f) Bounded params.** vol lookback / EWMA half-life; vol-target level; per-asset cap.

**(g) Capacity / decay / crowding.** Not an alpha, so no crowding decay; it's a risk control.
Main risk is vol-estimate lag around regime breaks.

**(h) Falsifiers.** (1) Inverse-vol weighting does not improve risk-adjusted return vs equal
weight on our sample (then it's just complexity). Note the engine already owns risk-budget
sizing — avoid double-counting.

**(i) URLs.** VanEck; XBTO; arXiv portfolio-construction paper.

---

## Idea 9 — Pairs / cointegration statistical arbitrage 🟡 (skeptical)

**(a) Source & publisher / bias.** Widely published (CoinAPI, dYdX Learn, LinkedIn how-tos,
several academic papers on BTC-ETH-LTC-BCH cointegration). Mostly educational/vendor content
and single-sample academic backtests — **low credibility for live edge.**

**(b) Claimed edge & evidence.** Trade the spread of a cointegrated pair when it deviates
>~2σ, betting on convergence. Academic backtests claim **Sharpe 1.58-2.45**, BTC-ETH pair
16.34% ann / 8.45% vol. **But Quantt — the most honest source — explicitly says "naive
cointegration" no longer works live.** Strong disagreement between marketing/academia and
practitioners.

**(c) Exact construction from our fields.** Estimate a rolling hedge ratio between two
`close` series (e.g. ETH vs BTC, or any correlated perp pair); trade the residual spread's
z-score. **Root risk:** cointegration relationships in crypto are unstable and break
regime-by-regime; the hedge ratio is itself a fitted parameter that can leak look-ahead.

**(d) Target book & cadence.** `{perp_A: +w, perp_B: −β·w}`, `0` when spread near mean.
Rebalance daily; re-estimate hedge ratio on a trailing window (causal only).

**(e) Datasets.** `crypto_perp_1min` (or spot). **(f)** pair set; hedge-ratio window; entry/exit
z; stop.

**(g) Capacity / decay / crowding.** Decayed per practitioners; the relationships that were
stable in 2020-21 broke as retail left. High model risk.

**(h) Falsifiers.** (1) Hedge ratio estimated causally (no future data) kills the backtest
edge. (2) Spread is non-stationary out-of-sample (the pair de-cointegrates). (3) Edge is just
Idea 3/7 in disguise (relative momentum/reversal between two names).

**(i) URLs.** CoinAPI; dYdX; academic cointegration papers.

---

## Idea 10 — BTC lead-lag / altcoin rotation 🟡 (proxy only) / ❌ as published

**(a) Source & publisher / bias.** Bitpanda, Nexo, KuCoin, TradingView (BTC.D), "Altcoin
Season Index" content. **Retail/exchange marketing** — narrative-heavy, evidence-light, and
the headline tools (**BTC dominance, Altcoin Season Index**) are **market-cap based → ❌ not
buildable** with our data.

**(b) Claimed edge.** Capital rotates BTC → large caps → mid/small caps → memecoins; high BTC
dominance = defensive, falling dominance = "altseason." Systematic version: rotate toward
higher-beta alts when dominance falls.

**(c) Buildable proxy from our fields.** We cannot compute dominance (no market cap). The
**buildable 🟡 proxy** is *relative strength vs BTC*: rank alts by trailing return **minus
BTC's return** (or ETH/BTC and alt/BTC ratios from `crypto_perp_1min`), and tilt toward alts
outperforming BTC. This collapses into **Idea 3 (cross-sectional momentum) with BTC as
benchmark** — so it is not a genuinely new edge, just a framing.

**(d)-(f)** Same mechanics/params as Idea 3, using return-minus-BTC as the ranking variable.

**(g) Capacity / decay / crowding.** As Idea 3. **(h) Falsifier:** adds nothing over plain
cross-sectional momentum once BTC beta is handled. **(i)** Bitpanda; Nexo; KuCoin; TradingView.

---

## Over-hyped / curve-fit / avoid

- **Single-MA-pair BTC trend backtests (e.g. Grayscale's 20/100).** Two parameters, one
  asset, one up-only sample — the archetypal overfit. Only trust trend as a *diversified
  multi-asset, robustness-checked* book, and expect negative skew.
- **Vendor "funding rate arbitrage" guides with no numbers (Amberdata).** Pure data-sales
  marketing; use the mechanism, ignore the implied returns.
- **"15-35% market-neutral yield" delta-neutral products.** Real mechanism, stale numbers;
  today's honest range is ~5-15% and falling. Treat any >20% claim as a 2021 artifact.
- **Naive pairs cointegration** — practitioners say it's dead; academic Sharpes are single-
  sample and leak the hedge ratio.
- **BTC-dominance / altseason rotation** as published — needs market cap; the buildable proxy
  is just momentum-vs-BTC.
- **Whale-following / on-chain long-horizon signals** — severe survivorship bias (Quantt) and
  ❌ not buildable anyway.

## Not buildable from our data (flag & skip)

| Published idea | Missing input |
|---|---|
| Market making / spread capture | Order book, latency, tick data ❌ |
| Cross-exchange funding arbitrage | Multi-venue quotes + latency ❌ |
| OI-weighted "composite" funding carry | Open interest ❌ (we have realized funding only 🟡) |
| Liquidation-cascade timing | Liquidation feed ❌ (proxy via funding+vol only) |
| On-chain flow signals (Glassnode, Coin Metrics) | On-chain data ❌ |
| Options / IV carry, vol surface (Deribit) | Options/IV ❌ |
| BTC dominance / Altcoin Season Index | Market cap ❌ |

---

## Sources

**Crypto quant funds / desks (highest credibility — they run this money):**
- Starkiller Capital — "Cross-Sectional Momentum in Cryptocurrency Markets" (Drogen,
  Hoffstein, Otte). Systematic crypto fund; *candidly discloses hindsight bias and OOS
  collapse.* https://www.starkiller.capital/post/cross-sectional-momentum-in-cryptocurrency-markets
- unravel.finance / aperiodic.io — "Cross-Sectional Alpha Factors in Crypto: 2+ Sharpe
  Without Overfitting." Research/infra firm; publishes established factors, withholds
  proprietary edge (licensing incentive → published Sharpes real but flattering).
  https://blog.aperiodic.io/p/cross-sectional-alpha-factors-in

**Asset managers / allocators (product-invested bias):**
- Grayscale Research — "The Trend is Your Friend: Managing Bitcoin's Volatility with Momentum
  Signals." Large asset manager; trend framed as drawdown management to keep clients invested.
  https://research.grayscale.com/reports/the-trend-is-your-friend-managing-bitcoins-volatility-with-momentum-signals
- VanEck — "Optimal Crypto Allocation for Portfolios." Allocator.
  https://www.vaneck.com/us/en/blogs/digital-assets/matthew-sigel-optimal-crypto-allocation-for-portfolios/
- XBTO — "Building a Diversified Crypto Portfolio (Institutions)."
  https://www.xbto.com/resources/building-a-diversified-crypto-portfolio-best-practices-for-institutions-in-2025

**Exchanges (fee incentive → promotional):**
- Kraken Learn — "Futures trading: funding rate strategy." Carry + sentiment/mean-reversion
  framing with concrete thresholds. https://www.kraken.com/learn/futures-trading-funding-rate-strategy
- Phemex Academy — funding as a trading signal. https://phemex.com/academy/what-is-funding-rate-in-crypto-futures

**Data vendors (data-sales incentive → mechanism yes, evidence weak):**
- Amberdata — "The Ultimate Guide to Funding Rate Arbitrage" (zero backtest evidence).
  https://blog.amberdata.io/the-ultimate-guide-to-funding-rate-arbitrage-amberdata
- CoinAPI — statistical arbitrage strategies & perpetual futures data.
  https://www.coinapi.io/blog/3-statistical-arbitrage-strategies-in-crypto ;
  https://www.coinapi.io/blog/historical-data-for-perpetual-futures
- Kaiko (order book / microstructure — flags what we *lack*). https://www.kaiko.com/
- Glassnode (on-chain — not buildable). https://research.glassnode.com/
- Coin Metrics (network/index data — mostly not buildable). https://coinmetrics.io/

**Practitioner / education shops (course / subscriber incentive; Quantt is unusually honest
about decay):**
- Quantt — "Crypto Quant Strategies 2026: What Actually Works." Honest what-works vs
  what's-decayed (basis carry compressed 30-50%→5-15%; naive cointegration & long-horizon
  factors dead; trend degraded). https://www.quantt.co.uk/resources/crypto-quant-strategies-2026
- quantjourney (Substack) — "Funding Rates in Crypto: The Hidden Cost, Sentiment Signal, and
  Strategy Trigger." Concrete contrarian thresholds. https://quantjourney.substack.com/p/funding-rates-in-crypto-the-hidden
- Hyperdash — "Basis Trading and Funding Rate Arbitrage on Perps." https://hyperdash.com/learn/basis-trading-and-funding-rate-arbitrage-on-perps
- BloFin Academy — "Delta-Neutral Crypto Strategies." https://blofin.com/en/academy/education/delta-neutral-crypto-strategies
- Coinmonks / Medium — CTA & momentum backtests (illustrative of overfit patterns).

**Authoritative reference (bridges to academic lit):**
- BIS Working Paper No. 1087 — "Crypto carry." Carry return dominated by the funding
  component; cross-sectional short-high-/long-low-funding framing. https://www.bis.org/publ/work1087.pdf
