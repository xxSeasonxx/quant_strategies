# Research Evaluation Surface MVP Design

- **Date:** 2026-06-01
- **Status:** Approved design; implementation planning should start after Season
  reviews this written spec.
- **Source context:** `docs/superpowers/specs/2026-06-01-foundation-mvp-roadmap-design.md`,
  `PRD.md`, `README.md`, `FOUNDATION_LOCK.md`, `TODOS.md`, and
  `docs/vectorbtpro.md`.

## Purpose

Add the missing C surface from the foundation roadmap: a stateless research
evaluation run for frozen candidates.

The MVP should answer:

```text
Given this frozen candidate and explicit assumptions, what did the
portfolio/economic/path evidence look like?
```

It should optimize first for portfolio path sanity, with a small robustness
slice across costs, windows, and fill timing.

## Product Boundary

Research evaluation is a third public surface, separate from quick run and
mechanical evidence validation.

```text
quick run             fast one-version diagnostic evidence
validation run        retained-candidate mechanical evidence validation
evaluation run        frozen-candidate portfolio/economic/path evidence
```

Evaluation must not:

- call `run_validation`;
- require validation artifacts;
- write validation artifacts;
- return validation verdicts;
- generate candidates;
- rank variants across a search ledger;
- define stopping rules;
- authorize promotion, paper trading, or live trading.

A human workflow may run evaluation before, after, or alongside validation.
There is no architectural dependency between the two surfaces.

## Public Surface

Expose evaluation as:

```bash
conda run -n quant quant-strategies evaluate path/to/candidate/evaluation.toml
```

and:

```python
from quant_strategies.evaluation import run_evaluation

result = run_evaluation("path/to/candidate/evaluation.toml")
```

The implementation should live under:

```text
src/quant_strategies/evaluation/
```

The result object should be shaped like the existing public result objects but
must not carry promotion authority:

```python
EvaluationRunResult(
    result_dir: Path | None,
    message: str,
    run_completed: bool,
    failure_stage: str | None,
    assessment_status: str,
    evidence_quality_warnings: tuple[str, ...],
)
```

`assessment_status` is status language only, such as
`evaluation_complete`, `evaluation_failed`, or `portfolio_backend_unavailable`.
It is not a pass/fail investment decision.

## Candidate-Local Config

Evaluation uses candidate-local `evaluation.toml` beside `strategy.py`.
Relative `strategy_path` and `[output].results_dir` resolve inside the
candidate directory.

Minimum shape:

```toml
strategy_path = "strategy.py"
strategy_id = "candidate"

[[windows]]
id = "2024_q1"
start = "2024-01-01"
end = "2024-03-31"

[data]
kind = "bars"
dataset = "equity_1min"
symbols = ["SPY", "QQQ"]
start = "2024-01-01"
end = "2024-03-31"
strict = true

[params]
# strategy-specific params

[fill_model]
price = "close"
entry_lag_bars = 1
exit_lag_bars = 0

[cost_model]
fee_bps_per_side = 1.0
slippage_bps_per_side = 2.0

[metrics]
annualization_periods_per_year = 252

[output]
results_dir = "evaluation_results/candidate"
```

`validate_params(params)` is required. Schema-less params must not produce
portfolio evidence.

## Strategy Contract

Evaluation reuses the existing strategy contract exactly:

```python
generate_decisions(rows, params) -> list[StrategyDecision]
validate_params(params) -> Mapping
```

The MVP supports target-weight `StrategyDecision` objects. It should not add a
separate weights, signal, or portfolio contract.

## Scenario Matrix

For each configured window, the MVP evaluates a fixed cross product:

- cost scenarios:
  - `zero_costs`
  - `realistic_costs`
  - `stressed_costs`
- fill scenarios:
  - `base_fill`
  - `fill_lag_plus_1`

Scenario IDs should be explicit and stable, for example:

```text
2024_q1/zero_costs/base_fill
2024_q1/realistic_costs/base_fill
2024_q1/stressed_costs/base_fill
2024_q1/zero_costs/fill_lag_plus_1
2024_q1/realistic_costs/fill_lag_plus_1
2024_q1/stressed_costs/fill_lag_plus_1
```

`zero_costs` sets fees and slippage to zero. `realistic_costs` uses the base
`[cost_model]`. `stressed_costs` doubles the base fees and slippage. `base_fill`
uses `[fill_model]`. `fill_lag_plus_1` increments `entry_lag_bars` by one while
leaving the rest of the fill model unchanged.

User-defined scenario matrices are out of scope for the MVP.

## Execution And Preflight

Evaluation should reuse shared execution primitives, not validation internals:

1. Load candidate-local config.
2. Initialize an evaluation artifact directory.
3. Adapt the config into `StrategyExecutionSpec` for each window with
   `require_param_validator=True`.
4. Execute the strategy through `execute_strategy_run`.
5. Run evaluation-owned preflight before portfolio evaluation.
6. Send normalized rows, decisions, fill model, cost model, scenario identity,
   and metrics assumptions into the VectorBT Pro portfolio evaluator.

Evaluation-owned preflight should cover:

- params were validated;
- rows were normalized and hashed;
- emitted decisions pass the existing decision output contract;
- hidden-lookahead and replay checks are reused through shared causality helpers
  where that can be done without importing validation policy or artifacts.

If hidden-lookahead/replay reuse would require coupling evaluation to validation
or doing a broad refactor, implementation should stop and raise that design
issue before reducing the preflight scope. The design intent is small local
preflight, not a validation dependency.

## Portfolio Backend

The MVP requires VectorBT Pro for portfolio/NAV semantics.

The backend should support:

