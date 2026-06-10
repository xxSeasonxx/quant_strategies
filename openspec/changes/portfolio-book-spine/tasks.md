## 1. Decision contract (the spine's input)

- [ ] 1.1 In `decisions/models.py`, define `RiskRule` (frozen, strict): optional `stop_loss`, `take_profit`, `trailing` thresholds; validation that present thresholds are finite and positive.
- [ ] 1.2 Replace the `open`-only `StrategyDecision` with `TargetDecision`: instrument, `as_of_time <= decision_time`, signed weight-of-NAV `target` (long `+`, short `-`, `0` = flat), optional `RiskRule`, observations, metadata, deterministic `decision_id`. Remove `DecisionAction`, `SizingKind`, the welded `ExitPolicy`, and the unbounded `PositionTarget.size`.
- [ ] 1.3 Remove the open-ticket translation layer: `engine/executable.py` (`executable_decision`, `base_unsupported_semantics`) and `engine_runner.py` `assert_supported_decisions` — including the `flat_target` / `leveraged_target_weight>1.0` rejections and the `direction → Side` mapping. The book consumes the target contract directly; flat and leveraged-intent targets are valid inputs governed by the feasibility verdict.
- [ ] 1.4 Keep the contract pure and causal: enforce `as_of_time <= decision_time` and JSON-safe metadata; no realized fills/NAV/book state exposed to strategies (v1). Update the purity lint (`decisions/purity.py`) expectations if the surface name/shape changed.

## 2. The unified causal portfolio book (the spine)

- [ ] 2.1 Rebuild `core/portfolio_foundation.py` as one causal single-account walk keyed by **per-symbol running signed quantity**: apply decisions effective at `t`, size target quantity from weight × one pre-entry equity snapshot, trade only the delta, charge costs on the delta and funding on the net held position, mark-to-market to one NAV path. Apply frictions at **one localized call site** in the walk — do **not** introduce a `MarketModel` abstraction now (only perp funding exists; the interface is extracted at F4 against two real terms).
- [ ] 2.2 Net same-symbol exposure by construction; emit a live mark-to-market gross/net exposure series and per-instrument concentration from the netted book. Size all same-bar entries against one equity snapshot taken before any of that bar's entries (fill-order-independent intended gross).
- [ ] 2.3 Enforce declared `RiskRule`s causally on the net position (flatten at the bar the end-of-bar printed mark crosses the level) with the **re-entry latch**: a fired rule holds the instrument flat until the strategy emits a new, different target.
- [ ] 2.4 Reconstruct the per-trade round-trip ledger as a derived attribution view of the same walk (no independent summation); reconcile with NAV realized PnL.

## 3. Scoring and the fail-closed feasibility verdict

- [ ] 3.1 Derive all scored statistics (Sharpe/SE/effective-sample inputs, drawdown, total return) from the NAV path over **at-risk bars**, not a zero-padded calendar. Re-base `closed_trade_count` on netted-book round trips.
- [ ] 3.2 Add a minimum at-risk-sample gate: below the floor, a subwindow/full-Train statistic is reported non-scoreable with a typed reason, not emitted from sample count alone.
- [ ] 3.3 Add a typed feasibility verdict on the run: `leverage_budget_breach` (observed gross/net), `zero_cost`, `insufficient_samples`, and a **required** `unfinanced_leverage` for asset classes without a modeled financing term (crypto-perp exempt). Surface a `causality_admissible` dimension read from existing causality evidence. Never clamp/normalize; never collapse to `None`.
- [ ] 3.4 Move the leverage budget out of agent-editable config: remove `foundation_max_gross_exposure` from `OutputConfig`/`[output]`; add a protocol-frozen budget covering **both gross and net** ceilings. A breach of intended exposure yields the verdict.

## 4. Runner wiring

- [ ] 4.1 Make `RunResult.foundation` the authoritative scored book; carry the typed feasibility verdict; remove the fail-open `except Exception -> (None, None)` path.
- [ ] 4.2 Gate `RunResult.succeeded` on the verdict by mapping an infeasible run to a typed `failure_stage` (keeps the `completed and failure_stage is None` formula intact).
- [ ] 4.3 Re-home `runner/economic_metrics.py` so the ledger is built from the book walk's round-trips (attribution); drop the `_trade_field` duck-typing fallback.
- [ ] 4.4 Replace free-form unavailable warnings with the typed verdict reasons; emit gross/net exposure utilization metrics (max/mean, time-integral) on full-train and subwindow records.
- [ ] 4.5 Remove the dead `promotion_eligible` field across runner, evidence DTOs, and validation; remove the `FoundationSubwindowMetric` alias.

