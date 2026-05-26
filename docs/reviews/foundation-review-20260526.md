# Foundation Review: quant_strategies

Date: 2026-05-26
Reviewer: Codex, project foundation review with quant math/research lens
Target: `/Users/Season_Yang/Personal/quant_strategies`

## Review Objective

I reviewed `quant_strategies` to determine whether it is a sound foundation for
a research-to-validation lifecycle:

```text
quant_data -> quant_strategies.runner -> quant_autoresearch
  -> researched/ handoff packages -> quant_strategies.validation
  -> Season-approved tested/ candidates -> separate paper/live systems
```

This review is not asking whether the repo is already a complete portfolio
backtester, execution system, or live-trading stack. It asks whether the current
foundation makes fast iteration, strategy math correctness, artifact honesty,
and conservative validation easy, while making lookahead, overfit promotion,
legacy drag, and overengineering hard.

### Clarified Scope

- **In scope**: `AGENTS.md`, `pyproject.toml`, `README.md`, `runs/`,
  `src/quant_strategies/{runner,engine,decisions,validation}`, `untested/`,
  `tested/`, `researched/`, and tests.
- **Out of scope**: paper trading, live trading, broker integration,
  production portfolio management, fixing findings in this pass, and external
  `quant_data` internals beyond this repo's usage.
- **Domain lenses**: project foundation, onboarding, architecture, senior
  software engineering, adversarial failure-mode review, and quant math/research
  correctness.
- **Additional concerns from Season**: whether the project is too heavy,
  whether legacy artifact handling should be cleaned, why repeated reviews keep
  finding new issues, whether design is clean/scalable, and whether the repo is
  overengineered.
- **Scope lock**: treated as confirmed when Season accepted the proposed success
  criteria and added the concerns above.

## Executive Verdict

`quant_strategies` is a solid smoke-runner and strategy-contract foundation,
but it is not yet trustworthy as a promotion-grade validation foundation.

The project is not too heavy at the core. The `runner`, `engine`, `decisions`,
and `validation` packages map to real lifecycle boundaries and should be
preserved. The repeated review findings are not random churn; they point to a
single root problem: artifact and validation semantics are becoming more
confident than the evidence can support. Validation can miss undeclared feature
lineage, `clear_yes` is too weak for disciplined strategy selection, smoke
return fields can be overread as portfolio returns, funding-aware validation is
currently a linear post-hoc adjustment, and default data loading depends on
implicit local `quant_data` environment discovery.

Do not rewrite the repo. Clean the foundation by tightening contracts,
validation policy, math labels, provenance, docs, and artifact lifecycle.

## Scope And Evidence Inspected

- **Primary source**:
  - `src/quant_strategies/runner/__init__.py` - public `run_config` flow.
  - `src/quant_strategies/runner/config.py` and `data_loader.py` - config and
    `quant_data` boundary.
  - `src/quant_strategies/engine/models.py` and `evaluation.py` - smoke engine
    timing, fills, costs, PnL.
  - `src/quant_strategies/decisions/models.py` - typed strategy decision
    contract.
  - `src/quant_strategies/validation/*` - validation config, matrix, audit,
    backend, policy, artifacts, manifest.
  - `untested/*.py`, `examples/strategies/simple_momentum.py`, `runs/*.toml`.
- **Tests inspected/executed**: full local pytest suite, plus targeted source
  traces through strategy decisions, validation audit, VectorBT adapter, and
  policy.
- **Docs treated as claims**: `README.md`, `AGENTS.md`, and stale/deleted
  tracked docs under `docs/superpowers` and prior `docs/reviews`.
- **Not verified**:
  - live `quant_data` database loads,
  - real VectorBT PRO numeric behavior outside existing tests,
  - production `quant_autoresearch` behavior,
  - paper/live trading workflows.

Verification command:

```bash
conda run -n quant pytest
```

Result: `365 passed in 14.61s`.

## Intended Foundation Model

The minimal correct foundation has these lifecycle states:

