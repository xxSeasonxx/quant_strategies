# Researched Strategy Validation Design

## Decision

Add a conservative validation workflow inside `quant_strategies` for moving
frozen candidates from `researched/` toward `tested/`.

The validation workflow is separate from the current smoke runner:

```text
quant-strategies run
  Fast research and smoke execution.
  Uses generate_signals.
  Supports quant_autoresearch iteration.

quant-strategies validate
  Conservative researched -> tested validation gate.
  Requires generate_decisions.
  Uses robust validation backend adapters.
```

This creates two workflows, not two strategy implementations. The validation
gate must use one canonical strategy decision contract, independent of
VectorBT PRO, the current internal evaluator, or any future paper/live adapter.

## Goals

- Validate one researched candidate package at a time.
- Bias the gate toward rejecting false positives.
- Require explicit exposure, sizing, timing, and exit semantics before a
  candidate can become `tested/`.
- Use VectorBT PRO as the first robust validation backend.
- Keep VectorBT PRO behind an adapter; strategy files must not import or emit
  VectorBT-specific objects.
- Produce auditable validation artifacts and a three-state decision:
  `hard_no`, `maybe`, or `clear_yes`.
- Keep portfolio construction, paper trading, and live execution out of v1.

## Non-Goals

- Do not replace the current runner or internal evaluator.
- Do not make `quant_autoresearch` own validation.
- Do not create a separate validation repository yet.
- Do not support portfolio allocation across multiple strategies in v1.
- Do not support options, margin liquidation, borrow constraints, partial
  fills, market impact, exchange rejects, or live routing in v1.
- Do not auto-promote code into `tested/` without Season's approval.

## Architecture

Keep lifecycle ownership in `quant_strategies`:

```text
untested/      raw or actively forming strategy ideas
researched/    frozen research handoff packages
tested/        strategies that passed the validation process

src/quant_strategies/
  runner/      current smoke/research runner
  engine/      current simple internal evaluator
  decisions/   typed validation strategy decision contract
  validation/  researched -> tested validation gate
```

The current runner remains narrow evidence infrastructure. It answers whether a
strategy can load, consume causal data, generate smoke-run signals, and complete
a deterministic evaluator run.

The validation workflow answers a stronger question: whether a frozen researched
candidate survives conservative data, cost, fill, sample, and robustness checks
with explicit semantics.

## Strategy Decision Contract

The validation gate requires strategy modules to expose:

```python
def generate_decisions(rows, params) -> list[StrategyDecision]:
    ...
```

`generate_signals(bars, params)` remains allowed for `untested/` research and
smoke runs. It is not enough for `researched -> tested` validation.

The contract should use industry-aligned concepts instead of a generic
"intent" vocabulary:

```text
StrategyDecision
  strategy-level decision at a decision_time using data as of as_of_time

InstrumentRef
  instrument identity and kind, such as crypto_perp, fx_pair, equity_or_etf

PositionTarget
  target long, short, or flat exposure with explicit sizing

OrderIntent
  optional lower-level order request when a target alone cannot express the rule

ExitPolicy
  max hold, stop loss, take profit, trailing stop, or signal-driven exit
```

For v1, prefer `PositionTarget` over raw buy/sell actions. A strategy should
state desired exposure; backend adapters decide whether that requires a buy,
sell, short sale, close, or reduce action.

The contract must distinguish:

```text
long / short / flat = exposure
buy / sell = order mechanics
put / call = instrument type
exit early = exit policy or a later decision to close/reduce exposure
```

Validation rejects ambiguous decisions. Examples:

```text
side="sell" without position context
put/call without option instrument metadata
missing or invalid sizing
non-positive stop/take-profit/trailing thresholds
decision_time before the as-of row was historically available
unsupported instrument or exit semantics required by the candidate
```

## V1 Supported Semantics

V1 supports only candidates whose economics can be represented by:

```text
instrument kinds:
  equity_or_etf
  fx_pair
  crypto_perp

decision semantics:
  target long / short / flat exposure
  fixed target weight or fixed notional sizing
  explicit decision_time and as_of_time
  configured fill timing / lag
  max hold exits
  stop loss / take profit / trailing stop where modeled honestly
  realistic and stressed fee/slippage assumptions
```

Unsupported semantics are roadmap items, not hidden approximations:

```text
options
futures margin and liquidation
borrow constraints
partial fills
capacity and market impact
exchange-specific rejects
live broker/exchange routing
portfolio allocation across multiple strategies
intrabar path ordering unless supported by data and backend
```

If a candidate requires unsupported semantics to be valid, validation should
return `maybe` with reason `unsupported_semantics`, or `hard_no` if the
candidate cannot be interpreted without lying about the economics.

## Backend Boundary

Define a backend adapter interface:

```text
ValidationBackend
  name
  supported_instruments
  supported_exit_policies
  run(decisions, rows, validation_config) -> BackendRunResult
```

The first real backend is:

```text
VectorBTProBackend
```

VectorBT PRO is available in the local `quant` conda environment at design time
as version `2026.4.7`. Unit tests should still use a fake backend so the core
validation orchestration can be tested without requiring the commercial backend
or live data access.

