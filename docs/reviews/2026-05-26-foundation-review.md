# Final Foundation Review: quant_strategies

Date: 2026-05-26
Reviewer: Codex, senior quantitative research / software foundation review
Target: `/Users/Season_Yang/Personal/quant_strategies`

This is the consolidated final review. It compares and supersedes:

- `docs/reviews/2026-05-26-foundation-review.md` as it existed before this
  consolidation.
- `docs/reviews/2026-05-26-foundation-review-quant-research.md`.

## Review Objective

I reviewed whether `quant_strategies` is a sound foundation for a
research-to-validation workflow:

```text
quant_data -> quant_strategies.runner -> quant_autoresearch
  -> researched/ handoff package -> quant_strategies.validation
  -> Season-approved move to tested/ -> separate paper/live workflow
```

The review is not asking whether this repo is already a complete backtesting,
portfolio-management, or live-trading platform. It asks whether the current
foundation makes the right things easy and dangerous things hard: reproducible
quick research, clear strategy contracts, causal data use, honest artifacts,
math-safe metrics, conservative validation, and enough performance that
`quant_autoresearch` has no reason to bypass the shared runner.

## Comparison And False-Positive Control

The two source reviews mostly agree. I kept the shared conclusions, added the
older review's missing concrete integrity findings, and softened claims that
were directionally right but too absolute.

| Prior claim | Final treatment | Reason |
|---|---|---|
| Core project may be too heavy | Kept as **not too heavy at the core** | Source boundaries are coherent; weight is mostly frozen researched artifacts and docs |
| Validation cannot clear current cross-sectional candidate | Softened to **backend capability mismatch likely blocks this candidate unless live decisions are single-asset/non-overlapping** | Source proves VectorBT rejects multi-asset target weights; only a real validation run proves the emitted decision set |
| `StrategyDecision` should be canonical | Softened to **canonical for validation-ready strategies** | `generate_signals` is still the right lightweight quick-research API |
| Mutation can break artifact provenance | Kept and added | Runner passes mutable `loaded.rows` after writing raw input artifacts; validation passes mutable rows/params through strategy and backend paths |
| Researched manifest hash is stale | Kept and verified | `shasum -a 256` for rank_03 strategy differs from `manifest.json` |
| Validation depends on runner internals | Kept as low-severity/deferred | Reuse is acceptable now; extract only if this becomes a real second reason to change |
| Result directory allocation has a race | Kept as low-severity | The check-then-create loop is real but not foundation-blocking |
| Status types should be narrower | Kept as secondary refactor | `BackendRunResult.status` is plain `str` while policy expects a finite vocabulary |

No material source-backed finding was discarded as false after spot-checking.
The main consolidation change is severity and wording: avoid claims that current
evidence is stronger or weaker than the code proves.

## Executive Verdict

`quant_strategies` is a solid candidate-research and smoke-evaluation
foundation, but it is not yet a trustworthy promotion-grade validation
foundation.

The project is not too heavy at the core. `runner`, `engine`, `decisions`, and
`validation` correspond to real lifecycle boundaries. The main failure mode is
not code sprawl; it is false confidence from semantic drift. Quick research
emits dict signals while validation requires typed decisions, validation policy
can return `clear_yes` from thin evidence, runner return labels can be read as
portfolio returns, validation artifacts lack runner-grade provenance, and broad
autoresearch loops are already stressing artifact and engine hot paths.

Do not rewrite the repo. Preserve the modular monolith and harden the boundary
contracts, evidence semantics, validation policy, and quick-run performance.

## Scope And Evidence Inspected

- **Repo instructions**: `AGENTS.md`.
- **Source**: `src/quant_strategies/runner`, `engine`, `decisions`,
  `validation`, selected `untested/`, `tested/`, and `researched/` strategies.
- **Configs/artifacts**: `runs/`, researched `config.toml`, `validation.toml`,
  researched `manifest.json`, and selected evidence files.
- **Tests**: runner, engine, validation, data audit, VectorBT backend, strategy
  contract, and researched-contract tests.
- **Docs as claims**: `README.md`, both source review docs, and relevant design
  docs.
- **Cross-repo note**:
  `/Users/Season_Yang/Personal/quant_autoresearch/UPSTREAM_LIMITATIONS_TODO.md`.