```text
raw idea
  -> untested/*.py
  -> configured quick runner smoke run
  -> quant_autoresearch fast iteration
  -> researched/<package> frozen handoff
  -> validation with typed decisions and backend economics
  -> Season-approved tested/
  -> separate paper/live system
```

Dependency direction should stay simple:

```text
quant_data
  owns materialization, refresh, repair, joins, and loader APIs
      |
      v
quant_strategies.runner
  loads rows, calls pure generate_decisions, writes smoke artifacts,
  builds internal smoke-engine requests
      |
      v
quant_strategies.engine
  deterministic causal smoke evaluator, not a portfolio validator
      |
      v
quant_autoresearch
  consumes run_config, searches candidates, freezes handoff packages
      |
      v
quant_strategies.validation
  loads typed decisions, audits data lineage, runs backend/matrix,
  writes advisory recommendation artifacts
      |
      v
manual promotion to tested/
```

## Project Ontology: Concepts, Contracts, Boundaries, Invariants

| Concept / boundary | Responsibility | Required invariant | Current fit |
|---|---|---|---|
| Strategy file | Pure rule code | No engine calls, data loading, loops, or artifact writes | Good |
| Strategy decision | Promotion-grade strategy output | Timezone-aware `decision_time` and `as_of_time`, explicit target, exit policy, observations when relevant | Good model, incomplete use of observations |
| Run config | One explicit runner experiment | TOML validated before import/data execution; repo-confined paths | Good |
| Data boundary | Consume `quant_data`, do not own materialization | Public loader APIs, reproducible source identity | Loader calls good; engine/env setup leaks |
| Smoke engine | Fast causal sanity check | Deterministic fills/costs, honest return model, no promotion claims | Useful, labels need stronger guardrails |
| Runner artifacts | Smoke evidence | Reproducible enough to debug; never promotion evidence | Mostly good |
| Researched package | Frozen autoresearch handoff | Strategy/config/data identity, lifecycle status, validation readiness | Under-specified in repo |
| Validation backend | Economic simulator | Honor semantics or reject explicitly | Good fail-closed posture, limited and approximate in places |
| Promotion decision | Human-facing advisory result | Conservative, robust, selection-pressure-aware | Underbuilt |

Invalid states that the foundation must make hard to represent:

- A quick runner artifact implying market validation.
- A validation artifact without full code/config/data/backend identity.
- A cross-sectional strategy passing validation while hiding undeclared
  feature rows.
- A `clear_yes` result being treated as paper/live readiness.
- A smoke return score being ranked as if it were an equity-curve return.
- A strategy silently accepting stale or typoed params.

## What Already Exists And Should Be Reused

| Existing code/flow | Evidence | Reuse / concern |
|---|---|---|
| Shared `generate_decisions` contract | `decisions.strategy_loader`, runner and validation loaders | Preserve. This cleaned up earlier signal/decision drift. |
| `StrategyDecision` Pydantic model | `decisions/models.py` | Preserve. It is the right future paper/live boundary. |
| Repo-confined Pydantic configs | `runner/config.py`, `validation/config.py` | Preserve. Good contract enforcement. |
| Immutable row/param views into strategies | `boundary.py`, runner and validation calls | Preserve. Good side-effect boundary. |
| Runner artifact semantics | `evidence_semantics.py`, `run_manifest.json`, summary flags | Preserve but strengthen labels. |
| Validation fail-closed backend | `validation/vectorbtpro_backend.py` | Preserve. Rejecting unsupported semantics is correct. |
| Full test suite | 365 passing tests | Preserve. Add missing failure-mode tests rather than broad rewrites. |

## Architecture And Boundary Review

### F0. Core Package Boundaries Are Right-Sized

- **Severity**: Positive finding
- **Action class**: Preserve
- **Evidence**: `src/quant_strategies/runner`, `engine`, `decisions`, and
  `validation` each own a coherent stage; CodeGraph indexes 70 files and 1,213
  symbols, not a sprawling project.
