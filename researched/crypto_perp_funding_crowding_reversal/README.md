# Crypto Perp Funding Crowding Reversal

This package is a curated handoff from `quant_autoresearch` for downstream evaluation.

This package is Train-only research evidence. It is not OOS, paper, live, or deployability evidence.

## Supersession note

This package **replaces** a prior offload of the same `strategy_id` (an earlier lifecycle whose
survivor was `attempt-0099`: a symbol-specific thesis — non-BTC-only, skip-ADA-early-session,
per-symbol holds — scored under a retired gate). That lifecycle is **superseded and preserved only
in git history**. The current lifecycle is a clean 8-symbol book with **no symbol-specific
exceptions**, re-run under the current `significance` gate, and it materially outperforms the prior
one. Do not mix the two lifecycles' ledgers or metrics; everything below is the current lifecycle.

## Current Train Survivor

- Current survivor: `attempt-0012` (recommended, robust)
- Strategy file: `strategy.py`
- Train score (deployed-return LCB, `return - 1*SE`): `0.3258`
- Significance (deflated, `return - 2*SE`): `+0.0414` (t = 2.15)
- Gates: all 8 pass (`trade_floor, minimum_evidence, path_risk, significance,
  cost_stress_retention, breadth, causality, complexity_cap`)
- Full-Train annualized return: `0.610` at deployed vol `0.150` (full risk budget)
- Profit factor: `1.837` · win rate `0.562` · trades `306`
- Subwindow trade counts: `125,54,16,7,62,42` (all 6 subwindows net positive)
- Economic symbol concentration (breadth): `0.319` (ceiling 0.70)
- Cost-stress return retention: `0.807`

The survivor is a **long-only crypto-perp funding-crowding-reversal** book on the frozen 8-symbol
universe:

- Fade crowded-short capitulations: go long names with **negative summed funding** (crowded shorts
  pay) plus **idiosyncratic price-down vs the cross-section** (relative-value dislocation).
- Rank/select cross-sectionally; hold a fixed **720-minute** horizon; rebalance on a **240-minute**
  cadence aligned to 8h funding settlements.
- **Two research wins define this survivor vs a plain equal-weight book:** (1) *exit-ramp
  decoupling* — spreading the synchronized fixed-horizon unwind over more bars than the entry
  relieves the bar-participation cap and deploys the full 15% risk budget; (2) *convex
  dislocation-conviction sizing* — weight each name by its idiosyncratic dislocation raised to a
  power (~cubic), concentrating capital on the biggest capitulations (which bounce biggest).
- Train-only next-bar (`close`, `entry_lag_bars=1`) fills and protocol-owned costs.

### Recommended survivor vs protocol numeric-max

The protocol keep-rule's highest-scoring row is `attempt-0014` (score `0.3410`), retained under
`candidates/gated_candidates/`. Its extra `+0.015` over `attempt-0012` comes from a
**mechanism-less overfit tail**: it adds funding *magnitude* to the conviction weight (funding
magnitude is non-predictive in this thesis) and pushes convexity to power 4. `attempt-0012` is the
recommended robust survivor; evaluate `attempt-0014` only as an overfit robustness check (does the
extra Train score survive OOS, or decay as expected?).

## Authoritative Files

- `strategy.py`: final Train survivor strategy snapshot from `attempt-0012`.
- `experiment.toml`: bounded params from `attempt-0012`.
- `protocol.train.toml`: the frozen Train protocol (data, costs, fills, capacity, leverage budget,
  objective, gates, stop rules) — this is the source `protocol.toml`, renamed.
- `results.tsv`: canonical Train ledger for this lifecycle (15 attempts).
- `loop_status.txt`: lifecycle status snapshot at offload.
- `rationale.md`: curated thesis, the two wins, candidate taxonomy, residual risks, reseed case.
- `candidates/`: retained attempts by bucket, each with `snapshot/` + `artifacts/`.
- `diagnostics/`: flat diagnostic/summary copies per retained attempt.
- `evaluation/README.md`: downstream evaluation plan.

## Train Setup

- Source repo: `/Users/Season_Yang/Personal/quant_autoresearch`
- Data kind: `crypto_perp_funding` (dataset `crypto_perp_1min_with_funding`).
- Symbols (8, protocol-frozen, return-blind): `BTC, ETH, SOL, XRP, BNB, DOGE, ADA, LINK` (`-PERP`).
- Train window: `2025-03-01 .. 2025-12-31`; data loaded to `2026-01-07`.
- Fills: `close`, `entry_lag_bars = 1` (next-bar).
- Costs: `fee 5.0 bps/side`, `slippage 1.0 bps/side`.
- Capacity: `adv_impact`, `$1,000,000` notional, `max_bar_participation 0.50`,
  `max_adv_participation 0.25`, impact `10 bps^0.5`.
- Leverage budget (operator-frozen): `max_gross 1.0`, `max_net 1.0`.
- Risk budget: `calibrate_vol`, `target_volatility 0.15`.
- Objective: `return_lcb_subwindow` (6 subwindows); significance gate deflates full-Train return at
  `k = 2.0` SE and requires it positive (≈ t ≥ 2).