- **Not verified**: live `quant_data` loads, real VectorBT PRO execution on the
  selected researched candidate, and full `quant_autoresearch` behavior beyond
  the named upstream limitations note.

## Intended Foundation Model

The foundation should express these lifecycle states:

```text
raw idea
  -> untested/*.py
  -> configured quick runner screen
  -> quant_autoresearch search / scoring
  -> researched/<package>/<variant> frozen handoff
  -> validation with typed decisions and backend economics
  -> Season-approved move to tested/
  -> separate paper/live execution system
```

Dependency direction should stay simple:

```text
quant_data
  owns materialization, refresh, repair, joining, and loader APIs
      |
      v
quant_strategies.runner
  loads rows, calls pure generate_signals, writes smoke artifacts,
  builds internal engine requests
      |
      v
quant_strategies.engine
  deterministic smoke evaluator, not a portfolio validator
      |
      v
quant_autoresearch
  consumes run_config, searches candidates, freezes handoff packages
      |
      v
quant_strategies.validation
  loads generate_decisions, audits data, runs backend/matrix,
  writes recommendation artifacts
      |
      v
manual promotion to tested/
```

## Project Ontology

| Concept / boundary | Responsibility | Required invariant | Current fit |
|---|---|---|---|
| Strategy file | Pure rule code | No engine calls, data loading, loops, or artifact writes | Good |
| Run config | One explicit quick experiment | TOML is validated before strategy/data execution | Good |
| Signal | Fast research output | Cheap dict form, not promotion-grade evidence | Useful but weakly typed |
| Engine request | Smoke evaluator input | Strict model, causal fill lags, no hidden strategy state | Good for smoke |
| Strategy decision | Validation output | Typed instrument, target, exit policy, as-of/decision time | Good model, thin adoption |
| Researched package | Frozen autoresearch handoff | Clearly separates loop score from validation evidence | Weak |
| Validation backend | Economic simulator | Honors semantics or rejects them explicitly | Good fail-closed posture, limited coverage |
| Promotion decision | Human-facing recommendation | Conservative, reproducible, robust, selection-aware | Underbuilt |

Invalid states that must be hard to represent:

- A quick runner artifact implying market validation.
- A validation artifact without code/config/data/backend identity.
- A strategy silently changing evidence because of an unknown TOML parameter.
- An unsupported backend semantic producing optimistic evidence.
- A broad autoresearch loop needing a private runner because the shared runner
  is too slow or artifact-heavy.

## What To Preserve

| Existing code/flow | Evidence | Why preserve it |
|---|---|---|
| Flat strategy files | `untested/`, `tested/`, `researched/.../strategy.py` | Audit-friendly and aligned with repo rules |
| Runner API | `src/quant_strategies/runner/__init__.py:28` | Correct shared entry point for `quant_autoresearch` |
| Data ownership boundary | `runner.data_loader` uses public `quant_data` APIs | Keeps refresh/materialization upstream |
| Pydantic configs/models | runner, engine, decisions, validation configs | Makes boundary failures explicit |
| Internal engine | `engine.evaluation.screen/validate` | Useful deterministic smoke evaluator |
| Typed decisions | `decisions.models.StrategyDecision` | Right validation and future execution boundary |
| Fail-closed VectorBT backend | `validation/vectorbtpro_backend.py:130` | Unsupported semantics should not become approximate passes |
| Runner promotion stance | `RunResult.promotion_eligible=False` | Correctly separates quick runs from promotion evidence |

## Findings

### F0: Core Package Boundaries Are Right-Sized

- **Severity**: Positive finding
- **Action class**: Preserve
- **Evidence**: `runner`, `engine`, `decisions`, and `validation` each own a
  coherent workflow; README documents quick runner and separate validation
  entry points.
- **What is right**: This should remain a modular monolith. Splitting into
  services or a larger platform would add weight before the core evidence
  semantics are trustworthy.
- **Recommendation**: Preserve the package shape and fix contracts/artifacts
  inside it.

### F1: Quick Research And Validation Contracts Can Drift

