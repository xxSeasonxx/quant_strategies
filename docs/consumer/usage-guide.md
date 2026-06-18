# Usage Guide — How to Use `quant_strategies`

*Write a pure strategy, then run it through quick-run, validation, and evaluation.*
For the front door and ownership boundaries see [README.md](README.md); for exact
signatures, schema, and config keys see [reference.md](reference.md).

> Every example below uses real, current signatures and config keys. Data windows
> and symbols are **not** authoritative here — what exists and what is safe to load
> is owned upstream by `quant_data` (`quant-data/docs/consumer/`).

---

## Mental model

One strategy contract, one execution kernel, **one accounting book**, three
evidence surfaces:

```text
pure strategy.py                 config.toml (run / validation / evaluation)
generate_decisions(rows, params)        │
        │                               ▼
        └───────────►  one execution kernel  ◄───────────┐
                       load rows via quant_data (strict)  │
                       → freeze inputs                     │
                       → typed TargetDecision[] (book)      │
                       → strict causal replay               │
                              │                             │
                       one causal netted portfolio book ────┘
                       (same-symbol netting · financing ·
                        mark-to-market) → NAV path = the
                        single scored object; per-trade
                        ledger is a derived attribution view
                              │
              ┌───────────────┼─────────────────┐
              ▼               ▼                  ▼
         quick run        validation         evaluation
       NAV-book Train    windows × stress    portfolio / NAV / path
       diagnostics       advisory decision   (+ Parquet trace serialization)
```

- **All three surfaces** consume the same target-book contract and the **same
  single causal netted portfolio book** (`netted_portfolio_book_v1`). The NAV path
  is the authoritative scored object; the per-trade ledger is a derived attribution
  view of that same walk, never an independent scored number — there is one model
  of money, not two.
- **Evaluation** runs that same pure book and adds only artifact serialization
  (pandas/pyarrow Parquet traces) around it.

You pick the surface by intent. You never wire them together yourself — each reads
one config and returns one typed result.

## Install & environment

All Python runs in the conda environment `quant`.

```bash
conda run -n quant python -m pip install -e .                                  # core
conda run -n quant python -m pip install -e '.[evaluation]' -c constraints/evaluation.txt  # + evaluation trace serialization
conda run -n quant quant-strategies --help
```

Evaluation runs the same pure portfolio book as quick run and validation, and adds
**Parquet trace serialization**, so it needs the `[evaluation]` extra for `pandas`
and `pyarrow`. Quick run and validation do not. To verify the foundation locally,
run `make check` (refreshes the editable install, checks the CLI, runs pytest).

---

## The strategy contract

A strategy is **flat, single-file, and pure**. It declares a **target book** and
exposes one required callable and one near-required one:

```python
generate_decisions(rows, params) -> Sequence[TargetDecision]   # required
validate_params(params) -> Mapping                             # required for validate/evaluate
```

A `TargetDecision` is a **standing, signed base target shape** for one instrument
(`+` long, `-` short, `0` = flat/close) that holds until your next decision for
that symbol changes it. Targets are **idempotent** (re-emitting the current target
is a no-op), so same-symbol exposure nets by construction and repeated signals
cannot stack into hidden leverage. You own the portfolio shape: allocation,
netting intent, rebalancing, explicit exits, and optional declared price-path risk.
The foundation owns conversion from shape to final executable weights through
`[risk_budget]`.

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

See [`candidates/krohn_mueller_whelan_fix_reversal/strategy.py`](../../candidates/krohn_mueller_whelan_fix_reversal/strategy.py)
for a strong provenance example (a published *Journal of Finance* paper with DOI).

### 2. `generate_decisions(rows, params)` — purity rules

You receive `rows` (an ordered sequence of plain mapping rows, already loaded and
normalized) and `params` (a mapping). You return a sequence of `TargetDecision`.

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

### 4. Authoring a `TargetDecision`

`TargetDecision` is a frozen, strict Pydantic model (`extra="forbid"`). Build it
with the public types from `quant_strategies.decisions`:

