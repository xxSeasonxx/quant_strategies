# Handoff: crypto_perp_funding_crowding_reversal_stateful_rebalance

Use this package as a starting point for comprehensive validation in `quant_strategies`. Do not treat the screening scores as live-trading evidence.

This package is archived evidence. Validation now runs from an explicit
`validation.toml` plus its referenced `strategy.py`; it does not validate the
`researched/` family/variant tree directly.

## Selected Families

- primary: `time_only_exit`
- secondary: `entry_filter`
- exploratory: `selection_or_breadth`

## Next Checks

- Re-run each retained config in the target repository.
- Review costs, fills, data availability, and trade attribution.
- Promote only after downstream validation passes.