- **Severity**: High
- **Action class**: Refactor
- **Evidence**:
  - Runner requires `generate_signals(...)` in
    `src/quant_strategies/runner/strategy_loader.py:37`.
  - Validation requires `generate_decisions(...)` in
    `src/quant_strategies/validation/strategy_loader.py:39`.
  - Only one researched strategy file currently exposes `generate_decisions`;
    14 expose `generate_signals`.
  - Rank_03 hand-rolls `generate_decisions` from `generate_signals` in
    `researched/.../rank_03/strategy.py:286`.
- **Risk**: `quant_autoresearch` can optimize one behavior while validation
  tests a hand-translated representation.
- **Root cause**: Missing shared signal-to-decision boundary.
- **Recommendation**: Keep `generate_signals` for quick research. Require
  validation-ready variants to either emit `StrategyDecision` directly or use a
  shared adapter/convention with equivalence tests.
- **Verify**: Contract test every `validation.toml` package for signal/decision
  equivalence or explicit `validation_ready=false`.

### F2: `clear_yes` Is Too Weak For Promotion-Grade Meaning

- **Severity**: Critical
- **Action class**: Retire
- **Evidence**:
  - `run_validation` hard-codes `min_trades = 10` in
    `src/quant_strategies/validation/__init__.py:54`.
  - Policy returns `clear_yes` when required scenarios are completed,
    `trade_count >= min_trades`, and `net_return > 0` in
    `src/quant_strategies/validation/policy.py:92`.
  - CLI returns success for `clear_yes` in `src/quant_strategies/runner/cli.py`.
- **Risk**: The word reads stronger than the math. It does not account for
  drawdown, exposure, turnover, cost margin, regime stability, out-of-sample
  protocol, or `quant_autoresearch` selection pressure.
- **Root cause**: Validation policy is under-modeled relative to the semantics
  of promotion evidence.
- **Recommendation**: Retire any interpretation of `clear_yes` as paper/live
  ready. Rename or add explicit fields such as `advisory_decision`,
  `paper_trade_eligible=false`, `live_eligible=false`, and
  `requires_manual_approval=true` until stronger policy exists.
- **Verify**: Tests assert CLI/artifacts cannot imply paper/live eligibility
  from current policy alone.

### F3: Current Validation Backend Semantics Do Not Clearly Cover The Selected Candidate

- **Severity**: High
- **Action class**: Add
- **Evidence**:
  - VectorBT backend rejects `multi_asset_target_weight` when target-weight
    decisions span more than one symbol in
    `src/quant_strategies/validation/vectorbtpro_backend.py:152`.
  - Rank_03 validation config uses five symbols and `top_n = 5` in
    `researched/.../rank_03/validation.toml:22` and `:35`.
  - The config itself warns that VectorBT v1 may report
    `multi_asset_target_weight`.
- **Risk**: The current selected researched candidate may only reach `maybe`,
  not `clear_yes`, unless generated decisions happen to be single-symbol and
  non-overlapping in every required scenario.
- **Root cause**: Backend capability gap for cross-sectional target-weight
  portfolio semantics.
- **Recommendation**: Keep fail-closed behavior. Add a backend capability table
  and decide whether v1 validation narrows to a single-symbol diagnostic slice
  or implements portfolio-level target weights.
- **Verify**: Run rank_03 validation and inspect `unsupported_semantics`.

### F4: Validation And Researched Artifacts Lack Promotion-Grade Provenance

- **Severity**: High
- **Action class**: Add
- **Evidence**:
  - Runner writes `run_manifest.json` with artifact hashes in
    `src/quant_strategies/runner/artifacts.py:115`.
  - Validation writes config snapshot, strategy snapshot, decision records,
    data audit, backend summary, robustness matrix, and promotion decision in
    `src/quant_strategies/validation/__init__.py:299` and `:314`, but no
    equivalent validation manifest.
  - Rank_03 researched manifest hash is stale: manifest has
    `0bccdc9c...`, while `shasum -a 256` of the strategy file returns
    `8a08aa02...`.
- **Risk**: A promotion recommendation cannot prove exactly which strategy,
  config, rows, backend, and artifacts produced it.
- **Root cause**: Artifact contract gap across validation and researched
  handoff packages.