```python
from quant_strategies.decisions import (
    TargetDecision, InstrumentRef, RiskRule, ObservationRef,
)

TargetDecision(
    strategy_id="my_strategy",
    instrument=InstrumentRef(kind="equity_or_etf", symbol="SPY"),
    #   kind ∈ {"equity_or_etf", "fx_pair", "crypto_perp"}
    decision_time=ts,          # tz-aware datetime; when the decision is effective
    as_of_time=ts,             # tz-aware; data cutoff. MUST be <= decision_time
    target=0.25,               # signed base shape: + long, - short, 0 = flat/close
    risk_rule=RiskRule(        # optional; engine-enforced price-path exits on the net position
        stop_loss=0.05,        # fraction of entry mark (5% adverse) — not bps
        take_profit=None,
        trailing=None,
    ),
    observations=(             # the rows your rule actually read
        ObservationRef(symbol="SPY", timestamp=prev_ts, field="close", source="strategy_input"),
        ObservationRef(symbol="SPY", timestamp=ts, field="close"),
    ),
)
```

Notes that matter:

- **The target is a standing signed shape, not a one-shot ticket.** It holds until
  your next decision for that instrument changes it. To close, emit `target=0`. To
  rebalance shape, emit explicit periodic decisions; the foundation applies the
  risk budget once the full shape stream is known, then the engine fixes the held
  quantity at each decision bar.
- **Targets net, they never stack.** Emitting `+0.20` then `+0.30` for one symbol
  resolves to `+0.30`, not `+0.50`. Re-emitting the standing target trades nothing.
- **Two kinds of exit.** Anything derivable from **data or time** (signal reversal,
  fixed hold horizon) is an explicit `target=0` (or new) decision — pure, because
  you know your own decision times. Anything derivable only from the **realized
  price path** (stop / take-profit / trailing) is a declared `RiskRule` the engine
  enforces causally; a strategy may not read future rows to place its own stop.
- **A fired `RiskRule` latches the instrument flat** until you emit a new (different)
  target for it — otherwise a standing target would immediately re-enter and the
  stop would be useless.
- **Exit thresholds are intrabar barriers.** `RiskRule` thresholds are evaluated against
  the bar's intrabar range (high/low), so a stop pierced intrabar fires even if the close
  recovered. The exit fills at the barrier level, worsened to the bar open on a gap-through
  (`take_profit` takes no gap-favorable bonus); an adverse barrier wins a same-bar tie with
  `take_profit`. A diagnostic `fill_stress` scenario applies extra adverse slippage to these
  barrier exits — it never changes the climbed `realistic_costs` path.
- **`observations` are evidence, not decoration.** Validation and evaluation audit
  that every declared observation is causally available (observation `timestamp`
  must be observable by `decision_time`). They default to requiring at least one
  observation and one observed symbol per decision; validation configs can require
  specific fields. Declare the rows your rule depended on.
- **`decision_id` is auto-derived** from the decision content if you leave it
  `None`. Equal decisions get equal ids.
