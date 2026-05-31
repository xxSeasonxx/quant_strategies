# quant_strategies

A disciplined research harness for **pure strategy functions**, deterministic
**quick runs**, and **advisory validation**.

It is *not* a trading system and does not imply paper or live readiness. Its one
job is to take a strategy idea from "pure function" to "auditable advisory
evidence" without ever letting a number you can't reproduce drive a conclusion.

## Architecture

```mermaid
flowchart TD
    cfg["experiment.toml / validation.toml"] --> strat
    strat["pure strategy.py<br/>generate_decisions(rows, params) → [StrategyDecision]"] --> spec
    spec["StrategyExecutionSpec<br/>(neutral; runner and validation both adapt into it)"] --> kernel
    kernel["one execution kernel<br/>load rows via quant_data · freeze · strict causal replay"] --> pnl
    pnl["one PnL contract — engine.screen()<br/>per-trade ledger · funding-aware net"]
    pnl --> quick["quant-strategies run<br/>quick run · diagnostic evidence · rank and iterate"]
    pnl --> valid["quant-strategies validate<br/>windows × scenarios → advisory verdict + audit ledgers"]
    valid -. "opt-in single-trade check" .-> oracle["VectorBT Pro<br/>single-trade check"]
    valid --> human["human promotion review<br/>(outside the code)"]
```

The design has one spine:

- **One strategy contract.** A strategy is a pure `generate_decisions(rows, params)`.
- **One neutral execution spec.** Runner and validation both adapt their config
  into the same `StrategyExecutionSpec`; neither owns the other's execution path.
- **One execution kernel.** Import → validate params → load rows (via `quant_data`)
  → freeze inputs → typed decisions → strict causal replay.
- **One PnL contract.** The engine's `screen()` is the single source of trade-level
  PnL, so **the number a human audits is the number the verdict is computed from.**
- **Two steps on top.** A fast *quick run* for ranking, and an *advisory validation
  run* for a verdict plus audit-replayable artifacts. VectorBT Pro is optional,
  single-trade only, and never produces verdict metrics.

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
  **required** for the validation run, so a paper-readiness verdict never rests on
  params that were never schema-checked.
- **Typed output.** The default output is `StrategyDecision` — a stable
  `decision_id`, instrument, `open` intent, decision/as-of times, target,
  `ExitPolicy`, and `ObservationRef` lineage for consumed rows.
- **Narrow default ontology.** Equities/ETFs, FX pairs, and crypto perps with
  `open` intent and `target_weight` sizing. Futures, options, multi-leg, book
  side, and other sizings live behind explicit imports from
  `quant_strategies.decisions.extended_ontology`.
- **Documented.** Each module docstring states thesis, observables, rule,
  assumptions, provenance, and falsifier.

## The two steps

**Quick run** — `quant-strategies run config.toml`

Loads rows, runs the pure strategy, validates the decision contract, replays for
hidden lookahead, and screens the decisions through the engine. Fast, deterministic
quick-run evidence for ranking and iteration. The default quick-run profile writes
bounded `diagnostics.json` behavior slices with
`replayable_from_artifacts = false`; use `artifact_profile = "full"` when audit
replay from emitted artifacts is required. See [docs/runner.md](docs/runner.md).

**Validation run** — `quant-strategies validate candidate/validation.toml`

Runs the same kernel across configured windows and stress scenarios, then classifies
the candidate into an advisory verdict (`hard_no` · `mechanical_pass` · `watchlist` ·
`mechanical_review_candidate`) with audit-replayable per-trade ledgers. Mechanical
only — never statistical significance, regime robustness, or promotion authority.
`promotion_eligible` / `paper_trade_eligible` / `live_eligible` always stay false.
See [docs/validation.md](docs/validation.md).

## Boundaries

- **`quant-data` owns data.** Materialization, refresh, backfill, repair, and
  source joining belong upstream. This repo uses public `quant_data` loader APIs
  only and does not discover upstream `.env` files.
- **The engine reports activity sums, not NAV.** Trade-result metrics live under
  `trade_result.sum_signed_trade_activity_*` and are linear per-trade sums, not
  portfolio/NAV-path returns. Validation gates the linear activity sum directly;
  it does not compound that metric as if it were a NAV path.
- **`researched/` is not market-validated.** It may hold frozen packages from
  upstream research; validation does not treat it as special.

## Usage

Use the `quant` conda environment for all Python commands:

```bash
conda run -n quant pytest
conda run -n quant quant-strategies run path/to/config.toml
conda run -n quant quant-strategies validate path/to/candidate/validation.toml
```

## Documentation

- **[docs/runner.md](docs/runner.md)** — quick-run reference: modes, evidence-quality
  fields, row contract, exit codes, replayability metadata, and artifacts.
- **[docs/validation.md](docs/validation.md)** — validation reference: config schema,
  paper-readiness gates, search pressure, the agreement oracle, the verdict ladder,
  metric semantics, and the replayable trade ledger.
- **[docs/quant-autoresearch-consumer.md](docs/quant-autoresearch-consumer.md)** —
  the stable Python consumer contract: `quant_strategies.runner.run_config` →
  `quant_strategies.runner.RunResult`, and
  `quant_strategies.validation.run_validation` → `ValidationRunResult`. No top-level
  facade is promised.

## Promotion discipline

Advisory validation artifacts support human review; they do not authorize paper
trading, live trading, or promotion. Moving a strategy to `tested/` requires the
separate validation process Season approves.
