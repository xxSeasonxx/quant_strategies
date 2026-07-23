# Academic Literature on Systematic Crypto Strategies Buildable from OHLCV, Funding, and Basis

**Scope.** This is an annotated bibliography and synthesis of peer-reviewed and high-quality working-paper evidence on *profitable, systematic* cryptocurrency strategies that can be built from **only** daily/minute OHLCV, realized perpetual funding rates, and spot-perp basis. It maps each strand to our data (25 large-cap perps + spot + `funding_8h` + basis, 1-min bars, 2020-03 → 2026-04) and engine (pure target-book strategies, cross-sectional portfolios, funding modeled as financing, vol-targeting, causal replay).

**Executive summary.**
- The **cross-section of crypto returns** is real and published in top journals (Liu-Tsyvinski-Wu, *JF* 2022; Liu-Tsyvinski, *RFS* 2021), but the strongest long-short premia (size, volume, short-term reversal) live in **micro-caps we do not and should not trade**; the honest critical literature shows these largely **vanish after costs, survivorship/delisting bias, and short-leg frictions**.
- The most **robust, cost-surviving, large-coin** effects are **trend / time-series momentum / moving-average** signals (Detzel et al. *FM* 2021; Fieberg et al. *JFQA* 2024 CTREND; Shen-Urquhart-Wang *Financial Review* 2022) and **funding/basis carry** (He-Manela-Ross-von Wachter 2022; Todorov-Schmeling-Schrimpf "Crypto Carry" 2025). These are the two themes best aligned with both the evidence *and* our data.
- **Cross-sectional momentum is fragile** (Grobys-Sapkota, *Economics Letters* 2019 find it insignificant); **short-term reversal is a liquidity/micro-cap artifact** that flips to *momentum* in the largest coins (Zaremba et al. 2021) — a warning that matters directly for our large-cap-only universe.
- **Volatility management** (Moreira-Muir, *JF* 2017) is a portfolio *overlay* with strong general evidence and is native to our engine; the crypto **low-volatility anomaly** itself is *not* reliably present (Burggraf-Rudolf 2020).
- **Seasonality** (day-of-week, weekend, intraday/overnight) is documented and minute-data-buildable, but effect sizes are small, unstable, and the highest data-snooping risk of any theme.
- **Buildability is gated far more by our universe (25 large-cap coins, no market cap, no order book) than by signal logic.** We sit precisely in the large-cap subset where the factor zoo is weakest but where trend and carry are strongest — which should shape prioritization.

---

## 1. The Cross-Section of Crypto Returns and the Factor Zoo

**Liu, Tsyvinski & Wu (2022), "Common Risk Factors in Cryptocurrency," *Journal of Finance* 77(2), 1133–1177.** The canonical crypto factor paper. Using weekly returns on coins above a market-cap floor (2014–2018 sample), they test crypto analogues of ~25 equity return predictors and find **ten characteristics form long-short strategies with sizable, significant excess returns**. A **three-factor model — crypto market (CMKT), size (CSMB), and momentum (CMOM)** — prices essentially all of them; size and momentum long-short legs are the dominant sources. *Cost treatment:* minimal (weekly rebalanced, VW, no realistic-fee stress). *Replication note:* the cross-section is genuine but is **built on a broad universe including many small coins**; the size premium in particular is a small-coin phenomenon (see §8). Strong in-sample, weaker once micro-caps and costs are stripped.
DOI: 10.1111/jofi.13119 · NBER w25882 · SSRN 3379131.

**Liu & Tsyvinski (2021), "Risks and Returns of Cryptocurrency," *Review of Financial Studies* 34(6), 2689–2727.** Establishes that crypto (BTC, ETH, XRP) returns are driven by **crypto-specific factors**: a strong **time-series momentum** effect (past 1-week return predicts next-week return) and **investor-attention proxies** (Google search, Twitter posts) that forecast returns; **network-adoption factors** are priced, **production/cost factors are not**. *Replication note:* the TS-momentum result is one of the most replicated in the field; the attention and network results are **not buildable from our data** (no search/social/on-chain feeds).
DOI: 10.1093/rfs/hhaa113 · NBER w24877.

