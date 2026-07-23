# Crypto Strategy Research — Synthesis & Autoresearch Shortlist

Date: 2026-07-22

Purpose: rank the crypto strategies worth putting into the autoresearch loop, judged
on three axes at once — **economic edge** (is there a real, non-arbitraged reason it
pays), **data fit** (can it be built from what we actually have), and **runnability**
(does the engine already execute it, or does it need wiring first). This is the entry
point; six detailed briefs sit alongside it (see [Detailed briefs](#detailed-briefs)).

Scope: crypto only. Every candidate is a pure `strategy.py` target book over the
25-perp universe, using only 1-min OHLCV, realized 8h funding, and (where wired)
spot-perp basis.

---

## What we can build on (data + engine, verified)

**Crypto data (all of it):**

| Dataset | Content | Window | Runner `[data].kind` |
|---|---|---|---|
| `crypto_perp_1min` | 25 perp OHLCV; base-asset `volume`, `num_trades`; **`vwap` null** | 2020-03-01 → 2026-04-13 | `bars` |
| `crypto_spot_1min` | 24 spot OHLCV | 2021-01-01 → | `bars` |
| `funding_8h` | realized perp funding settlements (`funding_rate`, `funding_timestamp`) | 2020-03-01 → | (joined) |
| `crypto_perp_1min_with_funding` | perp bars + realized funding at settlement minute | 2020-03-01 → | **`crypto_perp_funding`** |
| `crypto_spot_perp_basis_1min` | normalized basis + `basis_pct` (13 basis-ready symbols) | 2021-01-01 → | **not wired** |

25 perps: ADA, APT, ARB, ATOM, AVAX, BNB, BTC, DOGE, DOT, ETH, FET, INJ, LINK,
MATIC, NEAR, OP, PEPE, RENDER, SEI, SOL, SUI, TIA, UNI, WIF, XRP.
Basis-research-ready (13): ADA, ATOM, BTC, DOGE, DOT, ETH, FET, LINK, RENDER, SOL,
TIA, UNI, XRP.

**We do NOT have:** order book / L2 depth, tick data, taker-buy volume, open interest,
liquidation feeds, options / implied vol, on-chain data, sentiment/search, market cap
or circulating supply. This is the binding constraint on the whole shortlist.

**Engine facts that shape design (verified against source):**

- A strategy is a pure function emitting a **target book** — signed base weight per
  instrument per decision time, `0` = flat, idempotent netting. Cross-sectional
  multi-instrument portfolios are first-class (one netted, financed, marked NAV path
  is the scored object).
- `DataKind = {bars, crypto_perp_funding, forex_with_quotes}`. **Perp funding is
  modeled as financing only under `crypto_perp_funding`** (`_FINANCED_DATA_KINDS`). A
  `bars` crypto run does *not* charge funding — so any perp book held for hours/days
  must use `crypto_perp_funding` to pay/collect funding honestly.
- Built-in and operator-frozen (a climbing agent cannot relax them): vol-targeting
  (`calibrate_vol`, target annual vol → `book_scale`), gross/net leverage budget,
  cost model (per-side fee + slippage bps; **a zero-cost or zero-slippage run is
  fail-closed non-scoreable**), fill model (`price=close`, `entry_lag_bars>=1`),
  ADV-based capacity/impact (needs positive `volume` — we have it), strict causal
  replay on `available_at`, optional `RiskRule` (stop / take-profit / trailing).
- Train scoring is per-subwindow Sharpe over at-risk bars; the autoresearch loop
  climbs a robustness metric (worst-subwindow) editing only signal logic + a few
  bounded params. **Every candidate below is chosen to be a few-bounded-knob function**
  so it fits that surface.

---

## The one-paragraph conclusion

All six research angles — academic, industry, open-source, funding/basis,
momentum/factors, and volatility/seasonality — converge on the **same two durable
edges and the same overlay**: (1) **time-series trend / momentum** on a daily-ish clock
(robust across a decade, cost-survivable, and — because it is per-symbol — immune to
our survivorship problem), and (2) **funding/basis carry and its crowding signal**
(the one place our *distinctive* data — realized funding — gives an edge equity-trained
quants don't have), harvested **conditionally** because flagship BTC/ETH carry is
already arbitraged away and the residual lives in the alt cross-section. On top of both,
(3) **volatility targeting** is a near-free Sharpe multiplier that is native to the
engine. Everything else the literature celebrates — size, short-term reversal,
MAX/lottery, day-of-week, naive pairs — either **inverts or dies on a 25-large-cap
survivor universe**, **dies on our enforced cost floor**, or **needs data we don't have**.

---

## Ranked shortlist

Tiers reflect runnability today, then evidence strength × data fit. "Financed kind"
means run under `crypto_perp_funding` so funding is charged.

| # | Candidate | Tier | Runs today? | Edge / evidence | Biggest risk |
|---|---|---|---|---|---|
| 1 | Per-symbol time-series momentum + vol-target overlay | **1** | Yes (`crypto_perp_funding`) | Strongest, most-replicated; survivorship-immune | Whipsaw in chop; crowding decay |
| 2 | Cross-sectional funding-carry tilt (perp-only L/S, 25) | **1** | Yes (`crypto_perp_funding`) | Uses our distinctive data; real crowding premium | Decayed/crowded; hidden short-beta |
| 3 | Funding-crowding reversal (directional, perp-only, 25) | **1** | Yes (`crypto_perp_funding`) | Distinct directional edge; prior in-house work | Fat left tail; needs stops + price confirm |
| 4 | Cross-sectional price momentum (beta-neutral, 25) | **2** | Yes (`crypto_perp_funding`) | Published, but shown collapsing OOS | Survivorship-inflated; disguised BTC beta |
| 5 | Trend factor — multi-signal cross-sectional rank (CTREND-lite) | **2** | Yes (`crypto_perp_funding`) | Survives costs in *liquid* coins (Fieberg 2024) | Multi-signal over-mining |
| 6 | Delta-neutral cash-and-carry (long spot / short perp), 13 | **3** | **No — needs wiring** | Cleanest economic story; textbook trade | Basis-blowout tail; thin residual post-2024 |
| 7 | Spot-perp basis mean-reversion / basis momentum, 13 | **3** | **No — needs wiring** | Higher-resolution carry timing | Redundant with funding; cost-fragile |
| 8 | Inverse-vol / risk-parity multi-coin baseline | **4** | Yes (`crypto_perp_funding`) | Benchmark every active book must beat | Correlations → 1 in crashes |

### Tier 1 — build first (runnable, robust, distinctive or survivorship-safe)

**1. Per-symbol time-series momentum + vol-target overlay.** Per symbol, formation
return `r_L = close_t/close_{t−L} − 1` over `L` ≈ 1–8 weeks (or an MA crossover);
target `sign(r_L)` or `r_L/σ_i`, sized by the engine's `calibrate_vol`. Because it is
computed from each symbol's own history it does **not** depend on a broad survivor
cross-section — the single reason it dodges the bias that guts cross-sectional claims
here. Daily/weekly rebalance keeps turnover and ADV impact low, so it clears the cost
floor. Add the vol-managed overlay (target the book's own trailing PnL vol) as one extra
knob — a documented Sharpe multiplier (Moreira-Muir; crypto replication 1.12→1.42).
Params: `lookback_days∈{7,14,21,30,45,60}`, `signal∈{sign,vol_scaled}`,
`rebalance∈{daily,2d,weekly}`, optional `ma_gate`. Falsifier: net Sharpe ≤ 0 across all
bounded lookbacks, or PnL concentrated in the 2020-21 bull. *See briefs 02 §1-2, 03 §2,
06 §1/§4.*

**2. Cross-sectional funding-carry tilt (perp-only long-short).** Rank the 25 perps by
trailing realized funding (`funding_8h`, annualize ×1095); short the top quantile,
long the bottom, ~dollar- and beta-neutral, inverse-vol within legs. No spot leg → all
25 coins, no short-spot problem, and funding is collected natively as financing. Harvest
**conditionally** (only when funding is richly wide) — the residual edge is in the alt
cross-section and the right tail of funding, not always-on. Params: funding lookback
`{1,3,7,14}` events, quantile `{10,20,33}%`, `weighting∈{equal,inv_vol}`, beta-neutralize
on/off, rebalance `{8h,daily}`. Falsifier: edge vanishes after beta-neutralization (it
was short-beta), or turnover cost on the thin alt short leg exceeds the spread.
*Caveat: single-venue funding — a proxy for the industry OI-weighted composite. See
briefs 01 §1/§3, 03 §5, 04 Idea 2, 05 Theme 1.*

**3. Funding-crowding reversal (directional, perp-only).** Standardize funding per
symbol (`z_fund` over trailing window); when it exceeds an upper extreme → target short,
below a lower extreme → target long, `0` in the band; gate on a `close`-momentum
divergence (crowded **and** stalling) and attach a `RiskRule` stop/trailing to bound the
"run over by a real trend" tail. A *directional* edge distinct from carry, with more
capacity and less arb-crowding. Prior in-house work exists (`crypto_perp_funding_crowding_reversal`);
treat those results as the real prior. Params: z-window, upper/lower thresholds
(`z∈{2,2.5,3}` or annualized `±{20,40,60}%`), hold horizon, stop/trailing distances,
price-confirmation weight. Falsifier: adds nothing over plain short-horizon reversal, or
all PnL comes from 2-3 dated cascade events. *See briefs 01 §2, 04 Idea 5, and the
sibling `crypto_perp_volume_profile_strategies.md` Candidate 2.*

### Tier 2 — test with skepticism (real but fragile / inflated)

**4. Cross-sectional price momentum (beta-neutral).** Rank 25 perps by trailing return,
long top / short bottom tercile, weekly rebalance. **Our 25 survivors are exactly the
case where published cross-sectional momentum Sharpes are inflated by dead coins we
don't hold** (Grobys-Sandretto 2026: survivor-only momentum is insignificant), and a
real fund (Starkiller) published its **out-of-sample collapse** — use that collapse as
the null to beat. Must be **beta-neutral** (`Σwᵢβᵢ≈0`), not just dollar-neutral, or it's
a disguised BTC bet. *See briefs 02 §3/§8/§9, 03 §3, 04 Idea 3.*

**5. Trend factor — multi-signal cross-sectional rank (CTREND-lite).** Fieberg et al.
(2024, *JFQA*) is the strongest "survives costs *and* works in liquid coins" result:
aggregate a *small* subset of trend signals (a few MA ratios + breakout strength) into a
cross-sectional rank. Keep the signal set tiny — the risk is Hudson-Urquhart-style
over-mining. *See brief 03 §2.*

### Tier 3 — economically cleanest, but NOT runnable today (needs engine wiring)

**6. Delta-neutral cash-and-carry** and **7. spot-perp basis** trades are the
textbook crypto edge and the one place our basis data would shine — but they need
**both spot and perp legs in one book**, and the runner has no basis `DataKind` and
loads only one dataset per config. See [Engineering feedback](#engineering-feedback).
Until wired, the tradeable substitute is the perp-only funding tilt (#2), which captures
most of the same premium as financing on a single netted book.

### Tier 4 — baselines / conditioners (not standalone alpha)

**8. Inverse-vol / risk-parity allocation** is the benchmark every active book must
beat, not an edge itself; the engine's risk-budget operator already owns vol sizing, so
don't re-implement it in `strategy.py`. Likewise, **beta-neutralization** is the
methodology every cross-sectional book (#2, #4, #5) must apply and validate (regress NAV
on an equal-weight crypto benchmark; `|beta|>~0.2` means the "factor" was market beta).

---

## Do not build (and why)

| Idea | Why it fails here |
|---|---|
| Short-term cross-sectional reversal | Micro-cap/illiquidity effect; **flips to momentum** on our 25 liquid survivors (Zaremba 2021) |
| MAX / lottery | Sign is inverted vs equities and concentrated in low-priced micro-caps |
| Size / Amihud / dollar-volume factor | **No market cap**; our 25 are all large-cap → near-zero size dispersion |
| 1-min intraday mean-reversion | Dies on the enforced cost floor + `entry_lag_bars`; real edge is sub-minute (below our granularity) |
| Day-of-week / weekend / turn-of-month | Decayed to noise post-2015/2017; highest data-snooping surface |
| Naive pairs cointegration | Relationships de-cointegrate out-of-sample; practitioners call it dead; leaks hedge ratio |
| Cross-venue funding arbitrage | **Single funding series per symbol** — we can't observe a second venue |
| OI-weighted composite carry, liquidation-cascade timing | No open-interest or liquidation feed |
| On-chain / whale-flow, options-IV carry, BTC-dominance / altseason | No on-chain, options, or market-cap data (dominance proxy just collapses into #4) |

---

## Engineering feedback (to Season)

1. **Wire a crypto basis / spot-perp data kind — highest-value crypto addition.** The
   economically cleanest trades (cash-and-carry, basis mean-reversion) need spot **and**
   perp legs in one netted book. Today `DataKind = {bars, crypto_perp_funding,
   forex_with_quotes}` and a config loads one dataset, so they're unbuildable. Upstream
   `crypto_spot_perp_basis_1min` + `load_crypto_spot_perp_basis` already exist. Adding a
   `crypto_basis` (spot+perp panel with `basis_pct`, `available_at`, and financing on the
   short-perp leg) unlocks Tier 3 without new data.

2. **Funding is charged only under `crypto_perp_funding`.** A perp trend/momentum book
   run as plain `bars` collects/pays no funding and will overstate a multi-day holder's
   return. Default all perp candidates to the financed kind.

3. **Single-venue realized funding.** No OI, no cross-venue composite — the funding tilt
   (#2) is a proxy of the industry OI-weighted version. Document as a known deviation;
   don't chase cross-venue arb.

4. **Point-in-time universe / survivorship.** The 25 perps are survivors and have
   staggered listing dates; cross-sectional ranking logic must gate on per-symbol
   `available_at` / minimum history and never rank a coin before its start. The
   worst-subwindow Train objective partly defends against period-specific XS flukes —
   lean on it, and haircut any full-universe Sharpe hard.

---

## Recommended autoresearch order

1. **Per-symbol TSMOM + vol-target (#1)** — cleanest, survivorship-safe, cost-friendly;
   establishes whether trend pays at all on our universe before anything cross-sectional.
2. **Funding-crowding reversal (#3)** — extends the existing in-house line; distinct
   directional edge on our distinctive data.
3. **Cross-sectional funding tilt (#2)** — the carry factor, gated and beta-neutral.
4. Then, skeptically, **cross-sectional / trend-factor momentum (#4, #5)** against the
   inverse-vol baseline (#8) and with beta-neutrality as a hard validation gate.
5. In parallel, **wire the basis data kind** to unlock Tier 3.

Every candidate must clear the enforced cost floor on **recent** windows (not just the
rich 2020-22 era), and any "market-neutral" claim must pass the beta-neutrality gate.

---

## Detailed briefs

- [01 — Funding-rate & spot-perp basis](01_funding_and_basis.md)
- [02 — Cross-sectional & time-series momentum / reversal / factors](02_cross_sectional_momentum_reversal.md)
- [03 — Academic literature (annotated bibliography)](03_academic_literature.md)
- [04 — Industry & practitioner survey](04_industry_practitioner.md)
- [05 — Open-source / GitHub survey (+ walk-forward methodology to emulate)](05_open_source_github.md)
- [06 — Volatility, seasonality & trend](06_volatility_seasonality_trend.md)

Sibling research (same folder root): `../crypto_perp_volume_profile_strategies.md`
(auction/volume-profile candidates, including a funding-crowding value-area reversal that
overlaps candidate #3 above).

*Every headline Sharpe/return in the briefs is as reported by its source over its own
sample and is gross of our engine's mandatory cost floor and ADV impact — treat them as
upper bounds, not expectations for our net-of-cost backtests.*