- **What is right**: The repo should remain a modular monolith. Splitting
  services or replacing this with a large framework would increase weight before
  fixing the actual trust gaps.
- **Recommendation**: Preserve package boundaries; fix contracts and semantics
  inside them.

### F1. Validation Can Miss Lookahead Because Observation Lineage Is Optional

- **Severity**: Critical
- **Action class**: Add
- **Evidence**:
  - `StrategyDecision.observations` defaults to `()` in
    `src/quant_strategies/decisions/models.py:127`.
  - Validation audits only declared observations in
    `src/quant_strategies/validation/dependencies.py:17`.
  - `audit_decision_rows` checks the emitted `as_of_time` row in
    `src/quant_strategies/validation/data_audit.py:37`.
  - The crypto and FX strategies compute from history/cross-sections but emit
    decisions without `observations` in
    `untested/crypto_perp_funding_crowding_reversal.py:279` and
    `untested/fx_triangular_residual_reversion.py:125`.
- **Risk**: A strategy can inspect future rows or late cross-symbol rows, emit a
  plausible `as_of_time`, and pass current validation if it omits observations.
- **First-principles reason**: Causal validation must verify the data actually
  used by the decision, not only the timestamp the strategy claims.
- **Root cause**: Missing validation-ready dependency contract.
- **Recommendation**: Require non-empty `ObservationRef` lineage for researched
  and validation-ready strategies that use lookbacks, funding, cross-section,
  quotes, or derived features. Add future-poison tests against real strategy
  families, not only synthetic fixtures. Longer term, consider a causal row-view
  API that prevents future reads by construction.
- **Tradeoff**: More boilerplate in strategies, but this directly targets
  lookahead and repeated review churn.
- **Verification needed**: Tests where late synthetic-leg rows or future funding
  rows change the strategy if accessed, and validation fails unless observations
  declare them.

### F2. `clear_yes` Is Too Weak For Disciplined Strategy Selection

- **Severity**: Critical
- **Action class**: Retire
- **Evidence**:
  - `run_validation` hard-codes `min_trades = 10` in
    `src/quant_strategies/validation/__init__.py:73`.
  - `classify_validation` gates required scenarios on completed status,
    valid metrics, `trade_count >= min_trades`, and `net_return > 0` in
    `src/quant_strategies/validation/policy.py:113`.
  - Parameter perturbation is diagnostic and only covers the first numeric param
    in `src/quant_strategies/validation/matrix.py:100`.
- **Risk**: The label reads like a strong validation result, but the math is a
  minimal backend/matrix pass. It does not cover walk-forward or OOS separation,
  drawdown, Sharpe/PSR/DSR, PBO, negative controls, trial count, regime
  stability, or selection pressure from `quant_autoresearch`.
- **First-principles reason**: A promotion gate must test robustness of the
  selected process, not only positive net return on a small fixed matrix.
- **Root cause**: Promotion ontology is under-modeled.
- **Recommendation**: Retire the strong interpretation of `clear_yes`. Rename it
  to something like `mechanical_pass` or keep `clear_yes` only after adding
  explicit statistical/risk gates. Continue writing `paper_trade_eligible=false`
  and `live_eligible=false`.
- **Tradeoff**: More conservative labels may slow promotion, but they prevent
  false confidence.
- **Verification needed**: Policy tests proving diagnostic perturbation failure,
  missing manifest, no OOS evidence, or absent trial-count provenance cannot
  produce a promotion-sounding result.

### F3. Researched Package Shape And Integrity Are Not Mandatory Enough

- **Severity**: High
- **Action class**: Add
- **Evidence**:
  - `researched/` currently contains only `.gitkeep`.
  - Validation accepts a directory by appending `validation.toml` in
    `src/quant_strategies/validation/config.py:123`.
  - Missing research manifests pass in
    `src/quant_strategies/validation/research_manifest.py:19`.
  - Missing matching manifest variants pass with a warning in
    `src/quant_strategies/validation/research_manifest.py:42`.
- **Risk**: A validation result can be detached from the autoresearch handoff
  that produced the candidate.