- **Keep signal logic free of execution feasibility.** The engine owns fills,
  costs, netting, financing, and the leverage budget; `generate_decisions` declares
  the intended book, not the accounting.

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
[fill_model]        # price = "close"|"quote"; entry_lag_bars
[cost_model]        # fee_bps_per_side; slippage_bps_per_side
[capacity_model]    # mode = "adv_impact"|"off"; portfolio_notional + ADV/impact limits
[leverage_budget]   # max_gross_exposure; max_net_exposure
[risk_budget]       # mode + explicit annualization cadence + target_volatility/book_scale
[output]            # results_dir (+ profile/sizing for quick run)
```

Quick-run Train configs may use:

```toml
[risk_budget]
mode = "calibrate_vol"
annualization_periods_per_year = 98280
target_volatility = 0.10
```

Validation and evaluation configs use the retained quick-run scale:

```toml
[risk_budget]
mode = "fixed_scale"
annualization_periods_per_year = 98280
book_scale = 0.75
```

**Fill timing.** `entry_lag_bars = 1` means a close-derived signal at bar *t* fills
at bar *t+1*, not on the signal close. This is how you keep a close signal causal.

**Path anchoring.**

- Quick-run config paths are **repo-root-relative** (or pass `--repo-root`);
  quick-run `strategy_path` resolves relative to the TOML file.
- Validation/evaluation config paths resolve from the current directory (or
  `--repo-root`); once the TOML is found, its `strategy_path` and
  `output.results_dir` resolve **relative to the config's directory**. This is why
  candidate-local configs use `strategy_path = "strategy.py"` (sibling file)
  rather than a repo-root path.

Generated output roots — `results/`, `validation_results/`, `evaluation_results/`
— are git-ignored. Treat them as regenerable evidence, never as source.

---

## Surface 1 — Quick run

**Purpose:** diagnose one strategy version fast. Trade-level diagnostic evidence
for iteration. *Not* validation, ranking, or promotion.

```bash
conda run -n quant quant-strategies run examples/simple_momentum/run.toml
# add --events-jsonl to stream structured stage events to stderr
```

```python
from quant_strategies.runner import run_config

result = run_config("examples/simple_momentum/run.toml")  # repo_root=, event_sink= optional
if not result.succeeded:
    raise SystemExit(result.message)

