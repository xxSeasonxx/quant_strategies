# Usage Guide — How to Use `quant_strategies`

*Write a pure strategy, then run it through quick-run, validation, and evaluation.*
For the front door and ownership boundaries see [README.md](README.md); for exact
signatures, schema, and config keys see [reference.md](reference.md).

> Every example below uses real, current signatures and config keys. Data windows
> and symbols are **not** authoritative here — what exists and what is safe to load
> is owned upstream by `quant_data` (`quant-data/docs/consumer/`).

---

## Mental model

One strategy contract, one execution kernel, three evidence surfaces:

```text
pure strategy.py                 config.toml (run / validation / evaluation)
generate_decisions(rows, params)        │
        │                               ▼
        └───────────►  one execution kernel  ◄───────────┐
                       load rows via quant_data (strict)  │
                       → freeze inputs                     │
                       → typed StrategyDecision[]           │
                       → strict causal replay               │
                              │                             │
              ┌───────────────┼─────────────────┐          │
              ▼               ▼                  ▼          │
         quick run        validation         evaluation ────┘
       trade-activity    windows × stress    portfolio / NAV / path
       diagnostics       advisory decision   (VectorBT Pro · perp ledger)
```

- **Quick run and validation** share the internal engine's trade-activity PnL
  path — *the number a human audits is the number the validation decision is
  computed from.*
- **Evaluation** branches from the same frozen rows and decisions into
  portfolio/NAV evidence: VectorBT Pro for non-funding data, a project-owned perp
  ledger for `crypto_perp_funding`.

You pick the surface by intent. You never wire them together yourself — each reads
one config and returns one typed result.

## Install & environment

All Python runs in the conda environment `quant`.

```bash
conda run -n quant python -m pip install -e .                                  # core
conda run -n quant python -m pip install -e '.[evaluation]' -c constraints/evaluation.txt  # + evaluation backends
conda run -n quant quant-strategies --help
```

Evaluation writes Parquet traces and runs VectorBT Pro, so it needs the
`[evaluation]` extra (`pandas`, `pyarrow`, `vectorbtpro`). Quick run and validation
do not. To verify the whole foundation locally, run `make check` (refreshes the
editable install, checks the CLI, runs pytest, and runs the real VectorBT Pro
evaluation smoke).

---

## The strategy contract

A strategy is **flat, single-file, and pure**. It exposes one required callable
and one near-required one:

```python
generate_decisions(rows, params) -> list[StrategyDecision]   # required
validate_params(params) -> Mapping                            # required for validate/evaluate
```

### 1. The module docstring (required)

Open every strategy with a docstring covering, in plain prose:

- **Source / provenance** — specific enough to audit: paper title + authors +
  year + DOI/SSRN/URL, or a web/repository URL, or an internal note path *plus the
  upstream source it cites*. Vague labels are rejected in review.
- **Market rationale** — why an edge could plausibly exist.
- **Required observables** — which row fields the rule reads.
- **Decision rule** — the executable rule, stated precisely.
- **Assumptions** — proxy/data/fill assumptions that could break the result.
- **Falsifier** — what observation would make you reject the idea.

See [`untested/krohn_mueller_whelan_fix_reversal.py`](../../untested/krohn_mueller_whelan_fix_reversal.py)
for a strong provenance example (a published *Journal of Finance* paper with DOI).

### 2. `generate_decisions(rows, params)` — purity rules

You receive `rows` (an ordered sequence of plain mapping rows, already loaded and
normalized) and `params` (a mapping). You return a list of `StrategyDecision`.

**Allowed:** reading `rows`/`params`, arithmetic, pandas/numpy math over the given
rows, building decisions.

**Banned:** loading data, calling engines or run surfaces, file/network I/O,
dynamic imports, clocks (`datetime.now`), RNG, mutating inputs, and background
loops. A best-effort AST lint (`decisions/purity.py`) catches common violations;
the contract and review are the real guarantee. You can self-check:

```python
from quant_strategies.decisions import strategy_purity_violations
print(strategy_purity_violations("my_strategy.py"))  # pass the path; () means clean
```

**Respect causal time inside the rule.** Gate on each row's `available_at`, not its
`timestamp`. Do not let a decision at bar *t* read any value that only becomes
observable after `decision_time`. The harness re-runs your function under causal
replay and fails the run on hidden lookahead.

### 3. `validate_params(params)` — the params contract

Return a normalized mapping or raise on invalid input. Optional for quick runs
(an absent validator is a passthrough); **required** for validation and
evaluation. Keep it strict — reject non-finite, out-of-range, or unknown values.

