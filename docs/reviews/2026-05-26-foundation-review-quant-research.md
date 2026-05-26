# Foundation Review: quant_strategies

Date: 2026-05-26
Reviewer: Codex, senior quantitative research / software foundation review
Target: `/Users/Season_Yang/Personal/quant_strategies`

## Review Objective

I reviewed `quant_strategies` to determine whether it is a solid foundation for
a research-to-validation lifecycle: pure strategy files, explicit configured
runs through `quant_strategies.runner`, internal smoke evaluation,
`quant_autoresearch` consumption, and sufficient validation to decide which
candidates deserve Season-approved paper/live-trading follow-up.

This review is not asking whether the repo is a complete backtesting or trading
platform. It asks whether the current foundation makes the right things easy
and the dangerous things hard: reproducible quick research, clear contracts,
causal data use, honest artifact semantics, math-safe metrics, and conservative
promotion decisions.

### Clarified Scope

- **In scope**: `src/quant_strategies/{runner,engine,decisions,validation}`,
  `untested/`, `tested/`, `researched/`, `runs/`, tests, README, design docs,
  and `/Users/Season_Yang/Personal/quant_autoresearch/UPSTREAM_LIMITATIONS_TODO.md`.
- **Out of scope**: implementing fixes, live broker integration, full production
  portfolio management, and any claim that a strategy is ready for paper/live
  trading.
- **Explicit exclusion**: I did not read
  `docs/reviews/2026-05-26-foundation-review.md`.
- **Additional concerns from Season**: whether the project is too heavy,
  whether quick research and validation contracts are inconsistent, and whether
  quick research can stay performant enough for `quant_autoresearch`.
- **Assumptions**: `quant_autoresearch` is a high-frequency consumer of
  `run_config` and a producer of frozen `researched/` packages. `tested/`
  should mean Season-approved after separate validation, not runner smoke pass.

## Executive Verdict

`quant_strategies` is a good small-runner foundation, but it is not yet a
trustworthy promotion-grade validation foundation. The core package layout is
not too heavy: runner, engine, decisions, and validation each map to real
workflow boundaries. The main risks are semantic and quantitative: quick
research emits dict signals while validation requires typed decisions; copied
`quant_autoresearch` artifacts use promotion/validation language before local
validation can actually clear most variants; `clear_yes` is under-specified;
and the quick-research path writes and scans too much for large autoresearch
loops. The next work should not be a broad rewrite. It should tighten contracts,
artifact semantics, validation policy, and hot-path performance.

## Scope And Evidence Inspected

- **Repo instructions**: `AGENTS.md`, including strategy purity, flat strategy
  files, runner ownership, `quant_data` dependency boundary, and validation
  promotion discipline.
- **Manifests and structure**: `pyproject.toml`, `.gitignore`, CodeGraph file
  map, `runs/`, `src/`, `tests/`, `untested/`, `tested/`, and `researched/`.
- **Core source**:
  - `src/quant_strategies/runner/*`
  - `src/quant_strategies/engine/*`
  - `src/quant_strategies/decisions/*`
  - `src/quant_strategies/validation/*`
  - `untested/*.py`
  - one selected researched variant with `validation.toml`
- **Tests**: focused runner, engine, validation, data audit, matrix, decision,
  and researched-contract tests.
- **Docs treated as claims**: `README.md` and the `docs/superpowers/*` design
  and implementation-plan documents.
- **Cross-repo context inspected**:
  `/Users/Season_Yang/Personal/quant_autoresearch/UPSTREAM_LIMITATIONS_TODO.md`.
- **Not inspected**: live `quant_data` database state, real VectorBT PRO
  behavior beyond existing tests, the rest of `quant_autoresearch`, and the
  forbidden prior review file.

## Intended Foundation Model

The project has five real lifecycle states:

```text
raw idea
  -> untested/*.py
  -> quick configured runner screen
  -> quant_autoresearch campaign and handoff
  -> researched/<package>/<variant>
  -> validation gate with typed decisions and backend economics
  -> Season-approved move to tested/
  -> separate paper/live workflow
```

The minimal correct foundation should express these boundaries:

```text
quant_data
  owns data materialization, refresh, joins, and public loaders
      |
      v
quant_strategies.runner
  loads data, calls pure generate_signals, writes smoke artifacts,
  builds internal engine requests
      |
      v
quant_strategies.engine
  deterministic smoke evaluator, not a portfolio validator
      |
      v
quant_autoresearch
  consumes runner API, searches candidates, freezes handoff packages
      |
      v
quant_strategies.validation
  typed generate_decisions, data audit, backend economics, matrix,
  hard_no/maybe/clear_yes recommendation
      |
      v
manual promotion to tested/
```

### Project Ontology

| Concept / boundary | Responsibility | Key contracts or invariants | Current-code fit |
|---|---|---|---|
| Strategy file | Pure rule code | No data loading, engine calls, loops, or artifact writes | Good in runner path; validation adds a second callable contract |
| Run config | One explicit quick experiment | Stable TOML, strategy path, data, fill, cost, output mode | Good for small runs |
| Strategy signal | Quick research output | Dict with symbol, decision time, side, weight, hold/exit controls, metadata | Useful but weakly typed |
| Engine request | Smoke evaluator input | Pydantic `Bar`/`Signal`; causal fill lags; no hidden metadata | Good, but returns are additive trade sums |
| Strategy decision | Validation output | Typed instrument, target exposure, sizing, exit policy, as-of/decision time | Good model, thin adoption |
| Researched package | Frozen autoresearch handoff | Clear distinction between loop score and validation eligibility | Weak: copied artifacts still use promotion language |
| Validation backend | Economic simulation | Either honor semantics or reject them explicitly | Good fail-closed posture, limited supported semantics |
| Promotion decision | Pre-paper/live recommendation | Conservative, reproducible, robust, selection-pressure-aware | Underbuilt |

Required invariants:

- A quick-run artifact must never imply market validation or promotion.
- A validation artifact must be reproducible from frozen strategy/config/data
  identity and backend version.
- A strategy must not be able to silently change economics through unknown or
  mistyped parameters.
- Unsupported semantics must become `maybe` or `hard_no`, not approximated
  evidence.
- Quick research must remain fast enough that `quant_autoresearch` has no reason
  to bypass the shared runner.

## What Already Exists And Should Be Reused

| Existing code/flow | What it does | Reuse / concern |
|---|---|---|
| `src/quant_strategies/runner/config.py` | Pydantic TOML config with repo-confined paths | Reuse; add artifact/performance policy rather than replacing |
| `src/quant_strategies/runner/__init__.py` | Single `run_config` API for quick experiments | Reuse; this is the right integration point for `quant_autoresearch` |
| `src/quant_strategies/engine/models.py` | Strict Pydantic engine models | Reuse for smoke semantics |
| `src/quant_strategies/engine/evaluation.py` | Deterministic per-signal screen and simple gates | Reuse only as smoke evidence |
| `src/quant_strategies/decisions/models.py` | Typed validation decision contract | Reuse and make it the promotion boundary |
| `src/quant_strategies/validation/*` | First validation gate with backend adapters and matrix | Reuse; make policy/provenance/semantics stronger |
| `tests/` | 302 passing tests across contracts and math-heavy paths | Preserve; add targeted failure-mode tests |

## Architecture And Boundary Review

### Finding A1: Validation cannot clear the current cross-sectional candidate

- **Severity**: High
- **Evidence**:
  - `src/quant_strategies/validation/vectorbtpro_backend.py:152` rejects
    multi-asset target-weight semantics.
  - `researched/.../rank_03/validation.toml:22` uses five symbols.
  - `researched/.../rank_03/validation.toml:35` sets `top_n = 5`.
  - `src/quant_strategies/validation/policy.py:84` classifies unsupported
    semantics as `maybe`.
- **What is wrong or risky**: The only locally validatable researched variant is
  likely unable to reach `clear_yes` unless generated decisions happen to be
  single-asset in each required scenario. The config itself comments that
  VectorBT v1 may report `multi_asset_target_weight`.
- **First-principles reason it matters**: A validation gate must be able to
  faithfully test the actual economic object being promoted. If the selected
  candidate is cross-sectional, a single-symbol non-overlapping backend is not
  the right validator.
- **Root cause**: Validation backend semantics are narrower than the candidate
  ontology.
