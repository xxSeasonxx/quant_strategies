# Sizing Redesign Review: scale-homogeneity book-scale calibration

Date: 2026-06-21
Reviewer: Codex, quant-math-code-review lens (read-only)
Target: branch `sizing-homogeneity-redesign`, `src/quant_strategies/core/portfolio_foundation.py`

## Review Objective

Verify the math and correctness of replacing the two blind book-scale bisections
(`_feasible_frontier`, `_calibrated_book_scale`) with an analytic leverage frontier plus a
safeguarded bracketed secant on capacity utilization and at-risk volatility. The contract:
`book_scale` must stay equivalent to the bisection result within the volatility tolerance,
the returned scale must be verified-feasible (never less conservative than a verified
point), and the fail-closed verdicts must be unchanged.

## Findings and disposition

| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | P1→P2 | Capacity secant mixes utilization metrics: `util_low` is the feasible walk's peak utilization, `util_high` is the first-breach ratio (a lower bound on the true peak), so the secant slope is inconsistent and the seed can overshoot. | **Not a correctness bug** — the bracket only ever returns a verified-feasible scale. It is a convergence concern, bounded by the midpoint cap (#2 fix). Comment added documenting the first-breach seed as a lower bound. |
| 2 | P1 | `best_scale` could stay `0.0`: with a tiny true frontier or an uninformative first-breach seed (`util_high≈1`), the secant could creep without guaranteed bracket reduction and exhaust the iteration cap on infeasible probes. | **Fixed.** `_bracketed_scale` caps the candidate at the bracket midpoint, so every rejecting (still-infeasible) probe halves the bracket's infeasible end — the search reaches a feasible scale in bisection time, so no creep and no zero-stall; feasible probes then advance by verified secant steps. Regression test `test_capacity_frontier_first_breach_below_peak_converges` added (first-breach bar ≠ peak bar). |
| 3 | P1 | `FOUNDATION_LOCK.md` invariant overclaimed "scaling the book by `s` scales each position's notional by `s`" — false for rebalanced books, since positions are sized from live equity. | **Fixed.** Reworded: only the declared signed target shape (intended exposure) is exactly degree-1; realized notional/participation/volatility are first-order degree-1 with a NAV/impact residual. |
| 4 | P2 | The `[feasible, infeasible]` bracket is endpoint bookkeeping; "frontier" is not mathematically the supremum unless utilization is monotone in `s`. | **Accepted.** The returned scale is a verified-feasible point (conservative, contract-correct). The non-monotone-residual caveat is documented in the function docstring and `FOUNDATION_LOCK.md`. Matches the stated design subtlety. |
| 5 | P2 | Volatility `None` branch advanced `low` without updating `vol_low`, leaving a stale secant anchor. | **Fixed.** Branch merged into the feasible path; the lower anchor updates only with real values. The branch is provably unreachable (at-risk sample count is scale-invariant for `s>0`), documented inline. |
| 6 | P2 | `_breach_utilization` did not reject non-finite `observed_participation`. | **Fixed.** Added an `isfinite` guard returning `inf`, so the secant cleanly falls back to bisection. |

## Verdict

Correctness findings #2/#3 fixed; #1/#4/#5/#6 dispositioned (convergence-bounded, documented,
or guarded). Equivalence to a bisection reference within the volatility tolerance, result
feasibility, and the homogeneity invariants are pinned by `tests/test_sizing_homogeneity.py`;
the full suite passes (920). Real-data check on `crypto_perp_funding_crowding_reversal`:
post-change `book_scale` matches the pre-change bisection to ~1.6e-6 relative.
