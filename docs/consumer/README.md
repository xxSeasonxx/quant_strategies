# Consumer Guide

**The front door for anyone — human or AI agent — running a strategy through
`quant_strategies`.** If you are writing a strategy, running a quick diagnostic,
validating a candidate, or wiring this repo into `quant_autoresearch`, start here.

> You should never need to read the engine, runner, or evaluation source to use
> this. If you do, that is a documentation bug — please tell Season.

`quant_strategies` takes a strategy idea from *pure function* to *trustworthy
evidence*. It is **not** a trading system: nothing here authorizes paper trading,
live trading, ranking, or promotion. Its one job is to make sure no number with
unclear semantics ever drives a conclusion.

The unit of simulation is **one causal, single-account portfolio, not an isolated
trade.** Your strategy declares a *complete portfolio* — a **target book** of base
shape targets — and the foundation normalizes that shape, applies `[risk_budget]`,
folds the final executable weights into one netted, financed, marked book, and
scores that **NAV path**. The contract is two-sided: you can express any complete,
tradeable portfolio in `strategy.py`, and a strategy that passes Train evidence is
genuinely feasible to trade — an envelope breach (over the frozen risk budget or
leverage budget, zero-cost, zero-slippage, unfinanced leverage, degenerate sample)
is a typed **fail-closed** verdict that makes the run non-scoreable, never a clamp
and never a silent `None`.

---

## For AI agents (read this first)

If you are an LLM writing or running strategy code against this package, follow
these rules. They are the difference between evidence and noise.

1. **A strategy is a pure function declaring a target book.** You write one file
   that exposes `generate_decisions(rows, params) -> Sequence[TargetDecision]`. Each
   `TargetDecision` is a **standing, signed base target shape** for one
   instrument (`+` long, `-` short, `0` = flat/close) that holds until your next
   decision for that symbol changes it. Targets are **idempotent** — re-emitting the
   current target trades nothing — so same-symbol exposure nets and repeated signals
   cannot stack into hidden leverage. The foundation converts shape to final
   executable weights with `[risk_budget]`. Inspect only the `rows` and `params` you
   are handed. Do **not** load data, call engines, write files, open the network,
   read clocks, use RNG, or run background loops. Purity is checked by a best-effort
   static lint (`decisions/purity.py`) — treat the contract as the real guarantee,
   not the lint.
