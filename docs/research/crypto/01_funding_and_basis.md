# Crypto Perpetual Funding-Rate & Spot-Perp Basis Strategies — Research Brief

**Executive summary.** Perpetual funding and spot-perp basis are the *same underlying object* observed two ways: `basis_pct` is the continuous, un-clamped, minute-resolution premium of perp over spot; `funding_rate` is the clamped, 8-hourly *settled cash transfer* of (most of) that premium. Both are mechanically linked, so signals built on them are largely redundant in level and complementary in timing/resolution. The canonical academic result (Schmeling–Schrimpf–Todorov "Crypto Carry"; He–Manela "Fundamentals of Perpetual Futures") is that crypto carry is *large* (mean ~8%/yr, peaks 40–60%/yr), driven by retail leverage demand meeting scarce, friction-bound arbitrage capital — a genuine limits-to-arbitrage risk premium, **not** a free lunch. The bad news: the flagship BTC cash-and-carry Sharpe collapsed from ~6.5 (2020–25) to ~4.1 (2024) to **negative in 2025** as ETFs and delta-neutral products (Ethena) arbitraged the premium away. The residual edge is not in flagship BTC carry; it is in (1) the **cross-sectional funding tilt** across the 25 coins — especially alts where arb capital is scarcer and funding stays richer/more persistent, (2) **conditional/threshold timing** (only harvest when funding or basis is richly wide, sit out otherwise), and (3) **funding-crowding reversal** as a *directional* contrarian overlay at extremes. All three are parameterizable by a handful of bounded knobs, fit our data, and survive our cost floor only if entry is selective. The dominant tail risk is a basis/funding blowout during a leverage-flush cascade, which our vol-targeting will *amplify* on a delta-neutral book.

---

## 0. Mechanics primer — how funding, basis, and our engine relate

**The identity.** For a perpetual, the exchange charges longs (pays shorts) a funding rate roughly proportional to the premium of the perp mark over the spot/index price:

```
funding_rate_8h  ≈  clamp( (perp_price − index_price) / index_price  +  interest_component ,  ±cap )
basis_pct        =  (perp_price − spot_price) / spot_price          # continuous, per-minute, un-clamped
```

Consequences that drive everything below:

- **Sign coupling.** Positive basis → positive funding → **longs pay shorts** → *to collect funding you short the perp*. Negative basis → negative funding → shorts pay longs → *to collect you go long the perp*.
- **`basis_pct` leads `funding_rate`.** Basis updates every minute and is un-clamped; realized `funding_8h` is a lagged, clamped, discretized settlement of the premium that prevailed over the funding window. So `basis_pct` is a **higher-frequency forecast of the next funding settlement**, and `funding_8h` is the **actual cashflow** the book earns/pays.
- **Redundancy vs complementarity.** As *level* signals they are near-duplicates (correlation is high by construction). They diverge in *timing* (basis is faster) and at the *clamp* (when premium exceeds the exchange cap, basis keeps rising but funding saturates — a crowding tell). Combining them adds resolution, not an independent second factor. See §5.

**Annualizing funding.** `funding_rate` is per 8h settlement → 3/day → `funding_annualized ≈ funding_rate × 3 × 365 = funding_rate × 1095`. A `0.01%` (0.0001) 8h rate ≈ **10.95%/yr**.

**How our engine expresses these (target book).** Funding is modeled as financing/carry on the netted book, so carry strategies are first-class:

- **Delta-neutral cash-and-carry, coin i, positive funding:** emit `spot_i = +w`, `perp_i = −w`. Net price delta ≈ 0; the short perp leg accrues +funding as carry; the spread's only P&L is basis noise + funding. This is the Ethena/USDe shape.
- **Cross-sectional funding tilt (perp-only long-short):** short the high-funding perps (collect), long the low/negative-funding perps (collect), sized to ~dollar-neutral. Harvests the *funding cross-section*; residual is a coin-selection tilt, not per-coin delta-neutral.
- **Directional crowding-reversal:** a signed base target (`+`/`−`/`0`) on the perp alone, set contrarian to extreme funding/basis. No spot leg.

