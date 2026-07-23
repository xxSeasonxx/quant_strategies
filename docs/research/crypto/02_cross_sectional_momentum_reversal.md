# Crypto Cross-Sectional & Time-Series Momentum / Reversal / Factor Strategies

**Scope:** buildable factor, momentum, and reversal strategies for our engine (pure target-book,
cross-sectional multi-instrument, vol targeting, per-side bps costs, ADV capacity, funding-as-financing),
constrained to our **price/volume-only** crypto data (25 perp survivors, 1-min OHLCV, base-asset `volume`,
`num_trades`, realized `funding_8h`; **no market cap, OI, order book, on-chain, or sentiment**).

## Executive summary

- **Time-series momentum (per-symbol trend) is the single most robust and best-data-fit result in the crypto literature** and the one that survives realistic costs and our survivor universe. Cross-sectional (winners-minus-losers) momentum is *weaker* and — critically for us — its published Sharpes are **largely an artefact of coins that later died or delisted**, which our 25-survivor set does not contain.
- **Our universe is 25 large, liquid survivors.** The literature is unusually clear that *sign flips with liquidity*: large/liquid coins show short-horizon **momentum**, while short-term **reversal, size, Amihud-illiquidity, and MAX/lottery effects live almost entirely in micro-cap, illiquid, low-priced coins we do not trade**. Do not expect classic short-term reversal or a size/illiquidity premium to work on our set.
- **Survivorship bias is the dominant threat to every cross-sectional claim here.** Grobys–Sandretto (2026) show survivor-only momentum is statistically insignificant; Fieberg–Liedtke–Zaremba (2024) show anomaly alphas already decayed 9–76% by 2018–2022 and concentrate in hard-to-trade coins and *short* legs we cannot cheaply access.
- **Volatility management (Barroso–Santa-Clara style) is a cheap, few-knob Sharpe multiplier** that transfers to crypto, and our built-in `calibrate_vol` makes it near-free to add.
- **"Market-neutral" is a trap in crypto:** BTC/ETH dominate a single common factor; a naive dollar-neutral long-short still carries large residual market beta because betas are heterogeneous and time-varying. Neutralize explicitly.
- **Recommended build order:** (1) per-symbol TSMOM + vol target, (2) vol-managed overlay, (3) beta-neutralized cross-sectional momentum among the 25, (4) a low-volatility/BAB tilt as a momentum diversifier. Treat size, Amihud, MAX, and short-term reversal as **low-fit / likely-dead on our universe**.

---

## 0. Foundational asset-pricing backdrop (what the field agrees on)

- **Liu & Tsyvinski (2021, *RFS*), "Risks and Returns of Cryptocurrency":** cryptocurrency returns are driven by *crypto-specific* factors, not equity/macro production factors. **Strong time-series momentum** at 1–4 week horizons; investor-attention proxies (Google Trends) forecast returns. Establishes TSMOM as the headline predictable effect. Weekly data.
- **Liu, Tsyvinski & Wu (2022, *Journal of Finance*), "Common Risk Factors in Cryptocurrency":** a **three-factor model — crypto market (CMKT), size (CSMB), momentum (CMOM)** — prices the cross-section. They test 10+ characteristics that each form significant long-short strategies and show the 3-factor model spans them. Universe: coins with market cap **> $1M, 2014–2018**. **Size uses market cap** and momentum uses past 1–4 week returns. Implication for us: their size leg is **not reproducible** (no market cap) and lives in coins far smaller than ours.
- **Later factor extensions** add reversal and illiquidity factors (e.g., a four-factor CRm/CSMB/CLMW/CIHML model), but every added leg leans on small/illiquid coins.

**Takeaway:** the market factor is enormous and common; momentum is the durable cross-sectional/TS effect; size and illiquidity legs are structurally out of reach for a 25-large-cap-survivor book.

---

## 1. Time-Series Momentum / Trend-Following (TSMOM) — **highest conviction, best fit**

**Thesis & who's on the other side.** Trends persist because of gradual information diffusion, under-reaction, and herding/attention flows (Liu–Tsyvinski attention channel). The counterparties are mean-reversion/liquidity providers and discretionary traders fading extended moves; you pay them in whipsaw during range-bound regimes and at sharp trend reversals.