- **First-principles reason**: Validation evidence should prove exactly which
  frozen candidate, config, and upstream selection context it evaluated.
- **Root cause**: Missing package schema and mandatory integrity policy.
- **Recommendation**: Define one canonical researched package layout and commit
  a minimal example. For promotion workflows, require manifest presence,
  matching variant, lifecycle status, strategy hash, validation config hash, and
  upstream run identity before any strong advisory result.
- **Tradeoff**: Slightly more ceremony for handoffs, much less ambiguity.

### F4. Default `quant_data` Setup Leaks Upstream Implementation Details

- **Severity**: High
- **Action class**: Refactor
- **Evidence**:
  - `data_loader.py` uses public loader calls, which is good:
    `quant_data.loader.load_bars`, `load_universe_bars`,
    `load_crypto_perp_bars_with_funding`, and `load_fx_bars_with_quotes`.
  - `_default_engine()` imports `quant_data.db.get_engine` and
    `quant_data.config.DataConfig` in `src/quant_strategies/runner/data_loader.py:7`.
  - `_quant_data_env_file()` finds `.env` by walking from `loader.__file__` in
    `src/quant_strategies/runner/data_loader.py:128`.
- **Risk**: Runs can depend on local checkout/package layout rather than an
  explicit data source identity. Summary artifacts hash rows but omit raw rows,
  making upstream source identity more important.
- **First-principles reason**: If data is a boundary, connection/config identity
  must be explicit and reproducible.
- **Root cause**: Boundary leak from convenience engine creation.
- **Recommendation**: Move engine/config creation behind a public `quant_data`
  API or require explicit injected engine/config for automated workflows. Record
  data source identity, loader version, and snapshot/source metadata in
  manifests when available.
- **Tradeoff**: More explicit setup, less hidden local coupling.

## Engineering, Testability, And Operability Review

### F5. Smoke Return Fields Can Be Misread As Portfolio Returns

- **Severity**: High
- **Action class**: Refactor
- **Evidence**:
  - Engine gross return is per-trade weighted simple return in
    `src/quant_strategies/engine/evaluation.py:68`.
  - Totals are simple sums in `src/quant_strategies/engine/evaluation.py:98`.
  - `evidence_semantics.py` labels the model as
    `sum_weighted_trade_return`.
- **Risk**: `gross_return`, `funding_return`, `cost_return`, and `net_return`
  look like portfolio/equity-curve returns in artifacts, but they are smoke
  scores. Ranking strategies from them can select false positives.
- **First-principles reason**: Metric labels must match aggregation math.
- **Root cause**: Artifact semantics and metric naming.
- **Recommendation**: Either rename exposed smoke totals to
  `sum_weighted_trade_*` fields, or place them under a `smoke_score` object.
  Require validation/backend portfolio metrics for selection and promotion
  discussions.
- **Tradeoff**: Some consumer updates, but less risk of misusing smoke output.

### F6. Funding-Aware Validation Uses A Linear Post-Hoc Adjustment

- **Severity**: High
- **Action class**: Refactor
- **Evidence**:
  - VectorBT total return is extracted first in
    `src/quant_strategies/validation/vectorbtpro_backend.py:320`.
  - Funding is summed and added to produce `net_return` in
    `src/quant_strategies/validation/vectorbtpro_backend.py:356`.
  - Funding cashflow signs and interval logic live in
    `src/quant_strategies/validation/funding.py:21`.
- **Risk**: The metric is not equivalent to injecting funding cashflows into an
  equity path when compounding, cash sharing, variable weights, or large funding
  matter.
- **First-principles reason**: Return decomposition must preserve accounting
  order if it is used as a gate.
- **Root cause**: Approximate backend accounting exposed under a strong metric
  name.
- **Recommendation**: Keep price-cost backend `net_return` separate from
  `linear_funding_adjustment` and `linear_adjusted_net_return`, or implement
  funding cashflows inside the simulated portfolio path. Do not let the linear
  adjusted metric alone drive promotion.