- **Recommendation**: Keep unsupported results fail-closed, but choose one root
  path: either narrow the candidate to a single-symbol/non-overlapping validation
  slice for v1, or implement explicit portfolio-level target-weight semantics.
- **Tradeoff**: Narrowing is faster but tests a different strategy. Portfolio
  target weights take more work but align the validator with the research
  object.
- **Verify**: Run `quant-strategies validate` on rank_03 and confirm whether the
  backend returns `unsupported_semantics = ["multi_asset_target_weight"]`.

### Finding A2: Quick research and validation contracts are split without a shared adapter contract

- **Severity**: High
- **Evidence**:
  - Runner requires `generate_signals(...)` in
    `src/quant_strategies/runner/strategy_loader.py:37`.
  - Validation requires `generate_decisions(...)` in
    `src/quant_strategies/validation/strategy_loader.py:39`.
  - Runner maps raw signal dicts in
    `src/quant_strategies/runner/engine_runner.py:141`.
  - The selected researched strategy hand-rolls signal-to-decision conversion in
    `researched/.../rank_03/strategy.py:286`.
  - Only one researched strategy file exposes `generate_decisions`; most expose
    only `generate_signals`.
- **What is wrong or risky**: Two callable contracts are justified by lifecycle
  stage, but today the bridge is manual and per-strategy. Drift can make quick
  research evidence and validation decisions disagree.
- **First-principles reason it matters**: The same economic intent should have
  one promotion-grade representation. Dict signals are acceptable for speed, but
  promotion should not depend on copy-pasted translation logic.
- **Root cause**: Missing shared conversion boundary between quick signal dicts
  and typed validation decisions.
- **Recommendation**: Add a small public adapter or convention, for example
  `signals_to_decisions(strategy_id, signals, instrument_kind)` or a required
  per-strategy `signal_to_decision` helper with contract tests. Require every
  validatable researched variant to declare whether it is `runner_only`,
  `validation_ready`, or `unsupported_semantics`.
- **Tradeoff**: Slightly more structure in strategy files, but less hidden drift.
- **Verify**: Add a contract test that every `validation.toml` strategy maps
  `generate_signals` and `generate_decisions` consistently.

### Finding A3: The project is not too heavy at the core, but `researched/` is heavy as a working set

- **Severity**: Medium
- **Evidence**:
  - Core `src/quant_strategies` is split into coherent packages:
    runner, engine, decisions, validation.
  - `researched/crypto_perp_funding_crowding_reversal` has 106 files.
  - Python line count is 14,163 across source/strategy files; researched
    strategy clones account for most of that surface.
- **What is wrong or risky**: The package architecture is not overbuilt. The
  weight comes from frozen generated handoff variants, repeated large strategy
  files, evidence JSON, and plan docs. That can slow onboarding and review if
  not clearly separated from active source.
- **Root cause**: Artifact/package lifecycle boundary, not code architecture.
- **Recommendation**: Keep `researched/` as frozen handoff data, but add a
  manifest-level index naming validatable variants, runner-only variants, and
  authoritative evidence. Avoid treating every copied variant as active source.
- **Tradeoff**: More manifest discipline, less browsing ambiguity.
- **Verify**: A new engineer should be able to identify the one validatable
  rank_03 variant without recursively inspecting every `strategy.py`.

### Finding A4: Validation depends on runner internals, but this is currently acceptable

- **Severity**: Low
- **Evidence**:
  - `src/quant_strategies/validation/__init__.py:10` imports runner data loader.
  - `src/quant_strategies/validation/config.py:103` materializes `RunConfig` per
    validation window.
  - `src/quant_strategies/validation/__init__.py:87` loads rows through the
    runner data path.
- **What is wrong or risky**: If runner smoke behavior churns, validation may
  inherit changes that should not affect promotion evaluation.
- **Root cause**: Shared data-loading boundary is embedded in runner package.
- **Recommendation**: Do not refactor now. If validation and runner diverge,
  extract a shared `data` boundary with `load_rows(config)` and keep runner and
  validation as consumers.
- **Tradeoff**: Deferring avoids premature architecture.

## Engineering, Testability, And Operability Review

### Finding E1: Validation artifacts lack runner-grade provenance

