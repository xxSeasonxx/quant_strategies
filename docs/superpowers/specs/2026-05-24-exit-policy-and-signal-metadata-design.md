# Exit Policy And Signal Metadata Design

## Decision

Add deterministic per-signal exit controls and signal metadata pass-through to
the internal evaluator and runner artifact contract.

The first implementation should stay intentionally small:

- Use bar-close or configured-fill-price trigger evaluation only.
- Preserve old fixed-horizon signals.
- Add `exit_reason` to every evaluated trade.
- Preserve strategy-emitted audit metadata from signal generation through engine
  request, evidence, and trade output.
- Update the two real research strategies in `untested/` to emit exit controls
  and audit fields.

This is not a general backtesting engine, a stop-order simulator, or a portfolio
position manager.

## Context

The current evaluator exits every signal at:

```text
decision_index + entry_lag_bars + hold_bars + exit_lag_bars
```

That keeps screening causal and deterministic, but it cannot represent common
research exits such as max hold, take profit, stop loss, or trailing stop.

The current runner writes raw strategy signals to `signals.csv`, and that CSV can
include extra strategy fields. However, the engine request converts each signal
into a strict `Signal` model that only keeps:

```text
symbol, decision_time, side, weight, hold_bars
```

As a result, research metadata such as funding pressure or entry return
extension is visible in raw signal artifacts but lost from the exact engine
request, evidence packet, and trade output.

## Goals

- Represent practical single-trade exits without over-engineering the runner.
- Keep the evaluator causal, deterministic, and easy to audit.
- Preserve old strategies and existing tests unless their expected output needs
  targeted updates.
- Make every trade explain why it exited.
- Carry signal audit metadata through the same artifacts used to review
  screening results.
- Update current research strategies so generated signals explain their own
  evidence inputs.

## Non-Goals

- No intrabar high/low stop or target simulation.
- No same-bar stop-versus-target ordering model.
- No pluggable exit policy registry.
- No portfolio-level exits, position netting, or overlapping-signal aggregation.
- No changes to fee, slippage, or funding formulas except using the actual
  early-exit interval.
- No promotion claim from these new artifacts; they remain runner smoke evidence.

## Signal Contract

Existing signal fields remain valid:

```text
symbol
decision_time
as_of_time
side
weight
hold_bars
```

Add optional fields:

```text
max_hold_bars
take_profit_bps
stop_loss_bps
trailing_stop_bps
metadata
```

`max_hold_bars` is the maximum number of bars to hold after entry. If
`max_hold_bars` is absent, the evaluator uses `hold_bars` as the maximum hold.
If both are present, `max_hold_bars` wins and `hold_bars` remains accepted for
backward compatibility.

Exit thresholds are positive bps values:

- `take_profit_bps`: exit when side-adjusted return reaches or exceeds this
  value.
- `stop_loss_bps`: exit when side-adjusted return falls to or below the negative
  of this value.
- `trailing_stop_bps`: after a favorable move, exit when side-adjusted return
  retraces by at least this amount from the best post-entry observed return.

`metadata` is a JSON-compatible mapping. To keep strategy files simple, the
runner should also fold unknown top-level signal fields into `metadata` before
building the engine request. This preserves flat signal columns in
`signals.csv`, while giving the engine a stable structured metadata field.

Reserved signal fields should not be duplicated into metadata:

```text
symbol
decision_time
as_of_time
side
weight
hold_bars
max_hold_bars
take_profit_bps
stop_loss_bps
trailing_stop_bps
metadata
```

## Exit Evaluation

Entry behavior stays unchanged. For each signal:

```text
decision_index -> entry_index = decision_index + entry_lag_bars
```

The evaluator then scans trigger bars after the entry bar, bounded by the
maximum hold. If a rule fires on trigger bar `k`, the trade exits at:

```text
exit_index = k + exit_lag_bars
```

The fixed max-hold exit uses the same rule with:

```text
k = entry_index + max_hold_bars
```

With the current default `exit_lag_bars = 0`, the trigger bar and exit fill bar
are the same bar. A config author can set a positive exit lag to model waiting
after a close-confirmed trigger.

For each trigger bar, compute side-adjusted return in bps from entry to the
trigger bar using the configured fill price:

```text
long:  (trigger_price / entry_price - 1.0) * 10_000
short: (entry_price / trigger_price - 1.0) * 10_000
```

