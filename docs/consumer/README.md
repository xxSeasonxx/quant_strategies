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

---

## For AI agents (read this first)

If you are an LLM writing or running strategy code against this package, follow
these rules. They are the difference between evidence and noise.

1. **A strategy is a pure function.** You write one file that exposes
   `generate_decisions(rows, params) -> list[StrategyDecision]`. Inspect only the
   `rows` and `params` you are handed. Do **not** load data, call engines, write
   files, open the network, read clocks, use RNG, or run background loops. Purity
   is checked by a best-effort static lint (`decisions/purity.py`) — treat the
   contract as the real guarantee, not the lint.
2. **You do not load data.** The run surfaces load rows through `quant_data`'s
   strict contract loaders, normalize them, and pass them to you as plain mapping
   rows. Choosing which loader runs is a config decision (`[data].kind`), not
   something you call. See [usage-guide.md](usage-guide.md#choose-your-data-kind).
3. **Respect causal time.** Gate every signal on each row's **`available_at`**,
   never its `timestamp`. Causal replay enforces `available_at <= decision_time`
   on valid rows, and every `StrategyDecision` requires `as_of_time <= decision_time`.
   A missing or invalid `available_at` fails the row contract — it is never a
   tolerated warning.
4. **`validate_params` is required for validation and evaluation**, optional for
   quick runs. Make invalid params raise.
5. **Use `result.succeeded` as the success check** on all three surfaces.
   Validation's advisory `decision` label — including `mechanical_fail` — is
   evidence, not promotion logic.
6. **Artifacts are evidence, not truth.** Do not treat a generated `summary.json`
   or metric as a proven result. Nothing in this repo proves out-of-sample
   validity, freedom from in-sample fitting, or trading readiness.
7. **Cite real provenance.** Every strategy docstring must name a specific source
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

Write one pure strategy file and a small config, then run it. A complete working
example ships in the repo: [`examples/simple_momentum/strategy.py`](../../examples/simple_momentum/strategy.py)
and [`examples/simple_momentum/run.toml`](../../examples/simple_momentum/run.toml).

```python
# my_strategy.py — a pure strategy file
"""Strategy: my_strategy

Source / provenance: internal_note docs/notes/my_strategy.md citing <paper/url>.
Market rationale: <why an edge could exist>.
Required observables: symbol, timestamp, close.
Decision rule: go long for one bar after an up close.
Assumptions: fills occur after the decision bar (entry_lag_bars=1).
Falsifier: if the rule has no positive gross edge, reject before tuning.
"""
from __future__ import annotations
from collections.abc import Mapping, Sequence
from quant_strategies.decisions import (
    ExitPolicy, InstrumentRef, ObservationRef, PositionTarget, StrategyDecision,
)

def validate_params(params: Mapping[str, object]) -> dict[str, object]:
    weight = float(params.get("weight", 1.0))
    if weight <= 0.0:
        raise ValueError("weight must be positive")
    return {"weight": weight}

def generate_decisions(
    rows: Sequence[Mapping[str, object]], params: Mapping[str, object],
) -> list[StrategyDecision]:
    weight = float(validate_params(params)["weight"])
    out: list[StrategyDecision] = []
    for i in range(1, len(rows)):
        if float(rows[i]["close"]) > float(rows[i - 1]["close"]):
            ts, symbol = rows[i]["timestamp"], str(rows[i]["symbol"])
            out.append(StrategyDecision(
                strategy_id="my_strategy",
                instrument=InstrumentRef(kind="equity_or_etf", symbol=symbol),
                decision_time=ts, as_of_time=ts,
                target=PositionTarget(direction="long", size=weight),
                exit_policy=ExitPolicy(max_hold_bars=1),
                observations=(ObservationRef(symbol=symbol, timestamp=ts, field="close"),),
            ))
            break
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
weight = 1.0

[fill_model]
price = "close"
entry_lag_bars = 1
exit_lag_bars  = 0

[cost_model]
fee_bps_per_side = 0.0
slippage_bps_per_side = 0.0

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
assert result.succeeded, result.message
print(result.result_dir)        # where artifacts landed
print(result.outcome.assessment_status)
```

> **No data lives in this repo.** Rows are loaded on demand through `quant_data`
> using a strict contract loader chosen by `[data].kind`. If a window is outside
> the published readiness contract, the loader raises and the run fails at the
> data stage — `quant_strategies` never fabricates, forward-fills, or repairs
> rows. For what data exists and which windows are safe, read the **quant-data
> consumer guide** (`quant-data/docs/consumer/`).

**Then go where your question points:**

- *How do I write a strategy and run all three surfaces?* → [usage-guide.md](usage-guide.md)
- *How do I read quick-run `portfolio_foundation` output for Train scoring?* →
  [usage-guide.md#quick-run-portfolio-foundation-output](usage-guide.md#quick-run-portfolio-foundation-output)
  and [reference.md#runportfoliofoundation](reference.md#runportfoliofoundation)
- *What is the exact signature / field / config key / exit code?* → [reference.md](reference.md)
- *What data exists and is my window safe?* → quant-data consumer guide (upstream)

---

## Contract & ownership

`quant_strategies` sits between a strategy author and an upstream data product. The
boundaries are deliberate.

**The strategy author owns** the pure `generate_decisions` / `validate_params`
file: the thesis, the rule, the params contract, the declared `observations`, and
a specific provenance docstring. The strategy must not load data or cause side
effects.

**`quant_strategies` owns** loading rows through public `quant_data` APIs,
row-contract validation, the execution kernel (freeze inputs → typed decisions →
strict causal replay), fills, costs, the per-trade PnL contract, validation
policy, evaluation portfolio/NAV/path evidence, and all artifacts. It **preserves**
the upstream row order and never sorts, de-duplicates, joins, or repairs rows
locally.

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

Deeper internal contracts (for maintainers, not consumers) live in
[`docs/foundation-surfaces.md`](../foundation-surfaces.md), [`FOUNDATION_LOCK.md`](../../FOUNDATION_LOCK.md),
[`PRD.md`](../../PRD.md), and the agent contract [`AGENTS.md`](../../AGENTS.md).