- **Tradeoff**: Renaming is fast; portfolio cashflow integration is more
  correct but heavier.

### F7. Close-Triggered Exits Can Fill On The Same Close They Observe

- **Severity**: High
- **Action class**: Add
- **Evidence**:
  - Threshold checks scan trigger bars in
    `src/quant_strategies/engine/evaluation.py:214`.
  - The exit fills at `trigger_index + exit_lag_bars` in
    `src/quant_strategies/engine/evaluation.py:227`.
  - Runner config defaults `exit_lag_bars = 0` in
    `src/quant_strategies/runner/config.py:77`.
- **Risk**: With close fills and threshold exits, a strategy can observe a bar's
  close crossing a threshold and fill at that same close. That is only causal if
  explicitly modeled as a same-close executable exit.
- **First-principles reason**: Trigger observation time and fill execution time
  must be causally ordered.
- **Root cause**: Missing explicit opt-in for same-close exit semantics.
- **Recommendation**: Require `exit_lag_bars >= 1` for close-triggered threshold
  exits unless config adds an explicit `allow_same_bar_close_exit = true` with
  clear artifact labels.
- **Tradeoff**: More conservative smoke results, fewer lookahead-adjacent exits.

### F8. Parameter Contracts Are Optional Where They Matter Most

- **Severity**: Medium
- **Action class**: Add
- **Evidence**:
  - `validate_strategy_params` returns `dict(params)` if no validator exists in
    `src/quant_strategies/decisions/params.py:13`.
  - Current strategies parse params with `params.get(...)` defaults, for example
    `untested/crypto_perp_funding_crowding_reversal.py:59` and
    `untested/fx_triangular_residual_reversion.py:76`.
- **Risk**: Typoed, stale, or unused TOML params can silently create different
  experiments from what the researcher thinks they ran.
- **First-principles reason**: Invalid strategy states should be impossible at
  validation boundaries.
- **Root cause**: Optional boundary validation.
- **Recommendation**: Keep optional params for early `untested/` iteration, but
  require `validate_params` or a Pydantic/dataclass schema for researched and
  validation-ready packages.
- **Tradeoff**: More code per strategy, better auditability.

### F9. Validation Orchestration Is Too Concentrated In One Module

- **Severity**: Medium
- **Action class**: Simplify
- **Evidence**: `src/quant_strategies/validation/__init__.py` is 633 lines and
  owns config resolution, package manifest checks, data loading, strategy
  execution, matrix expansion, backend execution, classification, and artifact
  writing.
- **Risk**: New validation features will keep accumulating in the orchestrator,
  making behavior harder to reason about and increasing review churn.
- **First-principles reason**: A module should have one main reason to change.
- **Root cause**: Orchestration grew as features landed.
- **Recommendation**: Do not rewrite immediately. When touching validation next,
  extract small phase functions/modules around package intake, window execution,
  scenario execution, and artifact assembly. Keep the public `run_validation`
  API stable.
- **Tradeoff**: Controlled simplification, no broad architecture churn.

### F10. Validation Artifacts Can Emit Non-Standard `NaN`

- **Severity**: Low
- **Action class**: Add
- **Evidence**:
  - `BackendRunResult.metrics` accepts floats without finite-value validation in
    `src/quant_strategies/validation/backends.py:16`.
  - `write_json_artifact` uses `json.dumps(...)` without `allow_nan=False` in
    `src/quant_strategies/validation/artifacts.py:29`.
- **Risk**: Policy can reject non-finite metrics, but artifacts may still become
  non-standard JSON for strict consumers.
- **Recommendation**: Validate backend metric floats as finite, or serialize
  with `allow_nan=False` and fail closed.

## Domain-Specific Lens Findings: Quant / Trading Research

### Q1. Strategy Math Is Plausible, But Validation Does Not Yet Prove It Is Causal

- **Severity**: Critical
- **Action class**: Add
- **Evidence**: FX and crypto strategies use cross-symbol/history/funding rows
  but emit empty `observations`; validation currently accepts empty observations.