Exit checks use this priority when multiple close-confirmed rules fire on the
same trigger bar:

1. `stop_loss`
2. `take_profit`
3. `trailing_stop`
4. `max_hold`

This priority is intentionally conservative. Because v1 does not model intrabar
ordering, all triggers are confirmed from the same bar observation rather than
from an assumed path inside the bar.

Every trade writes `exit_reason` as one of:

```text
stop_loss
take_profit
trailing_stop
max_hold
```

For old fixed-horizon signals with no exit thresholds, `exit_reason` is
`max_hold`.

Funding and costs use the actual `entry_time` to `exit_time` interval. Early
exit shortens funding exposure. Aggregated screening and validation return
summaries keep their current shape.

## Artifact Contract

`signals.csv` remains the human-readable raw strategy output. It should prefer
the new exit columns and the audit fields named in "Strategy Updates" before
appending other keys.

`engine_request.json` should include normalized signal metadata and exit fields.
This file remains the exact request passed to `quant_strategies.engine`.

`evidence.json` should include the same request-derived signal metadata inside
screening result trades. A reviewer should be able to inspect one trade and see:

```text
symbol
decision_time
entry_time
exit_time
entry_price
exit_price
exit_reason
weight
gross_return
funding_return
cost_return
net_return
signal_metadata
```

The evidence schema version should move from
`quant_strategies.engine.evidence/v1` to
`quant_strategies.engine.evidence/v2` because serialized trade shape changes
with `exit_reason` and `signal_metadata`.

## Strategy Updates

Update only the two real research strategies under `untested/`.
`tested/simple_momentum.py` is a runner smoke fixture and should only change if
needed to keep compatibility tests clear.

`untested/crypto_perp_funding_crowding_reversal.py` should emit:

- `max_hold_bars`, sourced from params with the current `hold_bars` fallback.
- Optional `take_profit_bps`, `stop_loss_bps`, and `trailing_stop_bps` when
  present in params.
- `funding_pressure_bps`.
- `entry_return_extension_bps`.
- `signal_family = "crypto_perp_funding_crowding_reversal"`.

`untested/fx_triangular_residual_reversion.py` should emit:

- `max_hold_bars`, sourced from params with the current `hold_bars` fallback.
- Optional `take_profit_bps`, `stop_loss_bps`, and `trailing_stop_bps` when
  present in params.
- `residual_zscore`.
- `residual_bps`.
- `attribution_score`.
- `signal_family = "fx_triangular_residual_reversion"`.

Keep emitted metadata scalar and JSON-compatible. Flat strategy-emitted fields
are preferred for `signals.csv`; the runner owns normalizing those fields into
engine signal metadata.

## Validation And Errors

Model validation should reject invalid exit controls:

- `max_hold_bars` must be a positive integer.
- Exit bps thresholds must be finite positive numbers.
- `metadata` must be JSON-compatible.

Request building should fail closed when:

- Entry fill is outside available bars.
- No exit fill bar is available through the maximum hold and exit lag.
- A quote fill is requested but the selected entry or exit candidate lacks bid
  or ask.
- Metadata cannot be serialized to JSON.

The runner should continue writing prior-stage artifacts on failures, following
the current failure behavior.

## Testing

Add focused tests rather than broad backtester coverage:

- Engine model tests for valid and invalid exit controls.
- Engine screen tests for `max_hold`, `take_profit`, `stop_loss`,
  `trailing_stop`, and same-bar priority.
- Funding test proving early exit shortens funding exposure.
- Runner request-build test proving unknown flat signal fields are folded into
  metadata.
- Runner artifact test proving `engine_request.json`, `evidence.json`, and trade
  output preserve `exit_reason` and signal metadata.
- Strategy tests proving both `untested/` strategies emit the new exit fields and
  audit metadata.
- Regression tests proving old `hold_bars`-only signals still evaluate with
  `exit_reason = "max_hold"`.

## Documentation

Update `README.md` when implementing this design:

- Document signal exit fields.
- Document `exit_reason` in trade artifacts.
- Document signal metadata pass-through.
- State clearly that v1 exits are bar-close or configured-fill-price triggers,
  not intrabar stop-order simulation.
- Note that funding and costs are applied over the actual exit interval.

## Implementation Boundary

This design is one implementation plan. If intrabar stops, portfolio exits,
signal netting, or policy registries become necessary, they should be proposed
as separate changes after this deterministic v1 is working and tested.