The existing internal evaluator may be exposed through an optional cross-check
backend only where semantics overlap. It should not decide final validation,
because it does not model enough execution, portfolio, or robustness behavior
for `tested/` promotion.

No strategy file may import `vectorbtpro`, build VectorBT arrays, call the
internal evaluator, or write artifacts.

## Validation Flow

Command shape:

```bash
conda run -n quant quant-strategies validate researched/<strategy_id>
```

Pipeline:

```text
1. Intake
   - locate researched package
   - require generate_decisions
   - validate typed StrategyDecision objects
   - hash strategy/config/window definitions
   - reject generate_signals-only candidates

2. Data audit
   - load data through public quant_data APIs
   - verify required observables
   - verify as_of_time / decision_time causality
   - verify strict validation windows do not silently shift or fill gaps
   - record quant_data limitations explicitly

3. Backend simulation
   - run decisions through VectorBTProBackend
   - optionally run an internal-evaluator cross-check where semantics overlap
   - fail clearly when the requested backend is unavailable or unsupported

4. Robustness matrix
   - original researched windows
   - out-of-sample windows not optimized by the research loop
   - realistic costs
   - stressed costs
   - fill-lag sensitivity
   - parameter perturbation around selected values
   - symbol/time subsample stability
   - negative controls where meaningful

5. Decision
   - classify as hard_no, maybe, or clear_yes
   - write report and machine-readable decision artifact
   - require Season approval before any move into tested/
```

## Decision Policy

Use a three-state validation outcome:

```text
hard_no
maybe
clear_yes
```

`hard_no` is automatic. It applies when core validity, causality, sample, cost,
or robustness gates fail. Examples:

```text
no generate_decisions
ambiguous exposure or sizing
lookahead / availability violation
insufficient trades for the stated horizon
negative under realistic costs
edge disappears under modest cost or fill stress
extreme concentration in one symbol or tiny time slice
cannot be reproduced from frozen artifacts
```

`maybe` means the strategy remains interesting but is not eligible for
`tested/`. Examples:

```text
positive but under-sampled
works only in one regime
gross edge appears real but cost assumptions are unresolved
quant_data coverage has material known gaps
parameter perturbation is fragile
backend cross-check disagreement is explainable but unresolved
unsupported semantics are required for a fair test
```

`clear_yes` should be rare. Minimum meaning:

```text
typed decisions are unambiguous
data is causal and reproducible
realistic-cost performance is positive
trade count is adequate for the horizon
out-of-sample / walk-forward windows are stable enough
stress tests degrade gracefully
assumptions and falsifiers are documented
manual review approves movement to tested/
```

The validation tool may recommend `clear_yes`, but it must not automatically
copy code into `tested/`.

## Artifacts

Write validation artifacts under ignored generated output, for example:

```text
validation_results/<strategy_id>/<timestamp>/
  validation_config.toml
  strategy_snapshot.py
  decision_schema.json
  decision_records.jsonl
  data_audit.json
  backend_runs/
    vectorbtpro/
      summary.json
      metrics.json
      trades.parquet or trades.jsonl
  robustness_matrix.json
  promotion_decision.json
  validation_report.md
```

`promotion_decision.json` should be stable enough for automation. The markdown
report should be concise enough for manual review and should explicitly list
hard failures, assumptions, unsupported semantics, and remaining risks.

## Promotion Mechanics

Promotion remains explicit:

```text
researched/<strategy_id>/...
  -> quant-strategies validate researched/<strategy_id>
  -> validation_results/.../promotion_decision.json

if clear_yes + Season approval:
  copy or consolidate validated strategy into tested/<strategy_id>.py
  add focused tests for generate_decisions contract
  add validation report reference
```

The `tested/` folder should contain only strategies with `generate_decisions`.

## First Implementation Slice

Build the smallest end-to-end validator around the current crypto perp funding
candidate:

```text
1. Add typed decision models.
2. Convert one selected researched variant to generate_decisions.
3. Add package-local or repo-local validation config.
4. Add ValidationBackend and a fake backend for tests.
5. Add VectorBTProBackend behind the adapter boundary.
6. Add validation orchestration and artifacts.
7. Add promotion decision classification.
8. Add focused tests for models, intake, fake-backend orchestration,
   unsupported semantics, and decision policy.
```

Do not broaden to portfolio validation or unsupported instrument types until the
single-strategy crypto perp path works end to end.

## Verification Plan

Before implementation is considered complete:

- `conda run -n quant pytest`
- targeted tests for decision model validation
- targeted tests for researched package intake
- targeted tests for fake backend orchestration
- targeted tests for decision classification
- optional local VectorBT PRO integration smoke if the backend is installed
- one validation dry run against the selected researched crypto perp variant

The VectorBT PRO integration check may be skipped only if the environment lacks
the backend. In this repository at design time, the backend is installed in the
`quant` environment.

## References

- QuantConnect Algorithm Framework separates alpha insights, portfolio targets,
  risk management, and execution.
- Backtrader target order APIs separate desired final exposure from the raw
  buy/sell operation required to reach it.
- VectorBT PRO provides the first robust validation backend, but remains an
  adapter rather than the strategy API.
