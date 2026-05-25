# LLM Research Summary: crypto_perp_funding_crowding_reversal

This is an initial machine-written scaffold. The source JSON, config, strategy, and evidence files in this package are authoritative.

## Research Hypothesis

The campaign tested a crypto perpetual funding/return crowding reversal. The retained variants rank crowded names using funding, return, or breadth filters, then fade the crowded side with time-based holds and explicit signal exits from the upstream engine.

## Evidence Summary

The deterministic handoff ranker selected exactly three logic families: `selection_or_breadth` with 4 retained variants, `entry_filter` with 5 retained variants, and `time_only_exit` with 5 retained variants.

The strongest promoted candidate remains the time-only exit variant from attempt 95, with promotion score `0.016278311526520668`, improving on the prior best promoted score `0.015707175388822794`. In the retained package this appears under `family_03_exploratory_time_only_exit/variants/rank_03/`.

Threshold-style take-profit/stop-loss/trailing exits did not survive the deterministic top-three-family handoff. The best retained deterministic family by blended score was `selection_or_breadth`, driven by top-N and selection-score variants; those top variants were not promoted, so treat them as research leads, not validated replacements for the promoted time-only candidate.

## Validation Risks

This package is researched only, not market validated. Downstream validation should re-run retained configs, inspect promotion source-window evidence, stress costs/fills, and challenge whether the selected breadth and entry-filter variants are robust or just three-window artifacts.