print(result.result_dir)
print(result.outcome.assessment_status)      # diagnostic status, not a verdict
print(result.feasibility)                     # None on a feasible run; typed verdict on a breach
print(result.evidence.causality.replay_scope)
print(result.evidence.causality.verified)    # false for micro timeout/incomplete evidence
print(result.evidence.causality.replay_warning)
print(result.evidence.row_contract)          # row-contract summary
print(result.foundation.feasible)            # authoritative scored NAV book on a completed run
```

**Config** (`experiment.toml`): top-level `strategy_path`, `strategy_id`; `[data]`
with inline `start`/`end`; `[params]`, `[fill_model]`, `[cost_model]`,
`[capacity_model]`, `[leverage_budget]`, `[risk_budget]`; `[envelope] operator_frozen = true`
when the quick-run evidence may be retained; `[output]` with `results_dir`,
`quick_checks`, `artifact_profile`, optional
`causality_check`, quick-run foundation controls
(`foundation_subwindows`, `foundation_cost_stress_multiplier`,
`foundation_fill_stress_fraction`, `foundation_min_return_sample`), and (for the
diagnostic profile) `diagnostic_sample_trades`.
`foundation_subwindows` accepts 1-64 windows. `foundation_min_return_sample`
defaults to 20 and accepts integers >= 2 for explicit diagnostics.
The **leverage budget (gross and net) is operator-frozen** in the
`[leverage_budget]` section (`max_gross_exposure` / `max_net_exposure`, default
`1.0/1.0`, `>= 1.0`). `[output]` owns artifact controls. Intended exposure
beyond the budget makes the run non-scoreable through the feasibility verdict
(`leverage_budget_breach`), it is never clamped to fit.
The **capacity model is also operator-frozen**. `mode = "adv_impact"` requires a
positive `portfolio_notional`, causal prior ADV settings, max bar/ADV
participation limits, and impact parameters. Supported `bars` and
`crypto_perp_funding` rows must carry positive `volume`; impact is charged in the
same NAV cash path and the book is never resized or split to fit a capacity limit.
`mode = "off"` is explicit and allowed for profiling or flat/no-trade books, but a
traded book fails closed with `capacity_unpriced`. `forex_with_quotes` ADV impact
fails with `capacity_unsupported_volume_semantics` until FX notional liquidity is
calibrated.
Use `causality_check = "micro"` for Train/autoresearch iteration. Micro replay is
fast diagnostic evidence: detected causality violations fail closed, while timeout
or incomplete probe evidence can still score but is not complete retention proof.
Require `result.retainable` before advancing quick-run evidence to validation or
evaluation.
`result.foundation.sizing_report` records the frozen `book_scale`; use that value
in validation/evaluation `[risk_budget].mode = "fixed_scale"` configs.
Research candidates live as candidate-local bundles:
`candidates/<candidate_id>/strategy.py` plus `run.toml` and optional
`validation.toml` / `evaluation.toml`. In quick-run configs, `strategy_path`
resolves relative to the TOML file, so candidate configs should normally use
`strategy_path = "strategy.py"`. Generated artifacts still go under ignored
`results/`, not inside candidate folders.

For Train iteration, `[data].start` / `[data].end` are the strategy-visible
decision and scoring window. If exits need later bars, add `[data].load_end`
as execution-only coverage. The strategy and causality replay still cannot see
those buffer rows; the engine can use them only to resolve fills and exits.

**`artifact_profile`** controls how much is written. `full` is the only profile
that is replayable from artifacts (it writes the strategy input rows, decision
records, engine request, and evidence). `summary` and `diagnostic` are compact;
`diagnostic` adds `diagnostics.json` with economic slices and the
portfolio-foundation matrix. Completed runs always write `summary.json` (with
`economic_metrics` and compact `portfolio_foundation` when the foundation is
available), `run_manifest.json`, `notes.md`, `config.toml`,
`strategy_snapshot.py`, and `environment.json`.

Programmatic consumers can read the quick-run per-trade ledger from
`result.economics` on completed engine runs. This ledger is a **derived attribution
view** of the one portfolio book walk — each record is a completed netted-book
round-trip whose `net_return = gross_return + funding_return − cost_return`
reconciles with the NAV path. It is first-class for *alpha* attribution and
information-coefficient analysis, but it is **not** an independent scored number;
the NAV path is the scored object. The object carries the same summary
scalars/slices written to artifacts, even under `artifact_profile = "summary"`; no
`summary.json` scraping is required.
Completed, feasible quick runs expose the **authoritative scored portfolio book**
on `result.foundation`. Its NAV path is the single object Train scoring statistics
derive from; use it for full-Train and subwindow return statistics (computed over
**at-risk bars**, with a minimum-sample gate), PSR inputs, drawdown, closed
round-trip counts, concentration, gross/net utilization, total return, and
cost-stressed foundation metrics. It remains quick-run diagnostic evidence, not
promotion authority, and default artifacts write compact metrics rather than full
per-period traces.

### Quick-run portfolio foundation output

`portfolio_foundation` is the **authoritative scored NAV book** — the single object
Train scoring derives from, not a side-channel over a trade bag. The book is
mandatory, so it is populated on every completed, **feasible** engine evaluation;
an envelope breach makes the run non-scoreable (see the feasibility verdict
below), so a populated foundation already means the book passed the envelope.

Where to read it:

| Surface | Contains | Use for |
|---|---|---|
| `result.foundation.summary_payload()` | compact scenario summaries; same shape as `summary.json["portfolio_foundation"]` | hot-path scoring inputs that do not need every subwindow row |
| `result.foundation.matrix_payload()` | compact scenario summaries plus `subwindows`; same shape as `diagnostics.json["portfolio_foundation"]` | diagnosis of weak Train slices |
| `summary.json["portfolio_foundation"]` | compact persisted summary when foundation succeeds | artifact-only consumers |
| `diagnostics.json["portfolio_foundation"]` | compact matrix under diagnostic profile | artifact-only consumers that need subwindow records |

Every scenario has this shape:

```text
scenario_id                 # "realistic_costs" or "cost_stress"
cost_multiplier             # 1.0 or foundation_cost_stress_multiplier
feasibility                 # typed verdict payload (feasible, reason, observed_gross/net, detail)
full_train                  # one compact metric record for the full Train path
capacity                    # turnover, impact cost, bar participation, ADV participation
subwindow_count             # configured foundation_subwindows
min_closed_trade_count
max_symbol_concentration
warning_counts
subwindows                  # matrix payload only; one compact metric per Train slice
```

Each metric record (`full_train` and each subwindow) contains:

```text
window_id
start_time / end_time
total_return
max_drawdown
closed_trade_count          # netted-book round trips (a net position returning to flat)
max_symbol_concentration
max_gross_utilization       # live mark-to-market gross/net utilization series
mean_gross_utilization      #   (a winner drifting above the ceiling is a risk
max_net_utilization         #    signal, reported — not an infeasibility; only the
mean_net_utilization        #    intended target gross fails closed)
return_sample_count         # at-risk (capital-deployed) period returns, not zero-padded
mean_return
return_volatility
effective_sample_size
sharpe
sharpe_standard_error
skew
kurtosis
warnings
```

Important semantics for agents:

- `realistic_costs` is the base execution-cost scenario; `cost_stress` recomputes
  the same foundation under `foundation_cost_stress_multiplier`.
- The **leverage budget is the frozen envelope, not a tunable.** The *intended
  target gross/net* at a decision is the hard, fail-closed check; exceeding it
  makes the run non-scoreable (`feasibility.reason = "leverage_budget_breach"` with
  the observed exposure). The book is never clamped to fit. The `*_utilization`
  fields are the separate *live* mark-to-market exposure series — reported as a risk
  signal, not enforced intrabar.
- The **capacity model is part of the same frozen envelope.** ADV impact charges
  cash on each executed net delta; `capacity` reports execution-event count,
  normalized/real turnover, impact cost, and max/mean bar and ADV participation.
  Capacity-disabled traded books, unsupported FX ADV impact, missing/insufficient
  volume history, and participation-limit breaches are fail-closed feasibility
  reasons, not warnings.
- `full_train` exists so downstream can calculate full-window evidence exactly;
  do not reconstruct full-window Sharpe, PSR, or total return from subwindow
  summaries.
- `mean_return`, `return_volatility`, `sharpe`, `sharpe_standard_error`, `skew`,
  and `kurtosis` are computed from the NAV path's fixed-frequency period returns
  over **at-risk bars** (flat bars do not inflate the sample), not completed-trade
  returns. A subwindow below the minimum at-risk sample is reported non-scoreable
  with a typed warning rather than a finite Sharpe from sample count alone.
- Subwindow `total_return` compounds the same endpoint-assigned return intervals
  used for that subwindow's return statistics.
- PSR and the final Train score are downstream policy. A downstream scorer can
  compute `PSR = NormalCDF((sharpe - SR_h) / sharpe_standard_error)` from
  foundation fields, then choose its own score/gates. `quant_strategies` does not
  emit or optimize that score; significance stays with the consumer.
- Compact artifacts do **not** include full NAV traces, `portfolio_value` arrays,
  `period_return` arrays, or per-period positions. Use evaluation for
  survivor-grade NAV/path traces.

Minimal in-process read:

```python
from statistics import NormalDist

