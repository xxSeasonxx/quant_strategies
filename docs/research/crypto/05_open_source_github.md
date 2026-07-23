# Open-Source Crypto Strategy Survey (GitHub & Adjacent)

Survey of open-source, implementable crypto strategies restricted to what our data supports:
OHLCV (1-min perp/spot), realized perp funding (8h), and spot-perp basis. The public crypto
repo landscape is dominated by two archetypes: (1) **execution/detection bots** with real
economic logic but *no backtest evidence*, and (2) **in-sample TA demos** with backtest curves
but *no economic edge and no OOS discipline*. Genuine walk-forward methodology is rare. The
strategies with a defensible economic edge that also map cleanly to our target-book engine are
**cross-sectional funding carry**, **cross-sectional momentum**, and **single-venue spot-perp
basis carry** — all expressible as a signed multi-asset book with a handful of bounded params.
The best methodology to emulate comes not from strategy repos but from a walk-forward research
paper (`tmr-crypto`) and a production portfolio library (`ArturSepp/OptimalPortfolios`). Most
single-coin MA/Donchian/RSI repos are curve-fit demos; treat their equity curves as noise.

**Critical data constraint that filters most funding repos:** we have exactly **one funding
series per symbol** (single-venue realized funding). Every cross-venue funding-arb repo
(CEX↔CEX, DEX↔DEX) is therefore **NOT buildable** — we cannot observe a second venue's rate.
What *is* buildable is (a) the **cross-sectional** carry factor (rank our 25 perps by their own
funding) and (b) **single-venue basis carry** (long spot / short perp on the same coin), because
we have spot, perp, and `basis_pct` for the 13 basis-ready coins.

---

## Theme 1 — Funding-rate harvesting / delta-neutral basis bots

The single most common crypto-repo category. Economically the soundest idea in the space (funding
is a real, persistent risk/crowding premium), but the public code is almost entirely **live
execution plumbing with zero historical evidence**, and most target *cross-venue* rate divergence
we cannot replicate.

### `aoki-h-jp/funding-rate-arbitrage` — 304★, 67 forks, MIT
- **Logic:** Detection toolkit only (author explicitly states it does *not* execute). Scans 6
  CEXs (Binance, Bybit, OKX, Gate, CoinEx, Bitget) for funding-rate divergence — both single-venue
  (perp vs spot) and multi-venue gaps — and ranks opportunities by divergence magnitude or
  projected revenue.
- **Data/mapping:** Cross-venue rates → **not mappable** (we have one venue). The single-venue
  perp-vs-spot divergence framing *is* mappable to our `basis_pct` + `funding_8h`.
- **OOS:** None. No backtest at all — pure scanner.
- **Verdict:** NOT buildable as-is (cross-venue). The *ranking-by-projected-funding* idea is
  reusable as a cross-sectional signal. Highest-credibility repo in the category by stars, but it
  is a screener, not a strategy.

### `ynhy513/funding-rate-arbitrage` — 0★ (but well-specified risk controls)
- **Logic:** Single-venue delta-neutral cash-and-carry: long spot + short perp of equal notional.
  **Entry** when funding > 0.01% AND expected annual yield > 8% AND basis < 0.1%.
  **Exit** when funding turns negative, yield drops below floor, or risk limits breach.
  `Expected Annual Yield = funding × 3 × 365 − fees × 4`. Caps: 15% per asset, 60% total
  deployment, 2% global drawdown stop, delta re-hedge when |delta| > 0.5%.
- **Data/mapping:** Binance+OKX via CCXT, but the *logic* is single-venue and maps directly to
  our `funding_8h` + `crypto_spot_1min` + `crypto_perp_1min` + `basis_pct`. This is the cleanest
  spec of the basis-carry rule in the survey.
- **OOS:** None — live/testnet framework, no historical results.
- **Verdict:** BUILDABLE (with proxy) as a *single-coin or multi-coin basis-carry book*. Its entry
  formula and thresholds are directly reusable as bounded params. Evidence value = zero; logic
  value = high.

### `stephenpeters/delta_neutral_strategies` — 0★, 4 commits (early stage)
- **Logic:** Long spot/short perp when funding > 0, flip when funding < 0; "real-time rebalancing
  to preserve neutrality," liquidation-aware sizing. Hyperliquid-oriented. Ships `backtester.py`
  but no published results.
