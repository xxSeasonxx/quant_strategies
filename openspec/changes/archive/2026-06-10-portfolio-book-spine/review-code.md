# Code Review — `portfolio-book-spine` (general code-review lens)

Reviewer lens: correctness, maintainability, design/SOLID, error handling, type/data
boundaries, test quality, over-/under-engineering, no-legacy cutover cleanliness.
Diff reviewed: `main...portfolio-book-spine` (108 files, +7644/−13304). Read-only.

## VERDICT: sound-with-corrections

The refactor delivers its north star. The trade-as-atomic-unit scorer, the three
duplicate money-models, and the triple funding implementation are genuinely gone;
one causal, single-account, per-symbol-netted book (`core/portfolio_foundation.py`)
is the only PnL/NAV computation on all three surfaces (quick-run, validation,
evaluation). The netting math is internally consistent and conserves NAV (verified
by hand-tracing trim/reversal cases and by the reconciliation tests). The fail-open
`foundation=None` is replaced by a typed, fail-closed `FeasibilityVerdict`; at-risk
return statistics + a min-sample gate close the flat-bar DSR-inflation gap; the
no-legacy cutover is clean (no `getattr` tolerance, no dual money paths, no swallowed
failures; removed symbols are genuinely deleted). Full suite green except the two
known-deferred failures. Lint and mypy clean on the spine.

It is **sound-with-corrections** rather than fully sound because of one real
design-vs-contract deviation (the leverage budget the OpenSpec design calls
"protocol-frozen" was implemented as a hardcoded `1.0/1.0` constant that no surface
can override) plus a set of minor correctness/cleanliness items (reversal cost
mis-attribution in the derived ledger, orphaned `engine/` modules left by the
cutover, a tautological reconciliation assertion in the e2e test). None of these
breaks the authoritative NAV scoring; they are corrections, not a redesign.

## Severity-ranked findings

