## Why

The engine's atomic unit is the **trade**, not the **portfolio**. A strategy can
only emit independent `open` tickets with a baked-in auto-exit; the scored
number is a linear sum of weighted per-trade fractional returns
(`engine/evaluation.py:108-111`) that equals a portfolio NAV path **only for a
single trade** — the codebase concedes this by restricting its own cross-check
oracle to single-trade scenarios (`validation/agreement.py`). The only
exposure-aware surface, the portfolio NAV book, is **reconstructed afterward**
from the trade bag as an optional, **fail-open** side-channel, and it is
re-implemented **three times** (engine linear sum; `core/portfolio_foundation.py`
`_portfolio_path`; `evaluation/project_perp_ledger.py`), with funding coded three
times. Because no layer owns portfolio construction, signal-stacking, implicit
leverage, un-netted same-symbol exposure, and unfinanced leverage are all
expressible and rewarded by the climbed score.

This breaks the contract the downstream consumer depends on. `quant_autoresearch`
edits `strategy.py` freely to build a tradeable strategy and trusts that
"passes Train ⟹ genuinely tradeable" (`quant_autoresearch/program.md`). Today
the foundation cannot honor either side: it **blocks** the agent from expressing
a complete portfolio (no rebalance, no signal-driven close, no portfolio-level
risk — only auto-exit tickets), and it **rewards** untradeable books. The
engine must instead be a faithful simulation of one stateful portfolio so that
whatever the agent builds is measured as actually viable in live trading.

## What Changes

- **BREAKING** — Replace the open-ticket decision with a **target-book contract**.
  `generate_decisions(rows, params)` emits, per instrument and as of a causal
  time, a **signed weight-of-NAV target** (`0` = flat/close), **standing** until
  the next decision for that symbol changes it, optionally carrying a declared
  price-path **`RiskRule`** (stop-loss / take-profit / trailing). Targets are
  **idempotent** — re-emitting the current target is a no-op — so signal-stacking
  becomes structurally inexpressible. The strategy now owns the complete
  portfolio: allocation, sizing, netting intent, rebalancing, explicit exits, and
  declared risk.
- **BREAKING** — Collapse the three money-models into **one causal,
  single-account, stateful portfolio book**. A single bar-by-bar walk applies the
  decisions effective at each time, **nets same-symbol** to a running per-symbol
  quantity, trades only the **delta** against one shared cash/margin account
  through a market model (costs/funding/fills), and marks to market to produce one
  NAV path. The hand-rolled `project_perp_ledger` money-model is **removed**;
  funding lives in one place.
- **BREAKING** — The **NAV path is the single scored object.** The per-trade
  ledger becomes a **derived attribution / IC view** of the same walk — kept
  first-class for *alpha* research ("is the signal predictive?"), but no longer an
  independent scored "trade-unit."
- **BREAKING** — An envelope breach is a **typed, fail-closed feasibility
  verdict**, never a swallowed `foundation=None` and never clamped/normalized.
  Gross/net leverage over the operator ceiling, zero-cost, or a degenerate sample
  makes the run **infeasible / non-scoreable** with an actionable reason
  (e.g. `leverage_budget_breach` + observed gross). `RunResult.succeeded` is gated
  on the verdict, so over-leverage and zero-cost fiction can no longer be kept.
- Make the foundation's return statistics honest: compute them over
  **at-risk (capital-deployed) bars** rather than a zero-padded calendar, with a
  **minimum-sample gate** before a subwindow statistic is scoreable.
- Establish a **frozen-vs-free boundary**: the strategy owns the target book and
  declared risk (consumer-editable); the engine owns netting/accounting, the
  market model, and the operator-**frozen** envelope (leverage ceiling, cost
  floor, costs/fills, universe, window, objective — matching `protocol.toml`).
- Preserve strategy **purity** and the **dependency-light import wall** (the spine
  is pure-Python; no `pandas`/`numpy`/`vectorbtpro`/`evaluation` on the quick-run
  path). Realized-state-feedback policies (drift-triggered rebalance, realized-NAV
  vol targeting) are **out of scope for v1**.

Existing strategies in `candidates/` and `researched/` are **not** migrated; they
will be redeveloped against the new contract. No compatibility shim
(no-fallback principle).

## Capabilities

### New Capabilities

- `portfolio-decision-contract`: The strategy-facing contract that **all execution
  surfaces (quick-run, validation, evaluation) consume**. `generate_decisions`
  emits a standing, signed weight-of-NAV **target book** over causal time per
  instrument (`0` = flat), with an optional declared price-path `RiskRule`
  enforced by the engine on the net position. Idempotent targets; pure;
  expresses allocation, rebalancing, explicit/declared exits, side, and hedging.

### Modified Capabilities