from quant_strategies.runner import run_config

result = run_config("candidates/my_candidate/run.toml")
if not result.succeeded:
    # an infeasible book sets result.feasibility (reason + observed exposure);
    # a feasible completed run always populates result.foundation.
    raise SystemExit(f"{result.message} :: {result.feasibility}")

scenario = result.foundation.summary_payload()["scenarios"]["realistic_costs"]
matrix = result.foundation.matrix_payload()["scenarios"]["realistic_costs"]

sr_h = 0.0  # downstream protocol-owned hurdle

def psr(record: dict[str, object]) -> float | None:
    sharpe = record["sharpe"]
    sharpe_se = record["sharpe_standard_error"]
    if sharpe is None or sharpe_se is None:
        return None
    return NormalDist().cdf((float(sharpe) - sr_h) / float(sharpe_se))

full_psr = psr(scenario["full_train"])
subwindow_psrs = [psr(item) for item in matrix["subwindows"]]
if full_psr is None or any(item is None for item in subwindow_psrs):
    score = None
else:
    score = min(full_psr, min(item for item in subwindow_psrs if item is not None))
```

The micro causality policy is the Train/autoresearch replay annotation. It runs a
tiny bounded replay sample and records probe and timeout evidence. A detected
causality violation fails closed at `failure_stage="causality"`. Timeout or
incomplete probe evidence may still complete when request building and engine
evaluation succeed, but causality is marked unverified; `RunResult.retainable` is
false until retention-admissible causality evidence and envelope provenance are
present.
Survivor and audit evidence belongs in validation/evaluation. Low-level replay
settings and focused source-hash replay are advanced controls documented in the
reference; the strategy-writing LLM should not choose them during research
iteration.

**Reading it:** completion is `result.succeeded`. For quick-run evidence that may
advance to validation/evaluation, also require `result.retainable`. On failure, `result.outcome
.failure_stage` names the stage that failed and `summary.json` sets
`run_completed=false`. `assessment_status` stays diagnostic — it never authorizes
anything.

---

## Surface 2 — Validation

**Purpose:** audit retained-candidate evidence integrity across windows and a fixed
stress matrix; emit an **advisory** validation decision. Requires `validate_params`.
Runs strict row-contract, observation, and hidden-lookahead checks, and runs the
candidate through the same single causal netted portfolio book — an intended-gross
or unfinanced-leverage breach surfaces as the fail-closed feasibility verdict, not a
translation layer that rejects flat or leveraged targets.

```bash
conda run -n quant quant-strategies validate candidates/<candidate_id>/validation.toml
```

```python
from quant_strategies.validation import run_validation