- **Severity**: High
- **Evidence**:
  - Runner writes `run_manifest.json` with git identity, package versions, engine
    schema, artifact hashes in `src/quant_strategies/runner/artifacts.py:115`.
  - Validation writes static artifacts and summaries in
    `src/quant_strategies/validation/__init__.py:299`, but no equivalent
    validation manifest with git/backend/data/artifact hashes.
- **Why it matters**: A promotion recommendation is less useful than a smoke run
  if it cannot prove exactly which code, backend version, rows, and decisions
  produced it.
- **Root cause**: Artifact contract gap.
- **Recommendation**: Add `validation_manifest.json` with git identity,
  `quant-strategies`, `quant-data`, `pydantic`, `vectorbtpro` when present,
  strategy/config hashes, decision-record hash, row/data hash or data manifest,
  backend names/statuses, and artifact hashes.
- **Verify**: Validation tests should assert manifest existence and hash coverage
  for success and failure paths.

### Finding E2: Quick research has no performance contract and writes too much before expensive evaluation

- **Severity**: High for `quant_autoresearch`, Medium for manual use
- **Evidence**:
  - `run_config` always writes full `strategy_input_rows.csv/jsonl` before
    engine request/evaluation in `src/quant_strategies/runner/__init__.py:45`.
  - `write_strategy_input_rows` writes both CSV and JSONL in
    `src/quant_strategies/runner/artifacts.py:38`.
  - `request_json` serializes the full engine request in
    `src/quant_strategies/runner/engine_runner.py:107`.
  - Runner manifest hashes all artifacts and shells out to git status/diff in
    `src/quant_strategies/runner/artifacts.py:249`.
  - The upstream TODO reports a 46,136-signal FX run producing a 679M
    `engine_request.json`, 694M input CSV, and 1.4G input JSONL before the CPU
    bound engine loop.
- **Why it matters**: If `quant_autoresearch` needs 100-attempt loops, an
  audit-perfect artifact profile can make the shared runner too slow, pushing
  automation back toward a private harness.
- **Root cause**: One artifact policy for both curated audit runs and fast
  research screens.
- **Recommendation**: Add an explicit fast profile, probably config-driven:
  `artifact_profile = "summary"` for quick screens, with row counts, hashes,
  sampled rows, signals summary, and optional full dump on failure or promotion
  candidate. Keep full artifacts for validation and curated reproductions.
- **Tradeoff**: Summary artifacts are less inspectable, so promotion must rerun
  with full artifacts.
- **Verify**: Benchmark a representative `quant_autoresearch` loop and assert
  max runtime and max artifact bytes for quick mode.

### Finding E3: Engine timestamp lookup is linear in a hot path

- **Severity**: Medium
- **Evidence**:
  - Engine `_decision_index` loops over bars in
    `src/quant_strategies/engine/evaluation.py:170`.
  - Runner `_decision_index` loops similarly in
    `src/quant_strategies/runner/engine_runner.py:223`.
  - The upstream TODO identifies Python datetime comparisons inside linear
    decision-time lookup as the CPU-bound FX bottleneck.
- **Why it matters**: Broad intraday FX and high-signal crypto screens need
  `(symbol, decision_time) -> index` lookup, not per-signal scans.
- **Root cause**: Smoke evaluator optimized for clarity before scale.
- **Recommendation**: Pre-index bars by symbol and timestamp once per request.
  Reuse that index for fillability checks and evaluation. Skip funding scans for
  non-funding data.
- **Tradeoff**: Slightly more engine setup state, but no conceptual expansion.
- **Verify**: Add a synthetic benchmark with tens of thousands of signals and
  assert asymptotic improvement.

### Finding E4: Validation catches `BaseException` and converts `SystemExit` into evidence

- **Severity**: Medium
- **Evidence**:
  - `run_validation` catches `BaseException` in multiple stages starting at
    `src/quant_strategies/validation/__init__.py:58`.
  - `_raise_interrupt` only re-raises `KeyboardInterrupt` in
    `src/quant_strategies/validation/__init__.py:385`.
  - Tests assert `SystemExit` becomes `hard_no` in
    `tests/test_validation_runner.py:375`.
- **Why it matters**: Automation should not convert process-level termination
  into strategy evidence. `SystemExit`, `KeyboardInterrupt`, and `GeneratorExit`
  are not normal strategy failures.