- **OOS:** Backtest code exists; no disclosed metrics, no walk-forward.
- **Verdict:** BUILDABLE logic (same basis-carry family), but immature and unproven. The
  "flip to short-spot/long-perp when funding negative" wrinkle is worth encoding as a param.

### Others (lower value): `50shadesofgwei/funding-rate-arbitrage` (DEX↔DEX template),
`ksmit323/funding-rate-arbitrage` (hackathon, cross-DEX), `IrakliXYZ/ARBOT` (spot-futures,
markets 15-30% APY with no evidence), `Alex-bitok/okbitok-arbitrage-bot` (Bybit↔KuCoin cross-venue).
All are cross-venue execution bots → **NOT buildable** on our single-venue data, and none report a
credible backtest. Treat the advertised "15-30% annual" as unverified marketing.

**Theme verdict:** Economic edge is **plausible and well-documented** (carry premium from
persistent long-crowding). But (i) all evidence is absent and (ii) the *cross-venue* variant is
un-buildable. Our tractable version = **single-venue basis carry** and **cross-sectional funding
rank**, both of which our engine models correctly because it treats perp funding as financing
inside one netted NAV.

---

## Theme 2 — Cross-sectional & trend momentum (multi-coin ranking books)

The category that maps most naturally to our target-book engine. Public crypto-specific examples
are thin; the strong methodological examples are equities but transfer directly.

### `Fisjo/momentum-strategy-backtest` — 12-1 cross-sectional (equities)
- **Logic:** Rank by `∏_{k=2}^{12}(1+r_{t-k}) − 1` (12-month return skipping the most recent
  month). Long-only = equal-weight top 20%; long-short = long top 20% / short bottom 20%. Monthly
  rebalance, 1-month lag (no look-ahead). Costs = `turnover × 2 × 5bp`; turnover ≈ 0.8/month.
- **Reported (in-sample):** Long-only Sharpe 0.81 (CAGR 13.7%), **long-short Sharpe 0.02**
  (CAGR −2.5%, MaxDD −71.6%). Honest, unflattering LS result.
- **Data/mapping:** Equities/monthly, but the construction is asset-class-agnostic. Maps directly
  to a cross-sectional book over our 25 perps with a shorter (crypto-appropriate) lookback.
- **OOS:** In-sample only.
- **Verdict:** BUILDABLE (re-express, not reuse). Cleanest reference for the *mechanics* of a
  cross-sectional book. Note the LS ≈ 0 warning: the short leg is where crypto momentum bleeds.

### `tanish35/Momentum-Investing` — 11★, Backtrader, 6-factor composite (equities)
- **Logic:** Hierarchical long-only: (1) regime filter (index > 200-SMA), (2) time-series filter
  (name > own 200-SMA), (3) cross-sectional rank on blended 60/120/252-day momentum, (4) FIP score
  (fraction of positive days over 252d = trend *consistency*), (5) skewness penalty (90-day),
  (6) inverse-vol weighting (126-day). Score = `w_m·Mom + w_f·FIP − w_s·Skew`. Rebalances when
  top-N membership changes.
- **OOS:** In-sample 2-year backtest only; +89% unrealized reported (unverified, bull-period).
- **Verdict:** BUILDABLE (re-express). The **FIP consistency score** and **skewness penalty** are
  genuinely interesting, cheap-to-compute add-on signals (pure functions of OHLCV) worth testing as
  bounded refinements to a crypto momentum book. Regime filter maps to BTC > its 200-period MA.

### `alpacahq/notebooks` — 9★ — "Cross-Sectional Momentum Bot" (crypto, 9 coins)
- **Logic:** Live cross-sectional momentum over 9 cryptos via websockets. Credible source (Alpaca),
  but the repo page exposes only the description, not the ranking/lookback internals.
- **Verdict:** BUILDABLE concept, thin detail. Useful as a "this is a normal thing to do in crypto"
  credibility anchor; not a source of specific parameters.

### `sapk806/cross_sectional_factor_backtest_project`
- Equal-weight long/short on trailing 12-month return. Minimal, equities, in-sample. Redundant with
  Fisjo but confirms the standard recipe.