2. **You do not load data.** The run surfaces load rows through `quant_data`'s
   strict contract loaders, normalize them, and pass them to you as plain mapping
   rows. Choosing which loader runs is a config decision (`[data].kind`), not
   something you call. See [usage-guide.md](usage-guide.md#choose-your-data-kind).
3. **Respect causal time.** Gate every signal on each row's **`available_at`**,
   never its `timestamp`. Causal replay enforces `available_at <= decision_time`
   on valid rows, and every `TargetDecision` requires `as_of_time <= decision_time`.
   A missing or invalid `available_at` fails the row contract — it is never a
   tolerated warning.
4. **`validate_params` is required for validation and evaluation**, optional for
   quick runs. Make invalid params raise.
5. **Use `result.succeeded` as the completion check** on all three surfaces. For a
   quick run, `succeeded` means **feasible and completed**: the portfolio book
   was built and passed the feasibility envelope. A breach of that envelope is a
   typed, fail-closed verdict on `RunResult.feasibility` (reason + observed
   exposure) that sets `succeeded = False` — read the verdict reason
   (`leverage_budget_breach`, `zero_cost`, `zero_slippage`, `unfinanced_leverage`,
   `unpriced_short_financing`, `insufficient_samples`) to learn what to fix; it is
   not a clamp and not a silent absence of evidence. For quick-run evidence that
   may advance to validation/evaluation, also require `result.retainable`.
   Validation's advisory `decision` label — including `mechanical_fail` — is
   evidence, not promotion logic.
6. **Build within the frozen envelope.** Costs, fills, risk budget, the leverage
   ceiling (gross and net), asset universe, and window are operator-frozen — your
   strategy cannot relax them. Train quick runs may calibrate volatility; retained
   validation and evaluation consume the recorded fixed `book_scale`. Final
   executable gross/net over the budget is non-scoreable, not silently scaled down;
   a scoreable run with zero costs is non-scoreable.
7. **Artifacts are evidence, not truth.** Do not treat a generated `summary.json`
   or metric as a proven result. Nothing in this repo proves out-of-sample
   validity, freedom from in-sample fitting, or trading readiness.
8. **Cite real provenance.** Every strategy docstring must name a specific source
   (paper + DOI/SSRN/URL, a web/repository URL, or an internal note path plus the
   upstream source it cites). "Literature" or "outside-view note" is not enough.

---

## 30-second orientation

`quant_strategies` exposes **three public surfaces**. Pick by what you are doing —
they share one strategy contract and one execution kernel, but produce different
evidence.

| Surface | CLI | Python | Use it for | Success check |
|---|---|---|---|---|
| **Quick run** | `quant-strategies run` | `runner.run_config` | Fast causal diagnostics for one strategy version while iterating | `result.succeeded` |
| **Validation** | `quant-strategies validate` | `validation.run_validation` | Retained-candidate evidence integrity across windows + stress scenarios; advisory decision | `result.succeeded` |
| **Evaluation** | `quant-strategies evaluate` | `evaluation.run_evaluation` | Stateless frozen-candidate portfolio / NAV / path evidence | `result.succeeded` |

`quant_strategies.engine` is an **internal** execution kernel used by quick-run
and validation internals/tests. It is not a fourth public API — do not import it
in consumer code.

## Golden path (copy-paste)

Write one pure strategy file declaring a **target book** and a small config, then
run it. The strategy below sets a signed base target shape per instrument and
closes by setting the target back to `0`; `examples/simple_momentum/strategy.py`
and the `candidates/` strategy files follow the same shape.

```python
# my_strategy.py — a pure strategy file
"""Strategy: my_strategy

Source / provenance: internal_note docs/notes/my_strategy.md citing <paper/url>.
Market rationale: <why an edge could exist>.
Required observables: symbol, timestamp, close.
Decision rule: hold a long base shape target while the close rises; flatten otherwise.
Assumptions: fills occur after the decision bar (entry_lag_bars=1).
Falsifier: if the rule has no positive gross edge, reject before tuning.
"""
from __future__ import annotations
from collections.abc import Mapping, Sequence
from quant_strategies.decisions import (
    InstrumentRef, ObservationRef, RiskRule, TargetDecision,
)

def validate_params(params: Mapping[str, object]) -> dict[str, object]:
    weight = float(params.get("weight", 0.25))
    if not 0.0 < weight <= 1.0:
        raise ValueError("weight must be in (0, 1]")
    return {"weight": weight}

def generate_decisions(
    rows: Sequence[Mapping[str, object]], params: Mapping[str, object],
) -> list[TargetDecision]:
    weight = float(validate_params(params)["weight"])
    out: list[TargetDecision] = []
    current: float | None = None
    for i in range(1, len(rows)):
        ts, symbol = rows[i]["timestamp"], str(rows[i]["symbol"])
        up = float(rows[i]["close"]) > float(rows[i - 1]["close"])
        target = weight if up else 0.0
        if target == current:        # idempotent: re-emitting the standing target is a no-op
            continue
        current = target
        out.append(TargetDecision(
            strategy_id="my_strategy",
            instrument=InstrumentRef(kind="equity_or_etf", symbol=symbol),
            decision_time=ts, as_of_time=ts,
            target=target,            # signed base shape; 0 = flat/close
            risk_rule=RiskRule(stop_loss=0.05) if target else None,  # optional engine-enforced stop
            observations=(ObservationRef(symbol=symbol, timestamp=ts, field="close"),),
        ))
    return out
```

```toml
# experiment.toml — a quick-run config
strategy_path = "my_strategy.py"
strategy_id   = "my_strategy"

[data]
kind = "bars"
dataset = "equity_1min"
symbols = ["SPY"]
start = "2024-01-01"
end   = "2024-01-31"

[params]
weight = 0.25

[fill_model]
price = "close"
entry_lag_bars = 1

[cost_model]                          # a scoreable run needs positive fee + slippage;
fee_bps_per_side = 1.0                # zero cost or zero slippage is a fail-closed verdict
slippage_bps_per_side = 0.5

[capacity_model]
mode = "adv_impact"
portfolio_notional = 1000000.0
adv_lookback_bars = 390
adv_min_observations = 1
max_bar_participation = 0.50
max_adv_participation = 0.25
impact_coefficient_bps = 10.0
impact_exponent = 0.5

[leverage_budget]
max_gross_exposure = 1.0
max_net_exposure = 1.0

[risk_budget]
mode = "calibrate_vol"
annualization_periods_per_year = 98280
target_volatility = 0.10

[envelope]
operator_frozen = true

[output]
results_dir = "results"
artifact_profile = "diagnostic"
```

```bash
# Run it (data must be available upstream via quant_data; see note below)
conda run -n quant quant-strategies run experiment.toml
```

```python
from quant_strategies.runner import run_config

result = run_config("experiment.toml")
if not result.succeeded:
    # an infeasible book sets result.feasibility (reason + observed exposure)
    raise SystemExit(f"{result.message} :: {result.feasibility}")
if not result.retainable:
    raise SystemExit(f"quick-run evidence is diagnostic only :: {result.retainability}")
print(result.result_dir)        # where artifacts landed
print(result.outcome.assessment_status)
print(result.foundation.feasible)   # authoritative scored NAV book; True on a feasible run
```

> **No data lives in this repo.** Rows are loaded on demand through `quant_data`
> using a strict contract loader chosen by `[data].kind`. If a window is outside
> the published readiness contract, the loader raises and the run fails at the
> data stage — `quant_strategies` never fabricates, forward-fills, or repairs
> rows. For what data exists and which windows are safe, read the **quant-data
> consumer guide** (`quant-data/docs/consumer/`).

**Then go where your question points:**

- *How do I write a strategy and run all three surfaces?* → [usage-guide.md](usage-guide.md)
- *How do I read the quick-run `portfolio_foundation` NAV book for Train scoring?* →
  [usage-guide.md#quick-run-portfolio-foundation-output](usage-guide.md#quick-run-portfolio-foundation-output)
  and [reference.md#runportfoliofoundation](reference.md#runportfoliofoundation)
- *What is the exact signature / field / config key / exit code?* → [reference.md](reference.md)
- *What data exists and is my window safe?* → quant-data consumer guide (upstream)

---

## Contract & ownership

`quant_strategies` sits between a strategy author and an upstream data product. The
boundaries are deliberate.

**The strategy author owns** the pure `generate_decisions` / `validate_params`
file: the thesis, the rule, the params contract, the declared `observations`, a
specific provenance docstring, and the **complete portfolio** the target book
expresses — allocation, sizing, netting intent, rebalancing, explicit exits, and
declared `RiskRule`s. The strategy must not load data or cause side effects, and
cannot relax the frozen envelope (costs, fills, leverage budget, universe, window).

**`quant_strategies` owns** loading rows through public `quant_data` APIs,
row-contract validation, the execution kernel (freeze inputs → typed decisions →
strict causal replay), the **single causal netted portfolio book** (same-symbol
netting, financing/funding, mark-to-market) whose NAV path is the authoritative
scored object, the fail-closed feasibility envelope, the derived per-trade
attribution ledger, validation policy, evaluation portfolio/NAV/path evidence, and
all artifacts. It **preserves** the upstream row order and never sorts,
de-duplicates, joins, or repairs rows locally.

**`quant_data` owns** the data product: acquisition, refresh, repair, backfill,
source joining, adjustment/survivorship policy, deterministic row ordering, and
the causal `available_at` stamp. The supported contract range is pinned as
`quant-data>=0.1.0,<0.2.0`; the consumer-side data-boundary contract is locked in
[`FOUNDATION_LOCK.md`](../../FOUNDATION_LOCK.md) and `openspec/specs/data-boundary/spec.md`.

**Out of scope (by design):** choosing which ideas to research, mutating variants,
ranking candidates, search memory, stopping rules, promotion, and paper/live
trading. Those live in `quant_autoresearch` and human review — never here.

---

## The documents

| Doc | What it answers | Audience |
|---|---|---|
| **[README.md](README.md)** (this) | *Where do I start? What are the rules and boundaries?* | everyone, first |
| **[usage-guide.md](usage-guide.md)** | *How do I write a strategy and run quick-run / validation / evaluation?* | strategy authors, agents |
| **[reference.md](reference.md)** | *What is the exact API, decision schema, config key, result field, exit code?* | lookups |
| **[integration.md](integration.md)** | *What contract must I emit/consume, and what must `quant_autoresearch` reflect?* | consumers wiring a loop into this repo |

Deeper internal contracts (for maintainers, not consumers) live in
[`docs/foundation-surfaces.md`](../foundation-surfaces.md), [`FOUNDATION_LOCK.md`](../../FOUNDATION_LOCK.md),
[`PRD.md`](../../PRD.md), and the agent contract [`AGENTS.md`](../../AGENTS.md).