result = run_validation("candidates/<candidate_id>/validation.toml")
if not result.succeeded:                     # run integrity, not the verdict
    raise SystemExit(result.message)

print(result.decision.decision)              # advisory label; may be "mechanical_fail"
print(result.result_dir)
```

**Config** (`validation.toml`): top-level `strategy_path`, `strategy_id`, optional
`verdict_source` (`"engine"` only); one or more `[[windows]]` (each with a unique
`id` + `start`/`end`); `[data]`, `[params]`, `[fill_model]`, `[cost_model]`,
`[capacity_model]`, `[leverage_budget]`, `[risk_budget]`;
`[readiness]` (`min_observations_per_decision`, `required_observation_fields`);
`[output]`; `[search_pressure]` (`prior_search`); optional `[mechanical_thresholds]`.

For `crypto_perp_funding`, `[readiness]` additionally requires `close`,
`funding_timestamp`, `funding_rate`, and `has_funding_event` observations on every
decision. Window `id`s must be unique and must not collide after artifact-path
sanitization.

**Reading it:** `result.succeeded` means the run completed with no failure stage.
The advisory `result.decision.decision` (including `mechanical_fail`) is *evidence*
— it never authorizes promotion, paper trading, or live trading. The single verdict
backend is the netted portfolio book spine (`verdict_source = "engine"`).

---

## Surface 3 — Evaluation

**Purpose:** evaluate a frozen candidate through a stateless portfolio evidence
surface — portfolio, economic, and path metrics under explicit cost/fill
assumptions. Requires `validate_params`. Runs strict row-contract, a decision-row
data audit, and a complete causal-replay preflight *before* any scenario expands.

```bash
conda run -n quant quant-strategies evaluate candidates/<candidate_id>/evaluation.toml
# --events-jsonl streams structured evaluation_stage events to stderr
```

```python
from quant_strategies.evaluation import run_evaluation

result = run_evaluation("candidates/<candidate_id>/evaluation.toml")  # event_sink= optional
if not result.succeeded:
    raise SystemExit(f"{result.failure_stage}: {result.message}")