- **Root cause**: Overbroad exception boundary.
- **Recommendation**: Catch `Exception` for strategy/backend failures and let
  process-level exceptions propagate. Preserve failure artifacts for ordinary
  exceptions.
- **Tradeoff**: Some abrupt exits will not write validation artifacts, but that
  is better than mislabeling operational termination as strategy evidence.

### Finding E5: Strategy params are untyped and unknown keys can silently change evidence

- **Severity**: Medium
- **Evidence**:
  - Runner and validation accept `params: dict[str, Any]` in
    `src/quant_strategies/runner/config.py:108` and
    `src/quant_strategies/validation/config.py:80`.
  - Strategies pull defaults with `.get(...)`, for example
    `untested/crypto_perp_funding_crowding_reversal.py:54` and
    `researched/.../rank_03/strategy.py:83`.
- **Why it matters**: A TOML typo can produce a plausible run with default
  values. That is tolerable for casual exploration, not for validation.
- **Root cause**: Missing per-strategy parameter contract.
- **Recommendation**: Keep flat strategy files, but add a lightweight
  `validate_params(params)` or `PARAM_SCHEMA` convention. Require it for
  `researched/` validation configs and optionally warn in quick runs.
- **Tradeoff**: More boilerplate per strategy, less silent evidence drift.

## Domain-Specific Lens Findings: Quant Research And Math

### Finding Q1: `clear_yes` is mathematically too weak for promotion-grade evidence

- **Severity**: Critical
- **Evidence**:
  - Validation policy checks finite `net_return`, integer `trade_count`,
    `trade_count >= min_trades`, and `net_return > 0` in
    `src/quant_strategies/validation/policy.py:92`.
  - `min_trades = 10` is hard-coded in
    `src/quant_strategies/validation/__init__.py:54`.
  - VectorBT backend metrics expose only `net_return` and `trade_count` in
    `src/quant_strategies/validation/vectorbtpro_backend.py:301`.
- **Domain risk**: For selected strategies from a 100-attempt autoresearch
  process, positive net return and trade count do not account for selection
  pressure, volatility, drawdown, turnover, skew, regime stability, or
  multiple-hypothesis testing.
- **Root cause**: Promotion policy under-modeled relative to quant research
  evidence requirements.
- **Recommendation**: Until richer stats exist, rename or downgrade `clear_yes`
  to a non-promotional label, or gate `clear_yes` behind configured validation
  statistics: return, drawdown, Sharpe/t-stat, window stability, stress
  degradation, and selection-pressure provenance. Later add PSR/DSR/PBO/CPCV or
  a simpler explicit multiple-testing haircut.
- **Tradeoff**: Fewer false positives, more work before any strategy reaches
  `tested/`.

### Finding Q2: Runner engine returns are additive trade sums, not portfolio returns

- **Severity**: Critical if used beyond smoke, Medium if kept smoke-only
- **Evidence**:
  - Per-trade gross return is simple return times weight in
    `src/quant_strategies/engine/evaluation.py:60`.
  - Aggregate gross/funding/cost/net values are sums across trades in
    `src/quant_strategies/engine/evaluation.py:89`.
- **Domain risk**: Sums of weighted simple trade returns ignore cash,
  compounding, overlapping exposure, leverage, margin, and portfolio constraints.
  They are useful smoke metrics, not investment returns.
- **Root cause**: Metric labels are broader than evaluator semantics.
- **Recommendation**: Keep the simple engine, but rename fields in future schema
  or documentation to `sum_weighted_trade_return` semantics. Continue preventing
  `promotion_eligible` from ever being true in runner summaries.
- **Tradeoff**: Renaming is a schema change; documentation is the short-term
  mitigation.

### Finding Q3: Funding-aware validation adds funding linearly to portfolio return

- **Severity**: Important
- **Evidence**:
  - `src/quant_strategies/validation/vectorbtpro_backend.py:337` stores
    VectorBT `net_return` as `price_cost_return`.
  - `src/quant_strategies/validation/vectorbtpro_backend.py:342` sets
    `net_return = price_cost_return + funding_return`.