**Why it fits us best.** TSMOM is computed **per symbol from that symbol's own past return** — no cross-section, no ranking, no dependence on a broad universe. It is therefore **immune to the survivorship problem** that guts cross-sectional momentum, and it is exactly the effect Liu–Tsyvinski (2021) and Han–Kang–Ryu (2023) call "strong." Han–Kang–Ryu's central finding under realistic costs: **TS momentum evidence is strong; cross-sectional is weak**, and many XS portfolios get liquidated or lose significance once costs and intrabar price paths are modeled.

**Exact signal from our fields (perp close only).**
- Resample `crypto_perp_1min` (or `crypto_perp_1min_with_funding`) close to a decision cadence (e.g., daily or 12h bars).
- Formation return `r_L(t) = close(t)/close(t−L) − 1` over lookback `L` (literature sweet spot ≈ **1–8 weeks**; Bitcoin trend work also uses 10/20/50-day MA crossovers, Grayscale).
- Signal `s_i(t) = sign(r_L)` (binary) or `r_L / σ_i` (risk-scaled, à la Moskowitz–Ooi–Pedersen). Optionally gate with a moving-average crossover (`SMA_fast > SMA_slow`).
- Vol estimate `σ_i(t)` from trailing close-to-close (or Garman–Klass using our OHLC) return vol.

**Target-book expression.**
- Per symbol: `w_i = s_i(t) · (σ_target / σ_i(t))`, then apply the engine's gross/net leverage budget and `calibrate_vol` to hit a portfolio vol target. This is a **long/short, per-symbol standing target** — idempotent netting handles the flip when the sign changes.
- As a portfolio it is naturally **net-long-biased in bull regimes** (all signs positive) — that residual is *intended* directional trend exposure, not a bug, but disclose it.

**Required datasets.** `crypto_perp_1min` or `crypto_perp_1min_with_funding` (funding modeled as financing — matters because holding a trend position for weeks accrues funding). No other data needed.

**Bounded param set for autoresearch (few knobs).**
- `lookback_days ∈ {7, 14, 21, 30, 45, 60}`
- `signal ∈ {sign, vol_scaled}`
- `vol_lookback_days ∈ {14, 30, 60}`
- `rebalance ∈ {daily, 2d, weekly}`
- optional `ma_gate ∈ {off, 10/50, 20/100}`

**Realistic edge / decay / capacity.** Robust across studies but **crowded and decaying**: Fieberg et al. (2024) find alphas 9–76% lower in 2018–2022 vs earlier. Capacity is high on our universe (BTC/ETH/SOL etc. are deep); weekly-to-daily rebalancing keeps turnover and ADV impact modest. Expect a real-world **Sharpe of ~0.7–1.2** after costs on a liquid survivor set, well below the 2+ headline numbers (those use full/dead-coin universes and daily volume-weighting; e.g., Huang–Sangiorgi–Urquhart volume-weighted TSMOM reports 0.94%/day, SR 2.17 — treat as an upper bound inflated by universe breadth).

**Crash / tail behavior.** TSMOM is *long volatility* — it historically cushions sustained drawdowns (it flips short in downtrends) but bleeds in sharp V-shaped reversals and chop. Crypto's violent mean-reverting spikes (deleveraging cascades) are the main enemy; funding can turn sharply against a crowded trend.

**Falsifiers.**
- After realistic per-side costs and funding, net Sharpe on the 25 survivors ≤ 0 across all bounded lookbacks.
- No monotonic relationship between `L` and performance (pure noise-mining).
- Performance concentrated in a single symbol/regime (e.g., only 2020–2021 BTC bull).

**Citations:** Liu–Tsyvinski (2021); Han–Kang–Ryu (2023); Moskowitz–Ooi–Pedersen TSMOM (equity/futures origin); Huang–Sangiorgi–Urquhart (2024); Grayscale trend report.

---

## 2. Volatility-Managed / Risk-Managed Momentum (factor timing overlay) — **cheap Sharpe multiplier**

**Thesis & other side.** Momentum returns are heteroskedastic and its own realized variance predicts (negatively) its future risk-adjusted return; scaling exposure down when recent momentum vol is high avoids the worst of "momentum crashes" and raises the Sharpe. In equities this is Barroso–Santa-Clara (2015, *JFE*), "Momentum Has Its Moments" — scale by inverse trailing 6-month realized variance to a target; roughly **doubles the Sharpe**. Counterparty: you give up some upside convexity and take basis risk on the vol estimate.