**Data-driven constraints to respect throughout.**
- `volume` is **base-asset** volume → USD ADV ≈ `volume × close`. Our ADV-based capacity/impact model consumes this; alts have thin books.
- Spot exists for 24 symbols from 2021-01-01; **basis-research-ready** = ADA, ATOM, BTC, DOGE, DOT, ETH, FET, LINK, RENDER, SOL, TIA, UNI, XRP (13). Non-basis-ready perps (APT, ARB, AVAX, BNB, INJ, MATIC, NEAR, OP, PEPE, SEI, SUI, WIF) can still run **funding-only** (perp-only) strategies.
- **Shorting spot is the asymmetric leg.** Long-spot/short-perp (harvest *positive* funding) is clean. Harvesting *negative* funding needs short-spot/long-perp — spot borrow is costly/constrained, so treat negative-funding harvest as either perp-only-directional or out-of-scope, and lean on the fact that funding is positive the large majority of the time.
- Zero-cost/zero-slippage runs are rejected → every candidate must clear a per-side fee + slippage floor. This is exactly the hurdle that kills naive minute-level basis mean-reversion.

---

## 1. Funding carry / harvest (delta-neutral cash-and-carry + funding-tilt basket)

**(a) Thesis & who's on the other side.** Perpetual funding is a persistent, positive-on-average premium that leveraged directional traders (retail, trend-chasers) pay for convenient leveraged long exposure, because spot-crypto is capital-intensive and true cash-and-carry arbitrage is constrained by fragmented margin, withdrawal/settlement latency, venue/counterparty risk, and (historically) regulatory barriers. Schmeling–Schrimpf–Todorov formalize this as an **inconvenience yield / limits-to-arbitrage risk premium**: fundamentals (rate differentials) are far too small and stable to explain carry's level or volatility. You are paid to warehouse the basis and bear the tail. The other side is the crowd of leveraged longs; your counterpart risk is the arbitrageur exodus during a flush.

**(b) Exact signal from our fields.**
- Per-coin carry signal: `carry_i = EWMA/mean(funding_rate_i over last N settlements)` from `funding_8h` (annualize ×1095). Optionally confirm with current `basis_pct_i` from `crypto_spot_perp_basis_1min`.
- Harvest gate: enter coin i only if `carry_i > θ_enter` (a funding richness threshold net of the cost floor); exit/flatten if `carry_i < θ_exit`.

**(c) Target book.**
- *Delta-neutral (13 basis-ready coins):* for each gated coin, `spot_i = +w_i`, `perp_i = −w_i`, with `w_i` from equal-risk or vol-inverse weights, rebalanced each funding window (8h) or daily. Idempotent netting means re-emitting the same targets trades nothing.
- *Funding-tilt basket (all 25 perps, no spot needed):* cross-sectionally rank by `carry_i`; `perp_i = −k` for top-quantile, `+k` for bottom-quantile, scaled to gross budget and ~dollar-neutral.

**(d) Datasets.** `funding_8h` (signal + carry accrual), `crypto_perp_1min` (perp leg + ADV), `crypto_spot_1min` (spot leg, delta-neutral variant only), `crypto_spot_perp_basis_1min` (`basis_pct` confirmation). `crypto_perp_1min_with_funding` for the joined settlement view.

**(e) Bounded autoresearch params.** `N` (funding lookback, e.g. 3–30 settlements), `θ_enter` / `θ_exit` (annualized funding thresholds, e.g. 5–40%), quantile fraction for the basket (top/bottom 20–40%), rebalance cadence (8h vs 24h), max coins held. All small, bounded, monotone knobs — ideal for a bounded robustness climb.

**(f) Edge / decay / capacity.** This is the **most-arbitraged** family. BTC-only carry Sharpe: **6.45 (2020–2025) → 4.06 (from 2024) → negative (2025)** (Coming of Age; Schmeling et al.). Mean funding ~8%/yr, vol ~0.8%. Spot BTC ETF launch cut BTC carry ~3pp. Verdict: **flagship BTC/ETH carry is largely arbitraged away; do not build there.** Residual edge is (i) **cross-sectional** — the highest-funding alts stay rich because arb capital is scarce and borrow/inventory is hard there, and (ii) **conditional** — average funding is thin, but the *right tail* of funding (wide-basis regimes) still pays. Capacity is the binding constraint: a ~50% APR dislocation on ~$500k OI supports only ~$20k before slippage; a 20% APR on ~$50M OI supports real size. So edge and capacity are inversely related — the richest carry is in the least-liquid alts.

