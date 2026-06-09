# quant_strategies

A disciplined research foundation for **pure strategy functions**,
deterministic **quick runs**, **mechanical evidence validation**, and the
implemented **research evaluation** layer.

It is *not* a trading system and does not imply paper-trading or live-trading
readiness. Its one job is to take a strategy idea from "pure function" to
trustworthy evidence without ever letting a number with unclear semantics drive
a conclusion.

Research evaluation here means stateless evidence for a supplied frozen
candidate. Candidate generation, search memory, ranking, stopping rules, and
iteration decisions remain outside this repo in `quant_autoresearch`.

## Foundation jobs

The project contract separates three jobs:

- **Quick run**: implemented today through `quant-strategies run`; fast causal
  diagnostics for one strategy version.
- **Mechanical evidence validation**: implemented today through
  `quant-strategies validate`; retained-candidate integrity checks across
  windows and scenarios.
- **Research evaluation**: implemented today through `quant-strategies evaluate`;
  stateless portfolio, economic, and path evidence for frozen candidates under
  explicit assumptions.

Validation is not research evaluation. None of these jobs authorizes paper
trading, live trading, or autonomous promotion.

## Architecture

```mermaid
flowchart TD
    cfg["experiment.toml / validation.toml / evaluation.toml"] --> strat
    strat["pure strategy.py<br/>generate_decisions(rows, params) → [StrategyDecision]"] --> spec
    spec["StrategyExecutionSpec<br/>(neutral; all surfaces adapt into it)"] --> kernel
    kernel["one execution kernel<br/>load rows via quant_data · freeze · strict causal replay"] --> evidence
    evidence["frozen rows · typed decisions · causal preflight"] --> pnl
    pnl["one PnL contract<br/>per-trade ledger · funding-aware net"]
    pnl --> quick["quant-strategies run<br/>quick run · diagnostic evidence"]
    pnl --> valid["quant-strategies validate<br/>windows × scenarios → advisory evidence"]
    evidence --> eval["quant-strategies evaluate<br/>frozen candidate → portfolio/path evidence"]
    valid -. "opt-in single-trade check" .-> oracle["VectorBT Pro<br/>single-trade check"]
    eval --> vbt["portfolio backends<br/>VectorBT Pro · project perp ledger · Parquet traces"]
    valid --> human["human promotion review<br/>(outside the code)"]
```

The design has one spine:

- **One strategy contract.** A strategy is a pure `generate_decisions(rows, params)`.
- **One neutral execution spec.** Runner, validation, and evaluation adapt their
  config into the same `StrategyExecutionSpec`; none owns the other's execution
  path.
- **One shared decision/spec kernel plus separate price-evidence paths.** Quick
  run and validation use the internal engine trade-activity path; evaluation
  uses portfolio/NAV evidence through the non-funding VectorBT Pro path or the
  project perp ledger path.
- **One execution kernel.** Import → validate params → load rows (via `quant_data`)
  → freeze inputs → typed decisions → strict causal replay.
- **One PnL contract for quick run and validation.** The shared engine result is
  the single source of trade-level PnL, so **the number a human audits is the
  number the validation decision is computed from.** Evaluation branches from
  the same frozen rows and decisions into portfolio/NAV evidence instead of
  treating NAV metrics and linear trade-activity sums as interchangeable.
- **Three implemented public surfaces today.** A fast *quick run* for diagnostic
  evidence, an *advisory validation run* for retained-candidate mechanical
  evidence, and a stateless *evaluation run* for frozen-candidate portfolio,
  economic, and path evidence. VectorBT Pro remains out of validation verdict
  metrics and is the non-funding evaluation backend.
- **One internal execution engine.** `quant_strategies.engine` is an internal
  kernel used by the quick-run and validation surfaces, not a fourth user-facing
  API. Internal imports and tests can use it; consumers should use the three
  public surfaces above.

Promotion is always a separate human decision, outside this code.

## The strategy contract

Strategies are flat, single-file, and pure. They expose one callable:

```python
generate_decisions(rows, params) -> list[StrategyDecision]
```

- **Pure.** Inspect the `rows` and `params` you were handed; do not load data, call
  engines, write artifacts, loop, or mutate inputs. Computing on the given rows
  (e.g. pandas math) is fine. Purity is enforced by a **best-effort static lint**
  (`decisions/purity.py`) — a first line of defense, not a sandbox; the real
  guarantee is the contract plus review.
- **Optional `validate_params`.** A `validate_params(params) -> Mapping` hook is
  optional for the quick run (schema-less runs are flagged exploratory) but
  **required** for validation and evaluation, so candidate-level evidence never
  rests on params that were never schema-checked.