**Shen, Urquhart & Wang (2020), "A three-factor pricing model for cryptocurrencies," *Finance Research Letters* 34, 101248.** ~1,700 coins, Apr-2013 → Mar-2019. Proposes **market + size + *reversal*** (not momentum) as the third factor; smaller coins earn higher returns and short-term reversal strengthens as size falls. Outperforms a crypto-CAPM. *Replication note:* directly contradicts LTW's *momentum* third factor — the size/reversal effects are again **concentrated in small, illiquid coins**; the subsequent "momentum or reversal" debate (Jia-Goodell-Shen and others) remains unresolved and universe-dependent.
DOI: 10.1016/j.frl.2019.07.021.

**Zhang, Li, Xiong & Wang (2021), "Downside risk and the cross-section of cryptocurrency returns," *Journal of Banking & Finance* 133.** Finds a **positive** relation between downside risk (downside beta, VaR/ES) and future returns — investors are compensated for downside exposure — partly explained by limits-to-arbitrage. *Replication note:* downside beta is estimable from returns alone (buildable), but again panel includes many small coins; whether the premium survives in a 25-large-cap universe is untested and doubtful.
ScienceDirect: pii S0378426621002053 · RePEc: eee/jbfina/v133y2021.

**Burggraf & Rudolf (2020), "Cryptocurrencies and the low volatility anomaly," *Finance Research Letters* 36, 101683.** ~1,000 coins, 2013–2019. **No significant low-volatility premium** — in contrast to equities/bonds/commodities. *Replication note:* important negative result. Do **not** assume the equity low-vol anomaly transfers; if anything crypto rewards *higher* idiosyncratic vol/downside risk (consistent with Zhang et al.). More recent work is mixed and dataset-dependent.
ScienceDirect: pii S154461232030667X.

**Bianchi, Babiak & Dickerson (2022), "Trading volume and liquidity provision in cryptocurrency markets," *Journal of Banking & Finance* 142; and Bianchi & Babiak, "A Factor Model for Cryptocurrency Returns" (working paper).** Documents that **expected returns from liquidity provision are amplified in smaller, more volatile, less liquid pairs**, and the **interaction of lagged return × volume** predicts returns — a microstructure-flavored liquidity/reversal channel. *Replication note:* the tradeable part (return×volume interaction) is buildable from OHLCV+volume, but the *premium* is again a small/illiquid-coin effect; in our large-cap set the sign can invert (see Zaremba et al., §4).
SSRN 3239670.

**Buildability (this section):** Momentum, reversal, volatility, downside-beta, and volume signals are all **buildable from OHLCV+volume**. **Size is NOT buildable** — we have no market cap or circulating supply; dollar-volume (ADV) is a *liquidity* proxy, not size. **Network/production and attention factors are NOT buildable** (no on-chain, no sentiment). Critically, the premia these papers document are **strongest exactly where we cannot trade** (micro-caps), so importing the factor zoo wholesale into a 25-coin universe is the central replication trap.

---

## 2. Trend, Time-Series Momentum, and Moving Averages (the most robust theme)

**Detzel, Liu, Strauss, Zhou & Zhu (2021), "Learning and predictability via technical analysis: Evidence from bitcoin and stocks with hard-to-value fundamentals," *Financial Management* 50(1).** Shows **ratios of price to its 5–200-day moving averages forecast daily Bitcoin returns in- and out-of-sample**, and MA-based trading generates **economically significant alpha and Sharpe gains over buy-and-hold**. Grounded in an equilibrium model of rational learning without fundamentals — a genuine *reason* trend should work in an asset with no cash flows. *Cost treatment:* discussed; BTC costs are low enough to preserve the edge. *Replication note:* one of the best-supported single-asset results; single-asset (BTC), so cross-sectional breadth is untested here.
DOI: 10.1111/fima.12310 · SSRN 3115846.

**Fieberg, Liedtke, Poddig, Walker & Zaremba (2024), "A Trend Factor for the Cross-Section of Cryptocurrency Returns," *Journal of Financial and Quantitative Analysis*.** Builds **CTREND**, an ML aggregation of **28 technical signals** (moving averages, momentum oscillators, volume- and volatility-based indicators) across horizons, on 3,000+ coins. The trend signal **predicts the cross-section, is not subsumed by known factors, is robust across sub-periods/market states, survives transaction costs, and persists for large, liquid coins.** *Replication note:* the strongest "survives costs *and* works in liquid coins" claim in the literature — the single most encouraging paper for our universe. Uses ML to combine signals; our bounded-param climb can approximate with a handful of the strongest signals rather than the full ensemble.
SSRN 4601972 · Cambridge Core (JFQA, Sep 2024).