**Theme verdict:** Cross-sectional momentum has a **robust, cross-asset-validated economic edge**
(it survives out of sample in equities/futures literature). Buildable directly as our target book.
Biggest risks for crypto: (i) **momentum crashes / sharp reversals** (2021→2022), (ii) **turnover
cost** at high rebalance frequency (Fisjo's 80%/month is expensive), (iii) the **short leg is
weak/dangerous** — long-only or capped-short is safer. Trend-following single-coin MA variants
(below) are the overfit cousin; the *cross-sectional* form is the one with edge.

---

## Theme 3 — Mean-reversion / pairs / stat-arb among coins

### `fraserjohnstone/pairs-trading-backtest-system` — cointegration, crypto
- **Logic:** Tests all pair combinations for cointegration, trades hedged spreads on z-score
  reversion. Bitfinex 15-min data. Hedge ratio / exact z thresholds not documented in README.
- **Author's own caveat (verbatim):** using it as-is "would not be wise in the real world"; it
  "ignores crucial factors such as market charges." No stated OOS split.
- **Verdict:** BUILDABLE as a 2-leg book (e.g., ETH vs BTC, SOL vs ETH) but **low confidence**.
  Crypto cointegration is unstable/regime-dependent; ignoring costs flatters results. The author's
  honesty is the most useful thing here.

### `coderaashir/Crypto-Pairs-Trading`, `muMAJJI/Trading---Pair-Trading`
- Standard cointegration + z-score reversion, small repos, in-sample, no funding on the perp leg.
- **Verdict:** BUILDABLE mechanics, but same instability + cost-blindness. These are demonstrations,
  not evidence.

**Theme verdict:** **Mostly curve-fit / fragile.** Pairs cointegration in crypto is the classic
"looks great in-sample, breaks live" trap: relationships decointegrate, and none of these repos
charge funding on the short-perp leg (which our engine *would* charge, making them look worse and
more honest). A **cross-sectional mean-reversion** framing (short recent big winners / long recent
big losers over a short horizon) is more defensible than hand-picked pairs and maps better to our
book. Treat pairs repos as a caution, not a template.

---

## Theme 4 — Volatility targeting / risk parity multi-coin portfolios

### `ArturSepp/OptimalPortfolios` — 80★, MIT (production-grade) — **methodology reference**
- **Logic:** Implements ERC (risk parity), max-diversification, min-variance, max-Sharpe,
  quadratic-utility, and target-vol/target-return solvers. Covariance via **EWMA** (default 52-week
  span) or a hierarchical-clustering group-LASSO factor model. Three-layer design:
  solver → NaN-aware wrapper → **rolling backtester that estimates inputs as-of each update date**
  (no hindsight). Weights **drift between rebalances** on realized returns, so turnover/costs are
  computed against actual (drifted) holdings, not stale targets. Crypto explicitly supported
  (implements Sepp 2023 "Optimal Allocation to Cryptocurrencies").
- **Verdict:** BUILDABLE concepts; **strong methodology to emulate** for the weighting layer. Note:
  our engine already owns **vol-targeting and risk-budget sizing in the foundation** — so we do not
  re-implement the solver in `strategy.py`. What to borrow is the *discipline*: as-of covariance
  estimation, weight drift, and realized-turnover costing. The ERC idea (size each coin so it
  contributes equal risk = inverse-vol-ish weighting) is a clean default overlay for any of our
  cross-sectional books.

### `Moe-Dada/Multi-Asset-Portfolio-Crypto-Backtest` — 2★
- SMA-crossover entries + fixed % stops across Binance pairs, grid-searched (10/20/30 vs 30/50/100),
  0.05-0.2 capital per position. No costs/funding, in-sample grid only.
- **Verdict:** BUILDABLE but this is a **TA demo mislabeled as portfolio construction** — no risk
  balancing, no OOS. Curve-fit.

### `LucasIsntCoding/risk-parity-portfolio`, `libolight/risk-parity`
- Clean implementations of naive risk parity (inverse-vol), ERC, min-variance, HRP, max-div.
  Educational, not crypto-specific, no strategy alpha.
- **Verdict:** Useful as **weighting-layer reference**, not a strategy.

**Theme verdict:** Vol-targeting/risk-parity is **not alpha** — it is a risk overlay. It has no
standalone edge but reliably improves risk-adjusted returns and drawdown of a real signal. Our
engine already provides it; the open-source value is methodological (ArturSepp's as-of rolling
estimation + realized-turnover costing). Apply it *on top of* a carry or momentum book.

---

## Theme 5 — Classic TA systems (breakout / MA cross / Donchian / RSI)

This is where the "backtest evidence" is loudest and the edge is weakest.

- **`jsn-l/bitcoin-momentum-backtest`, `michaelwhl0925/Backtesting-Momentum-Trading-Strategy`:**
  Single-coin MA-crossover backtests. In-sample, single asset, grid-tuned lookbacks. Textbook
  curve-fit demos — no OOS, no cost sensitivity, no cross-section.
- **Donchian/Turtle breakout (blog-backtested, e.g. 20/55 on BTC daily):** The most *honest* of the
  TA family — trend-following genuinely captures crypto's fat-tailed bull runs — but public results
  are single-asset, in-sample, and rarely net of realistic cost/funding. Win rate 30-40%, winners
  3-5× losers is the standard (survivorship-flattered) claim.
- **Freqtrade strategy repos (e.g. `NostalgiaForInfinity`):** Large, actively-used, but heavily
  parameter-tuned to recent regimes; community-known to degrade out-of-regime. Framework is
  excellent; the *strategies* are not evidence of edge.

**Theme verdict:** **Predominantly curve-fit.** The one durable idea is **trend-following as a
convexity/tail-capture overlay** (Donchian/breakout), which has cross-asset support in the CTA
literature — but express it *cross-sectionally* (breakout strength as a rank signal across our 25
perps) rather than as a single-coin timing system, and always test net of our funding+cost model.
The walk-forward paper below shows the sobering truth: a properly OOS-tested EMA crossover only
*matches* buy-and-hold with lower drawdown — it does not beat it.

---

## Theme 6 — Walk-forward / OOS methodology worth emulating

### `tmr-crypto/wf_optim_crypto_analysis` (arXiv 2602.10785) — **best methodology in survey**
- **Setup:** Strict split — **global training** (Feb-2018→Sep-2019) optimized freely; **unseen
  period** (Nov-2019→Aug-2021) evaluated **exactly once** to avoid data-mining bias.
- **Innovation:** Treats **walk-forward window *lengths* as an optimization variable** (9 train ×
  9 test lengths = 81 combos), building a Sharpe grid, then **smooths the grid** (a cell's neighbors
  vote) to pick robust window pairs rather than the single lucky peak.
- **Base strategy:** EMA crossover (fast ∈ {5..30}, slow ∈ {40..200}), optimized on **BTC only**,
  then parameters applied **unchanged** to ETH/BNB (a real cross-asset generalization test).
- **Costs:** 0.1%/trade (0.2% on a long→short flip); break-even sensitivity ≈ 0.4%.
- **Significance:** Two bootstraps — (1) vs 1,000 random EMA combos, (2) trade-block shuffling —
  both significant at 5%.
- **Headline finding:** In-sample everything beats buy-and-hold; **out-of-sample the strategy only
  matches buy-and-hold with lower drawdown / higher information ratio.** A *blend* of the strategy +
  buy-and-hold beat everything with ~50% less drawdown.
- **What to emulate:** (i) grid-smoothing to pick robust params instead of the peak; (ii) optimize
  on one asset, validate on others unchanged; (iii) evaluate the unseen window **once**; (iv) block-
  shuffle bootstrap for significance; (v) honest reporting that OOS ≈ buy-and-hold. This aligns with
  our design: **bounded climb on Train, single-shot `evaluate` gate downstream, OOS removed from the
  auto-loop.** The "optimize on BTC, apply to ETH/BNB" trick is a cheap generalization check we can
  bake into review.

### `ArturSepp/OptimalPortfolios` (see Theme 4) — as-of rolling estimation, weight drift, realized-
turnover costing. The portfolio-construction analogue of good walk-forward hygiene.

### `coin-test/coin-test` — 9★, framework
- Multi-currency backtester with slippage/fees, `dataset.split(percent=0.75)` train/test, and a
  **GARCH synthetic-data generator** (stress-test a strategy on simulated paths, not just the one
  historical path). **No funding-rate support.** Framework only (one MACD example).
- **Verdict:** The **GARCH synthetic-path idea** is worth emulating as a robustness check
  (does the edge survive on resampled/simulated vol regimes?). Not a strategy source.

---

## Frameworks (context, not strategies)

| Framework | Funding handling | Walk-forward | Relevance to us |
|---|---|---|---|
| **freqtrade** (+FreqAI) | Yes — refactored funding-fee accounting, dry-run/live parity | Community WFA tooling | Best reference for *correct funding accounting in backtest*; our engine already does this |
| **vectorbt** (`marketcalls/vectorbt-backtesting-skills`) | Maker/taker + funding cost modeling, 12 templates | Manual | Cost-modeling reference; fast vectorized cross-sectional |
| **NautilusTrader** | Perp funding/margin/no-expiry semantics | Event-driven | Closest engine philosophy to ours (causal replay) |
| **coin-test** | No | train/test split + GARCH synthetic | Synthetic-path robustness idea |
| **Lumibot / btrccts / backtrader** | Partial | No | Generic; nothing crypto-funding-specific |

**Takeaway:** Frameworks confirm that funding-as-financing (our model) is the correct approach and
that realistic cost modeling is the differentiator between honest and curve-fit results. None
provides a strategy with proven edge; they provide plumbing and, occasionally (coin-test, tmr-crypto),
good robustness methodology.

---

## Plausible economic edge vs curve-fit demo (explicit split)

**Plausible economic edge (adapt these):**
1. **Cross-sectional funding carry** — rank our 25 perps by realized funding; long low/negative-
   funding, short high-funding. Rooted in a real crowding/risk premium (`aperiodic/unravel` reports
   multi-factor Sharpe ≈ 2 combining carry + momentum, top-50-mcap, daily rank, top/bottom 20%,
   inverse-vol weight). Buildable directly from `funding_8h`.
2. **Cross-sectional momentum** — 30-day-ish return rank across our perps (Fisjo/tanish35 mechanics,
   crypto-shortened lookback). Cross-asset-validated edge; long-biased to avoid the weak short leg.
3. **Single-venue spot-perp basis carry** — long spot / short perp on the same coin when funding is
   positive (`ynhy513` spec). Real carry; our engine captures it natively as financing on one NAV.
4. **Vol-targeting / ERC risk overlay** — no standalone alpha, but a robust wrapper (ArturSepp).

**Curve-fit demos / no evidence (do not chase):**
- Single-coin MA/Donchian/RSI timing backtests (jsn-l, michaelwhl0925, Moe-Dada) — in-sample,
  cost-blind, single asset.
- Crypto pairs cointegration (fraserjohnstone, coderaashir, muMAJJI) — unstable, author-acknowledged
  fragility, no funding on short leg.
- Cross-venue funding-arb bots (aoki-h-jp exec, 50shadesofgwei, ksmit323, ARBOT, okbitok) —
  economically real but **un-buildable on our single-venue data** and evidence-free.
- Freqtrade tuned strategy packs — excellent framework, regime-overfit strategies.

---

## How to re-express the winners as our target book

- **XS funding carry:** signal `s_i = −rank(funding_i)` (short high-funding); weights =
  vol-scaled cross-sectional z, top/bottom quantile → signed book, `0` for the middle. Bounded
  params: lookback for funding smoothing (1-7 funding events), quantile fraction (10-30%), rebalance
  spacing (per-funding-event → daily), inverse-vol on/off. Data: `funding_8h`, `crypto_perp_1min`.
- **XS momentum:** `s_i = past-return_i` over L∈[3d,30d] skipping last k bars; same quantile→book.
  Bounded params: L, skip k, quantile, long-only vs capped-short. Data: `crypto_perp_1min`.
- **Basis carry:** per basis-ready coin, target `+w` spot and `−w` perp when funding>threshold
  (nets to ~0 delta; NAV earns funding − costs). Bounded params: funding entry/exit thresholds,
  `basis_pct` cap, per-coin cap. Data: `crypto_spot_1min`, `crypto_perp_1min`,
  `crypto_spot_perp_basis_1min`, `funding_8h`. (13 basis-ready coins.)
- **Overlay:** apply engine vol-target / ERC-style inverse-vol on top of any of the above; keep the
  weighting in the foundation's risk-budget operator, not in `strategy.py`.

All four are pure functions of our fields, cross-sectional-first, and fit the bounded-climb
autoresearch surface (edit signal logic + a few bounded params; symbols/window/costs/objective
stay read-only).

---

## Sources

**Funding / basis:**
- [aoki-h-jp/funding-rate-arbitrage](https://github.com/aoki-h-jp/funding-rate-arbitrage) (304★, detection toolkit)
- [ynhy513/funding-rate-arbitrage](https://github.com/ynhy513/funding-rate-arbitrage) (single-venue basis-carry spec)
- [stephenpeters/delta_neutral_strategies](https://github.com/stephenpeters/delta_neutral_strategies) (Hyperliquid, backtester, early)
- [50shadesofgwei/funding-rate-arbitrage](https://github.com/50shadesofgwei/funding-rate-arbitrage) (DEX↔DEX template)
- [ksmit323/funding-rate-arbitrage](https://github.com/ksmit323/funding-rate-arbitrage) (hackathon, cross-DEX)
- [IrakliXYZ/ARBOT](https://github.com/IrakliXYZ/ARBOT) (spot-futures, unverified APY)
- [Alex-bitok/okbitok-arbitrage-bot](https://github.com/Alex-bitok/okbitok-arbitrage-bot) (Bybit↔KuCoin)

**Cross-sectional / trend momentum:**
- [Fisjo/momentum-strategy-backtest](https://github.com/Fisjo/momentum-strategy-backtest) (12-1 XS, in-sample)
- [tanish35/Momentum-Investing](https://github.com/tanish35/Momentum-Investing) (11★, 6-factor composite, FIP + skew)
- [alpacahq/notebooks](https://github.com/alpacahq/notebooks) (9★, XS momentum crypto bot)
- [sapk806/cross_sectional_factor_backtest_project](https://github.com/sapk806/cross_sectional_factor_backtest_project)

**Pairs / stat-arb:**
- [fraserjohnstone/pairs-trading-backtest-system](https://github.com/fraserjohnstone/pairs-trading-backtest-system) (crypto cointegration, author caveat)
- [coderaashir/Crypto-Pairs-Trading](https://github.com/coderaashir/Crypto-Pairs-Trading)
- [muMAJJI/Trading---Pair-Trading](https://github.com/muMAJJI/Trading---Pair-Trading)

**Vol targeting / risk parity:**
- [ArturSepp/OptimalPortfolios](https://github.com/ArturSepp/OptimalPortfolios) (80★, methodology reference)
- [Moe-Dada/Multi-Asset-Portfolio-Crypto-Backtest](https://github.com/Moe-Dada/Multi-Asset-Portfolio-Crypto-Backtest) (2★, SMA demo)
- [LucasIsntCoding/risk-parity-portfolio](https://github.com/LucasIsntCoding/risk-parity-portfolio)
- [libolight/risk-parity](https://github.com/libolight/risk-parity)

**TA (curve-fit examples):**
- [jsn-l/bitcoin-momentum-backtest](https://github.com/jsn-l/bitcoin-momentum-backtest)
- [michaelwhl0925/Backtesting-Momentum-Trading-Strategy](https://github.com/michaelwhl0925/Backtesting-Momentum-Trading-Strategy)

**Walk-forward / OOS methodology:**
- [tmr-crypto/wf_optim_crypto_analysis](https://github.com/tmr-crypto/wf_optim_crypto_analysis) + [arXiv 2602.10785](https://arxiv.org/html/2602.10785) (double-OOS, grid-smoothing, block-bootstrap)
- [coin-test/coin-test](https://github.com/coin-test/coin-test) (9★, GARCH synthetic paths, train/test split)

**Frameworks:**
- [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade), [robcaulk/freqai](https://github.com/robcaulk/freqai)
- [marketcalls/vectorbt-backtesting-skills](https://github.com/marketcalls/vectorbt-backtesting-skills)
- [NautilusTrader](https://nautilustrader.io/) · [Lumiwealth/lumibot](https://github.com/Lumiwealth/lumibot) · [btrccts/btrccts](https://github.com/btrccts/btrccts)
- [wilsonfreitas/awesome-quant](https://github.com/wilsonfreitas/awesome-quant) (curated index)

**Methodology article:**
- [Cross-Sectional Alpha Factors in Crypto: 2+ Sharpe Without Overfitting](https://blog.aperiodic.io/p/cross-sectional-alpha-factors-in) (carry + momentum, top-50, daily rank, inverse-vol)