**Crypto evidence.** A 2025 replication ("Cryptocurrency market risk-managed momentum strategies") finds risk management **raises average weekly return 3.18% → 3.47% and Sharpe 1.12 → 1.42** — but, unlike equities, the gain comes from **augmented returns, not crash avoidance**, because crypto lacks the prolonged momentum crashes seen in equities. Caveat: Cederburg et al. (2020) show vol-management often *fails* out-of-sample across 100+ equity portfolios — so treat the overlay as a hypothesis to test, not a guarantee.

**Exact signal / target-book.** This is an **overlay on Strategy 1 (or 3)**: multiply the whole book's gross exposure by `σ_target / σ_realized(momentum_pnl, window)`, or simply lean on the engine's `calibrate_vol` targeting the *strategy's own* trailing PnL vol. One extra knob.

**Bounded params.** `vol_target_window ∈ {4w, 8w, 12w}`, `target_vol ∈ {engine default ± band}`. Nothing else.

**Fit / capacity / tail.** Free on our engine, no new data, no capacity cost (it only *reduces* gross in turbulent periods). Main risk: over-fitting the vol window; and it can de-risk right before a rebound.

**Falsifier.** Vol-managed variant does not beat the un-managed base strategy on net-of-cost Sharpe across the bounded windows → drop the overlay.

**Citations:** Barroso–Santa-Clara (2015); "Cryptocurrency market risk-managed momentum strategies" (2025); "Cryptocurrency momentum has (not) its moments" (2025); Cederburg et al. (2020, skeptic).

---

## 3. Cross-Sectional Momentum (Winners-minus-Losers among the 25) — **moderate conviction, heavy caveats**

**Thesis & other side.** Rank coins by past return; long recent winners, short recent losers, expecting continuation. Providers of the return are under-reacting momentum traders; takers are contrarians and, in crypto, the *dead-coin distribution* — losers that keep falling (delisting) historically fed the short leg, which we cannot replicate.

**The survivorship problem (read before building).** This is our single biggest risk.
- **Grobys & Sandretto (2026), "On survivor cryptocurrency momentum":** only **9 of the top-100 (Dec 2016) survived to 2024**; a survivor-only momentum portfolio (SCMP) has **statistically insignificant** payoffs. Their conclusion: momentum profits are "an artefact of coins that are only temporarily accessible for trading." **Our 25-survivor perp set is exactly the SCMP case.**
- **Ammann–Burdorf–Liebi–Stöckl (2022):** survivorship/delisting bias inflates equal-weighted crypto portfolio returns by ~**62%/yr** (0.93%/yr value-weighted); the size premium is overstated ~50%.
- **Fieberg–Liedtke–Zaremba (2024):** cross-sectional anomalies concentrate in micro-caps and *short* legs, incur heavy costs, and decayed 9–76% into 2018–2022.

**The counter-evidence that keeps it on the table.** Zaremba et al. (2021), "Up or down?": among **large, liquid coins** the short-horizon pattern is **momentum, not reversal** (weekly momentum t = 2.33 for large/liquid vs reversal t = −7.31 for small/illiquid). So a cross-sectional *momentum* tilt restricted to liquid coins is directionally defensible where classic reversal is not. Reported (full-universe) XS-momentum magnitudes: winners ≈1.65%/wk (SR 1.28), losers ≈0.62%/wk, **WML ≈0.52%/wk (SR ≈0.67)** — expect materially less on 25 survivors.

**Exact signal from our fields.**
- Weekly formation return per symbol (as §1), rank the 25.
- Long top tercile/quintile, short bottom; equal-weight within leg, or scale by inverse vol.
- **Neutralize** (see §8): demean signals cross-sectionally and/or beta-adjust so the book is not a disguised BTC bet.

**Target-book expression.** Dollar-neutral (Σw ≈ 0) standing targets, top-K long / bottom-K short, weekly rebalance, engine gross-leverage + `calibrate_vol`. With only 25 names, use terciles (≈8 long / 8 short) not deciles.

