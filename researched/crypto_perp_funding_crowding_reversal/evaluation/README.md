# Evaluation Plan

This directory is for downstream evaluation notes and artifacts.

Do not run evaluation inside `quant_autoresearch`. Do not feed evaluation results back into the same
Train thesis.

## One-Way Rule

Evaluation results may decide whether the candidate deserves paper/live review. They must not be
used to patch the same candidate or continue tuning this same Train thesis. If OOS fails, archive
this package or start a fresh thesis from the learned principles.

## Primary Candidate

- `attempt-0012` (convexity power 3): the recommended robust Train survivor.

## Comparison Set

Use a small structurally-diverse set rather than all retained attempts:

- `attempt-0004`: the exit-ramp capacity win before conviction sizing (isolates the capacity lever).
- `attempt-0008`: linear dislocation-conviction (isolates conviction vs equal-weight).
- `attempt-0011`: convexity power 2 (nearest-parent to the headline; tests convexity robustness).
- `attempt-0014`: protocol score-max — **explicit overfit robustness check**. Its extra Train score
  over 0012 comes from a mechanism-less tail (non-predictive funding magnitude + power-4 convexity);
  the OOS question is whether that +0.015 survives or decays. If it decays, 0012 is confirmed as the
  robust choice.

Near-miss candidates (`attempt-0003`, `attempt-0007`) should be evaluated only if the question is
explicitly about their structural hypothesis (capacity overshoot at the t=2 knife-edge; signal
reference form).

## Minimum Checks

- Confirm the OOS window does not overlap the Train window (`2025-03-01 .. 2025-12-31`).
- Run causality replay or equivalent decision-time verification.
- Compare OOS subwindow trade counts, profit factor, and cost-stress retention against Train.
- Review symbol contribution concentration (Train breadth 0.319; edge in high-vol altcoins).
- Review sample trades for entry-lag and fill assumptions (next-bar `close`, `entry_lag_bars=1`).
- Watch the significance margin: Train t ≈ 2.1 is a knife-edge; a small OOS degradation flips it.

## Do Not Infer

- Train gates do not prove deployability.
- Positive OOS does not prove live readiness.
- This package includes no paper-trading or live execution evidence.
- The 8-name universe is the binding constraint (duty-cycle-limited t); a wider-universe reseed is
  Season's call, not implied by any OOS result here.