- **Recommendation**: Add `validation_manifest.json` with git identity,
  package/backend versions, strategy/config hashes, data/row hashes or data
  manifest reference, decision-record hash, backend statuses, and artifact
  hashes. Add researched manifest integrity tests and mark stale hashes as
  validation blockers.
- **Verify**: Tests fail if any researched manifest hash or validation artifact
  hash is stale/missing.

### F5: Mutable Strategy Boundaries Can Break Artifact Truth

- **Severity**: Medium
- **Action class**: Refactor
- **Evidence**:
  - Runner writes input rows, then passes the same `loaded.rows` into strategy
    code and later uses it for readiness and request construction in
    `src/quant_strategies/runner/__init__.py:45`, `:52`, and `:69`.
  - Validation passes `loaded.rows` and `config.params` into strategy generation
    and backend scenarios in `src/quant_strategies/validation/__init__.py:103`
    and `:157`.
- **Risk**: Strategy or backend mutation can make raw input artifacts disagree
  with engine/validation evidence.
- **Root cause**: Mutable lists/dicts cross trust boundaries.
- **Recommendation**: Freeze or deep-copy rows and params at strategy/backend
  boundaries. Give each validation scenario a fresh read-only view.
- **Verify**: Add mutation regression tests for runner and validation.

### F6: Quick Research Performance And Artifact Size Are Already A Real Constraint

- **Severity**: High for `quant_autoresearch`, Medium for manual runs
- **Action class**: Simplify
- **Evidence**:
  - Runner always writes full CSV/JSONL input rows in
    `src/quant_strategies/runner/artifacts.py:38`.
  - Runner writes full `engine_request.json` in
    `src/quant_strategies/runner/__init__.py:76`.
  - Engine and runner decision-time lookup scan linearly in
    `src/quant_strategies/engine/evaluation.py:170` and
    `src/quant_strategies/runner/engine_runner.py:223`.
  - Upstream TODO reports a 46,136-signal FX run with 679M
    `engine_request.json`, 694M CSV, 1.4G JSONL, and CPU-bound linear datetime
    comparisons.
- **Risk**: Autoresearch will bypass `run_config` or artificially over-filter
  strategies to fit the harness.
- **Root cause**: One audit-heavy artifact policy and a clarity-first lookup
  path are used for all run profiles.
- **Recommendation**: Add `artifact_profile = "summary"` for quick screens:
  row counts, hashes, sampled rows, signal summary, and full artifacts only for
  curated reruns or promotion candidates. Pre-index bars by
  `(symbol, timestamp)` once per request.
- **Verify**: Benchmark a representative autoresearch loop and assert runtime
  and artifact-byte limits.

### F7: Observation-Dependency Causality Is Incomplete

- **Severity**: High
- **Action class**: Add
- **Evidence**:
  - Runner readiness checks only the signal symbol/as-of row in
    `src/quant_strategies/runner/data_readiness.py:25`.
  - Validation data audit checks only decision symbol/as-of rows in
    `src/quant_strategies/validation/data_audit.py:50`.
  - Cross-sectional crypto and FX triangle strategies can depend on unselected
    symbols, funding lookbacks, and triangle legs.
  - README says validation data audit is not complete lookahead proof.
- **Risk**: A future, late, or unavailable unselected observation can influence
  a chosen signal without failing readiness.
- **Root cause**: Strategy dependency graph is implicit.
- **Recommendation**: Add explicit `observations`/`dependencies` metadata for
  validation decisions, or add conservative family-specific dependency audits.
  Add future-poison tests for cross-section and FX triangle strategies.
- **Verify**: Perturb rows after each declared `as_of_time` and require
  decisions to remain unchanged for promotion-grade validation.

### F8: Runner Return Labels Are Additive Trade Sums, Not Portfolio Returns

- **Severity**: Critical if used beyond smoke, Medium if kept smoke-only
- **Action class**: Retire
- **Evidence**:
  - Per-trade return is simple return times weight in
    `src/quant_strategies/engine/evaluation.py:60`.
  - Aggregate return fields are sums across trades in
    `src/quant_strategies/engine/evaluation.py:89`.
- **Risk**: `gross_return` and `net_return` can be misread as portfolio NAV
  returns despite ignoring cash, compounding, overlap, leverage, and exposure
  constraints.