- **Domain risk**: Funding cashflows have timing and compounding effects. A
  linear add-on may be acceptable for a small v1 diagnostic, but it is not a
  full portfolio cashflow model.
- **Root cause**: Funding economics are bolted onto backend metrics instead of
  modeled as timestamped cashflows in the portfolio path.
- **Recommendation**: Label this as funding-adjusted approximation until modeled
  in portfolio cashflows, or classify funding-aware promotion as `maybe` when
  funding contribution is material.
- **Tradeoff**: Conservative semantics may block crypto perp candidates sooner,
  but reduces false precision.

### Finding Q4: Lookahead cannot be fully enforced while strategies receive the full window

- **Severity**: Important
- **Evidence**:
  - Runner passes all loaded rows to `generate_signals` in
    `src/quant_strategies/runner/__init__.py:52`.
  - Validation passes all loaded rows to `generate_decisions` in
    `src/quant_strategies/validation/__init__.py:103`.
  - Readiness/audit checks only declared `as_of_time` rows and `available_at` in
    `src/quant_strategies/runner/data_readiness.py:29` and
    `src/quant_strategies/validation/data_audit.py:50`.
  - README explicitly says data audit is not full lookahead proof at
    `README.md:96`.
- **Domain risk**: A malicious or accidentally future-peeking strategy can emit
  causal-looking timestamps after inspecting future rows.
- **Root cause**: Batch strategy API without causal replay or instrumented data
  access.
- **Recommendation**: Do not pretend this is solved. Add a malicious-lookahead
  regression test to document the current limitation, then decide whether
  validation needs causal replay for promotion-grade checks.
- **Tradeoff**: Causal replay can be slower, so reserve it for validation or
  promotion candidates.

### Finding Q5: Parameter perturbation scenarios do not regenerate decisions

- **Severity**: Important
- **Evidence**:
  - Decisions are generated once before matrix expansion in
    `src/quant_strategies/validation/__init__.py:103`.
  - Parameter perturbations are added in
    `src/quant_strategies/validation/matrix.py:100`.
  - The same decisions are passed to each backend run in
    `src/quant_strategies/validation/__init__.py:155`.
  - README discloses this limitation at `README.md:80`.
- **Domain risk**: Parameter sensitivity evidence is mostly a no-op if the
  strategy decisions were produced from base params.
- **Root cause**: Matrix scenario semantics are not fully represented in the
  execution flow.
- **Recommendation**: Either regenerate decisions per parameter scenario or add
  machine-readable `decisions_regenerated = false` / `diagnostic_only = true` to
  robustness artifacts and exclude them from any promotion language.
- **Tradeoff**: Regeneration is more expensive but mathematically meaningful.

### Finding Q6: Autoresearch handoff artifacts use promotion words for screening evidence

- **Severity**: Important
- **Evidence**:
  - `researched/.../rank_03/evidence/promotion_score.json:14` says
    "Loop feedback only. Not market evidence."
  - The same file has `passed_validation: true` at line 15 and
    `eligible_for_promotion: true` at line 28.
  - `promotion_decision: "promote"` appears at line 34.
- **Domain risk**: Machine readers and future humans can treat loop feedback as
  local validation evidence, especially because the filenames themselves say
  `promotion_*`.
- **Root cause**: Cross-repo artifact semantics are not normalized at handoff.
- **Recommendation**: On import into `researched/`, wrap or rewrite these fields
  under `autoresearch_loop_feedback`, or add a local manifest that explicitly
  declares them non-validation artifacts. Reserve `promotion_decision` for
  `quant_strategies.validation`.
- **Tradeoff**: Historical artifacts remain intact but become safer to consume.

## Unknown Unknowns And Assumption Risks

| Assumption | Why it may be wrong | How to test or de-risk |
|---|---|---|
| `quant_autoresearch` will consume only `run_config` | The runner may be too slow and push it back to a private harness | Add a cross-repo contract test and performance benchmark |
| `quant_data` exposes all needed availability fields | FX quote exact availability is named as approximate in upstream TODO | Add fill-availability tests using `available_at`, quote timestamps, and strict FX quotes |
| VectorBT PRO metrics mean what policy expects | Current adapter extracts only total return and trade count | Add backend integration tests that trace one trade and compare return/cost/funding math |
| `clear_yes` is only advisory | CLI returns exit code `0`, so automation may treat it as approval | Rename outcome or add explicit `paper_trade_eligible = false` until manual approval |
| Frozen `researched/` packages are read-only | Future edits may accidentally mutate handoff evidence | Add manifest hashes and validation-ready status per variant |