**Bounded params.** `lookback_days ∈ {7,14,21,30}`, `holding/rebalance ∈ {weekly, 2w}`, `n_per_leg ∈ {5,6,8}`, `weighting ∈ {equal, inverse_vol}`, `neutralization ∈ {demean, beta_neutral}`.

**Edge / decay / capacity.** Likely **thin after costs**; short leg on our perps is cheap to *hold* (funding) but the classic loser-continuation alpha depended on dead coins. Turnover higher than TSMOM. Capacity fine on 25 liquid perps.

**Crash / tail.** Momentum crashes on sharp market rebounds (short winners squeeze); crypto rebounds are violent → pair with §2 vol management. Residual beta can dominate PnL if not neutralized.

**Falsifiers.** WML net-of-cost Sharpe ≤ 0 on the 25; PnL explained (R² high) by BTC/market beta after neutralization → it was never cross-sectional alpha. Long-only leg carries all the alpha (short leg dead) → not a true CS effect on our set.

**Citations:** Liu–Tsyvinski–Wu (2022); Grobys–Sandretto (2026); Ammann et al. (2022); Fieberg–Liedtke–Zaremba (2024); Zaremba et al. (2021); Han–Kang–Ryu (2023); Dobrynskaya (crypto momentum & reversal); "Cryptocurrency Factor Momentum."

---

## 4. Short-Term Reversal (1-day to 1-week) — **low fit on our universe; document why**

**Thesis & other side.** Short-horizon reversal = compensation for **liquidity provision**: a coin that spiked on uninformed order flow reverts as inventory-bearing market makers unwind. You *are* the liquidity provider; the risk is adverse selection (the move was informed) and inventory during a trend.

**Why it likely does NOT work for us.** The crypto reversal is overwhelmingly an **illiquid, small-cap** effect:
- Zaremba et al. (2021): daily/weekly **reversal exists only for small/illiquid coins (weekly t = −7.31)**; **large, liquid coins show momentum instead (t = +2.33).** Our 25 are the large/liquid bucket.
- Farag–Luo–Yarovaya–Zięba (2025, *JBF*), "Returns from liquidity provision": reversal profits are "primarily concentrated in trading pairs with lower levels of market activity … amplified in smaller, more volatile, less liquid pairs." Predictable by VIX, realized variance, risk aversion, crash/tail risk, Tether liquidity innovations.

**If tested anyway.** Signal = negative of last-1-to-5-day return, cross-sectionally demeaned; long biggest losers / short biggest winners; daily rebalance. **Expect it to invert to momentum on our liquid set** — which is why §3's momentum tilt is the better expression of short-horizon cross-section for us. A defensible variant: use `num_trades`/volume to build a within-universe *relative* illiquidity/activity conditioner and only take reversal in the least-active of our 25 — but with 25 large coins the dispersion is small.

**Bounded params (if tested).** `lookback ∈ {1d,3d,5d}`, `rebalance ∈ {daily, 3d}`, `activity_filter ∈ {off, bottom-third num_trades}`.

**Crash/tail.** Reversal blows up when a "loser" keeps falling on real news (adverse selection) — exactly the delisting/deleveraging events crypto produces.

**Falsifier (expected outcome).** On the 25 liquid survivors the short-term reversal Sharpe is ≤ 0 (or the sign flips to momentum) → confirms it is an illiquid-coin effect and should be shelved.

**Citations:** Zaremba et al. (2021); Farag et al. (2025); Grobys–Sapkota (2019, no significant crypto momentum premium in early work — the reconciliation is liquidity).

---

## 5. Low-Volatility / Betting-Against-Beta / Idiosyncratic-Vol — **defensible price-only diversifier**

**Thesis & other side.** Leverage-constrained/attention-driven investors overpay for high-beta, high-vol "exciting" assets, so low-risk assets earn higher risk-adjusted returns (Frazzini–Pedersen BAB). Counterparty: leverage-constrained longs of hot coins.