- **Root cause**: Metric labels are broader than evaluator semantics.
- **Recommendation**: Retire the portfolio-return interpretation. Add
  `return_model = "sum_weighted_trade_return"` to artifacts/docs, or rename
  fields in a future schema. Keep `promotion_eligible=false` for runner output.
- **Verify**: Add tests for overlapping trades and weights summing above 1.0
  that document the current smoke semantics.

### F9: Funding-Aware Validation Uses A Linear Add-On

- **Severity**: Medium
- **Action class**: Retire
- **Evidence**:
  - VectorBT metrics store `price_cost_return` and then set
    `net_return = price_cost_return + funding_return` in
    `src/quant_strategies/validation/vectorbtpro_backend.py:337`.
- **Risk**: Funding cashflows have timing and compounding effects. A linear
  add-on is a useful diagnostic, not full portfolio accounting.
- **Root cause**: Funding economics are bolted onto portfolio metrics instead
  of modeled as timestamped cashflows.
- **Recommendation**: Retire any reading of this metric as full cashflow
  accounting. Label it as a funding-adjusted approximation until a portfolio
  cashflow model exists.
- **Verify**: If funding contribution is material, classify promotion as
  `maybe` until cashflow modeling is implemented.

### F10: Parameter Perturbation Scenarios Do Not Regenerate Decisions

- **Severity**: Medium
- **Action class**: Refactor
- **Evidence**:
  - Decisions are generated once in
    `src/quant_strategies/validation/__init__.py:103`.
  - Parameter scenarios are added in
    `src/quant_strategies/validation/matrix.py:100`.
  - The same decision list is passed to every backend scenario in
    `src/quant_strategies/validation/__init__.py:157`.
  - README discloses parameter perturbations are diagnostic until regenerated.
- **Risk**: Repricing unchanged decisions can look like parameter robustness.
- **Root cause**: Scenario semantics are not represented in decision
  generation flow.
- **Recommendation**: Regenerate decisions per parameter scenario, or mark
  `decisions_regenerated=false` and exclude parameter scenarios from promotion
  language.
- **Verify**: Robustness artifacts include the regeneration flag and tests cover
  a parameter that changes emitted decisions.

### F11: Validation Exception And Backend Status Contracts Are Too Loose

- **Severity**: Medium
- **Action class**: Refactor
- **Evidence**:
  - `run_validation` catches `BaseException` in several stages in
    `src/quant_strategies/validation/__init__.py:58`.
  - `_raise_interrupt` re-raises only `KeyboardInterrupt` in
    `src/quant_strategies/validation/__init__.py:385`.
  - Tests assert `SystemExit` becomes validation evidence in
    `tests/test_validation_runner.py:375`.
  - `BackendRunResult.status` is plain `str` in
    `src/quant_strategies/validation/backends.py:15`.
- **Risk**: Process-level termination can be mislabeled as strategy evidence,
  and unexpected backend statuses can flow to policy code.
- **Root cause**: Overbroad exception boundary and under-typed backend result
  contract.
- **Recommendation**: Catch expected `Exception` subclasses for strategy,
  config, data, and backend failures; let `SystemExit`, `KeyboardInterrupt`,
  and `GeneratorExit` propagate. Use a `Literal` or enum for backend statuses.
- **Verify**: Tests assert process-level exits propagate and invalid status
  values fail model validation.

### F12: Strategy Parameters Are Untyped At The Strategy Boundary

- **Severity**: Medium
- **Action class**: Add
- **Evidence**:
  - Runner and validation accept `params: dict[str, Any]` in
    `src/quant_strategies/runner/config.py:108` and
    `src/quant_strategies/validation/config.py:80`.
  - Strategies pull defaults with `.get(...)`, for example rank_03 uses
    `.get(...)` across parameters in `researched/.../rank_03/strategy.py:83`.
- **Risk**: A TOML typo can produce a plausible run with default values.
- **Root cause**: Missing per-strategy parameter contract.
- **Recommendation**: Add lightweight `validate_params(params)` or
  `PARAM_SCHEMA` convention. Require it for validation-ready researched
  variants and optionally warn in quick runs.
- **Verify**: Unknown-parameter tests for researched validation configs.