**Shen, Urquhart & Wang (2022), "Bitcoin intraday time series momentum," *Financial Review* 57(2), 319–344.** **The first half-hour return positively predicts the last half-hour return**; predictability concentrates in the highest-volume/volatility opening sessions. **Abnormal returns remain positive after fees, especially for leveraged investors.** *Replication note:* directly buildable from our 1-min bars; intraday effects are more fragile to microstructure and our bar granularity (1-min, no tick/quote), but the core signal is clean. A high-value, distinctly crypto (24/7) result.
DOI: 10.1111/fire.12290.

**Hudson & Urquhart (2021), "Technical trading and cryptocurrencies," *Annals of Operations Research* 297, 191–220.** Tests **~15,000 technical trading rules** (5 classes) across two BTC markets + three coins; finds **significant predictability/profitability**, with break-even transaction costs **above** realistic crypto costs, and better risk-adjusted returns and drawdown protection than buy-and-hold. *Replication note:* headline caveat is **massive multiple testing / data snooping** — 15,000 rules demands White's Reality Check / Hansen SPA before any rule is trusted. Treat as evidence that *trend/MA rules as a class* work, not that any specific mined rule will.
DOI: 10.1007/s10479-019-03357-1 · SSRN 3387950.

**Also relevant:** Liu-Tsyvinski (2021, §1) — weekly TS-momentum; and general crypto TS-momentum working papers reporting daily-strategy Sharpe > 1.2 with counter-cyclical diversification (out-of-sample verified). *Note:* several report cross-sectional momentum works less reliably than time-series in crypto (consistent with §3).

**Buildability (this section):** **Fully buildable as-is.** MA ratios, breakouts, oscillators, and TS-momentum come straight from OHLCV; intraday variants from 1-min bars. The engine's vol-targeting and stop/trailing rules complement trend naturally. **This is the theme where the academic evidence and our data align best.** Primary risk to internalize: Hudson-Urquhart-style over-mining — prefer a *small* set of economically motivated signals over a swept grid.

---

## 3. Cross-Sectional Momentum and Its Fragility

**Grobys & Sapkota (2019), "Cryptocurrencies and momentum," *Economics Letters* 180, 6–10.** 143 coins, 2014–2018. **Finds no significant momentum payoff** (overall weekly payoff 0.90%, insignificant), arguing the market is more efficient than earlier studies implied. *Replication note:* the key counter-weight to LTW's CMOM — cross-sectional momentum in crypto is **regime- and universe-sensitive** and does not reliably clear significance. Buildable, but expect instability.
DOI: 10.1016/j.econlet.2019.03.028.

**Synthesis with §1:** LTW find CMOM prices the cross-section; Grobys-Sapkota find CS momentum insignificant; Shen-Urquhart-Wang prefer *reversal* over momentum as the third factor. The reconciliation in the literature: **time-series momentum/trend (§2) is robust; cross-sectional momentum is fragile and horizon/universe-dependent.** For a 25-coin book, TS-momentum and a cross-sectional trend rank are more defensible than classic 1–4 week CS-momentum sorts.

---

## 4. Short-Term Reversal, Overreaction, and Liquidity

**Zaremba, Bilgin, Long, Mercik & Szczygielski (2021), "Up or down? Short-term reversal, momentum, and liquidity effects in cryptocurrency markets," *International Review of Financial Analysis* 78.** 3,600+ coins, 2015–2021. **Low prior-day-return coins outperform high ones (daily reversal)** — but the effect is **driven by illiquidity** and is **cross-sectionally conditional on liquidity: the largest, most tradeable coins show daily *momentum*, not reversal.** *Replication note:* the most important paper for our universe — it says the classic short-term reversal premium **is a micro-cap/illiquidity artifact and flips sign in exactly the liquid coins we trade.** Do not build naive daily-reversal sorts on 25 large caps; if anything, short-horizon *continuation* is the large-cap phenomenon.
ScienceDirect: pii S1057521921002349 · RePEc: eee/finana/v78y2021.

**Related overreaction/liquidity-provision evidence** (Bianchi-Babiak-Dickerson, §1) reinforces that reversal profits reflect **liquidity shocks and adverse-selection compensation** concentrated in small, volatile pairs.