## Retention Policy

The retained set was selected for **structural diversity and diagnostic value**, not performance
rank. This is a small lifecycle (15 attempts), so **all 15 are retained**, each with a one-line
verdict, bucketed as: `survivors/` (gate-passing keeps on the winning path), `gated_candidates/`
(all gates pass but not the recommended survivor), `near_misses/` (failed exactly one gate —
significance — narrowly), `anti_patterns/` (representative falsified mechanism-classes not to
repeat).

## Retained Candidates

| Attempt | Bucket | Lever tested | Score | Gates | Verdict |
|---|---|---|---|---|---|
| 0001 | survivors | warm-start baseline (equal wt, exit=entry ramp) | 0.196 | pass | Feasible anchor; t 2.02, capacity-throttled to 10% vol. |
| 0004 | survivors | **exit-ramp decoupling (exit=30)** | 0.282 | pass | WIN: deploys full 15% budget; +44% score. |
| 0008 | survivors | dislocation-conviction sizing (linear) | 0.291 | pass | WIN: conviction lifts PF; edge is vol-seeking/absolute. |
| 0011 | survivors | convex conviction (power 2) | 0.311 | pass | WIN: super-linear conviction; broad subwindow gain. |
| 0012 | survivors | **convex conviction (power 3)** | 0.326 | pass | **HEADLINE**: robust peak; t 2.15, PF 1.84. |
| 0013 | survivors | convex conviction (power 4) | 0.335 | pass | Still climbing but decelerating; power-3 is the robust choice. |
| 0014 | gated_candidates | combined (funding+dislocation) conviction, power 4 | 0.341 | pass | Protocol score-max, but +0.015 is mechanism-less overfit (non-predictive funding magnitude). |
| 0010 | gated_candidates | beta-adjusted idiosyncratic dislocation | 0.271 | pass | Gates pass but worse than raw; cross-name adjustment de-selects the high-vol altcoins that carry the edge. |
| 0003 | near_misses | exit-ramp too far (exit=40) | 0.282 | fail (sig) | Full deployment overshoots; t 1.997 — the t=2 knife-edge. |
| 0007 | near_misses | median cross-section reference | 0.274 | fail (sig) | Near-inert vs mean; signal reference is well-formed. |
| 0002 | anti_patterns | vol-normalized dislocation | -0.187 | fail | Catastrophic: normalizing kills the edge (it is absolute-bps, vol-seeking). |
| 0005 | anti_patterns | funding recency weighting | 0.062 | fail | Funding is sign-only; timing/magnitude non-predictive. |
| 0006 | anti_patterns | vol-scaled hold | 0.231 | fail | Varying hold length lowers t via return-series heterogeneity. |
| 0009 | anti_patterns | dislocation-scaled hold | 0.246 | fail | Same heterogeneity cost; conviction belongs in sizing, not hold. |
| 0015 | anti_patterns | recent-capitulation conviction | 0.278 | fail | Worse conviction axis than cross-sectional dislocation. |

## Lessons From Train

- The edge is **long-only** (crowded-short capitulations; the short side has no gross edge in a
  structurally long-funding market), **cross-sectional** (relative-value dislocation is
  load-bearing), and **vol-seeking in absolute bps** (concentrated in high-vol altcoins;
  DOGE/XRP/ADA/SOL, not BTC/ETH).
- **Conviction helps only via sizing, and only on the dislocation axis.** Convex
  dislocation-weighting is a genuine, broad, inspected-robust win. Funding magnitude, recent-return
  magnitude, and any cross-name normalization (vol- or beta-) do **not** help.
- **Capacity is a real alpha lever, not a wall.** Decoupling the exit ramp deploys the full risk
  budget; this is where most of the deployed-return gain comes from.
- The exit is **fixed-horizon 720 min**; every timing/scaling variant hurts (heterogeneity or
  cutting winners). The cadence is **240 min** (funding-settlement aligned).

### What not to repeat

Vol-/beta-normalized dislocation, funding-magnitude/recency signals, varied (vol- or
dislocation-scaled) hold lengths, and adding funding magnitude to the conviction weight. See
`anti_patterns/` and `gated_candidates/attempt-0014-*`.

## Evaluation Plan

See `evaluation/README.md`. Primary candidate `attempt-0012`; structurally-diverse comparison set;
strict one-way rule (OOS results must not be fed back to patch this Train thesis).

## Do Not Infer

- Train gates do not prove deployability; the significance pass is **marginal** (t ≈ 2.1 on 8
  names — a knife-edge), which is itself a key finding.
- This package includes no OOS, paper, or live execution evidence.
- The binding constraint is the **universe** (8 majors supply only 1-3 concurrent crowded-short
  setups → duty cycle ~33% → t pinned near 2), not the edge. A wider return-blind universe is the
  documented reseed lever (see `rationale.md`), and is Season's call — not implied by this package.