**Crypto evidence (mind the sign — it is contested).**
- **Low realized-vol premium:** "Revisiting the low-volatility anomaly in cryptocurrency markets" (2026) documents a **low-vol premium post-2017** — low realized-vol coins outperform on a risk-adjusted basis across formation/holding windows. Supports a low-vol long tilt.
- **Idiosyncratic vol, opposite sign:** Zhang & Li (2020) find IVOL is **positively** related to the cross-section of crypto returns (>500 coins) — high-IVOL coins earn *higher* returns — but with **no time-series predictability**. This conflicts with the low-total-vol result, so **the sign is regime/measure-dependent**; test both directions and do not assume the equity sign.
- **Downside beta is priced:** Zhang & Li (2021, *JBF*), 900+ coins weekly 2014–2018 — crypto returns are very sensitive to *market* drawdowns (downside beta), less so to other assets. Suggests a downside-beta or semibeta sort.

**Exact signal from our fields.** Per symbol: trailing realized vol (close-to-close or Garman–Klass from OHLC), or beta to an equal-weight/BTC benchmark (regress symbol returns on market return over trailing window). Rank the 25; **long low-vol/low-beta, short high-vol/high-beta**, then **lever the low-vol leg up / high-vol leg down to equalize risk** (the BAB construction) — our `calibrate_vol` and leverage budget do this natively.

**Target-book.** Beta-weighted long-short (long-leg scaled by `1/β_low`, short-leg by `1/β_high`) or a simpler low-vol long tilt. Weekly-to-monthly rebalance (vol/beta are slow-moving → low turnover, high capacity).

**Bounded params.** `vol/beta_lookback ∈ {30d,60d,90d}`, `construction ∈ {BAB_beta_neutral, low_vol_long_tilt}`, `n_per_leg ∈ {5,8}`, `rebalance ∈ {weekly,2w,monthly}`.

**Edge / decay / capacity.** Low turnover → cheap, high capacity, good momentum diversifier (BAB and momentum are lowly correlated). Edge is modest and sign-uncertain in crypto.

**Crash/tail.** BAB is *short* high-beta — it can be squeezed in explosive altcoin rallies; low-vol tilts lag badly in euphoric bull runs. Manage with §2.

**Falsifiers.** Low-vol and high-vol legs earn the same risk-adjusted return; BAB PnL is just inverse-market-beta exposure (no residual alpha); sign is unstable across the two bounded lookback halves.

**Citations:** Frazzini–Pedersen (BAB, origin); "Revisiting the low-volatility anomaly in cryptocurrency markets" (2026); Zhang & Li (2020, IVOL); Zhang & Li (2021, downside risk, *JBF*); "Good/bad volatility and the cross-section of crypto returns" (2023).

---

## 6. MAX / Lottery Effect — **low fit; and the crypto sign is inverted**

**Thesis.** In equities, high maximum-daily-return ("lottery") stocks *underperform* (investors overpay for lottery payoffs). **In crypto the effect inverts:** MAX is **positively** related to future returns ("MAX momentum").

**Evidence.** "Lottery-like preferences and the MAX effect in the cryptocurrency market" (2021, *Financial Innovation*): weekly raw / risk-adjusted return spread between **highest and lowest MAX deciles = 3.03% / 1.99%**, positive and significant; robust to holding period and MAX definition — but **concentrated in small-sized, low-priced coins**. So on our 25 large-cap survivors the effect is expected to be weak or absent.

**Exact signal.** MAX = max of daily returns over trailing month (from resampled OHLC). Rank; the crypto result says **long high-MAX, short low-MAX** — but note this collides with the low-vol premium (§5), so they partly offset. Given our universe, treat MAX as a **feature/conditioner** (e.g., avoid shorting the highest-MAX names in §3) rather than a standalone book.

**Bounded params.** `max_window ∈ {14d,30d}`, `n_max_days ∈ {1,3,5}` (MAX vs average-of-N-highest).

**Falsifier / expected outcome.** No monotone MAX-return relation across the 25 → confirms it is a small/low-price-coin phenomenon.

**Citations:** "Lottery-like preferences and the MAX effect in the cryptocurrency market" (2021); "Someone like you: lottery-like preference and the cross-section of crypto returns" (2024); Bali–Cakici–Whitelaw (equity MAX origin).

---

## 7. Size / Dollar-Volume / Amihud Illiquidity — **structurally out of reach; state the limitation**

**Thesis.** Small and illiquid assets earn a premium for size/liquidity risk. Crypto size (Liu–Tsyvinski–Wu CSMB) and illiquidity (Amihud) factors are real *in the full universe*.

