# Evaluation Plan

This directory is for downstream evaluation notes and artifacts.

Do not run evaluation inside `quant_autoresearch`. Do not feed evaluation results back into the same Train thesis.

## One-Way Rule

Evaluation results may decide whether the candidate deserves paper/live review. They must not be used to patch the same candidate or continue tuning this same thesis.

If OOS fails, archive this package or start a fresh thesis from the learned principles.

## Primary Candidate

- `attempt-0099`: final Train survivor.

## Comparison Set

Use a small structurally diverse set rather than all retained attempts:

- `attempt-0098`: nearest parent to final.
- `attempt-0080`: ADA timing survivor before final hold tuning.
- `attempt-0068`: per-symbol hold survivor.
- `attempt-0059`: selloff-gated survivor.
- `attempt-0033`: first strong non-BTC survivor.

Near-miss candidates should be evaluated only if the evaluation question is explicitly about their structural hypothesis, such as strong funding threshold versus sparse coverage.

## Minimum Checks

- Confirm OOS window does not overlap Train.
- Run causality replay or equivalent decision-time verification.
- Compare OOS subwindow trade counts and cost stress against Train.
- Review symbol contribution concentration.
- Review sample trades for timing and fill assumptions.

## Do Not Infer

- Train gates do not prove deployability.
- Positive OOS does not prove live readiness.
- This package does not include paper-trading or live execution evidence.