## Overbuilt / Underbuilt / Right-Sized Areas

- **Overbuilt**: The core package is not materially overbuilt. The heavy part is
  copied `researched/` variants and long implementation-plan docs, which should
  be treated as frozen handoff/history rather than active architecture.
- **Underbuilt**: Promotion policy, validation provenance, quick-run performance
  controls, parameter contracts, and cross-repo artifact semantics.
- **Right-sized**: Flat strategy files, Pydantic boundary models, explicit TOML
  configs, repo-confined paths, fail-closed backend unsupported semantics,
  runner `promotion_eligible = false`, and focused synthetic tests.

## Missing Docs, PRD, ADR, Or Decision Records

- **Missing ADR**: "Runner smoke evidence vs validation evidence vs promotion
  decision." README documents the distinction, but an ADR should lock the terms
  `screened`, `smoke_passed`, `hard_no`, `maybe`, `clear_yes`, `tested`, and
  `paper/live eligible`.
- **Missing ADR**: "Validation backend supported semantics." The current code
  rejects multi-asset target weights, threshold exits, and overlapping windows.
  This should be a durable capability table.
- **Missing decision record**: Whether `clear_yes` is allowed before
  PSR/DSR/PBO/CPCV-style selection-pressure adjustment. If not, rename it now.
- **Missing performance contract**: Quick research should have explicit limits
  for runtime, artifact bytes, and max signal count per run profile.
- **Stale/ambiguous docs**: README says `tested/` contains strategies that passed
  validation, while `tested/simple_momentum.py` is a smoke fixture. Rename the
  fixture location or document that `tested/simple_momentum.py` is an exception.

## Preserve / Refactor / Add / Retire

This is the practical change taxonomy. It separates what should stay stable
from what should be changed, added, or retired so the project does not grow by
accumulating parallel contracts.

### Preserve

| Area | Keep | Reason |
|---|---|---|
| Strategy layout | Flat one-file strategy modules with thesis, observables, rule, and falsifier in the docstring | This is audit-friendly and keeps strategy logic inspectable |
| Runner boundary | `quant_strategies.runner.run_config` as the shared quick-research entry point | `quant_autoresearch` should not own a parallel runner harness |
| Configs | Explicit TOML run configs under `runs/` | They make experiments repeatable and reviewable |
| Boundary types | Pydantic models for external/system contracts | Invalid run specs and validation policies should fail before producing evidence |
| Backend safety | Fail-closed unsupported backend semantics | Unsupported weights, exits, or overlapping windows should not become optimistic evidence |
| Evidence stance | Runner artifacts remain `promotion_eligible = false` | Fast screening and promotion validation need separate meanings |

### Refactor

| Area | Refactor to | Reason |
|---|---|---|
| Quick-research vs validation contracts | A shared signal-to-decision adapter or one typed decision convention for strategies that are validation-ready | Current hand-rolled bridges make screening and validation drift |
| Engine bar lookup | Pre-index bars by `(symbol, timestamp)` before replay | The upstream FX run exposed CPU-bound linear timestamp lookup |
| Validation exception boundaries | Catch expected backend/config/data exceptions, not broad process-level failures | Validation should fail loudly on interrupts, memory failures, and programmer errors |
| Researched package metadata | A local manifest with `runner_only`, `validation_ready`, source hashes, and artifact class | Frozen handoff packages need machine-readable status |
| Parameter diagnostics | Regenerate decisions per perturbed parameter set, or mark `decisions_regenerated = false` | Repricing unchanged decisions can falsely look like parameter robustness |

### Add