- target-weight long/short decisions;
- multi-asset evaluation where VectorBT Pro handles it naturally;
- cash sharing for portfolio-level NAV;
- explicit cost/slippage assumptions per scenario;
- explicit fill-lag assumptions per scenario;
- per-asset breakdowns where VectorBT Pro exposes them cleanly.

The package should add a dedicated optional extra:

```toml
[project.optional-dependencies]
evaluation = [
    "pandas>=2.2",
    "pyarrow>=16",
    "vectorbtpro",
]
```

Evaluation runs require this extra. Missing `pandas`, `pyarrow`, or
`vectorbtpro` is a structured evaluation failure. There must be no fallback code
that writes non-Parquet trace artifacts.

## Metrics

Metric outputs are evidence, not gates.

The MVP should emit absolute portfolio/economic/path metrics:

- NAV/path:
  - total return;
  - ending value;
  - periodic return path;
  - max drawdown;
  - drawdown path.
- Economic:
  - annualized return;
  - volatility;
  - Sharpe;
  - Sortino;
  - Calmar.
- Trade behavior:
  - trade count;
  - win rate;
  - profit factor;
  - average win;
  - average loss.
- Risk/path:
  - tail loss metric;
  - worst period return;
  - exposure;
  - gross exposure;
  - net exposure;
  - concentration.
- Activity:
  - turnover.
- Per-asset:
  - return contribution;
  - trade count;
  - exposure basics;
  - turnover basics.

Annualized metrics require explicit
`[metrics].annualization_periods_per_year`. The implementation must not infer
annualization from timestamps.

Benchmark-relative metrics are deferred.

## Artifacts

Evaluation writes a compact human-readable summary plus efficient trace-level
tables.

Small JSON/text artifacts:

- `evaluation_config.toml`
- `strategy_snapshot.py`
- `data_manifest.json`
- `evaluation_metrics.json`
- `scenario_summary.json`
- `evaluation_manifest.json`
- `notes.md`

Detailed trace artifacts are Parquet only:

- `portfolio_path.parquet`: timestamp, scenario ID, portfolio value, returns,
  drawdown, and related path fields.
- `trades.parquet`: trade-level or order-level detail if VectorBT Pro exposes
  it cleanly.
- `positions.parquet`: scenario, timestamp, asset, exposure or position weight
  where available.
- `per_asset_metrics.parquet`: compact asset-level summaries.

The manifest must record every artifact with:

- relative path;
- artifact kind;
- row count for tables;
- column names and logical schema for tables;
- sha256;
- scenario IDs covered;
- metric semantics;
- backend name and version context when available.

Large human-readable trace files are intentionally out of scope. Reviewers
should use `evaluation_manifest.json` to discover and verify Parquet tables.

## Error Handling

Evaluation should return structured results rather than raw tracebacks for
expected failures:

- config load or TOML validation failure;
- artifact initialization failure;
- strategy import failure;
- missing `validate_params`;
- data load or row normalization failure;
- decision generation or decision contract failure;
- preflight integrity failure;
- portfolio backend unavailable;
- portfolio backend unsupported semantics;
- metric extraction failure;
- artifact write failure.

CLI exit-code policy should match existing conventions where practical:

- `0`: completed evaluation run;
- `1`: config, strategy, backend, metric, or artifact failure;
- `3`: data readiness or data availability failure.

No evaluation outcome should use validation's `hard_no`, `watchlist`,
`mechanical_complete`, or similar labels.

## Documentation Updates

Implementation of C must update active docs that describe public surfaces:

- `README.md`
- `PRD.md`
- `FOUNDATION_LOCK.md`
- `TODOS.md`
- `docs/foundation-surfaces.md`
- `docs/vectorbtpro.md`
- `docs/quant-autoresearch-consumer.md` if consumer guidance changes

Docs must preserve these statements:

- evaluation is separate from validation;
- evaluation evidence is advisory;
- evaluation does not authorize promotion, paper trading, or live trading;
- benchmark-relative metrics are deferred;
- detailed trace artifacts are Parquet only with no JSONL fallback.

## Tests

Focused implementation tests should cover:

- candidate-local config path anchoring;
- required `validate_params`;
- CLI/API result behavior and exit codes;
- scenario matrix expansion;
- VectorBT Pro or dependency unavailable structured failure;
- Parquet dependency required with no fallback path;
- backend adapter behavior on small synthetic single-asset and multi-asset
  cases, guarded or mocked so the normal test suite does not require a licensed
  VectorBT Pro install;
- artifact inventory, manifest table metadata, and metric semantics labels;
- docs-language checks that prevent evaluation from drifting into validation or
  promotion language.

## Non-Goals

The MVP does not include:

- benchmark-relative metrics;
- user-defined scenario matrices;
- autonomous ranking;
- search memory;
- stopping rules;
- promotion policy;
- paper-trading readiness;
- live-trading readiness;
- a custom internal portfolio engine fallback;
- JSONL fallback for trace-level evaluation artifacts.

## Risks

- Metric names can imply more authority than the surface has. The artifact and
  docs language must consistently say evidence, not verdict.
- Sharpe, Sortino, Calmar, and annualized return are easy to misuse without
  explicit annualization. The config requires annualization explicitly.
- Reusing validation internals would undo the product-contract clarification.
  Evaluation can reuse shared primitives, but it must not depend on validation
  policy or artifacts.
- High-volume traces can become unreadable or expensive if written as JSONL.
  The MVP requires Parquet and records table schemas in the manifest.

## Implementation Handoff

After Season reviews and approves this written spec, invoke the writing-plans
workflow for C. The plan should start with public config/result contracts,
scenario expansion, the VectorBT Pro/Parquet artifact boundary, and docs updates
before broadening into metric extraction details.