| # | Severity | Location | Issue | Why it matters | Suggested fix |
|---|----------|----------|-------|----------------|---------------|
| 1 | **major** | `core/portfolio_foundation.py:48-49` (`PortfolioFoundationConfig.max_gross_exposure/max_net_exposure` default `1.0`); `runner/__init__.py:802-808`; `evaluation/spine_backend.py:143`; `validation/engine_backend.py:58` | The leverage budget the design (D6) and spec require to be **operator-frozen in the protocol set** ("owned by the protocol, alongside costs and fills") was implemented as a **hardcoded `1.0/1.0` constant**. `foundation_max_gross_exposure` was correctly removed from agent-editable `[output]`, but no protocol-frozen replacement field was added; the runner, evaluation backend, and validation backend all construct `PortfolioFoundationConfig` **without** setting the ceilings, so every surface enforces a fixed `1.0/1.0`. | The fail-closed *behavior* is achieved and is safe (more frozen than configurable, no leak). But the operator cannot set a non-1.0 ceiling (e.g. a perp 2.0 ceiling that `program.md`'s frozen set is supposed to own) without a code edit, which is the opposite of the design's "operator-frozen, protocol-owned" intent. The guard test (`test_runner_config_has_no_agent_editable_leverage_budget`) only asserts the field's *absence* from `[output]`, so it does not catch that the protocol-frozen half is missing. | Add a protocol-frozen budget field (gross+net) to the frozen config surface and thread it into the `PortfolioFoundationConfig(...)` constructions on all three surfaces. If a fixed `1.0/1.0` is the deliberate decision for v1, reconcile design.md D6 / spec "Leverage budget is operator-frozen" to say "frozen constant, not yet protocol-configurable" so the doc matches the code. |
| 2 | minor | `core/portfolio_foundation.py:794-806` (`_apply_decision` reversal branch); docstring `_close_leg` lines 845-853 | On a reversal (cross-zero), the **full delta cost** (close-of-old + open-of-new, computed at line 783 on the whole delta) is charged entirely to the **closing** round-trip; the re-opened leg gets `open_cost = 0.0`. The new leg's eventual round-trip therefore under-reports its entry cost. Verified by trace: a long→short→flat sequence at 10bps gave the long trip `cost_cash=0.32` (its own open + the entire reversal-bar cost) and the short trip `cost_cash=0.10` (close only, zero entry cost). | **NAV reconciles exactly** (`sum_realized == final_nav − INITIAL_EQUITY`), so this is *not* a scoring bug — the authoritative object is correct. It only skews the **derived per-trade cost attribution** (`economics.by_direction`/`by_symbol` cost, per-trade `cost_return`), which D4 explicitly demotes to non-scored diagnostics. But `_close_leg`'s docstring claims each round-trip's `cost_cash` is "the leg's open cost + the closing cost", which is false for the reversed leg. | Either split the reversal cost between the closed leg (its share of the delta back to flat) and the re-opened leg (the residual), or correct the `_close_leg`/`RoundTrip.cost_cash` docstrings to state that a reversal books the whole reversal-bar cost on the closing trip. Attribution-only; low urgency. |
| 3 | minor | `engine/bar_index.py` (orphan); `engine/__init__.py:exports`; `engine/evaluation.py:EvaluationError` | No-legacy cutover left dead code. `engine/bar_index.py` (`BarIndex`, 62 lines) has **zero** references anywhere in `src/` or `tests/`. `engine/models.py` symbols `EvaluationRequest`/`StrategySpec`/`Bar`/`CostModel`/`FillModel` have **zero** live `src/` usage outside `engine/` itself — only `EVIDENCE_SCHEMA_VERSION` is live (one constant, used in `runner/artifacts.py:15`). `engine/evaluation.py::EvaluationError` duplicates `evaluation/errors.py::EvaluationError` (the latter is the one `evaluation/dependencies.py` actually uses). `tests/test_engine_models.py` pins the otherwise-dead model DTOs. | AGENTS.md NG5: "Removing the old path is part of the change, not a follow-up." The branch deleted the scorer but left orphaned model/index modules + a test that keeps them alive, which is exactly the dead-tolerance the no-legacy rule targets. Low risk (importable, internally coherent, lint-clean) but it is residue. | Delete `engine/bar_index.py`; re-home `EVIDENCE_SCHEMA_VERSION` (e.g. into `evidence_semantics`/`artifacts`) and drop the unused `engine/models.py` exports + `test_engine_models.py` cases, or keep them only if the "validation/evaluation rebuilt on the spine in a later phase" (per `engine/__init__.py` docstring) will demonstrably reuse `EvaluationRequest`/`StrategySpec`. The duplicate `EvaluationError` should be one type. |
| 4 | minor | `tests/test_runner_api_cli.py:2047-2049` | The e2e "ledger reconciles with the book's realized NAV PnL (one model of money)" assertion compares `economics.sum_net_return` to `sum(t.net_return for t in economics.trades)` — both derived from the **same** round-trip source, so it is a `sum==sum` tautology, not a NAV↔ledger cross-check. | The real reconciliation (vs the NAV path) lives in `test_portfolio_foundation.py::_reconcile` and is correct; this is a test-quality gap, not a missing invariant. The comment overstates what the assertion proves. | Either assert `economics.sum_net_return ≈ (foundation.ledger.final_nav − INITIAL_EQUITY)/INITIAL_EQUITY` (requires book to end flat) or relabel the assertion to "internal ledger totals are self-consistent." |
| 5 | minor (by-contract) | `runner/__init__.py:241,788` (`_decision_window_decisions` vs book fed `execution_normalized_rows`) | The book walks the **buffered** load window (`execution_normalized_rows`, may extend before `data.start`) but only receives decisions whose `decision_time` ∈ `[data.start, data.end]` (`_decision_window_decisions`). A decision emitted inside the warmup buffer (before `data.start`) is **silently dropped** rather than asserted-against. | Correct by the execution-buffer contract (buffer is for observation warmup; decisions are expected only in the scoring window, matching `program.md`). But the silent drop means a contract violation would pass unnoticed. Pre-existing behavior, not introduced here. | Out of scope to fix; consider a future assertion that no decision falls strictly inside the warmup buffer, so a mis-emitting strategy fails loudly instead of silently losing exposure. |
| 6 | minor (documented) | `core/portfolio_foundation.py:855` / `RoundTrip` semantics; reconciliation only on flat-ending books | The derived ledger reconciles with NAV **only when the book ends flat**. Unrealized PnL and accrued funding on a still-open leg at window end are in NAV but in no `RoundTrip`, so `economics.sum_net_return` ≠ NAV total return for a book that ends with open positions. | Intended per D4 ("when the book ends flat …") and the reconciliation test correctly guards itself with `assert path[-1].gross_exposure ≈ 0.0`. Worth stating because a consumer reading `economics` as a NAV proxy on an open-ended window would be misled. | No code change required; ensure consumer docs say the per-trade ledger attributes **closed** round-trips only and NAV is authoritative. |

## What's done well (preserve)

- **The netting model is correct.** Per-symbol running signed quantity with a
  moving-average `cost_basis`; costs on the traded delta only; reversal realizes the
  closed leg and re-opens the residual. Hand-traced trim-at-moved-price and
  long→short→flat: NAV is conserved and the single round-trip captures the full
  economic PnL. `_equity_at_mark = cash + Σ(signed_qty·mark − cost_basis)` is a clean,
  consistent accounting identity.
- **At-risk gating closes the headline gap.** `at_risk = previous_gross > tol`
  correctly excludes the flat→position entry bar and the flat tail; the entry-bar
  return is not a position return (close fills), so nothing is lost. Min-sample gate
  is enforced via a typed `insufficient_samples` verdict. `test_flat_bars_*` and
  `test_flat_tail_does_not_change_sample_count_vs_short_window` lock the contract.
- **Fail-closed verdict is genuinely fail-closed.** `_check_intended_budget` raises a
  typed `FeasibilityError` (leverage/unfinanced) mid-walk and is never clamped; the
  non-raising gates (`zero_cost`, `insufficient_samples`) flow through
  `_scenario_feasibility` with documented precedence. `RunResult.succeeded` is gated
  by mapping infeasibility to a `feasibility` `failure_stage`, keeping the existing
  `completed and failure_stage is None` formula intact (no contract churn). A benign
  build error (missing/unfillable rows) is a separate `portfolio_foundation` stage
  failure — the three failure classes the design wanted to distinguish are distinct.
- **No-legacy cutover is real.** No surviving `project_perp_ledger`,
  `assert_supported_decisions`, `_select_exit`, `promotion_eligible`,
  `FoundationSubwindowMetric`, `DecisionAction`/`ExitPolicy` in `src/` (only comments
  + a build-generated `SOURCES.txt`). No `getattr`/optional-old-field tolerance, no
  dual money paths, no broad `except` swallowing failures in the book/backends. The
  stale agent-editable budget key is *rejected* on load (extra-forbidden), not
  silently ignored. `_REQUIRED_COMPLETED_FUNDING_MODELS` was correctly **updated** to
  `{SHARED_ACCOUNTING_MODEL}` (not deleted), satisfying the evaluation-fold-returns
  "gate reflects the single model" scenario.
- **One model of money on every surface.** `walk_portfolio_book` is the lower-level
  per-(window,scenario) entry; `spine_backend`/`engine_backend` both project the same
  walk; evaluation adds only pandas/pyarrow serialization *around* the pure book,
  preserving the dependency-light import wall. The intentional evaluation-calendar vs
  foundation-at-risk return-sample divergence is spec-consistent (evaluation-fold-
  returns keeps the prior calendar observable).
- **Decision contract is well-typed at the boundary.** `TargetDecision`/`RiskRule`
  are frozen, strict Pydantic with finite/positive/timezone validators, deterministic
  `decision_id`, and JSON-safe frozen metadata. Idempotent same-weight target is a
  structural no-op (anti-stacking by construction). Flat/leveraged targets are valid
  inputs governed by the verdict, not rejected by a translation layer — exactly the
  contract flip the proposal promised.
- **RiskRule + re-entry latch** is subtle and correctly handled: fired rule latches
  the symbol flat at the standing weight; an identical re-emission is suppressed; a
  different target clears the latch and re-enters. The "no intrabar fill realism"
  limitation (exit fills at the printed mark, not the threshold) is explicitly
  documented as deferred (F3/F5), not silently wrong.
- **Inverted tests are legitimate, not weakened.** The fail-open contract test was
  inverted to assert the *new* contract (`succeeded is False`, typed
  `leverage_budget_breach`, observed gross), with a comment marking the deliberate
  flip — not a weakened expectation to make a stale test pass.