**(g) Crash / tail risk.** Delta-neutral in price but **not** in basis. During a leverage flush the perp can gap away from spot, forcing a mark-to-market loss on the short-perp leg before it mean-reverts; simultaneously funding can flip hard negative. Because a delta-neutral book has tiny realized vol, our **vol-targeting will lever it aggressively**, magnifying the blowout — respect the leverage ceiling and stress the basis-gap scenario. Carry unwinds are self-reinforcing: Schmeling et al. show a 10% rise in standardized carry predicts a **22% rise in sell-liquidations / OI** over the next month.

**(h) Falsifiers.** (i) After the cost floor and ADV impact, net funding captured ≤ 0 out-of-sample. (ii) Performance is entirely a BTC/ETH artifact and vanishes cross-sectionally in alts. (iii) Returns are indistinguishable from short-vol / short-crash exposure (i.e., you're just selling tail insurance). (iv) The `θ_enter` gate never binds — i.e., unconditional harvest ≈ gated harvest, meaning no timing edge.

**(i) Citations.** Schmeling, Schrimpf & Todorov, *Crypto Carry* (BIS WP 1087; SSRN 4268371; Management Science 2024); He, Manela, Ross & von Wachter, *Fundamentals of Perpetual Futures* (arXiv 2212.06888); *Cryptocurrency as an Investable Asset Class: Coming of Age* (arXiv 2510.14435); Ethena funding-risk docs; Funding Arb HQ 2026 guide.

---

## 2. Funding mean-reversion & funding-crowding reversal (directional contrarian)

**(a) Thesis & who's on the other side.** Funding is **mean-reverting**, not a random walk: ADF tests reject a unit root, ACF/PACF decay, and negative-funding streaks are short (Ethena reports the longest negative streak was **13 days**). Extreme positive funding = crowded, over-leveraged longs paying up; this crowding is fragile because a modest adverse move triggers forced liquidations that cascade (a 2–3% spot move can force 15–30% drawdowns through leverage). So **extreme funding predicts a near-term reversal / snapback** of the *price*, and reversion of the *funding itself*. You are the contrarian providing liquidity to a crowd about to be flushed; the other side is the late, over-leveraged momentum trader. (This is a *directional* edge distinct from delta-neutral carry.)

**(b) Exact signal from our fields.**
- Crowding score: standardize funding, `z_fund_i = (funding_rate_i − mean_N) / std_N` from `funding_8h`; augment with `basis_pct_i` z-score (faster) and a short-horizon `close`-return run-up (momentum confirmation that positioning is stretched). No OI available → funding + basis + price *are* our crowding proxy.
- Contrarian trigger: when `z_fund_i` (and/or `basis_pct_i`) exceeds `+τ`, target **short** perp i; below `−τ`, target **long**; else `0`.

**(c) Target book.** Signed base target on the perp only: `perp_i = −s · clip(z_fund_i)` for longs-crowded, `+s` for shorts-crowded, `0` inside the band. Cross-sectional (fade the most-crowded coins) or per-coin time-series. Pair with an engine `RiskRule` stop/trailing to bound the "run over by momentum" tail. Rebalance each funding window or daily.

**(d) Datasets.** `funding_8h` (crowding signal), `crypto_perp_1min` (execution + price-confirmation + ADV), `crypto_spot_perp_basis_1min` (`basis_pct` faster confirmation). No spot leg required → **all 25 perps eligible**.

**(e) Bounded autoresearch params.** `N` (z-score window), `τ_enter` / `τ_exit` (entry/exit z-thresholds), holding horizon / cooldown, stop-loss & trailing distances, optional weight on price-momentum confirmation. Handful of bounded knobs.

**(f) Edge / decay / capacity.** Widely used as a sentiment/timing overlay; the *directional* extreme-funding reversal is real but **noisy and regime-dependent** — it works at genuine extremes and hurts in strong persistent trends (you fade a real move). Because it trades the perp only and fires at extremes, it has **more capacity than delta-neutral carry** and less crowding among systematic arbs (most treat funding as a filter, not a standalone signal). This is plausibly a better *residual-edge* home than pure carry, but with fatter tails. (The repo already carries a `crypto_perp_funding_crowding_reversal` line of work — treat that as prior art, not a fresh discovery.)

**(g) Crash / tail risk.** You are short crowded longs — usually right, occasionally run over by a blow-off top before it breaks. Symmetric danger going long deeply negative funding into a capitulation that keeps going. Stops/trailing are essential; without them the left tail is severe.

**(h) Falsifiers.** (i) Forward returns after extreme funding are not significantly negative (positive) net of costs OOS. (ii) Edge disappears once you require price-confirmation (i.e., it was just momentum in disguise). (iii) A simple always-in short-funding overlay dominates the reversal timing (no reversal alpha). (iv) All P&L comes from 2–3 dated cascade events (not a repeatable signal).

**(i) Citations.** *Two-Tiered Structure of Cryptocurrency Funding Rate Markets* (MDPI, Mathematics 2026); Inan, *Predictability of Funding Rates* (SSRN 5576424); Yellow.com "How Funding Rates Predict Crypto's Most Violent Reversals"; Gate crypto-wiki derivatives-signals; Ethena funding-risk docs (negative-streak stat); MetaMask funding-trend monitoring.

---

## 3. Funding momentum / persistence as a cross-sectional factor

**(a) Thesis.** Funding is autocorrelated: a coin paying high funding now tends to keep paying (persistence) — which is *why* the cross-sectional carry tilt in §1 works. As a **return** predictor, funding *momentum* (funding trending up) is weak and mostly subsumed by price momentum and the carry level; the durable, exploitable property is **persistence of the funding level**, i.e. carry is sticky enough to harvest over multi-day horizons.

**(b) Exact signal.** Persistence-weighted carry: `signal_i = carry_i × persistence_i`, where `persistence_i` = trailing autocorrelation or sign-stability of `funding_rate_i` over the last `N` settlements (`funding_8h`). Down-weight coins whose funding is high but flip-floppy; up-weight coins with stable positive funding.

**(c) Target book.** Same cross-sectional perp-only long-short as §1(c)(basket), but weights scaled by `persistence_i`. Or use persistence purely as a **filter** on §1's delta-neutral harvest (only warehouse coins with stable funding).

**(d) Datasets.** `funding_8h` (level + persistence), `crypto_perp_1min` (execution/ADV). Spot optional (for the delta-neutral variant).

**(e) Bounded params.** Persistence lookback `N`, persistence weight/exponent, min-persistence filter threshold, blend weight vs raw carry.

**(f) Edge / decay / capacity.** Best treated as a **refinement/overlay** on §1, not a standalone family — it improves harvest quality (fewer whipsaws, lower turnover → better cost survival) rather than adding a new return source. Capacity/decay inherit from §1.

**(g) Tail risk.** Persistence breaks precisely in regime shifts (the flush), so a persistence filter can lull you into the highest-funding alt right before it snaps — same left tail as §1, possibly concentrated.

**(h) Falsifiers.** (i) Adding persistence weighting does not improve net-of-cost Sharpe vs raw carry. (ii) `funding momentum` (Δfunding) adds nothing beyond funding *level* and price momentum. (iii) Turnover reduction is illusory once thresholds are cost-tuned.

**(i) Citations.** *Two-Tiered Structure...* (MDPI, 2026, autocorrelation/half-life); Liu, Tsyvinski & Wu / Bianchi cryptocurrency factor models (C-3/C-4: market, size, momentum, value — funding not among the surviving cross-sectional factors); *A Trend Factor for the Cross Section of Cryptocurrency Returns* (JFQA 2024).

---

## 4. Spot-perp basis trades (carry, momentum, mean-reversion, crowding proxy)

**(a) Thesis.** `basis_pct` is the continuous premium; four sub-strategies:
- **Basis carry** — economically identical to funding carry (long spot / short perp when basis positive). *Redundant with §1*; the only reason to use basis over funding is the minute-resolution entry timing.
- **Basis mean-reversion** — basis z-score reverts intraday; fade wide basis expecting convergence.
- **Basis momentum** — a widening basis reflects strengthening leverage demand that persists short-term (spot-based basis/basis-momentum has cross-sectional predictive power in commodities and, more weakly, crypto).
- **Basis as crowding/sentiment proxy** — same role as funding in §2 but faster and un-clamped; the *basis-minus-implied-funding gap* (basis above the funding clamp) is a pure over-crowding tell.

**(b) Exact signal.** From `crypto_spot_perp_basis_1min`: `z_basis_i = (basis_pct_i − mean_N)/std_N`. Carry: level of `basis_pct`. Mean-reversion: fade `|z_basis| > τ`. Momentum: sign of trailing Δ`basis_pct`. Crowding gap: `basis_pct − funding_implied_premium`.

**(c) Target book.** Carry/crowding: as §1/§2. Mean-reversion (delta-neutral spread): when `z_basis_i > +τ`, `perp_i = −w, spot_i = +w` (expect basis to fall); when `< −τ`, reverse **only if spot-short is feasible**, else skip. Exit on `z_basis → 0`. Basis-ready 13 coins only.

**(d) Datasets.** `crypto_spot_perp_basis_1min` (signal), `crypto_spot_1min` + `crypto_perp_1min` (legs + ADV), `funding_8h` (the carry you actually collect while holding the spread; distinguishes true convergence P&L from funding P&L).

**(e) Bounded params.** z-window `N`, entry/exit `τ`, holding horizon, min-basis-width gate, rebalance cadence.

**(f) Edge / decay / capacity.** Minute-level basis mean-reversion looks great gross and **usually dies on the cost floor** (per-side fee + slippage on two legs, each round trip) — this family is the one most likely to be a fee-mirage; it only survives at **wide** thresholds with low turnover. Basis carry decays exactly as §1. Basis-as-crowding-proxy is the genuinely additive use (see §5). A basis-overlay on a spot BTC book has been shown to add modest alpha (e.g., harvesting basis only when it exceeds SOFR+300bps lifted a spot sleeve's Sharpe 1.33→1.51 with little added vol) — i.e., **conditional/threshold** harvesting, not always-on.

**(g) Tail risk.** Basis blowout / decoupling during dislocations (delisting, outage, oracle failure) — the mean-reversion bet is wrong exactly when it's largest, and the short-perp leg bleeds before rolling. Thin-spot alts (non-basis-ready set) are worst; stick to the 13.

**(h) Falsifiers.** (i) Net-of-two-leg-cost mean-reversion Sharpe ≤ 0 OOS. (ii) Basis signal adds nothing beyond funding (redundancy confirmed — see §5). (iii) Convergence P&L is actually just funding collected (mislabeled carry). (iv) Edge only exists below the cost floor.

**(i) Citations.** Amberdata "logs, hedge ratios, z-scores"; CFBenchmarks "Revisiting the Bitcoin Basis"; Luo & Xue *Spot-Based Basis and Basis Momentum* (SSRN 6546878); Boons & Prado *Basis-Momentum* (JF); TradingView krugermacro perp-spot-basis indicator.

---

## 5. Combining funding + basis + price — redundant or complementary?

**Level: redundant.** `funding_rate` and `basis_pct` are the clamped-slow and continuous-fast views of one premium; their *levels* correlate ~1 by construction. Stacking both as level signals double-counts. Pick funding for the *cashflow you earn* and basis for *when to act*.

**Timing/resolution: complementary.** `basis_pct` (1-min) forecasts the next `funding_8h` settlement; use basis to enter/exit inside the 8h window and funding to size the carry. The **basis-minus-funding-clamp gap** is a genuinely orthogonal signal: when premium exceeds the exchange cap, funding saturates while basis keeps climbing → maximal crowding → strongest §2 reversal setup.

**Price is the independent third axis.** Funding/basis measure *positioning*; `close`-return momentum measures *realized trend*. Their **interaction** is where the informative signal lives:
- High funding **+** strong up-trend = crowded but confirmed → carry-harvest, don't fade yet.
- High funding **+** stalling/rolling-over price = crowded **and** exhausted → §2 reversal (fade).
- This "funding × price-divergence" gate is the single most-cited practitioner refinement and the most promising *combination* on our data.

**Design rule for us:** one carry/positioning signal (funding level, basis for timing) + one price/trend signal (`close` momentum) + their interaction. Adding basis *and* funding *and* their gap is fine; adding basis and funding as two separate level factors is not.

---

## 6. Cross-cutting: alpha decay, capacity, crash/tail, cost survival

- **Decay is real and dated.** BTC carry Sharpe 6.45→4.06→negative (2020–25/2024/2025). Institutionalization (ETFs, Ethena-style delta-neutral funds) compressed the flagship premium. Any candidate must be validated on **recent** windows, not just the rich 2020–2022 era, and should assume the easy BTC/ETH carry is gone.
- **Capacity ⟂ edge.** Richest funding/basis is in illiquid alts; our base-volume-derived USD ADV + impact model will (correctly) penalize size there. Expect the sweet spot to be mid-cap alts, not BTC (too arbitraged) or micro-caps (too thin).
- **Crash/liquidation cascade is the dominant tail.** Extreme funding/OI crowding precedes violent flushes; a 2–3% spot move → 15–30% leverage-driven drawdowns; carry rises predict sell-liquidation surges. Delta-neutral books hide this in low realized vol → vol-targeting over-levers → blowout. **Always stress a synchronized basis-gap + funding-flip + slippage-widening scenario** and lean on the engine `RiskRule` + leverage ceiling.
- **Cost survival.** Funding accrues per-minute but round-trip fees are paid at entry/exit; illiquid round-trips can cost ~$220, and a 20bps spread on $10k needs ~3.7 days of funding just to break even. **Selective, low-turnover, wide-threshold** entry is the only way these clear our (mandatory, non-zero) cost floor. Naive minute-level basis reversion generally fails here.
- **What survives, honestly.** Not flagship carry. Plausible residual edge: (1) *conditional cross-sectional* funding harvest in alts, gated on richness + persistence + capacity; (2) *funding-crowding reversal* at genuine extremes with price confirmation and hard stops; (3) *funding × price-divergence* as an overlay. Everything else is either arbitraged away (BTC carry) or a cost mirage (minute basis reversion).

---

## 7. Recommended autoresearch candidates (ranked)

1. **Conditional cross-sectional funding-tilt basket (perp-only long-short).** Best data fit (uses `funding_8h` + `crypto_perp_1min`, all 25 coins, no spot-short problem), few bounded knobs, roughly dollar-neutral. Edge lives in alt cross-section + threshold gating. Biggest risk: crowded, decayed — must beat cost floor on recent windows and not be a hidden short-crash bet.
2. **Funding-crowding reversal (directional, perp-only).** Distinct *directional* edge, more capacity, less arb-crowded, all 25 coins. Prior art exists in-repo. Biggest risk: fat left tail when it fades a real trend — needs stops + price confirmation.
3. **Delta-neutral cash-and-carry harvest, conditional, 13 basis-ready coins.** The textbook trade; cleanest economic story; uses spot+perp+funding+basis. Biggest risk: basis-blowout tail amplified by vol-targeting, and thin residual edge post-2024.
4. **Funding × price-divergence overlay** (combination per §5) — as a refinement layer on top of 1 or 2 rather than a standalone.

---

## 8. Citations

**Academic / working papers**
- Schmeling, M., Schrimpf, A., & Todorov, K. *Crypto Carry.* BIS Working Papers No. 1087 (2023); Management Science (2024). https://www.bis.org/publ/work1087.pdf · https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4268371 · https://pubsonline.informs.org/doi/10.1287/mnsc.2024.05069 · (summary) https://cepr.org/voxeu/columns/crypto-carry-market-segmentation-and-price-distortions-digital-asset-markets
- He, S., Manela, A., Ross, O., & von Wachter, V. *Fundamentals of Perpetual Futures.* arXiv:2212.06888 (2022). https://arxiv.org/abs/2212.06888
- *Cryptocurrency as an Investable Asset Class: Coming of Age.* arXiv:2510.14435 (2025). https://arxiv.org/abs/2510.14435 · https://arxiv.org/html/2510.14435v4
- *The Two-Tiered Structure of Cryptocurrency Funding Rate Markets.* Mathematics (MDPI) 14(2):346 (2026). https://www.mdpi.com/2227-7390/14/2/346
- *Exploring Risk and Return Profiles of Funding Rate Arbitrage on CEX and DEX.* ScienceDirect S2096720925000818. https://www.sciencedirect.com/science/article/pii/S2096720925000818
- Inan, E. *Predictability of Funding Rates.* SSRN 5576424 (2025). https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5576424
- Zhang, T. *Funding Rate Mechanism in Perpetual Futures.* SSRN 6185958 (2026). https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6185958
- *Designing funding rates for perpetual futures in cryptocurrency markets.* arXiv:2506.08573. https://arxiv.org/html/2506.08573v1
- Ackerer, D., Hugonnier, J., & Jermann, U. *Perpetual Futures Pricing.* arXiv:2310.11771; Mathematical Finance (2026). https://arxiv.org/pdf/2310.11771 · https://finance.wharton.upenn.edu/~jermann/AHJ-main-10.pdf
- *A Trend Factor for the Cross Section of Cryptocurrency Returns.* Journal of Financial and Quantitative Analysis (2024). https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/trend-factor-for-the-cross-section-of-cryptocurrency-returns/4C1509ACBA33D5DCAF0AC24379148178
- Bianchi, D., et al. *A Factor Model for Cryptocurrency Returns.* http://wp.lancs.ac.uk/fofi2022/files/2022/08/FoFI-2022-056-Daniele-Bianchi.pdf
- Luo, Z., & Xue, S. *Spot-Based Basis and Basis Momentum in Commodity Futures Markets.* SSRN 6546878. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6546878
- Boons, M., & Prado, M. *Basis-Momentum.* Journal of Finance. https://assets.super.so/e46b77e7-ee08-445e-b43f-4ffd88ae0a0e/files/450c1d44-aa3f-46a9-bda1-945e917e26dd.pdf

**Industry / data-vendor**
- Glassnode Research, *Strategy Watch #5* (2026). https://research.glassnode.com/strategy-watch-05-2026/
- Amberdata, *Constructing Your Strategy with Logs, Hedge Ratios, and Z-Scores.* https://blog.amberdata.io/constructing-your-strategy-with-logs-hedge-ratios-and-z-scores
- CF Benchmarks, *Revisiting the Bitcoin Basis.* https://www.cfbenchmarks.com/blog/revisiting-the-bitcoin-basis-how-momentum-sentiment-impact-the-structural-drivers-of-basis-activity
- Binance Blog, *What Is Futures Funding Rate and Why It Matters.* https://www.binance.com/en/blog/futures/what-is-futures-funding-rate-and-why-it-matters-421499824684903247
- Ethena Labs, *Funding Risk.* https://docs.ethena.fi/solution-overview/risks/funding-risk · ChainArgos USDe case study: https://www.chainargos.com/risks-for-synthetic-stablecoins-ethena-labs-usde-case-study/
- MetaMask, *Perpetual futures funding: frequency & strategies* / *Monitoring funding-rate trends.* https://metamask.io/news/perpetual-futures-funding-frequency-strategies · https://metamask.io/news/monitoring-perps-funding-rate-trends-signals

**Practitioner**
- Funding Arb HQ, *2026 Funding Arb Guide.* https://fundingarbhq.com/funding-arb-guide-2026-infrastructure-tools-strategy
- Buildix, *Cash and Carry in Crypto.* https://www.buildix.trade/blog/cash-and-carry-crypto-delta-neutral-funding-rate-strategy-2026
- Hyperdash, *Basis Trading and Funding Rate Arbitrage on Perps.* https://hyperdash.com/learn/basis-trading-and-funding-rate-arbitrage-on-perps
- ArbitrageScanner, *Crypto Funding Rate Arbitrage: Delta-Neutral Guide.* https://arbitragescanner.io/blog/crypto-funding-rate-arbitrage-guide
- Wundertrading, *Crypto Funding Rate Arbitrage.* https://wundertrading.com/journal/en/funding-arbitrage
- Yellow.com, *How Funding Rates Predict Crypto's Most Violent Reversals.* https://yellow.com/learn/how-to-read-funding-rates-crypto-reversals
- Gate, *How to Interpret Crypto Derivatives Signals: Funding, OI, Liquidations.* https://www.gate.com/crypto-wiki/article/how-to-interpret-crypto-derivatives-market-signals-funding-rates-open-interest-and-liquidation-data-explained-20251227

*Note on numbers: Sharpe/return figures are as reported in the cited sources over their stated samples (mostly Binance BTC/ETH, 2020–2025) and are gross of our engine's mandatory cost floor and ADV impact; treat them as upper bounds, not expectations for our net-of-cost backtests.*