**Why we can't build it well.**
- **No market cap.** Size must be proxied by **dollar volume = close × base `volume`**. The literature warns this proxy is contaminated: "dollar-volume volatility strongly correlates with size … primarily driven by differences in price levels of coins" — i.e., a dollar-volume size proxy mostly re-prices coin unit-price, not economic size.
- **The premium lives where we don't trade.** Fieberg et al. (2024): "size and volume anomalies originate from **micro-cap coins of negligible economic importance**." Our 25 are all large caps → **near-zero size dispersion**, so the sort has almost nothing to rank.
- **Amihud** = mean(|daily return| / daily dollar volume) is computable from our fields, but again it is a small/illiquid-coin effect and our survivors are the liquid tail.

**Only defensible use.** A **within-universe relative-illiquidity conditioner** (Amihud or `num_trades`/dollar-volume, ranked among the 25) used to (a) size down capacity-risky names or (b) tilt the reversal test in §4 — not as a standalone premium.

**Bounded params (if used as conditioner).** `amihud_lookback ∈ {7d,14d,30d}`.

**Falsifier / expected outcome.** Size/Amihud sorts among the 25 produce no significant spread → confirms the effect is micro-cap and non-tradeable for us.

**Citations:** Liu–Tsyvinski–Wu (2022, CSMB); Amihud (2002, origin); Fieberg–Liedtke–Zaremba (2024); "Trading volume and liquidity provision in cryptocurrency markets" (2022); "Momentum and liquidity in cryptocurrencies" (2019).

---

## 8. Neutralization & market-beta contamination (methodology owning-section for all cross-sectional books)

**The problem.** Crypto returns load heavily on **one dominant common factor** (the crypto market, proxied by BTC/ETH). A naive dollar-neutral (Σw = 0) long-short is **not** market-neutral because:
1. Betas are **heterogeneous** — a small-cap alt has beta ≫ 1 to BTC, so equal *dollar* weights leave large net *beta*.
2. Betas are **time-varying** and rise in stress ("everything correlates in a crash"), so residual beta spikes exactly when it hurts.
3. **BTC dominance / alt-season rotation** is itself a slow factor: XS momentum among alts can become a disguised "long alts, short BTC" dominance bet.

**Correct neutralization (in order of rigor).**
- **Cross-sectional demeaning:** subtract the equal-weight universe mean signal before ranking → removes the level, not the beta.
- **Beta-neutral construction (preferred):** estimate each symbol's trailing beta to an equal-weight universe (or BTC) return; set leg weights so **Σ(wᵢ·βᵢ) ≈ 0**, not just Σwᵢ ≈ 0. Our leverage budget + per-symbol weights support this directly.
- **Explicit market hedge:** carry an offsetting BTC/ETH (or equal-weight basket) position sized to cancel net book beta.
- **Report residual beta** of the final NAV path to an equal-weight crypto benchmark as a *validation gate* — a "market-neutral" strategy whose NAV has |beta| > ~0.2 is mislabeled.

**Falsifier for any "neutral" claim.** Regress strategy NAV returns on the equal-weight universe (and on BTC) — if R² is high and alpha insignificant, the "factor" was market beta.

**Citations:** Liu–Tsyvinski–Wu (2022, CMKT dominance); general BAB/neutralization methodology; arXiv "Spot Regressions with Candlesticks" (Bitcoin market-beta estimation).

---

## 9. Survivorship bias — how our 25-survivor universe biases every result

- Our set = coins that **survived and stayed liquid** → the exact population where Grobys–Sandretto (2026) find momentum is **insignificant** and Ammann et al. (2022) find EW returns overstated ~62%/yr in general datasets.
- **Direction of bias for us:** because we *exclude* dead coins, we are **not** inheriting the classic upward return bias from including-then-dropping winners; instead we inherit the opposite distortion — **cross-sectional alpha that depended on losers dying is simply absent.** So published XS Sharpes are an **overstatement of what our universe can deliver**, and any XS strategy that *does* look great on our 25 is suspect (likely period-specific — Grobys–Sandretto: "highly sample-dependent").
- **Mitigations we can apply:** (1) prefer **time-series** effects (§1) that don't need a broad survivor cross-section; (2) require robustness across **sub-windows** (matches our autoresearch worst-subwindow objective); (3) discount any XS result whose alpha is carried by the short leg (dead-coin leg we lack); (4) never extrapolate full-universe Sharpes (0.5–3.0) to our set — haircut hard.