print(result.result_dir)
print(result.assessment_status)
print(result.evidence_quality_warnings)
```

**Config** (`evaluation.toml`): top-level `strategy_path`, `strategy_id`;
`[[windows]]`; `[data]`, `[params]`, `[fill_model]`, `[cost_model]`,
`[capacity_model]`, `[leverage_budget]`, `[risk_budget]`; `[metrics]`
with `annualization_periods_per_year` (must match bar cadence) and optional
`min_annualized_samples` (default `20`); optional `[readiness]`, optional
`[benchmark]` (`symbol`, which must also appear in `data.symbols`), and optional
`[[scenarios]]` (each with `id`, labels, `required`, and nested
`[scenarios.cost_model]` / `[scenarios.fill_model]` overrides); `[output]`. See
[`examples/simple_momentum/evaluation.toml`](../../examples/simple_momentum/evaluation.toml).

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

**Accounting and funding.** Evaluation runs the **same single causal netted
portfolio book** as quick run and validation (`netted_portfolio_book_v1`); it adds
only Parquet trace serialization around that pure book. There is one funding home:
for `crypto_perp_funding` the book's NAV path includes price PnL, configured
fees/slippage, and funding cashflows. Fillable perp windows with no funding events
in the open interval accrue zero funding; malformed/conflicting/mark-misaligned
funding rows still fail. The metric payload reports the single shared accounting
model.

Evaluation writes Parquet-only traces (`tables/portfolio_path.parquet`, `trades`,
`target_positions`, `target_exposure_summary`, `execution_events`,
`funding_cashflows`) and requires `pyarrow`. `execution_events` is the detailed
capacity/impact trace: one row per executed net delta with normalized/real notional,
base cost, impact cost, total cost, bar/ADV notional volume, and bar/ADV
participation. There is no JSONL fallback for row snapshots or traces.

**Per-fold OOS returns in-process (no Parquet scraping).** A completed
`EvaluationRunResult` also carries the per-`(window, scenario)` out-of-sample
return series typed and in-process, so a consumer never has to read
`tables/portfolio_path.parquet`. Orchestrate one window (one fold) per `evaluate`
call and read the series for the scenario your protocol selects:

```python
result = run_evaluation("candidates/<candidate_id>/evaluation.toml")
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
`period_return` rows in the Parquet trace. `series.per_symbol` is `None` because the
single shared book is one cash-shared account (no independent per-symbol NAV path is
computed). No significance statistics (PSR/DSR/PBO) are provided — significance is
the consumer's job.

---

## Reading results programmatically

All three result types expose `result.succeeded` — use it as the completion check.
It means the run completed and `failure_stage is None`. Quick-run evidence also
exposes `result.retainable`; require it before advancing quick-run evidence to
validation/evaluation.

| Result | Success | Verdict / status field | On failure |
|---|---|---|---|
| `RunResult` | `result.succeeded`; for retained evidence also `result.retainable` | `outcome.assessment_status` (diagnostic), `retainability.reason` | `outcome.failure_stage`; `evidence.warnings`; `retainability` |
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

For quick-run search loops, score on `RunResult.foundation` — the authoritative
NAV book — and check `RunResult.feasibility` to interpret a non-scoreable run.
Use `RunResult.retainable` as the boundary for advancing a quick-run result to
retained-candidate validation/evaluation.
`RunResult.economics.trades` is the derived per-trade attribution view of that same
book (for alpha / IC slicing by time or symbol), not an independent scored number.
Use `run_evaluation` for OOS portfolio/NAV evidence and survivor-grade trace
artifacts.

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
- **Do not put accounting or final sizing in signal logic.** Fills, costs,
  netting, financing, leverage, and risk-budget sizing belong to the foundation;
  declare the intended target-book shape.
- **Do not emit a fresh target to add exposure.** Targets net to the latest value,
  not a stack — express your total intended weight, not an increment.
- **Do not read future rows to place a stop.** Use a declared `RiskRule`; a
  data/time exit is an explicit `target=0` decision.
- **Do not expect an over-budget fixed-scale book to be scaled down.** Final
  executable gross/net over the frozen leverage budget is non-scoreable
  (fail-closed), never clamped to fit.
- **Do not treat a metric or artifact as proof.** They are evidence; nothing here
  proves out-of-sample validity or trading readiness.
- **Do not read `mechanical_fail` as a crash**, or `result.succeeded` as a positive
  verdict. They answer different questions.
- **Do not sort, de-duplicate, join, or repair rows** to make a run pass. A bad row
  shape is upstream feedback for `quant_data`, not a local shim.
- **Do not commit `results/` artifacts as source** — they are regenerable.