**Buildability (this section):** Buildable from OHLCV+volume, **but with an explicit sign warning**: reversal premia belong to illiquid coins; our large-cap universe is where they weaken or invert. A defensible large-cap use is *reversal after extreme volume/vol shocks* on individual liquid coins, treated as mean-reversion, not a cross-sectional micro-cap sort.

---

## 5. Perpetual Funding and Spot-Perp Basis (Carry)

**He, Manela, Ross & von Wachter (2022), "Fundamentals of Perpetual Futures," working paper (arXiv:2212.06888; SSRN 4301150; widely cited).** Derives **no-arbitrage prices for perpetual futures** (frictionless) and **bounds under trading costs**. Empirically, **crypto perp-spot deviations are larger than in traditional FX, comove across coins, and shrink over time**, and an **implied arbitrage (long spot / short perp when funding is positive, and vice versa) earns high Sharpe ratios.** *Cost treatment:* explicitly bounds mispricing by trading costs — the rigorous framework for reading funding as a tradeable premium. *Replication note:* the cleanest theoretical basis for our funding/basis data; edge decays over time and is capacity-limited by borrow/short costs. Our engine models funding as financing and can hold spot vs perp (for the 13 basis-ready symbols).

**Todorov, Schmeling & Schrimpf (2025), "Crypto Carry" (BIS/CEPR).** Documents **"crypto carry" (futures-spot gap) averaging ~7–8%/yr, occasionally >40% annualized**, that **fundamentals (rate differentials) cannot explain**. Carry is **demand-driven**: smaller, trend-following, leverage-seeking traders push up net long positioning and thus funding; introduction of CME micro-BTC futures **raised** carry ~11%, and spot-BTC-ETF launch (Jan 2024) **cut** carry 3–5pp. *Replication note:* strong, recent, institutionally credible; frames funding as a **crowding/positioning signal**, not just a yield — directly supportive of a funding-carry *and* a funding-as-sentiment (crowding-reversal) reading of `funding_8h`.
CEPR VoxEU column, Dec 2025.

**Ackerer, Hugonnier & Jermann (2024), "Perpetual Futures Pricing," working paper (Wharton).** Formal pricing model for perpetuals linking funding mechanics to the spot-perp gap. *Use:* theoretical grounding for how funding should track basis, useful for constructing a fair-value residual signal.

**Supporting empirical:** working papers report a **crypto carry (long high-funding / short low-funding perps, or short-perp/long-spot when funding is high) with very high full-sample Sharpe that decays sharply post-2023 and turned negative in 2025** — a strong reminder that the raw carry is **alpha-decaying and regime-dependent**, not a free yield.

**Buildability (this section):** **Buildable as-is and uniquely well-matched to our data.** `funding_8h` is exactly the realized funding series these papers use; `crypto_spot_perp_basis_1min` gives basis for 13 symbols; the engine finances perp positions and can run spot-vs-perp books. This is the **only major theme where we have the *distinctive* data (funding, basis) that most equity-trained researchers lack** — our comparative advantage. Primary risk: documented **alpha decay** and dependence on borrow/short capacity (partly outside our data).

---

## 6. Seasonality and Calendar Effects

**Caporale & Plastun (2019), "The day of the week effect in the cryptocurrency market," *Finance Research Letters* 31, 258–269.** Finds **some evidence of a day-of-week effect** (notably anomalous Monday/weekend behavior in BTC) exploitable by a simple trading rule in-sample. *Replication note:* small, unstable across sub-periods and coins; classic calendar-anomaly fragility.

**Day-of-week / volatility timing (e.g., Kinateder-Papavassiliou and others, *Research in International Business & Finance* / *FRL*).** Consensus: **no robust classical day-of-week return effect, but lower weekend *volatility* and higher early-week volatility** — more useful for vol-timing than directional bets.

**Weekend effect (crypto-stock spillover).** Recent work finds **negative crypto weekend returns predict weak Monday US-equity returns** — interesting cross-asset, but the equity leg is outside our data.

**Intraday / overnight seasonality.** Documented **time-of-day effects** (specific hours systematically stronger/weaker) and an **overnight-vs-intraday split tied to US market hours**. Overlaps with intraday TS-momentum (Shen-Urquhart-Wang 2022, §2). *Replication note:* minute-data-buildable but the **highest data-snooping surface** of any theme (hour-of-day × day-of-week × coin = hundreds of cells); demands multiple-testing discipline.