## 5. Remove the old money-models (no compatibility shim)

- [ ] 5.1 Delete the per-trade linear-sum scorer in `engine/evaluation.py` (`net_total = sum(...)`); make screening a derived view over the book walk.
- [ ] 5.2 Delete the isolated `_select_exit` exit engine and the window-replay `_portfolio_path` / `_decision_windows` / dead `_fill_price` and the per-window position model.
- [ ] 5.3 Delete `evaluation/project_perp_ledger.py`, the perp-ledger routing and model-name in `evaluation/vectorbtpro_backend.py` and `evaluation/metrics.py`, and the `_REQUIRED_COMPLETED_FUNDING_MODELS` gate in `validation/_pipeline.py`. Route all NAV through the shared spine book.
- [ ] 5.4 Collapse funding to one implementation in `funding.py`; remove the foundation `_apply_funding` and the perp-ledger funding copies.
- [ ] 5.5 Retire the single-trade-only agreement oracle in `validation/agreement.py` (per the D9 retire-VBT decision); keep DSR as a **diagnostic** recomputed on the at-risk statistics — re-home it, do not delete it.

## 6. Validation and evaluation surfaces consume the contract

- [ ] 6.1 Make the pure-Python spine the single book for validation and evaluation; evaluation adds pandas/pyarrow artifact serialization *around* the pure book at its own layer (quick-run import wall preserved).
- [ ] 6.2 Retire the VectorBT Pro and perp-ledger evaluation backends (D9, confirmed); remove the public `funding_model` perp-ledger name from the evaluate metric payload and any data-kind backend routing.
- [ ] 6.3 Confirm the preserved `evaluation-fold-returns` observable behavior (typed fold returns net of costs, causal-integrity flag, `succeeded`) still holds on the spine.

## 7. Tests

- [ ] 7.1 Author a minimal reference target-book strategy + config fixture (cross-sectional rebalance and a single-name entry with a `RiskRule`) for end-to-end tests.
- [ ] 7.2 Invert the fail-open contract test in `tests/test_runner_api_cli.py`: a leverage breach is now a typed infeasible verdict with `succeeded = False`.
- [ ] 7.3 Test netting (offsetting/again targets net, no stacking), the weight→quantity-at-decision-bar hold, same-bar fill-order-independent gross, and the `RiskRule` re-entry latch.
- [ ] 7.4 Test at-risk-bar statistics and the min-sample gate (a 99%-flat strategy no longer inflates effective sample size / passes min-evidence).
- [ ] 7.5 Test the feasibility verdict: `leverage_budget_breach`, `zero_cost`, and `unfinanced_leverage` (equity/FX gross>1 non-scoreable; crypto-perp exempt); and that flat/leveraged-intent targets are accepted (no translation-layer rejection).
- [ ] 7.6 Add a reconciliation test: the derived per-trade ledger attributions reconcile with the NAV path's realized PnL.
- [ ] 7.7 Update/remove engine, decision, foundation, evaluation, and candidate-config tests that encode the old open-ticket / trade-unit / fail-open / perp-ledger-model contract.

## 8. Docs

- [ ] 8.1 Update `docs/consumer/*`, `docs/foundation-surfaces.md`, and `TODOS.md` (§2.3 O14–O23, R-residuals) to the target-book contract, the authoritative NAV book, and the fail-closed verdict. (`PRD.md` G1/G2/G3/G8/NG4 and `AGENTS.md` already updated.)
- [ ] 8.2 Update the consumer contract notes in `quant_autoresearch/program.md` / `score_research.md` describing the scored unit, the frozen leverage budget, and feasibility (coordinate with Season — cross-repo).
- [ ] 8.3 Update `live-trade-feasibility-review-2026-06-10.md` §14 action-map statuses for the items this change closes (0a/0b/0c collapsed; No.1/5/16; F2; F3; F7).

## 9. Verification

- [ ] 9.1 `conda run -n quant make check` (or the nearest format/lint/type target) passes; run `make fix` for formatting rather than hand-formatting.
- [ ] 9.2 `conda run -n quant pytest -q` passes on the updated suite.
- [ ] 9.3 Grep the tree for surviving legacy: no references to `project_perp_ledger`, `_REQUIRED_COMPLETED_FUNDING_MODELS`, `assert_supported_decisions`, `promotion_eligible`, `FoundationSubwindowMetric`, `_select_exit`, `DecisionAction`/`ExitPolicy`, or open-ticket shapes. Report changed-line counts (source / tests / docs separated).