### F13: Handoff And Folder Semantics Still Invite Misreading

- **Severity**: Medium
- **Action class**: Retire
- **Evidence**:
  - Researched evidence files contain `passed_validation`,
    `eligible_for_promotion`, and `promotion_decision` even though the same
    artifact says it is loop feedback only.
  - README says `tested/` contains strategies that passed separate validation,
    while `tested/simple_momentum.py` says it is an internal runner smoke
    strategy.
- **Risk**: Humans or automation can treat autoresearch loop feedback or a
  smoke fixture as market validation.
- **Root cause**: Cross-repo artifact vocabulary and folder semantics are not
  normalized.
- **Recommendation**: Wrap imported autoresearch fields under
  `autoresearch_loop_feedback`; reserve `promotion_decision` for local
  validation. Move the smoke fixture out of `tested/`, or document it as an
  explicit exception.
- **Verify**: Manifest contract tests distinguish `runner_only`,
  `validation_ready`, and `validated_for_testing`.

### F14: Result Directory Creation Has A Small Race

- **Severity**: Low
- **Action class**: Simplify
- **Evidence**:
  - Runner and validation use check-then-create loops in
    `src/quant_strategies/runner/artifacts.py:19` and
    `src/quant_strategies/validation/artifacts.py:12`.
- **Risk**: Parallel same-second runs can collide.
- **Root cause**: Non-atomic allocation loop.
- **Recommendation**: Catch `FileExistsError` around `mkdir` and retry, or add
  an atomic unique suffix.
- **Verify**: Parallel allocation test with fixed timestamp.

## Unknown Unknowns And Assumption Risks

| Assumption | Why it may be wrong | De-risking check |
|---|---|---|
| `quant_autoresearch` will use only `run_config` | Runner may stay too slow and push it to a private harness | Cross-repo contract test and quick-run benchmark |
| `quant_data` provides exact availability semantics | Upstream FX note names quote availability as approximate | Loader/API contract tests for `available_at`, quote timestamps, and data revision semantics |
| VectorBT metrics match policy expectations | Current adapter extracts limited metrics and approximates funding | One-trade integration tests tracing price, fee, slippage, funding, and return math |
| Rank_03 actually emits multi-asset target weights in validation | Source strongly suggests it, but only live rows decide emitted decisions | Run validation and inspect `unsupported_semantics` |
| Frozen researched packages are immutable | Stale manifest hash proves drift already happened | Hash tests and import-time manifest status |

## Overbuilt / Underbuilt / Right-Sized

- **Overbuilt**: The core package is not materially overbuilt. The heavy surface
  is copied `researched/` variants, generated evidence, and long historical
  design docs. Treat those as handoff/history, not active architecture.
- **Underbuilt**: Validation policy, validation provenance, quick-run artifact
  profiles, hot-path indexing, strategy parameter contracts, observation
  dependencies, and cross-repo artifact semantics.
- **Right-sized**: Flat strategy files, explicit TOML configs, Pydantic boundary
  models, `run_config`, smoke engine, typed decisions, fail-closed backend
  semantics, and runner `promotion_eligible=false`.

## Missing Docs, PRD, ADR, Or Decision Records

- **Foundation contract**: lifecycle terms for `untested`, `researched`,
  `tested`, paper, and live; what each artifact can and cannot prove.
- **ADR**: runner smoke evidence vs validation evidence vs promotion decision.
- **ADR**: validation backend supported semantics and capability matrix.
- **Decision record**: whether `clear_yes` can exist before richer validation
  statistics and selection-pressure adjustment.
- **Performance contract**: quick-run limits for runtime, signal count, and
  artifact bytes by artifact profile.
- **Docs cleanup**: clarify or move `tested/simple_momentum.py`.

## Preserve / Refactor / Simplify / Add / Retire