### 4. Authoring a `StrategyDecision`

`StrategyDecision` is a frozen, strict Pydantic model (`extra="forbid"`). Build it
with the public types from `quant_strategies.decisions`:

```python
from quant_strategies.decisions import (
    StrategyDecision, InstrumentRef, PositionTarget, ExitPolicy, ObservationRef,
)

StrategyDecision(
    strategy_id="my_strategy",
    instrument=InstrumentRef(kind="equity_or_etf", symbol="SPY"),
    #   kind ∈ {"equity_or_etf", "fx_pair", "crypto_perp"}
    decision_time=ts,          # tz-aware datetime; when the decision is made
    as_of_time=ts,             # tz-aware; data cutoff. MUST be <= decision_time
    target=PositionTarget(
        direction="long",      # "long" | "short" | "flat"
        sizing_kind="target_weight",   # only target_weight today
        size=0.25,             # >= 0; long/short require > 0; flat must be 0
    ),
    exit_policy=ExitPolicy(
        max_hold_bars=10,      # >= 1
        stop_loss_bps=None,    # optional, bar-sampled (see caveat)
        take_profit_bps=None,
        trailing_stop_bps=None,
    ),
    observations=(             # the rows your rule actually read
        ObservationRef(symbol="SPY", timestamp=prev_ts, field="close", source="strategy_input"),
        ObservationRef(symbol="SPY", timestamp=ts, field="close"),
    ),
)
```

Notes that matter:

- **`observations` are evidence, not decoration.** Validation and evaluation audit
  that every declared observation is causally available (observation `timestamp`
  must be observable by `decision_time`). They default to requiring at least one
  observation and one observed symbol per decision; validation configs can require
  specific fields. Declare the rows your rule depended on.
- **Exit thresholds are bar-sampled, not intrabar barriers.** `stop_loss_bps`,
  `take_profit_bps`, and `trailing_stop_bps` are evaluated against the configured
  fill price (`close` or `quote`) at bar timestamps — not as intrabar high/low
  barrier orders. Size your `max_hold_bars` and thresholds accordingly.
- **`decision_id` is auto-derived** from the decision content if you leave it
  `None`. Equal decisions get equal ids.
- **Keep signal logic free of execution feasibility.** Fillability and hold-window
  feasibility belong in execution/evaluation, not in `generate_decisions`.

---

## Choose your data kind

`[data].kind` selects the upstream strict loader and the row fields you can read.
You never call the loader; you just declare the kind, dataset, symbols, and window.

| `[data].kind` | Upstream loader | `dataset` key | Extra row fields | Typical instrument kind | Fill price |
|---|---|---|---|---|---|
| `bars` (one symbol) | `load_strategy_bars` | required (e.g. `equity_1min`, `equity_daily`, `crypto_perp_1min`, `forex_1min`, `forex_daily`) | — | `equity_or_etf` / `crypto_perp` / `fx_pair` | `close` |
| `bars` (many symbols) | `load_strategy_universe_bars` | required | — | as above | `close` |
| `forex_with_quotes` | `load_fx_bars_with_quotes` | inferred from kind | `bid`, `ask`, `mid` (`bid<=mid<=ask`) | `fx_pair` | `quote` |
| `crypto_perp_funding` | `load_crypto_perp_bars_with_funding` | inferred from kind | `funding_timestamp`, `funding_rate`, `has_funding_event` | `crypto_perp` | `close` |

Every kind delivers `symbol`, `timestamp`, `available_at`, and OHLC
(`open`/`high`/`low`/`close`). **`available_at` is a hard requirement on every row
in every surface** — a missing or invalid stamp fails the row contract before any
lookahead check. Multi-symbol `bars` returns one frame ordered `(timestamp,
symbol)`; a missing requested symbol raises upstream.

For a single name use one entry in `symbols`; for a universe list every symbol you
want (a missing one is an error, not a silent drop). For what symbols and windows
actually exist, read the quant-data consumer guide — do not infer them from names.

---

## Shared config building blocks

