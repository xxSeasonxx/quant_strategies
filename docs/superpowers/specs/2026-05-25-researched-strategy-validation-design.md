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
- Run a required validation matrix before any `clear_yes` decision. The matrix
  must include base windows, realistic costs, stressed costs, fill-lag
  sensitivity, and parameter perturbations for v1.
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

The v1 data flow is:

```text
validation.toml
  -> load rows once per validation window
  -> generate_decisions(rows, params)
  -> data audit
  -> expand validation matrix
       base / realistic costs / stressed costs / fill lag / params
  -> backend adapter runs
  -> aggregate matrix results
  -> hard_no | maybe | clear_yes
  -> artifacts + report
```

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

Backend adapters must either honor the typed decision semantics or reject them
explicitly. In v1, `target_weight` sizing is supported and must affect the
backend run. Any unsupported sizing kind must be reported as unsupported rather
than silently simulated with a default.

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

Backend adapters must fail closed on unfillable decisions. Missing symbols,
missing decision bars, missing entry fills, and missing exit fills are validation
failures, not skipped trades. The default classification is `hard_no`; use
`maybe` only when the failure is clearly an upstream data-coverage limitation
that prevents a fair test.

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
   - load each validation window once, then reuse those rows across all matrix
     scenarios for that window
   - verify required observables
   - verify as_of_time / decision_time causality
   - verify strict validation windows do not silently shift or fill gaps
   - record quant_data limitations explicitly

3. Matrix expansion
   - produce one base scenario per window
   - produce realistic-cost and stressed-cost scenarios
   - produce fill-lag sensitivity scenarios
   - produce parameter perturbation scenarios around selected values
   - mark any scenario as required or diagnostic before execution

4. Backend simulation
   - run each required scenario through VectorBTProBackend
   - optionally run an internal-evaluator cross-check where semantics overlap
   - fail clearly when the requested backend is unavailable or unsupported

5. Decision
   - aggregate scenario-level backend results into robustness_matrix.json
   - classify as hard_no, maybe, or clear_yes
   - write report and machine-readable decision artifact
   - require Season approval before any move into tested/
```

When config loading succeeds, validation must write a decision artifact even on
failure. Data loading failures, strategy import failures, `generate_decisions`
exceptions, data audit failures, backend unavailability, unsupported semantics,
and backend crashes should produce `promotion_decision.json` and
`validation_report.md` with the failing stage and reason. Raw exceptions are
acceptable only before a validation config has been loaded and a result
directory can be created.

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
unfillable decision under the configured validation data
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
backend unavailable for an otherwise interpretable candidate
```

`clear_yes` should be rare. Minimum meaning:

```text
typed decisions are unambiguous
data is causal and reproducible
realistic-cost performance is positive
trade count is adequate for the horizon
out-of-sample / walk-forward windows are stable enough
all required matrix scenarios pass and stress tests degrade gracefully
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
`robustness_matrix.json` should list every scenario, whether it was required or
diagnostic, the backend status, the key metrics, and the classification reason
when a scenario blocks `clear_yes`.

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
4. Add validation matrix scenario models and expansion.
5. Add ValidationBackend and a fake backend for tests.
6. Add VectorBTProBackend behind the adapter boundary.
7. Add validation orchestration, failure envelope, and artifacts.
8. Add promotion decision classification across required matrix scenarios.
9. Add focused tests for models, intake, fake-backend orchestration, matrix
   expansion, failure artifacts, sizing, fillability, unsupported semantics, and
   decision policy.
```

Do not broaden to portfolio validation or unsupported instrument types until the
single-strategy crypto perp path works end to end.

## Verification Plan

Before implementation is considered complete:

- `conda run -n quant pytest`
- targeted tests for decision model validation
- targeted tests for researched package intake
- targeted tests for fake backend orchestration
- targeted tests for validation matrix expansion and aggregation
- targeted tests for failure-envelope artifact writing
- targeted tests for backend sizing fidelity and unfillable-decision rejection
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