- **Declared observations.** Validation and evaluation require decision
  observations for candidate-level evidence. Evaluation defaults to at least one
  observation and one observed symbol per decision; validation configs may also
  require specific observation fields.
- **Typed output.** The default output is `StrategyDecision` — a stable
  `decision_id`, instrument, `open` intent, decision/as-of times, target,
  `ExitPolicy`, and `ObservationRef` lineage for consumed rows.
- **Sampled threshold exits.** `ExitPolicy` stop-loss, take-profit, and trailing
  thresholds are evaluated on the configured bar fill-price sample (`close` or
  `quote`) at bar timestamps. They are not intrabar high/low barrier orders.
- **Narrow default ontology.** Equities/ETFs, FX pairs, and crypto perps with
  `open` intent and `target_weight` sizing. Futures, options, multi-leg, book
  side, and other sizings live behind explicit imports from
  `quant_strategies.decisions.extended_ontology`.
- **Documented.** Each module docstring states thesis, observables, rule,
  assumptions, provenance, and falsifier.

## Foundation Surfaces

**Quick run** — `quant-strategies run config.toml`

Loads rows, runs the pure strategy, validates the decision contract, applies the
configured causality replay policy, and computes trade-level diagnostic evidence
for one strategy version. For Train/autoresearch iteration, `micro` replay is a
cheap annotation that never blocks scoring; complete replay remains available
through explicit strict replay and the later validation/evaluation surfaces.
Completed quick-run summaries include engine-derived
`economic_metrics` from the internal trade ledger. Python callers receive
`RunResult`; status lives under `result.outcome`, while replayability,
row-contract, causality, and warning fields live under `result.evidence`.
The runner API does not keep flat compatibility aliases for older result fields.
Use `result.succeeded` as the preferred terminal success check.
Runner-stage failures return `result.outcome.completed is False`, set
`failure_stage`, and write `summary.json` with `run_completed: false`.

**Validation run** — `quant-strategies validate candidate/validation.toml`

Runs the same kernel across configured windows and stress scenarios, then returns
advisory retained-candidate mechanical evidence. It is an evidence audit, not
research evaluation: never statistical significance, regime robustness,
portfolio quality, capacity, or promotion authority. `promotion_eligible` /
`paper_trade_eligible` / `live_eligible` always stay false.
Validation configs require unique window IDs and explicit `[readiness]`
observation coverage. For `crypto_perp_funding`, readiness also requires
decision observations for `close`, `funding_timestamp`, `funding_rate`, and
`has_funding_event`. Per-scenario validation artifacts always expose
`agreement_oracle.status`; raw `agreement` details are emitted only when the
opt-in oracle ran. Validation causality replay defaults to complete replay and
can be explicitly configured as bounded for large-panel research runs.

**Evaluation run** — `quant-strategies evaluate candidate/evaluation.toml`

Runs a frozen candidate through the research evaluation surface and writes
portfolio, economic, and path evidence. Evaluation uses VectorBT Pro for
non-funding data and the project perp ledger for `crypto_perp_funding`; detailed
trace artifacts are Parquet through `pyarrow`, with no JSONL fallback.
Evaluation also writes normalized input row snapshots as Parquet and decision
records as JSONL so completed evaluation metrics can be traced through the
artifact package.
Annualized evaluation metrics use full-grid portfolio returns from
`portfolio_path`, including flat/no-position bars. The configured
`annualization_periods_per_year` must match the bar cadence; completed runs emit
an advisory annualization cadence summary, `annualization_cadence`, with
warnings for cadence mismatches or insufficient observed spacing. Annualized/risk metrics (`annualized_return`, `volatility`,
`sharpe`, `sortino`, and `calmar`) are emitted only when
`annualization_cadence.status` is `ok` and `return_sample_count` meets the
minimum return-sample floor, `[metrics].min_annualized_samples` (default `20`).
Any non-ok cadence status or insufficient samples null that annualized/risk metrics
family without nulling core economics such as `total_return`, `ending_value`,
`max_drawdown`, `return_sample_count`, or `worst_period_return`.
Sortino uses downside semivariance over the full return sample and returns
`None`, not infinity, when undefined.

Python callers use `quant_strategies.evaluation.run_evaluation` and receive
`EvaluationRunResult`. Use `result.succeeded` as the preferred terminal success
check.

Evaluation is not validation. It does not authorize promotion, paper trading, or live trading.
Benchmark-relative metrics are evidence only: when `[benchmark]` is configured,
evaluation reports passive benchmark and excess total return per scenario
without ranking, promotion, paper-trading, or live-trading authority.
Evaluation causality replay defaults to complete replay and can be explicitly
configured as bounded; result provenance records the replay scope.

## Boundaries