- **Domain risk**: Lookahead and feature-lineage leakage are among the fastest
  ways to select strategies that vanish out of sample.
- **Recommendation**: Make dependency declarations mandatory for validation
  candidates and add family-specific future-poison tests.

### Q2. The Current Validation Policy Is A Mechanical Screen, Not A Research-Grade Gate

- **Severity**: Critical
- **Action class**: Retire
- **Evidence**: `clear_yes` requires positive net return and minimum trades on
  required matrix scenarios only.
- **Domain risk**: Positive net return after autoresearch search is weak
  evidence without trial-count, OOS, robustness, and negative-control context.
- **Recommendation**: Treat current validation as advisory mechanical
  eligibility only. Add a second stronger promotion policy before any move to
  `tested/`.

### Q3. PnL And Funding Labels Need Stronger Accounting Boundaries

- **Severity**: High
- **Action class**: Refactor
- **Evidence**: Runner returns are summed smoke scores; funding validation is
  linear post-hoc adjustment.
- **Domain risk**: Misnamed returns lead to wrong ranking, wrong economic
  interpretation, and weak promotion decisions.
- **Recommendation**: Split smoke scores, backend native returns, funding
  adjustments, and promotion metrics into separate named fields.

## Unknown Unknowns And Assumption Risks

| Assumption | Why it may be wrong | How to test or de-risk |
|---|---|---|
| `quant_data` rows include sufficient `available_at`/source identity | This repo cannot prove upstream joins and timestamps are causally correct | Add loader/source metadata to manifests; document upstream limitations to `quant-data` |
| VectorBT PRO `valuepercent`/cash-sharing semantics match target-weight intent | Existing tests rely heavily on fakes and kwargs | Add small numeric integration traces when VectorBT PRO is available |
| Autoresearch will not rank by runner smoke returns | The API exposes compact totals that are easy to consume | Require backend/promotion metrics for ranking; label smoke scores aggressively |
| Strategy authors will remember to emit observations | Current models default to empty observations | Make validation-ready contracts fail without lineage for nontrivial strategies |
| Deleted docs are intentional cleanup | Worktree shows deleted tracked docs, not committed cleanup | Decide whether to retire or restore them before making docs authoritative |

## Overbuilt, Underbuilt, And Right-Sized Areas

- **Right-sized**:
  - Modular monolith package shape.
  - Flat strategy files.
  - Pydantic config and decision models.
  - Internal smoke engine as a deterministic causal sanity checker.
  - Fail-closed backend semantics.
  - Full test suite for current behavior.
- **Underbuilt**:
  - Observation lineage enforcement.
  - Strong promotion/selection policy.
  - `quant_data` source identity and connection boundary.
  - Researched package schema and manifest requirements.
  - Parameter schemas for validation-ready strategies.
  - Metric/accounting labels for smoke and funding-adjusted returns.
- **Overbuilt or heavy**:
  - Validation orchestration concentrated in one large module.
  - Stale tracked docs/plans that describe old `generate_signals` contracts.
  - Ignored local artifact volume: `results/` is about 3.0G in this checkout.
  - Internal `hold_bars` compatibility fields still leak into smoke artifacts.

## Missing Docs, PRD, ADR, Or Decision Records

- **Missing ADR: validation evidence taxonomy**. Define what `mechanical_pass`,
  `advisory`, `promotion_candidate`, `tested`, `paper_trade_eligible`, and
  `live_eligible` mean.
- **Missing ADR: `quant_data` boundary**. Decide what APIs are public for engine
  creation/config and what source identity must be recorded.
- **Missing researched package schema**. Document canonical required files,
  lifecycle statuses, hash fields, and validation readiness.
- **Missing metric semantics reference**. Document smoke score vs portfolio
  return vs backend native return vs funding-adjusted approximation.
- **Stale docs**: tracked docs under `docs/superpowers` and deleted prior
  reviews still reference older `generate_signals` architecture. Either retire
  them intentionally or mark them historical.