**Buildability (this section):** **Fully buildable as-is** from minute timestamps (day-of-week, hour-of-day, weekend flags). **But** effect sizes are small, unstable, and the multiple-testing risk is severe. Best used as a **conditioning/overlay** (e.g., vol-timing by weekend, or gating trend signals by session) rather than a standalone alpha.

---

## 7. Volatility Management

**Moreira & Muir (2017), "Volatility-Managed Portfolios," *Journal of Finance* 72(4), 1611–1644.** Scaling exposure **inversely to recent realized variance** (wₜ ∝ 1/σ²ₜ₋₁) raises Sharpe ratios and produces alpha across the market, value, momentum, profitability, and **currency carry** factors, because volatility spikes are **not** matched by proportional expected-return increases. *Replication note:* general, top-journal, and repeatedly replicated (with debate on out-of-sample real-time gains). *Not crypto-specific*, but the mechanism (vol clustering, weak vol-return tradeoff) is *stronger* in crypto.

**Crypto application.** The **crypto low-volatility anomaly is absent** (Burggraf-Rudolf 2020, §1), so do not expect a *cross-sectional* low-vol premium. But **volatility *managing* an existing signal** (trend, carry) is well-motivated and **native to our engine's vol-targeting**.

**Buildability (this section):** **Buildable as-is / native.** Realized vol from OHLCV; the engine already offers vol-targeting. Best deployed as an **overlay on trend/carry books**, not as a standalone low-vol factor.

---

## 8. Critical and Adversarial Literature (read before trusting any of the above)

**Ammann, Burdorf, Liebi & Stöckl (2022/2024), "Survivorship and Delisting Bias in Cryptocurrency Markets," SSRN 4287573.** 3,904 coins, 2014–2021. **Annualized survivorship/delisting bias ≈ 0.93% (value-weighted) but ≈ 62% (equal-weighted).** The **size premium is overestimated ~50%** in survival-conditioned samples, and **controlling for the bias, the one-week momentum premium disappears.** *Implication for us:* equal-weighted micro-cap results are **massively inflated**; our fixed large-cap, effectively value-weighted-scale universe is **far less exposed**, but we still carry **listing-date bias** (many of our 25 perps listed mid-sample) and must use a **point-in-time universe**.

**Fieberg, Liedtke & Zaremba (2024), "Cryptocurrency anomalies and economic constraints," *International Review of Financial Analysis* 94.** 500+ major coins, 2017–2023. **Size and volume anomalies originate in negligible micro-caps; momentum survives in large coins but incurs substantial trading costs and extracts alpha mostly from the *short* leg**; anomalies concentrate where **limits to arbitrage are high** and **decline over time**. Prescription: **focus on long positions, account for costs, avoid hard-to-trade coins, emphasize recent performance.** *Implication:* the single best "how to not fool yourself" checklist for our setting — and it is **by the same authors as the CTREND trend factor**, lending their pro-trend result extra credibility.
ScienceDirect: pii S1057521924001509 · RePEc: eee/finana/v94y2024.

**General multiple-testing / data-snooping.** Hudson-Urquhart's 15,000 rules (§2) and the day-of-day/hour seasonality surface (§6) are textbook data-mining hazards; the equity-side warnings (Harvey-Liu-Zhu "…and the Cross-Section of Expected Returns"; Bailey-López de Prado deflated Sharpe / backtest overfitting) apply directly. **Any mined signal needs a multiple-testing-aware haircut before it is believed.**

**Synthesis of the critical strand:** After honest treatment of **(a) survivorship/delisting, (b) transaction costs, (c) short-leg/borrow frictions, and (d) multiple testing**, the crypto anomalies that **survive in a large-cap, long-biased, cost-realistic setting** are essentially **trend/time-series momentum and funding/basis carry** — the same two themes flagged as best-supported for our data. The factor-zoo cross-section (size, volume, short-term reversal) largely does **not** survive in our universe.

---

## Buildability Map (evidence → our data/engine)