---

## Fit summary table

| Strategy | Data fit (our fields) | Survivorship-robust | Expected net edge on 25 liquid survivors | Build priority |
|---|---|---|---|---|
| §1 TSMOM (per-symbol trend) | Excellent (close only) | **Yes** (time-series) | Modest-positive, decaying | **1 (build first)** |
| §2 Vol-managed overlay | Excellent (engine-native) | n/a (overlay) | Sharpe multiplier | **2** |
| §3 XS momentum (WML, neutralized) | Good | **No** (biased down) | Thin, period-dependent | 3 (test, skeptical) |
| §5 Low-vol / BAB | Good | Partial | Modest, sign-uncertain, diversifier | 4 |
| §4 Short-term reversal | Poor on liquid set | No | ≤0 / flips to momentum | Test to confirm dead |
| §6 MAX / lottery | Poor (large caps) | No | ~0; sign inverted vs equities | Feature only |
| §7 Size / Amihud / dollar-vol | Poor (no mkt cap; large caps) | No | ~0 dispersion | Conditioner only |

---

## Citations (with URLs)

**Core asset pricing / factors**
- Liu, Y., & Tsyvinski, A. (2021). *Risks and Returns of Cryptocurrency.* Review of Financial Studies 34(6), 2689–2727. https://academic.oup.com/rfs/article-abstract/34/6/2689/5912024 · SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3226952
- Liu, Y., Tsyvinski, A., & Wu, X. (2022). *Common Risk Factors in Cryptocurrency.* Journal of Finance 77(2), 1133–1177. https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.13119 · SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3379131 · NBER WP: https://www.nber.org/system/files/working_papers/w25882/w25882.pdf
- *Unravelling cross-sectional patterns in cryptocurrencies: a four-factor asset pricing model.* China Accounting and Finance Review 27(4). https://www.emerald.com/cafr/article/27/4/493/1271913/

**Momentum (time-series & cross-sectional)**
- Han, C., Kang, B., & Ryu, J. (2023). *Time-Series and Cross-Sectional Momentum in the Cryptocurrency Market: A Comprehensive Analysis under Realistic Assumptions.* SSRN 4675565. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4675565 · PDF: https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf
- Huang, Z.-C., Sangiorgi, I., & Urquhart, A. (2024). *Cryptocurrency Volume-Weighted Time Series Momentum.* SSRN 4825389. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4825389
- *Cryptocurrency Factor Momentum.* https://open.icm.edu.pl/server/api/core/bitstreams/86a51c47-8cd3-4201-88ee-42f44fb89227/content
- Dobrynskaya, V. *Cryptocurrency Momentum and Reversal.* https://conference.hse.ru/files/download_file_ex?hash=FAE0AB2DC7A67656E89A0B1CB27D8C7D&id=3B5EE9A5-0B18-458A-9458-B4ED0F6C6664
- Grayscale Research. *The Trend is Your Friend: Managing Bitcoin's Volatility with Momentum Signals.* https://research.grayscale.com/reports/the-trend-is-your-friend-managing-bitcoins-volatility-with-momentum-signals

**Trend factor**
- Han, Y. et al. (2024). *A Trend Factor for the Cross-Section of Cryptocurrency Returns.* Journal of Financial and Quantitative Analysis. https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/trend-factor-for-the-cross-section-of-cryptocurrency-returns/4C1509ACBA33D5DCAF0AC24379148178 · JFQA note: https://jfqa.org/2024/09/20/a-trend-factor-for-the-cross-section-of-cryptocurrency-returns/