- **README gap**: artifact list should distinguish successful full-profile
  artifacts from partial failure artifacts.

## Preserve / Refactor / Simplify / Add / Retire Action Map

| Action class | Findings / recommendations | Rationale |
|---|---|---|
| Preserve | Keep modular monolith, flat strategies, `run_config`, Pydantic configs, `StrategyDecision`, fail-closed backend | These boundaries match the lifecycle and are not the source of repeated issues |
| Refactor | `quant_data` setup, smoke return fields, funding-adjusted metrics | Same capabilities should remain, but their boundaries and names need to express reality |
| Simplify | Validation orchestration, stale docs/artifact working set | Reduce review surface and stop layering new features into one large module |
| Add | Observation lineage enforcement, future-poison tests, researched package schema, mandatory validation params, finite JSON metric validation, source identity | Trustworthiness requires explicit contracts and checks |
| Retire | Strong interpretation of `clear_yes`, stale signal-era docs, compatibility fields as public artifacts | Preserving misleading names and old contracts fights the objective |

## Prioritized Recommendations

| Priority | Action class | Recommendation | Why now | Verify |
|---|---|---|---|---|
| P0 | Add | Require observation lineage or causal row views for validation-ready strategies | Biggest lookahead risk | Real FX/crypto future-poison tests fail before fix and pass after |
| P0 | Retire | Downgrade or rename current `clear_yes`; keep paper/live eligibility false | Prevent false promotion confidence | Policy tests show weak evidence cannot produce promotion-sounding output |
| P1 | Refactor | Rename/split smoke return metrics from portfolio returns | Prevent autoresearch misuse | Artifact schema tests assert smoke score naming |
| P1 | Refactor | Separate native backend return, funding adjustment, and adjusted return | Prevent approximate funding math from acting as exact PnL | Unit and artifact tests for metric names and gates |
| P1 | Refactor | Make `quant_data` connection/config explicit and record source identity | Reproducibility boundary | Manifests include loader/source identity |
| P2 | Add | Require researched package manifest and canonical layout for promotion workflows | Clean handoff from autoresearch | Minimal committed example and manifest integrity tests |
| P2 | Add | Require param schemas for researched/validation packages | Avoid stale/typo params | Validation rejects unknown params for ready packages |
| P2 | Add | Require explicit same-close exit opt-in or `exit_lag_bars >= 1` for threshold exits | Avoid close-trigger lookahead | Config/model tests around threshold exits |
| P3 | Simplify | Split `validation/__init__.py` by phase when next touched | Improve maintainability | No behavior change; full suite passes |
| P3 | Retire | Settle deleted docs and ignored artifact cleanup | Reduce legacy drag | Git status clean except intentional work |

## NOT In Scope

- Building live or paper trading.
- Adding portfolio allocation across strategies.
- Replacing VectorBT PRO or building a full engine now.
- Moving anything from `untested/` or `researched/` to `tested/`.
- Refactoring all validation internals in this review.
- Inspecting or changing `quant_data` internals.

## Verification Summary

- **Verified**:
  - Full test suite: `conda run -n quant pytest` passed, `365 passed in 14.61s`.
  - CodeGraph project index was healthy: 70 indexed files.
  - Source/test/docs inspection across runner, engine, decisions, validation,
    strategy files, run configs, and README.
  - Five independent read-only review lenses: onboarding, architecture, senior
    engineering, adversarial, and quant math/research.
  - Worktree state before edits included deleted tracked docs and untracked
    `.codegraph/` and `.cursor/`; this review did not restore or revert them.
- **Not verified**:
  - Live `quant_data` loads.
  - Real VectorBT PRO numeric traces beyond existing tests.
  - Production `quant_autoresearch` behavior.
  - Whether deleted docs are intentionally retired.
- **Residual risk**:
  - The repo is currently correct for its tested contracts, but current
    validation artifacts should be treated as advisory mechanical evidence only
    until lineage, policy, and metric semantics are strengthened.