| Strategy / signal | Key citation | Buildable with our data? | Notes / constraint |
|---|---|---|---|
| Time-series momentum / MA ratios (per-coin) | Detzel et al. 2021; Liu-Tsyvinski 2021 | **As-is** | Daily OHLCV; strongest large-coin evidence |
| Trend factor (multi-signal, cross-sectional rank) | Fieberg et al. 2024 (CTREND) | **Proxy** | Build a small signal subset; full ML ensemble heavier but signals are OHLCV+volume |
| Intraday time-series momentum | Shen-Urquhart-Wang 2022 | **As-is** | 1-min bars; more microstructure-fragile |
| Funding carry (long high-funding / short low, or short-perp vs spot) | He et al. 2022; Todorov et al. 2025 | **As-is** | `funding_8h` is the exact series; engine finances perps |
| Basis carry / perp-spot arbitrage | He et al. 2022; Ackerer et al. 2024 | **As-is (13 symbols)** | `basis_pct` available for 13 basis-ready coins |
| Funding as crowding/positioning signal | Todorov et al. 2025 | **As-is** | Funding = demand/leverage proxy; supports crowding-reversal reading |
| Volatility management overlay | Moreira-Muir 2017 | **Native** | Engine vol-targeting; overlay on trend/carry |
| Cross-sectional momentum (1–4wk sorts) | Liu-Tsyvinski-Wu 2022 vs Grobys-Sapkota 2019 | **As-is but fragile** | Insignificant/unstable; prefer TS-momentum |
| Short-term reversal (cross-sectional) | Shen et al. 2020; Zaremba et al. 2021 | **As-is but sign-flipped** | Premium is micro-cap/illiquidity; large caps show continuation |
| Volume / liquidity-provision effect | Bianchi et al. 2022 | **Proxy** | Base-asset volume + num_trades; no order book/taker split |
| Downside-risk / idiosyncratic-vol premium | Zhang et al. 2021; Burggraf-Rudolf 2020 | **As-is but unlikely** | Estimable from returns; unproven in large-cap set |
| Day-of-week / weekend / intraday seasonality | Caporale-Plastun 2019; intraday work | **As-is** | Minute timestamps; small, unstable, high snooping risk — use as overlay |
| Size factor (market cap) | Liu-Tsyvinski-Wu 2022 | **NOT buildable** | No market cap / circulating supply; ADV is a liquidity proxy, not size |
| Network / on-chain / production factors | Liu-Tsyvinski 2021 | **NOT buildable** | No on-chain data |
| Investor-attention (search/social) predictors | Liu-Tsyvinski 2021 | **NOT buildable** | No sentiment/search feeds |

---

## References