All three surfaces share these sections (full key list in
[reference.md](reference.md#config-reference)):

```toml
[data]              # kind, dataset (bars only), symbols; start/end for quick run
[params]            # passed verbatim to your strategy's validate_params/generate_decisions
[fill_model]        # price = "close"|"quote"; entry_lag_bars; exit_lag_bars
[cost_model]        # fee_bps_per_side; slippage_bps_per_side
[output]            # results_dir (+ profile/sizing for quick run)
```

**Fill timing.** `entry_lag_bars = 1` means a close-derived signal at bar *t* fills
at bar *t+1*, not on the signal close. This is how you keep a close signal causal.

**Path anchoring.**

- Quick-run relative paths are **repo-root-relative** (or pass `--repo-root`).
- Validation/evaluation config paths resolve from the current directory (or
  `--repo-root`); once the TOML is found, its `strategy_path` and
  `output.results_dir` resolve **relative to the config's directory**. This is why
  candidate-local `validation.toml` / `evaluation.toml` use `strategy_path =
  "simple_momentum.py"` (sibling file) rather than a repo-root path.

Generated output roots — `results/`, `validation_results/`, `evaluation_results/`
— are git-ignored. Treat them as regenerable evidence, never as source.

---

## Surface 1 — Quick run

**Purpose:** diagnose one strategy version fast. Trade-level diagnostic evidence
for iteration. *Not* validation, ranking, or promotion.

```bash
conda run -n quant quant-strategies run runs/simple_momentum_spy_daily.toml
# add --events-jsonl to stream structured stage events to stderr
```

```python
from quant_strategies.runner import run_config

result = run_config("runs/simple_momentum_spy_daily.toml")  # repo_root=, event_sink= optional
if not result.succeeded:
    raise SystemExit(result.message)

print(result.result_dir)
print(result.outcome.assessment_status)      # diagnostic status, not a verdict
print(result.evidence.causality.replay_scope)
print(result.evidence.causality.verified)    # false for micro failures/timeouts
print(result.evidence.causality.replay_warning)
print(result.evidence.row_contract)          # row-contract summary
print(result.economics.trade_count)          # after-cost trade ledger summary
```

**Config** (`experiment.toml`): top-level `strategy_path`, `strategy_id`; `[data]`
with inline `start`/`end`; `[params]`, `[fill_model]`, `[cost_model]`; `[output]`
with `results_dir`, `quick_checks`, `artifact_profile`, optional
`causality_check`, and (for the diagnostic profile) `diagnostic_sample_trades`.
Use `causality_check = "micro"` for Train/autoresearch iteration. See
[`runs/simple_momentum_spy_daily.toml`](../../runs/simple_momentum_spy_daily.toml).

For Train iteration, `[data].start` / `[data].end` are the strategy-visible
decision and scoring window. If exits need later bars, add `[data].load_end`
as execution-only coverage. The strategy and causality replay still cannot see
those buffer rows; the engine can use them only to resolve fills and exits.

**`artifact_profile`** controls how much is written. `full` is the only profile
that is replayable from artifacts (it writes the strategy input rows, decision
records, engine request, and evidence). `summary` and `diagnostic` are compact;
`diagnostic` adds `diagnostics.json` with economic slices. Completed runs always
write `summary.json` (with `economic_metrics`), `run_manifest.json`, `notes.md`,
`config.toml`, `strategy_snapshot.py`, and `environment.json`.

Programmatic consumers can read quick-run after-cost economics from
`result.economics` on completed engine runs. The object carries the raw per-trade
ledger plus the same summary scalars/slices written to artifacts, even under
`artifact_profile = "summary"`; no `summary.json` scraping is required.

The micro causality policy is the Train/autoresearch replay annotation. It runs a
tiny bounded replay sample, records probe and timeout evidence, and never blocks
quick-run scoring. If micro replay fails or times out, quick-run economics still
complete when request building and engine evaluation succeed, and causality is
marked unverified; downstream ranking should read that replay status explicitly.
Survivor and audit evidence belongs in validation/evaluation. Low-level replay
settings and focused source-hash replay are advanced controls documented in the
reference; the strategy-writing LLM should not choose them during research
iteration.

**Reading it:** success is `result.succeeded`. On failure, `result.outcome
.failure_stage` names the stage that failed and `summary.json` sets
`run_completed=false`. `assessment_status` stays diagnostic — it never authorizes
anything.

---

## Surface 2 — Validation

**Purpose:** audit retained-candidate evidence integrity across windows and a fixed
stress matrix; emit an **advisory** validation decision. Requires `validate_params`.
Runs strict row-contract, observation, and hidden-lookahead checks, and rejects
levered or aggregate-overexposed target-weight evidence before backend scenarios.

```bash
conda run -n quant quant-strategies validate path/to/candidate/validation.toml
```

```python
from quant_strategies.validation import run_validation

result = run_validation("path/to/candidate/validation.toml")
if not result.succeeded:                     # run integrity, not the verdict
    raise SystemExit(result.message)

print(result.decision.decision)              # advisory label; may be "mechanical_fail"
print(result.result_dir)
```

**Config** (`validation.toml`): top-level `strategy_path`, `strategy_id`, optional
`verdict_source`; one or more `[[windows]]` (each with a unique `id` + `start`/`end`);
`[data]`, `[params]`, `[fill_model]`, `[cost_model]`; `[readiness]`
(`min_observations_per_decision`, `required_observation_fields`); `[output]`;
`[search_pressure]` (`prior_search`); optional `[mechanical_thresholds]` and
`[agreement_oracle]`. See
[`examples/strategies/simple_momentum_spy_daily_validation.toml`](../../examples/strategies/simple_momentum_spy_daily_validation.toml).

For `crypto_perp_funding`, `[readiness]` additionally requires `close`,
`funding_timestamp`, `funding_rate`, and `has_funding_event` observations on every
decision. Window `id`s must be unique and must not collide after artifact-path
sanitization.

**Reading it:** `result.succeeded` means the run completed with no failure stage.
The advisory `result.decision.decision` (including `mechanical_fail`) is *evidence*
— it never authorizes promotion, paper trading, or live trading. The production
verdict backend is the internal engine; VectorBT Pro participates only as an
opt-in single-trade agreement oracle (not multi-trade confidence).

---

## Surface 3 — Evaluation

**Purpose:** evaluate a frozen candidate through a stateless portfolio evidence
surface — portfolio, economic, and path metrics under explicit cost/fill
assumptions. Requires `validate_params`. Runs strict row-contract, a decision-row
data audit, and a complete causal-replay preflight *before* any scenario expands.

```bash
conda run -n quant quant-strategies evaluate candidate/evaluation.toml
# --events-jsonl streams structured evaluation_stage events to stderr
```

```python
from quant_strategies.evaluation import run_evaluation

result = run_evaluation("candidate/evaluation.toml")  # event_sink= optional
if not result.succeeded:
    raise SystemExit(f"{result.failure_stage}: {result.message}")

print(result.result_dir)
print(result.assessment_status)
print(result.evidence_quality_warnings)
```

**Config** (`evaluation.toml`): top-level `strategy_path`, `strategy_id`;
`[[windows]]`; `[data]`, `[params]`, `[fill_model]`, `[cost_model]`; `[metrics]`
with `annualization_periods_per_year` (must match bar cadence) and optional
`min_annualized_samples` (default `20`); optional `[readiness]`, optional
`[benchmark]` (`symbol`, which must also appear in `data.symbols`), and optional
`[[scenarios]]` (each with `id`, labels, `required`, and nested
`[scenarios.cost_model]` / `[scenarios.fill_model]` overrides); `[output]`. See
[`examples/strategies/simple_momentum_spy_daily_evaluation.toml`](../../examples/strategies/simple_momentum_spy_daily_evaluation.toml).

With no custom `[[scenarios]]`, evaluation fans out the default fixed six-scenario
cost/fill matrix per window.

**Metric trust boundary.** Annualized/risk metrics (`annualized_return`,
`volatility`, `sharpe`, `sortino`, `calmar`) are emitted **only** when the
annualization cadence status is `ok` and `return_sample_count` meets
`[metrics].min_annualized_samples`. Otherwise that family is nulled — without
nulling core economics (`total_return`, `ending_value`, `max_drawdown`,
`worst_period_return`, `return_sample_count`). Sortino returns `None`, not
infinity, when undefined. `[benchmark]` adds passive `benchmark_total_return` and
`excess_total_return` evidence only — no ranking or promotion.

**Funding.** For `crypto_perp_funding`, evaluation uses a project-owned perpetual
futures ledger whose NAV path includes price PnL, configured fees/slippage, and
funding cashflows (VectorBT Pro `cash_dividends` is not used for funding). Fillable
perp windows with no funding events in the open interval accrue zero funding;
malformed/conflicting/mark-misaligned funding rows still fail.

Evaluation writes Parquet-only traces (`tables/portfolio_path.parquet`,
`trades`, `target_positions`, `target_exposure_summary`, `funding_cashflows`) and
requires `pyarrow`. There is no JSONL fallback for row snapshots or traces.

**Per-fold OOS returns in-process (no Parquet scraping).** A completed
`EvaluationRunResult` also carries the per-`(window, scenario)` out-of-sample
return series typed and in-process, so a consumer never has to read
`tables/portfolio_path.parquet`. Orchestrate one window (one fold) per `evaluate`
call and read the series for the scenario your protocol selects:

```python
result = run_evaluation("candidate/evaluation.toml")
if not result.succeeded:
    raise SystemExit(f"{result.failure_stage}: {result.message}")

# per-fold Tier-0 causal-replay / decision-contract integrity
assert result.causal_replay_passed is True

# pick the costs-on / fixed-fill scenario your protocol uses
series = result.returns_for("eval_2026_h1", "eval_2026_h1/realistic_costs/base_fill")
returns = series.values            # numpy float64, net of costs (synthetic first return dropped)
times = series.timestamps          # numpy datetime64[ns], aligned to returns
ppy = series.periods_per_year      # annualization cadence from [metrics]

metrics = result.metrics_for(series.window_id, series.scenario_id)
sharpe = metrics.sharpe            # undeflated; None under a cadence/sample guard
```

The series `values` use the same observed-return definition as the summary metrics
(drop the synthetic first return, exclude non-finite), so they match the
`period_return` rows in the Parquet trace. `series.per_symbol` is `None` for the
current grouped cash-shared backends. No significance statistics (PSR/DSR/PBO) are
provided — significance is the consumer's job.

---

## Reading results programmatically

All three result types expose `result.succeeded` — **use it as the success check.**
It means the run completed and `failure_stage is None`.

| Result | Success | Verdict / status field | On failure |
|---|---|---|---|
| `RunResult` | `result.succeeded` | `outcome.assessment_status` (diagnostic) | `outcome.failure_stage`; `evidence.warnings` |
| `ValidationRunResult` | `result.succeeded` | `decision.decision` (advisory; may be `mechanical_fail`) | `failure_stage`; config-load failure → `result_dir=None`, `failure_stage="config_load"` |
| `EvaluationRunResult` | `result.succeeded` | `assessment_status` | `failure_stage` (`data_audit`, `preflight`, …); `evidence_quality_warnings` |

`mechanical_fail` is **not** a run failure — the run succeeded and produced an
advisory negative verdict. Distinguish "did the run complete?" (`succeeded`) from
"what did it conclude?" (`decision` / `assessment_status`). Full field lists and
CLI exit codes are in [reference.md](reference.md#result-reference).

---

## Programmatic consumer (`quant_autoresearch` and friends)

Downstream automation should consume **only** the three public entry points and
the `result.succeeded` check:

```python
from quant_strategies.runner import run_config        # -> RunResult
from quant_strategies.validation import run_validation # -> ValidationRunResult
from quant_strategies.evaluation import run_evaluation  # -> EvaluationRunResult
```

Each accepts `(config_path, *, repo_root=None, event_sink=None)`. Pass an
`event_sink` for structured stage observability.

For quick-run search loops, use `RunResult.economics.trades` as the in-process
after-cost trade sample for Train slicing by time or symbol. This is trade-unit,
point-to-point engine economics only; use `run_evaluation` for OOS period-return
series or portfolio/NAV evidence.

**In scope downstream:** generating candidate strategies and configs, deciding
what to run, and reading the typed results/artifacts. **Out of scope (stays in
`quant_autoresearch`, not here):** ranking, comparison, search memory, stopping
rules, and promotion. Do not import `quant_strategies.engine` or any
`_`-prefixed/internal module — they are not the contract.

---

## Pre-flight checklist (before validate / evaluate)

1. Docstring states a **specific** provenance (paper+DOI/URL or note+source).
2. `validate_params` exists and rejects invalid input.
3. `generate_decisions` is pure — run `strategy_purity_violations` and confirm `()`.
4. Signals gate on `available_at`; no decision reads a future row.
5. Every decision declares the `observations` its rule actually used.
6. `[data].kind`, `dataset` (for `bars`), `symbols`, and window match what
   `quant_data` actually publishes.
7. For evaluation, `annualization_periods_per_year` matches your bar cadence.
8. Config paths follow the anchoring rule (candidate-local `strategy_path` is a
   sibling path).

---

## Anti-patterns (do not do these)

- **Do not load data inside a strategy.** No DB calls, file reads, or `quant_data`
  imports in `generate_decisions`. Declare `[data]` and read the rows you are given.
- **Do not import the engine or internals** (`quant_strategies.engine`, `_`-modules)
  in consumer code. Use the three public surfaces.
- **Do not key signals off `timestamp`.** Use `available_at` for observability.
- **Do not put execution feasibility in signal logic.** Fillability and hold
  windows belong to execution/evaluation.
- **Do not treat a metric or artifact as proof.** They are evidence; nothing here
  proves out-of-sample validity or trading readiness.
- **Do not read `mechanical_fail` as a crash**, or `result.succeeded` as a positive
  verdict. They answer different questions.
- **Do not sort, de-duplicate, join, or repair rows** to make a run pass. A bad row
  shape is upstream feedback for `quant_data`, not a local shim.
- **Do not commit `results/` artifacts as source** — they are regenerable.
