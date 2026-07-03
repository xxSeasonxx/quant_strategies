# Rationale — Crypto Perp Funding Crowding Reversal (curated Train handoff)

Curated for downstream evaluation. Train-only evidence; not OOS/paper/live/deployability proof.
This is the current lifecycle; it supersedes the prior symbol-specific lifecycle (git history).

## Thesis

Realized same-sign funding pressure plus same-direction price extension marks crowded crypto-perp
positioning that mean-reverts over an intraday fixed-horizon hold. Negative summed funding (shorts
are paying — a crowded-short capitulation) plus a name being idiosyncratically down versus the
cross-section marks the crowded move; the book fades it by going long and exits at a fixed horizon.

## Observable (decision-time causal)

- Data: `crypto_perp_1min_with_funding`; fields `close`, `available_at`, `funding_timestamp`,
  `funding_rate`, `has_funding_event`. A row is used only when `available_at <= decision_time`.
- Signal: sum of the latest realized funding settlements (crowding, sign-only — see below), plus
  price extension vs a completed prior close, measured idiosyncratically against the cross-section
  mean over the candidates present at the signal bar.

## Universe (protocol-frozen, return-blind)

Eight liquid majors: `BTC, ETH, SOL, XRP, BNB, DOGE, ADA, LINK` (`-PERP`). Selected for liquidity
and full in-window coverage, never for realized return. Breadth is converged via the signal (the
active book holds fewer names where the edge is strongest), never by pruning the frozen universe.

## Survivor (attempt-0012, recommended robust)

Long-only; cadence 240; `min_same_sign=1`, `min_abs_funding=1 bp`, `min_idio=2.5 bp` (raw, mean
reference); recent-return guard off; hold 720; `top_n=5`; `entry_twap=20`, `exit_twap=30`;
`weighting=dislocation` with `dislocation_weight_power=3`. Score 0.326 (deployed-return LCB), t 2.15,
PF 1.84, deployed vol 15.0% (full risk budget), breadth 0.319, all 8 gates pass, 6/6 subwindows
positive. Edge concentrated in high-vol altcoins (DOGE/XRP/ADA/SOL), broadly cross-sectional (7/8
names net positive), not a one-name artifact.

## The two research wins (what makes this survivor)

1. **Exit-ramp decoupling (capacity).** All names in a cohort exit together at the fixed horizon;
   that synchronized unwind pinned the 0.50 bar-participation cap and throttled the book to ~10%
   vol. Spreading the *exit* over more bars than the entry (`exit_twap=30` vs `entry_twap=20`)
   relieves the pin and deploys the full 15% risk budget — smoothly and monotonically (not the
   fragile entry-TWAP spike). This is the dominant deployed-return lever; capacity relief is alpha,
   not a wall.
2. **Convex dislocation-conviction sizing.** Equal-weighting the 1-3 held names leaves return on the
   table: the edge scales *super-linearly* with idiosyncratic dislocation (the biggest crowded-short
   capitulations bounce biggest). Weighting each name by its dislocation raised to ~cubic power
   (gross preserved) lifts profit factor and t. Inspected as robust: it improves the *weakest*
   subwindow while PnL stays spread across 5-6 names — a genuine cross-sectional feature, not
   in-sample winner-weighting.

## Durable falsifications (candidate taxonomy)

- **Signal is absolute-bps, vol-seeking.** Vol-normalizing the dislocation is catastrophic
  (attempt-0002); beta-adjusting it is mildly worse (0010); median vs mean reference is inert
  (0007). The raw absolute dislocation vs the cross-section mean is the right form.
- **Funding is a sign detector only.** Level/count/magnitude/recency and adding funding magnitude to
  the conviction weight are all non-predictive (0005; and 0014's overfit tail).
- **Exit is fixed-horizon 720.** Any *varied* exit — shorter/longer fixed, take-profit, vol-scaled
  (0006), dislocation-scaled (0009) — hurts: shorter cuts the slow bounce; any per-name variation
  adds return-series heterogeneity that lowers the effective sample size and t.
- **Conviction belongs in sizing, not hold, and on the dislocation axis, not funding or recent
  return** (0015 worse; 0009 worse).

## Residual risks (for OOS scrutiny)

- **Marginal significance.** t ≈ 2.1 on 8 names is a knife-edge; the pass is not robust-with-margin.
  This is universe-bound: 8 majors supply only 1-3 concurrent crowded-short setups (duty cycle
  ~33%), which pins statistical independence and hence t near 2 regardless of shape or scale.
- **Overfit tail.** The protocol numeric-max (attempt-0014, 0.341) adds a mechanism-less +0.015 via
  non-predictive funding magnitude and power-4 convexity. Prefer attempt-0012; treat 0014 as an
  explicit overfit robustness check.
- **Lumpy edge.** Per-trade kurtosis is high; the big bounces are the edge (tail-trimming hurt), so
  the return distribution is fat-tailed by construction.

## Reseed case (Season's call; not part of this package)

The binding constraint is the universe/envelope, not the edge. The same long-only
funding-crowding-reversal mechanism — carrying both wins (exit-ramp decoupling, convex conviction) —
on the full ~25-name return-blind data-ready crypto-perp universe should raise t mainly via **duty
cycle** (more names firing → more at-risk calendar → higher effective sample size) and lower
per-name ADV participation (more deployable capacity). The diversification/Sharpe gain is limited
(crypto-perp crowding is one highly-correlated factor, cross-perp ρ ≈ 0.6-0.8). This is a new
lifecycle with a new protocol/ledger, decided by Season — not an extension of this Train thesis.