1. Ackerer, D., Hugonnier, J., & Jermann, U. (2024). *Perpetual Futures Pricing.* Working paper, The Wharton School. https://finance.wharton.upenn.edu/~jermann/AHJ-main-10.pdf
2. Ammann, M., Burdorf, T., Liebi, L., & Stöckl, S. (2022/2024). *Survivorship and Delisting Bias in Cryptocurrency Markets.* SSRN Working Paper 4287573. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4287573
3. Bianchi, D., Babiak, M., & Dickerson, A. (2022). Trading volume and liquidity provision in cryptocurrency markets. *Journal of Banking & Finance* 142, 106547. SSRN 3239670. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3239670 · https://www.sciencedirect.com/science/article/abs/pii/S0378426622001418
4. Bianchi, D., & Babiak, M. (2022). *A Factor Model for Cryptocurrency Returns.* Working paper. http://wp.lancs.ac.uk/fofi2022/files/2022/08/FoFI-2022-056-Daniele-Bianchi.pdf
5. Burggraf, T., & Rudolf, M. (2020). Cryptocurrencies and the low volatility anomaly. *Finance Research Letters* 36, 101683. https://www.sciencedirect.com/science/article/abs/pii/S154461232030667X
6. Caporale, G. M., & Plastun, A. (2019). The day of the week effect in the cryptocurrency market. *Finance Research Letters* 31, 258–269. https://www.mendeley.com/catalogue/087b7d50-c015-3c99-b805-49853be85bb9/
7. Detzel, A., Liu, H., Strauss, J., Zhou, G., & Zhu, Y. (2021). Learning and predictability via technical analysis: Evidence from bitcoin and stocks with hard-to-value fundamentals. *Financial Management* 50(1), 107–137. DOI: 10.1111/fima.12310. https://onlinelibrary.wiley.com/doi/abs/10.1111/fima.12310 · SSRN 3115846: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3115846
8. Fieberg, C., Liedtke, G., Poddig, T., Walker, T., & Zaremba, A. (2024). A Trend Factor for the Cross-Section of Cryptocurrency Returns. *Journal of Financial and Quantitative Analysis.* https://jfqa.org/2024/09/20/a-trend-factor-for-the-cross-section-of-cryptocurrency-returns/ · SSRN 4601972: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4601972 · https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/trend-factor-for-the-cross-section-of-cryptocurrency-returns/4C1509ACBA33D5DCAF0AC24379148178
9. Fieberg, C., Liedtke, G., & Zaremba, A. (2024). Cryptocurrency anomalies and economic constraints. *International Review of Financial Analysis* 94. https://www.sciencedirect.com/science/article/abs/pii/S1057521924001509 · RePEc: https://ideas.repec.org/a/eee/finana/v94y2024ics1057521924001509.html
10. Grobys, K., & Sapkota, N. (2019). Cryptocurrencies and momentum. *Economics Letters* 180, 6–10. DOI: 10.1016/j.econlet.2019.03.028. https://www.sciencedirect.com/science/article/pii/S0165176519301077
11. He, S., Manela, A., Ross, O., & von Wachter, V. (2022). *Fundamentals of Perpetual Futures.* arXiv:2212.06888. https://arxiv.org/abs/2212.06888 · SSRN 4301150: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4301150
12. Hudson, R., & Urquhart, A. (2021). Technical trading and cryptocurrencies. *Annals of Operations Research* 297, 191–220. DOI: 10.1007/s10479-019-03357-1. https://link.springer.com/article/10.1007/s10479-019-03357-1 · SSRN 3387950: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3387950
13. Liu, Y., & Tsyvinski, A. (2021). Risks and Returns of Cryptocurrency. *Review of Financial Studies* 34(6), 2689–2727. DOI: 10.1093/rfs/hhaa113. https://academic.oup.com/rfs/article-abstract/34/6/2689/5912024 · NBER w24877: https://www.nber.org/papers/w24877
14. Liu, Y., Tsyvinski, A., & Wu, X. (2022). Common Risk Factors in Cryptocurrency. *Journal of Finance* 77(2), 1133–1177. DOI: 10.1111/jofi.13119. https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.13119 · NBER w25882: https://www.nber.org/papers/w25882 · SSRN 3379131: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3379131
15. Moreira, A., & Muir, T. (2017). Volatility-Managed Portfolios. *Journal of Finance* 72(4), 1611–1644. DOI: 10.1111/jofi.12513. https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12513 · NBER w22208: https://www.nber.org/papers/w22208
16. Shen, D., Urquhart, A., & Wang, P. (2020). A three-factor pricing model for cryptocurrencies. *Finance Research Letters* 34, 101248. DOI: 10.1016/j.frl.2019.07.021. https://www.sciencedirect.com/science/article/abs/pii/S1544612319304519
17. Shen, D., Urquhart, A., & Wang, P. (2022). Bitcoin intraday time series momentum. *Financial Review* 57(2), 319–344. DOI: 10.1111/fire.12290. https://onlinelibrary.wiley.com/doi/abs/10.1111/fire.12290
18. Todorov, K., Schmeling, M., & Schrimpf, A. (2025). *Crypto Carry: Market segmentation and price distortions in digital asset markets.* BIS Working Paper / CEPR VoxEU column (22 Dec 2025). https://cepr.org/voxeu/columns/crypto-carry-market-segmentation-and-price-distortions-digital-asset-markets
19. Zaremba, A., Bilgin, M. H., Long, H., Mercik, A., & Szczygielski, J. J. (2021). Up or down? Short-term reversal, momentum, and liquidity effects in cryptocurrency markets. *International Review of Financial Analysis* 78. https://www.sciencedirect.com/science/article/pii/S1057521921002349 · RePEc: https://ideas.repec.org/a/eee/finana/v78y2021ics1057521921002349.html
20. Zhang, W., Li, Y., Xiong, X., & Wang, P. (2021). Downside risk and the cross-section of cryptocurrency returns. *Journal of Banking & Finance* 133. https://www.sciencedirect.com/science/article/abs/pii/S0378426621002053 · RePEc: https://ideas.repec.org/a/eee/jbfina/v133y2021ics0378426621002053.html

---

*Compiled 2026-07-22. Citations verified against publisher/NBER/SSRN/RePEc records via web search; exact article numbers or forthcoming-status of the two working papers (He et al.; Todorov et al.) may update on final publication. Headline statistics are reported as stated by the authors and are pre-cost / broad-universe unless noted — read every figure through the §8 critical lens before use.*
