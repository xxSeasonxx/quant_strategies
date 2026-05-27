# LLM Research Summary: crypto_perp_funding_crowding_reversal_stateful_rebalance

This package moves the selected 15 research variants out of the `quant_autoresearch` bench and into `quant_strategies/researched`.
The source JSON, config, strategy, and evidence files in this package are authoritative.

## New 15 Rerun

- Variant count: `15`
- Scored count: `15`

Top rerun variants:

- `time_only_exit` rank `1`: score `0.004535132408957629`, raw net `0.8163238336123732`, trades `909`
- `time_only_exit` rank `2`: score `0.0037971232831075013`, raw net `0.6834821909593503`, trades `697`
- `entry_filter` rank `1`: score `0.003646585581964076`, raw net `0.6563854047535337`, trades `510`
- `selection_or_breadth` rank `1`: score `0.0036449770596589806`, raw net `0.6560958707386165`, trades `666`
- `selection_or_breadth` rank `2`: score `0.0036449770596589806`, raw net `0.6560958707386165`, trades `666`

## Validation Risks

These are smoke-screened research candidates. Before paper trading or live trading, run downstream validation for costs, fills, venue/data availability, regime robustness, exposure limits, and duplicate variant behavior.