**Short-term reversal & liquidity provision**
- Zaremba, A., Bilgin, M. H., et al. (2021). *Up or down? Short-term reversal, momentum, and liquidity effects in cryptocurrency markets.* International Review of Financial Analysis 78. https://www.sciencedirect.com/science/article/pii/S1057521921002349 · https://ideas.repec.org/a/eee/finana/v78y2021ics1057521921002349.html
- Farag, H., Luo, D., Yarovaya, L., & Zięba, D. (2025). *Returns from Liquidity Provision in Cryptocurrency Markets.* Journal of Banking & Finance. https://www.sciencedirect.com/science/article/pii/S0378426625000317 · SSRN: https://doi.org/10.2139/ssrn.4057510
- *Trading volume and liquidity provision in cryptocurrency markets* (2022). Journal of Banking & Finance. https://www.sciencedirect.com/science/article/abs/pii/S0378426622001418
- *Momentum and liquidity in cryptocurrencies* (2019). https://arxiv.org/pdf/1904.00890

**Volatility management / momentum crashes**
- Barroso, P., & Santa-Clara, P. (2015). *Momentum Has Its Moments.* Journal of Financial Economics. https://www.researchgate.net/publication/256017573_Momentum_Has_Its_Moments
- *Cryptocurrency market risk-managed momentum strategies* (2025). Finance Research Letters. https://www.sciencedirect.com/science/article/abs/pii/S1544612325011377
- *Cryptocurrency momentum has (not) its moments* (2025). Financial Markets and Portfolio Management. https://link.springer.com/article/10.1007/s11408-025-00474-9

**Low-vol / beta / idiosyncratic / downside risk**
- *Revisiting the low-volatility anomaly in cryptocurrency markets* (2026). Finance Research Letters. https://www.sciencedirect.com/science/article/abs/pii/S1544612326003818
- Zhang, W., & Li, Y. (2020). *Is idiosyncratic volatility priced in cryptocurrency markets?* Research in International Business and Finance. https://www.sciencedirect.com/science/article/abs/pii/S0275531920301926
- Zhang, W., & Li, Y. (2021). *Downside risk and the cross-section of cryptocurrency returns.* Journal of Banking & Finance. https://www.sciencedirect.com/science/article/abs/pii/S0378426621002053
- *Good volatility, bad volatility, and the cross section of cryptocurrency returns* (2023). https://www.sciencedirect.com/science/article/abs/pii/S1057521923002284

**MAX / lottery**
- *Lottery-like preferences and the MAX effect in the cryptocurrency market* (2021). Financial Innovation. https://jfin-swufe.springeropen.com/articles/10.1186/s40854-021-00291-9
- *Someone like you: Lottery-like preference and the cross-section of expected returns in the cryptocurrency market* (2024). https://www.sciencedirect.com/science/article/abs/pii/S1042443124000234
- *Speculation and lottery-like demand in cryptocurrency markets* (2021). https://www.sciencedirect.com/science/article/pii/S1042443121000081

**Survivorship / anomaly decay / economic constraints**
- Grobys, K., & Sandretto, D. (2026). *On survivor cryptocurrency momentum.* Finance Research Letters. https://www.sciencedirect.com/science/article/pii/S1544612326001339 · PDF: https://iris.unito.it/retrieve/f41aebe6-ee86-4e5e-b065-e85c3e38cb3b/1-s2.0-S1544612326001339-main%20(1).pdf
- Ammann, M., Burdorf, T., Liebi, L., & Stöckl, S. (2022). *Survivorship and Delisting Bias in Cryptocurrency Markets.* SSRN 4287573. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4287573 · PDF: https://www.alexandria.unisg.ch/bitstreams/2bc8397d-47dd-4f66-8467-9004b2c9d212/download
- Fieberg, C., Liedtke, G., & Zaremba, A. (2024). *Cryptocurrency anomalies and economic constraints.* International Review of Financial Analysis 94. https://www.sciencedirect.com/science/article/abs/pii/S1057521924001509 · https://ideas.repec.org/a/eee/finana/v94y2024ics1057521924001509.html
- McLean, R. D., & Pontiff, J. (2016). *Does Academic Research Destroy Stock Return Predictability?* (post-publication decay ≈50%). Journal of Finance.
- StratBase. *Survivorship Bias: Dead Coins Your Backtest Ignores.* https://stratbase.ai/en/blog/survivorship-bias-crypto

**Practitioner / market-beta estimation**
- Unravel Finance. *Cross-Sectional Alpha Factors in Crypto.* https://blog.unravel.finance/p/cross-sectional-alpha-factors-in
- arXiv (2025). *Spot Regressions with Candlesticks* (Bitcoin market-beta / neutrality). https://arxiv.org/pdf/2510.12911