- `quick-run-portfolio-foundation`: The portfolio book becomes the **single
  authoritative scored object** (NAV path), not an optional diagnostic. Adds
  intrinsic **same-symbol netting**, an operator-frozen **gross+net leverage
  budget that fails closed** via a typed feasibility verdict (replacing the
  fail-open `foundation=None`), **at-risk-bar return statistics** with a
  min-sample gate, and a per-scenario **market-model boundary** that future
  asset-class frictions extend.
- `quick-run-economics`: The per-trade ledger is redefined as a **derived
  attribution view** of the one book walk (first-class for alpha research), no
  longer the independent scored trade-unit; NAV is authoritative. The
  dependency-light import wall is preserved.

- `evaluation-fold-returns`: Evaluation executes the **same target-book contract**
  and the single shared accounting model. The open-ticket translation layer that
  rejects flat/leveraged targets, and the hand-rolled perp-ledger money-model — its
  public model-name in the metric payload and the validation gate that *requires*
  it — are removed. A second backend may remain only as an independent cross-check
  that must agree, never a divergent model routed by data kind. The typed
  fold-return series, causal-integrity flag, and `succeeded` formula are otherwise
  unchanged.

## Impact

- **Affected source (spine):**
  - `src/quant_strategies/decisions/models.py` — new `TargetDecision` / `RiskRule`;
    remove `DecisionAction="open"`-only, `SizingKind`, the welded `ExitPolicy`, and
    the unbounded `PositionTarget.size`.
  - `src/quant_strategies/engine/executable.py` + `engine_runner.py` — remove the
    open-ticket translation layer (`executable_decision`, `base_unsupported_semantics`,
    `assert_supported_decisions`) that rejects `flat`/`leveraged` targets and maps
    `direction → Side`; the book consumes the target contract directly.
  - `src/quant_strategies/engine/evaluation.py` — remove the per-trade linear-sum
    scorer **and** the isolated `_select_exit` exit engine; screening becomes a
    derived view over the book walk; `RiskRule` exits are enforced on the net book.
  - `src/quant_strategies/core/portfolio_foundation.py` — becomes the unified causal
    netted book; positions keyed per-**symbol** (running quantity), gross/net
    measured on live exposure, fail-closed verdict; remove the
    `FoundationSubwindowMetric` alias.
  - `src/quant_strategies/core/config.py` — remove `foundation_max_gross_exposure`
    from the agent-editable `[output]`/`OutputConfig`; add a protocol-frozen
    **gross and net** leverage budget.
  - `src/quant_strategies/runner/` — `RunResult` gains the typed feasibility verdict;
    `succeeded` gated on it (a breach sets a `failure_stage`); foundation
    authoritative, not optional; remove the dead `promotion_eligible` field across
    runner/evidence (and validation).
  - `src/quant_strategies/runner/economic_metrics.py` — ledger derived from the book
    walk (attribution), not an independent computation; drop `_trade_field`
    duck-typing.
  - `src/quant_strategies/funding.py` — the single funding implementation;
    `_apply_funding` (foundation) and `project_perp_ledger` funding are removed.
  - `src/quant_strategies/evaluation/` — backends consume the target book; remove
    `project_perp_ledger.py`, the perp-ledger routing and model-name in
    `vectorbtpro_backend.py` / `metrics.py`, and the
    `_REQUIRED_COMPLETED_FUNDING_MODELS` gate in `validation/_pipeline.py`.
  - `src/quant_strategies/validation/agreement.py` — the single-trade-only oracle is
    retired (VBT cross-check retired; an independent netted-book oracle is a
    follow-on).
- **Affected APIs (BREAKING):** the `generate_decisions` return contract;
  `RunResult.succeeded` semantics; `RunResult.foundation` (authoritative, typed
  verdict on breach instead of `None`); the public `evaluate` metric payload (the
  `funding_model` name and the completed-funding-model validation gate change).
- **Tests:** `tests/test_portfolio_foundation.py`, `tests/test_runner_api_cli.py`
  (the fail-open contract test is intentionally inverted), engine/decision/
  evaluation tests, and the candidate-config tests will change.
- **Docs:** `docs/consumer/*`, `docs/foundation-surfaces.md`, and the consumer
  contract (`quant_autoresearch/program.md`, `score_research.md`) descriptions of
  the scored unit and feasibility must be updated.
- **Dependencies:** no new heavy runtime dependency; the quick-run import wall is
  preserved.
- **Explicit follow-on changes (plug into the spine's market-model / risk
  interfaces; several need `quant_data` / `quant-data` upstream work — named here
  so they are not silently dropped):**
  1. Asset-class financing realism — equity short-borrow + dividends, FX
     rollover/carry, margin financing on gross > 1 (review F4).
  2. Capacity / liquidity / market-impact modeling + a `volume`/ADV data field
     (review F1; touches `data-boundary`).
  3. Intrabar OHLC stop-fill realism for `RiskRule` (review F5).
  4. Causality-gates-scoreability tightening (review F6; downstream-coupled —
     the verdict surfaces a causality dimension now, policy tightening follows).
  5. PIT `available_at >= timestamp` row-contract hardening (review F8; touches
     `data-boundary`).