- **`quant-data` owns data.** Materialization, refresh, backfill, repair, and
  source joining belong upstream. This repo uses public `quant_data` loader APIs
  only, bounds the supported dependency range as `quant-data>=0.1.0,<0.2.0`,
  and does not discover upstream `.env` files. `quant_data` owns stable row
  ordering for supplied rows; `quant_strategies` preserves supplied row order
  for strategy input, hashing, and execution and does not sort rows locally
  before hashing or execution.
- **The engine reports activity sums, not NAV.** Trade-result metrics are linear
  per-trade sums, not portfolio/NAV-path returns. Validation uses the linear
  activity sum directly; it does not compound that metric as if it were a NAV path.
- **Default executable exposure is unlevered.** Target-weight evidence above
  `1.0` and aggregate active gross target exposure above `1.0` are not normal
  validation evidence. Strategies that need leverage require an explicit future
  ontology/evidence contract.
- **Funding basis differs by surface.** Engine funding is linear trade-activity
  funding folded into validation `net_return`; evaluation funding is NAV-ledger
  cashflow through `project_perp_ledger_v1`. Fillable crypto perp windows with
  no funding events in the open interval accrue zero funding; flagged funding
  rows still fail when malformed, conflicting, or mark-misaligned.
- **Evaluation owns funding-aware perp NAV for research evidence.**
  `crypto_perp_funding` evaluation uses the project-owned
  `project_perp_ledger_v1` cash ledger so NAV, drawdown, trade stats, fees,
  slippage, and funding cashflows share one accounting path. VectorBT Pro remains
  the non-funding portfolio backend.
- **The engine package is internal.** Do not build user workflows on
  `quant_strategies.engine`; call quick run, validation run, or evaluation run.
- **Research evaluation is separate from validation.** Historical portfolio,
  economic, and path evidence belongs in the stateless evaluation surface for
  frozen candidates, not in validation decisions or quick-run hot paths.
  Benchmark-relative metrics are evidence only and do not rank candidates.
- **Causal replay is not statistical proof.** hidden-lookahead replay proves
  point-in-time causal replay; it does not prove out-of-sample validity and it
  does not prove freedom from in-sample fitting.
- **Research archives live outside this repo.** Search-loop archives, ranks, and
  handoff records do not live in the active foundation context. Regenerate or
  rerun evidence instead of relying on historical outputs.

## Usage

Use the `quant` conda environment for all Python commands:

```bash
make check
make check-vectorbtpro-smoke

conda run -n quant python -m pip install -e .
conda run -n quant python -m pip install -e '.[evaluation]' -c constraints/evaluation.txt
conda run -n quant quant-strategies --help
conda run -n quant pytest
conda run -n quant env RUN_VECTORBTPRO_SMOKE=1 pytest tests/test_evaluation_backend.py::test_vectorbtpro_evaluation_backend_real_smoke_if_installed
conda run -n quant quant-strategies run path/to/config.toml
conda run -n quant quant-strategies validate path/to/candidate/validation.toml
conda run -n quant quant-strategies evaluate path/to/candidate/evaluation.toml
```

Run `make check` before relying on the local environment for foundation runs.
It refreshes the editable install, checks the installed CLI, and runs the full
test suite plus the real VectorBT Pro evaluation smoke. The smoke fails loudly
when `pandas`, `pyarrow`, or `vectorbtpro` is missing. Run
`make check-vectorbtpro-smoke` directly when only the real backend smoke matters.
Controlled evaluation runs should install the optional evaluation stack with
`constraints/evaluation.txt`; `pyproject.toml` keeps broad optional dependency
ranges for installability.

Path anchoring differs by surface. Quick-run configs resolve relative paths
against the repository root. Validation and evaluation configs are
candidate-local: after the TOML file is found, `strategy_path` and
`output.results_dir` resolve beside that config file. CLI `--repo-root` anchors
relative config-path lookup; it does not turn candidate-local fields into
repo-root-relative fields.

## Documentation

- **[PRD.md](PRD.md)** — product intent, goals, non-goals, constraints, and
  durable ownership boundaries.
- **[FOUNDATION_LOCK.md](FOUNDATION_LOCK.md)** — locked contracts, accepted debt,
  deferred triggers, and review protocol.
- **[docs/foundation-surfaces.md](docs/foundation-surfaces.md)** — current quick-run,
  validation-run, and evaluation-run command/API/artifact reference.
- **[docs/vectorbtpro.md](docs/vectorbtpro.md)** — VectorBT Pro package facts and
  project boundary.
- **[AGENTS.md](AGENTS.md)** — agent operating rules for this repository.

## Promotion discipline

Advisory validation artifacts support human review; they do not authorize paper
trading, live trading, or promotion. Any future promotion state requires a
separate standard Season approves.