| Area | Add | Reason |
|---|---|---|
| Validation provenance | `validation_manifest.json` with git SHA, package/version, backend, config, data window, data hashes, and artifact hashes | Promotion evidence must be reproducible |
| Policy semantics | Explicit fields for advisory result, paper-trade eligibility, live eligibility, and required manual review | `clear_yes` should not silently mean deployable |
| Quick-run performance | `artifact_profile = "summary"` plus benchmark limits for runtime, signal count, and artifact bytes | Shared runner usage must stay cheap enough for autoresearch loops |
| Strategy parameters | Per-strategy allowed-parameter validation | TOML typos should not create false evidence |
| Causality tests | Replay tests that detect future-window access for promotion-grade validation | Strategies currently receive windows large enough to hide lookahead bugs |
| Backend capability record | ADR or table for supported validation semantics | Multi-asset target weights and exit rules need explicit support status |

### Retire Or Rename

| Area | Retire or rename | Reason |
|---|---|---|
| Autoresearch loop feedback wording | Stop using local promotion/validation labels for non-validation artifacts; wrap under `autoresearch_loop_feedback` | Screening feedback should not be mistaken for market validation |
| `clear_yes` deployability | Retire any interpretation that `clear_yes` alone means paper/live ready | The current policy is advisory and lacks selection-pressure adjustment |
| Runner return labels | Rename or document runner `gross_return`/`net_return` as additive weighted trade sums unless portfolio returns are implemented | They should not be read as portfolio NAV returns |
| Smoke fixture location | Move `tested/simple_momentum.py` out of `tested/`, or document it as an explicit fixture exception | `tested/` should mean validation-passed strategy code |
| Parallel private runners | Remove any duplicate runner harness in `quant_autoresearch` once it can call `run_config` with acceptable performance | One source of runner truth avoids contract drift |

## Prioritized Recommendations

| Priority | Recommendation | Why now | Verify |
|---|---|---|---|
| P1 | Make validation policy explicit and conservative; do not let `clear_yes` imply paper/live readiness | Prevent false promotion evidence | Tests for policy thresholds and CLI semantics |
| P1 | Add `validation_manifest.json` with git/package/backend/data/artifact hashes | Promotion evidence must be reproducible | Validation artifact tests |
| P1 | Normalize researched handoff semantics and mark variants `runner_only` vs `validation_ready` | Avoid confusing loop feedback with validation | Manifest contract test over `researched/` |
| P1 | Decide how to validate cross-sectional target-weight candidates | Current backend cannot clear the main candidate | End-to-end rank_03 validation result |
| P2 | Add quick-run `artifact_profile = "summary"` and benchmark `quant_autoresearch` loops | Shared runner must remain usable at scale | Runtime and artifact-size benchmark |
| P2 | Pre-index engine bars by `(symbol, timestamp)` | Fix named FX bottleneck without changing concepts | Synthetic large-signal benchmark |
| P2 | Add per-strategy param validation for researched/validation configs | Avoid silent TOML typo evidence | Unknown-param tests |
| P2 | Label or regenerate parameter perturbation decisions | Current diagnostics can mislead | Robustness artifact includes regeneration flag |
| P3 | Extract shared data-loading boundary only if runner/validation needs diverge | Avoid premature refactor | No action until duplicated behavior appears |

## NOT In Scope

- Full live-trading architecture, broker routing, execution algos, or exchange
  failures.
- Full portfolio optimizer or capacity model.
- Options, margin liquidation, borrow constraints, partial fills, and market
  impact.
- Declaring any current strategy paper/live ready.
- Reading or relying on the prior forbidden review file.

## Verification Summary

- **Verified**:
  - CodeGraph index was healthy: 58 indexed files, 1,031 nodes.
  - Full test suite passed locally with
    `conda run -n quant pytest -q`: `302 passed in 9.21s`.
  - Source-level traces for runner, engine, validation, researched package
    contracts, artifact writers, and upstream FX performance limitation.
  - Five independent read-only review lenses: onboarding, architecture, senior
    engineering, adversarial, and quant math/code.
- **Not verified**:
  - Live `quant_data` loads.
  - Real VectorBT PRO run on the selected researched candidate.
  - `quant_autoresearch` codebase behavior beyond the named TODO file.
  - Runtime benchmark for large FX/crypto loops.
- **Residual risk**: Some recommendations may change after an end-to-end
  `quant_autoresearch -> quant_strategies.runner -> researched package ->
  validation` integration test. The largest unverified fact is whether the
  current rank_03 validation actually hits `multi_asset_target_weight` in live
  data, though the source strongly suggests it can.