| Action class | Findings / recommendations | Rationale |
|---|---|---|
| Preserve | F0; flat strategy files; `run_config`; Pydantic configs/models; smoke engine; typed decisions; fail-closed backend behavior | These are right-sized boundaries |
| Refactor | F1 signal/decision bridge; F5 immutable boundary; F10 parameter scenario flow; F11 exception/status contracts | Keep capabilities but put the contract in the right place |
| Simplify | F6 quick artifact profile and indexed lookup; F14 atomic directory allocation | Reduce weight and avoid duplicate/private harness pressure |
| Add | F3 backend capability/portfolio semantics; F4 validation manifest; F7 dependency metadata/tests; F12 param schema | Missing evidence and contract pieces needed for trust |
| Retire | F2 deployable meaning of `clear_yes`; F8 portfolio-return reading of runner metrics; F9 full-cashflow reading of linear funding add-on; F13 misleading handoff/folder language | These names/interpretations create false confidence |

## Prioritized Recommendations

| Priority | Action class | Recommendation | Why now | Verify |
|---|---|---|---|---|
| P1 | Retire | Stop letting `clear_yes` imply paper/live readiness; add explicit eligibility fields | Prevent false promotion evidence | CLI/artifact tests |
| P1 | Add | Add `validation_manifest.json` and researched manifest integrity tests | Promotion evidence must be reproducible | Hash contract tests |
| P1 | Refactor | Add shared signal-to-decision adapter/convention for validation-ready variants | Prevent quick/validation drift | Equivalence tests |
| P1 | Add | Decide and document validation backend support for cross-sectional target weights | Current selected candidate may be unsupported | Rank_03 validation run |
| P1 | Retire | Label runner returns as summed weighted trade returns | Avoid portfolio-return false positives | Return-model tests/docs |
| P2 | Simplify | Add `artifact_profile = "summary"` and quick-run benchmark | Keep autoresearch on shared runner | Runtime/artifact-size benchmark |
| P2 | Simplify | Pre-index bars by `(symbol, timestamp)` | Fix named FX bottleneck | Large-signal benchmark |
| P2 | Refactor | Freeze/copy rows and params at strategy/backend boundaries | Preserve artifact truth | Mutation regression tests |
| P2 | Add | Add observation dependency metadata or causal replay tests | Reduce hidden lookahead risk | Future-poison tests |
| P2 | Refactor | Regenerate decisions for parameter scenarios or mark diagnostic-only | Avoid fake robustness | Robustness artifact tests |
| P2 | Add | Add per-strategy parameter validation for researched validation configs | Avoid TOML typo evidence | Unknown-param tests |
| P2 | Refactor | Narrow validation exception/status contracts | Avoid process exits as evidence | SystemExit/status tests |
| P3 | Simplify | Make result directory allocation atomic | Remove small race | Parallel allocation test |
| P3 | Refactor | Extract shared data-loading boundary only if runner/validation diverge | Avoid premature abstraction | No action until duplicated reasons appear |

## NOT In Scope

- Full live-trading architecture, broker routing, OMS, risk manager, kill
  switches, idempotency, position ledger, or execution reports.
- Full portfolio optimizer, market impact, capacity, borrow, margin, options,
  or liquidation modeling.
- Declaring any current strategy paper/live ready.
- Splitting the repo into services.
- Adding advanced statistical machinery before causality, provenance, return
  semantics, and contract drift are corrected.

## Verification Summary

- **Verified in this consolidation**:
  - Both review docs were read and compared.
  - Source spot-checks for runner artifacts, validation artifacts, policy,
    exception handling, backend status, VectorBT unsupported semantics, funding
    adjustment, engine return aggregation, data audit/readiness, and strategy
    loaders.
  - Rank_03 researched strategy hash mismatch against `manifest.json`.
  - Only one researched strategy file exposes `generate_decisions`; 14 expose
    `generate_signals`.
  - Upstream FX limitation with 46,136 signals and multi-GB artifacts.
  - Full test suite passed with `conda run -n quant pytest -q`:
    `302 passed in 28.26s`.
  - CodeGraph index was healthy with 58 indexed files and 1,031 nodes.
- **Not verified**:
  - Live `quant_data` loads.
  - Real VectorBT PRO validation run for rank_03.
  - Full `quant_autoresearch` code behavior beyond the named TODO file.
  - New runtime benchmark for broad FX/crypto loops.
- **Residual risk**: The biggest remaining uncertainty is whether rank_03
  validation actually emits multi-asset target-weight decisions on live data.
  The source strongly suggests a capability mismatch, but the final verdict
  should be updated after an end-to-end validation run.
