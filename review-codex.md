# Foundation Review: quant_strategies

Date: 2026-06-04
Reviewer: Codex, with senior quant researcher lens
Target: `/Users/Season_Yang/Personal/quant_strategies`

## Review Objective

I reviewed `quant_strategies` to determine whether it is a sound stateless
advisory research foundation for `quant_autoresearch`, Season as senior quant
researcher, and future strategy authors.

Locked objective: the project should provide three public jobs: quick run,
mechanical evidence validation, and research evaluation for supplied or frozen
candidates. A solid foundation should make math-correct, auditable,
deterministic, hard-to-misuse research evidence easy, and should prevent
lookahead, misleading metrics, legacy shims, overbroad framework scope,
promotion automation, and hidden workflow complexity.

This review is not trying to make the project perfect. It asks whether the
foundation is good enough to start running research evidence without being
misled by math, contracts, artifacts, or legacy shape.

### Clarified Scope

- **In scope**: `PRD.md`, active instructions, public APIs/CLI, decision
  ontology, shared execution kernel, quick-run runner, validation pipeline,
  evaluation pipeline, engine math, evaluation portfolio/NAV math, active docs,
  tests, configs, and current strategy modules under `untested/`.
- **Out of scope**: implementing fixes, judging alpha quality, optimizing
  strategy parameters, paper-trading/live-trading readiness, `quant_data`
  internals, `quant_autoresearch` internals, and historical review-body
  archaeology beyond the active disposition docs.
- **Additional concerns from Season**: overengineering, consumer workflow
  simplicity, layered design, legacy compatibility/artifacts, not being biased
  by existing outputs, willingness to rewrite/rerun, critical math correctness,
  and not overrating low-priority issues.
- **Assumptions after clarification**: broad review was explicitly requested
  despite `FOUNDATION_LOCK.md` preferring delta reviews by default.

## Executive Verdict

The foundation is broadly good and not a rewrite case. The core shape is right:
one typed decision ontology, one shared execution kernel, three clear public
jobs, engine trade-activity evidence separated from evaluation NAV/path
evidence, advisory-only language, ignored generated result roots, and strong
tests. I did not find a wrong core return, funding, fill, or annualization
formula in the inspected paths. The original critical validation exposure hole,
the evaluation decision-readiness gap, and the positive drawdown sign gap are
now addressed. The remaining major foundation risk is row-order ownership,
which is intentionally left open while upstream `quant_data` addresses the data
contract feedback.

Practical answer: start running targeted quick runs, validation runs, and
evaluation experiments, but continue treating multi-symbol row-order-sensitive
evidence cautiously until the upstream row-order contract and local
data-boundary behavior are reconciled.

## Scope And Evidence

- **Primary target**: `/Users/Season_Yang/Personal/quant_strategies`.
- **Product objective**: `PRD.md` lines 35-67, 111-227, 290-351, 355-375.
- **Instructions and disposition**: `AGENTS.md`, `FOUNDATION_LOCK.md`,
  `docs/reviews/README.md`.
- **Public surfaces**: `src/quant_strategies/cli.py`,
  `src/quant_strategies/runner/__init__.py`,
  `src/quant_strategies/validation/_pipeline.py`,
  `src/quant_strategies/evaluation/_pipeline.py`.
- **Core contracts**: `src/quant_strategies/decisions/models.py`,
  `src/quant_strategies/decisions/output_validation.py`,
  `src/quant_strategies/core/execution.py`,
  `src/quant_strategies/core/data_loader.py`,
  `src/quant_strategies/data_contract.py`,
  `src/quant_strategies/causality.py`.
- **Math/evidence paths**: `src/quant_strategies/engine/evaluation.py`,
  `src/quant_strategies/validation/engine_backend.py`,
  `src/quant_strategies/evaluation/vectorbtpro_backend.py`,
  `src/quant_strategies/evaluation/project_perp_ledger.py`,
  `src/quant_strategies/evaluation/_portfolio_common.py`,
  `src/quant_strategies/funding.py`.
- **Tests/configs/docs**: `tests/`, `pyproject.toml`, `Makefile`,
  `constraints/evaluation.txt`, `README.md`, `docs/foundation-surfaces.md`,
  `docs/vectorbtpro.md`, `TODOS.md`, `runs/`, `examples/strategies/`.
- **Not inspected**: real `quant_data` source and live data outputs,
  `quant_autoresearch` source, prior review bodies in full, and generated
  historical results.

Required perspective lenses were run as read-only fresh-context subagents:
onboarding, architecture, senior software engineering, adversarial, and quant
math. The main synthesis reconciles those findings against source evidence.

## Intended Foundation Model

From first principles, the minimal correct foundation is:

- Strategy authors write pure, flat strategy files.
- Strategies consume only supplied rows and params.
- Strategy output has one ontology: typed decisions with instrument, time,
  as-of lineage, target, exit policy, observations, and metadata.
- The shared execution kernel imports the strategy, validates params, loads rows
  through `quant_data`, normalizes and freezes inputs, generates decisions, and
  validates decision shape.
- Quick run diagnoses one strategy version quickly.
- Validation mechanically audits retained-candidate evidence integrity.
- Evaluation gives stateless frozen-candidate portfolio/path/economic evidence.
- Evidence is advisory. No public job promotes, paper trades, or live trades.
- Every metric declares its unit/base and does not pretend that linear
  trade-activity sums are NAV returns.
- Artifacts are reproducible evidence, not truth.

```text
strategy.py + config
        |
        v
public job: run / validate / evaluate
        |
        v
shared execution kernel
  import -> params -> quant_data rows -> normalize -> freeze -> decisions
        |
        +--> quick run: causality + engine trade-activity diagnostics
        |
        +--> validation: row/data/causality/readiness audit
        |                -> engine trade-activity scenarios
        |                -> advisory validation decision
        |
        +--> evaluation: row/data/causality preflight
                         -> portfolio/NAV backend
                         -> replayable evaluation artifacts
```

## Project Ontology: Concepts, Contracts, Boundaries, Invariants

| Concept / boundary | Responsibility | Key contracts or invariants | Current-code fit |
|---|---|---|---|
| Strategy module | Express one research rule as pure code | One file, `generate_decisions(rows, params)`, optional/required `validate_params` by surface, no data loading or artifacts | Mostly matches |
| Decision ontology | Single strategy output model | Time-aware `decision_time` and `as_of_time`, typed instrument, target, exit, observations, JSON metadata | Strong; exposure admissibility is now explicit for validation/evaluation evidence |
| Data boundary | Consume `quant_data` rows only | Loader APIs only, row contract feedback, no local data acquisition | Mostly matches, but row-order ownership contradicts code |
| Execution kernel | Shared import/params/load/freeze/decision path | No surface owns a forked execution path | Strong |
| Quick run | Fast diagnostics | Causality hygiene, bounded artifacts, no promotion | Strong |
| Validation | Mechanical retained-candidate evidence | Strict row contract, data audit, causality, readiness, exposure admissibility, engine verdict only, advisory labels | Good shape; public backend injection is now removed |
| Evaluation | Frozen-candidate research evidence | Strict preflight, decision readiness, portfolio/NAV evidence, trace artifacts, no promotion | Good shape |
| Artifacts | Audit evidence | Full profile/evaluation replayable, generated outputs ignored, immutable result dirs | Strong |
| Metrics | Quant evidence semantics | Unit/base/comparability clear, no alpha/promotion claims | Strong; positive drawdown values are now rejected |

## What Already Exists And Should Be Reused

| Existing code/flow | What it does | Reuse / concern |
|---|---|---|
| `src/quant_strategies/core/execution.py` | Shared strategy import, params, data load, row normalization, freezing, decision generation | Preserve; this is the right spine |
| `src/quant_strategies/decisions/models.py` | Frozen Pydantic decision ontology | Preserve; admissible executable exposure is handled outside the model |
| `src/quant_strategies/causality.py` | Deterministic replay and strict suppression replay | Preserve; good hidden-lookahead foundation |
| `src/quant_strategies/validation/_pipeline.py` | Retained-candidate mechanical evidence workflow | Preserve shape; exposure/admissibility is addressed, backend seam remains open |
| `src/quant_strategies/evaluation/_pipeline.py` | Frozen-candidate evaluation workflow and artifact fan-out | Preserve shape; decision observation readiness is addressed |
| `src/quant_strategies/evaluation/project_perp_ledger.py` | Funding-aware perp NAV ledger | Preserve as evaluation-specific accounting |
| `src/quant_strategies/evidence_semantics.py` and `evaluation/metrics.py` | Metric unit/base semantics and non-authority labels | Preserve; drawdown sign guard is addressed |
| `tests/` | Extensive contract, math, artifact, boundary, and docs coverage | Preserve; add targeted missing tests, do not rewrite broadly |

## Architecture And Boundary Review

### Findings

1. **[Addressed] Mechanical validation accepted levered evidence that evaluation rejected**
   - Action class: Add
   - Evidence: `src/quant_strategies/decisions/models.py:105`,
     `src/quant_strategies/decisions/models.py:116`,
     `src/quant_strategies/engine/executable.py:41`,
     `src/quant_strategies/engine/evaluation.py:70`,
     `src/quant_strategies/engine/evaluation.py:80`,
     `src/quant_strategies/validation/engine_backend.py:51`,
     `src/quant_strategies/evaluation/vectorbtpro_backend.py:206`,
     `src/quant_strategies/evaluation/_portfolio_common.py:62`.
   - Original risk: default `target_weight` had no upper bound in the validation
     engine. The validation engine multiplied return and cost by weight and
     emitted completed metrics, while evaluation flagged `target.size > 1.0` as
     `leveraged_target_weight` and rejected aggregate gross target exposure above
     1.0.
   - Resolution: `engine.executable.base_unsupported_semantics()` now classifies
     `leveraged_target_weight`, and validation checks single-decision and
     aggregate active gross exposure across required scenario fill models before
     backend execution.
   - First-principles reason it matters: validation is supposed to mechanically
     audit retained-candidate evidence under executable assumptions. If one
     surface treats levered evidence as completed and another treats it as
     unsupported, the foundation has no single admissible execution contract.
   - Root cause: missing validation exposure/admissibility contract.
   - Verification: regression tests cover levered single decisions, base overlap,
     and required-scenario fill-model overlap.
   - Tradeoff: unlevered research remains simple; levered strategies need an
     explicit future ontology instead of accidental support.

2. **[High] Row-order ownership is contradictory across docs, code, and tests**
   - Action class: Refactor
   - Evidence: `README.md:172`, `README.md:176`,
     `FOUNDATION_LOCK.md:64`, `FOUNDATION_LOCK.md:67`,
     `docs/foundation-surfaces.md:35`, `docs/foundation-surfaces.md:38`,
     `src/quant_strategies/core/data_loader.py:70`,
     `tests/test_runner_data_loader.py:120`.
   - What is wrong or risky: active docs say `quant_data` owns stable row order
     and this repo preserves supplied row order before hashing/execution. Code
     sorts locally by `(symbol, timestamp)` before normalization; tests expect
     multi-symbol rows to reorder.
   - First-principles reason it matters: row order is part of the strategy input
     contract and artifact identity. If a strategy is sequence-sensitive or
     cross-sectional, sorting can change behavior. If sorting is intended, it
     must be an explicit canonicalization contract; if not, it is a bug.
   - Root cause: data boundary/contract drift.
   - Recommendation: choose one contract. My recommendation is to honor the
     lock: remove local sorting, assert or test upstream ordering where needed,
     and include row-order contract smoke coverage against `quant_data`.
     Alternative: declare local canonical ordering and update docs/tests/strategy
     author guidance accordingly.
   - Tradeoff: preserving upstream order places more responsibility on
     `quant_data`; local canonical order is simpler internally but must be named
     truthfully and may constrain strategy authors.

3. **[Addressed] Evaluation preflight accepted decisions with no declared observations**
   - Action class: Add
   - Evidence: `src/quant_strategies/decisions/models.py:151`,
     `src/quant_strategies/decisions/output_validation.py:24`,
     `src/quant_strategies/validation/_pipeline.py:416`,
     `src/quant_strategies/evaluation/_pipeline.py:307`,
     `src/quant_strategies/evaluation/config.py:119`.
   - Original risk: validation had a readiness gate requiring declared
     observations. Evaluation ran data audit and caught invalid declared
     observations, but a decision with an empty `observations=()` could still
     reach portfolio metrics if the as-of row existed and causality replay passed.
   - First-principles reason it matters: research evaluation is the surface meant
     to produce audit-grade frozen-candidate evidence. If decision provenance is
     opaque, artifacts show the decision but not the actual observed inputs that
     justified it.
   - Root cause: missing evaluation readiness contract.
   - Resolution: decision readiness is now a shared core helper, and evaluation
     defaults to at least one observation and one observed symbol per decision
     before portfolio backend execution.
   - Tradeoff: this makes evaluation configs slightly heavier, but prevents
     opaque portfolio evidence.

4. **[Addressed] Public backend injection could bypass official evidence semantics**
   - Action class: Refactor
   - Evidence: `src/quant_strategies/validation/_pipeline.py:90`,
     `src/quant_strategies/validation/_pipeline.py:140`,
     `src/quant_strategies/validation/backends.py:72`,
     `src/quant_strategies/evaluation/__init__.py:4`,
     `src/quant_strategies/evaluation/_pipeline.py:93`.
   - Original risk: validation configs were engine-only, but the Python API
     accepted `backend=...`; evaluation exported `EvaluationBackend` and accepted
     injected backends. This was useful for tests, but `quant_autoresearch` is a
     Python consumer, so the seam could be mistaken for a supported production
     extension point.
   - First-principles reason it matters: evidence semantics are only true for the
     backend assumptions they describe. Injected metrics with official labels can
     become false evidence.
   - Root cause: test seam leaked across the public trust boundary.
   - Resolution: public `run_validation` and `run_evaluation` no longer accept
     `backend=...`; fake backend support uses private `_run_validation` and
     `_run_evaluation` helpers.
   - Tradeoff: tests use private helpers, while the consumer surface is harder
     to misuse.

## Engineering, Testability, And Operability Review

### Findings

1. **[Addressed] Positive `max_drawdown` values were accepted under negative-drawdown semantics**
   - Action class: Add
   - Evidence: `src/quant_strategies/evaluation/metrics.py:108`,
     `src/quant_strategies/evaluation/vectorbtpro_backend.py:360`,
     `src/quant_strategies/evaluation/_pipeline.py:1037`,
     `src/quant_strategies/evaluation/project_perp_ledger.py:159`.
   - Original risk: metric semantics define `max_drawdown` as minimum drawdown
     over the NAV path. The VectorBT/custom backend path accepted any finite
     scalar from `get_max_drawdown()`.
   - Why it matters: drawdown sign conventions are a common research-footgun.
     A positive value can make downstream ratios or human interpretation wrong.
   - Resolution: shared metric extraction rejects positive `max_drawdown` values
     in both VectorBT/custom and project perp ledger metric paths.

2. **[Medium] Windowed configs silently accept legacy `[data].start/end`**
   - Action class: Retire
   - Evidence: `src/quant_strategies/core/config.py:30`,
     `tests/test_validation_config.py:404`,
     `tests/test_evaluation_config.py:171`,
     `PRD.md:283`, `PRD.md:368`.
   - What is wrong or risky: `WindowedDataConfig` discards `start` and `end`
     before Pydantic's `extra="forbid"` can reject them. Tests lock that stale
     dates are accepted and overridden by `[[windows]]`.
   - Why it matters: the PRD explicitly rejects legacy shims. Silent discards
     hide stale candidate configs and make workflow behavior less obvious.
   - Recommendation: reject `start`/`end` in validation/evaluation `[data]`, or
     require exact consistency with configured windows. Prefer rejection.
   - Verification: update the two tests to expect config errors.

3. **[Medium] No real `quant_data` row-contract smoke in the standard check**
   - Action class: Add
   - Evidence: `Makefile:3`, `Makefile:9`,
     `tests/test_runner_data_loader.py:91`,
     `tests/test_repository_boundaries.py:165`.
   - What is wrong or risky: loader tests use fakes and package metadata bounds
     `quant-data`, but there is no small real upstream contract smoke for loader
     shape, `available_at`, ordering, funding, and quote fields.
   - Why it matters: `quant_data` is the only data source. The row-order
     contradiction makes this more than test purism.
   - Recommendation: add an opt-in or standard smoke that uses an upstream
     fixture/dry-run loader to assert row fields, ordering contract, and data-kind
     semantics. Keep it small; do not build data materialization here.
   - Verification: `make check` or `make check-quant-data-contract`.

## Domain-Specific Lens Findings

### Quant / Trading Research

1. **[Critical] Levered validation evidence is the main quant trust blocker**
   - Action class: Add
   - Evidence: same as Architecture finding 1.
   - Domain risk: a validation label can become false mechanical evidence if it
     is computed on unbounded target weights or overlapping gross exposure that
     the portfolio evaluation surface refuses to model.
   - Recommendation: gate exposure admissibility before validation policy.

2. **[Important] I did not find a critical formula error in inspected core math**
   - Action class: Preserve
   - Evidence: `src/quant_strategies/engine/evaluation.py:70`,
     `src/quant_strategies/engine/evaluation.py:80`,
     `src/quant_strategies/funding.py:15`,
     `src/quant_strategies/evaluation/project_perp_ledger.py:75`,
     `src/quant_strategies/evaluation/vectorbtpro_backend.py:349`,
     `src/quant_strategies/evaluation/_portfolio_common.py:291`.
   - Domain risk: none found at formula level in the inspected paths. The
     important risks are admissibility and semantics, not arithmetic.
   - Recommendation: preserve current explicit semantics, funding-window rule
     `entry < ts <= exit`, full-grid annualized metric guards, and advisory-only
     labels.

### Consumer Workflow / `quant_autoresearch`

1. **[Medium] Consumer surface is mostly simple, but Python test seams need clearer trust boundaries**
   - Action class: Refactor
   - Evidence: `docs/foundation-surfaces.md:100`,
     `src/quant_strategies/validation/_pipeline.py:90`,
     `src/quant_strategies/evaluation/__init__.py:4`.
   - Domain risk: `quant_autoresearch` should consume only
     `run_config`, `run_validation`, and `run_evaluation` with official
     assumptions. Backend injection makes that easier to accidentally bypass.
   - Recommendation: document or enforce backend injection as test-only/private.

## Unknown Unknowns And Assumption Risks

| Assumption | Why it may be wrong | How to test or de-risk |
|---|---|---|
| `quant_data` row ordering and `available_at` semantics match the locked contract | Current code sorts locally and tests expect sorting | Add real upstream contract smoke and resolve row-order ownership |
| Evaluation backend drawdown sign matches project semantics | Addressed for positive `max_drawdown`; future custom backends still need semantic review | Keep positive-drawdown regressions and review any new backend semantics |
| Strategy modules under `untested/` are causally clean under real data | Unit tests cover synthetic paths, not full live data windows | Run quick/evaluation configs and inspect data-audit/causality artifacts |
| Backend injection remains private/test-only | Future public extension pressure could reintroduce a trust-boundary leak | Keep public API signature tests and require explicit evidence semantics for any future custom backend |
| Prior review dispositions are complete | I did not inspect every historical review body | Use `FOUNDATION_LOCK.md` as anchor; run delta review only after P1 fixes |

## Overbuilt / Underbuilt / Right-Sized

- **Overbuilt**: silent legacy `[data].start/end` compatibility is unnecessary
  process weight; public backend injection is more extension surface than the
  PRD needs; large pipeline modules are bulky but currently acceptable.
- **Underbuilt**: validation exposure admissibility, evaluation observation
  readiness, row-order contract enforcement, drawdown sign guard, and real
  `quant_data` contract smoke.
- **Right-sized**: three public job vocabulary, shared execution kernel, pure
  strategy contract, Pydantic decision ontology, artifact profiles, strict
  causality replay, advisory-only validation/evaluation labels, and separate
  engine trade-activity versus evaluation NAV evidence.

## Documentation And Decision Gaps

- **Stale PRD**: `PRD.md` still says benchmark-relative metrics are deferred,
  while current code/docs implement optional benchmark evidence as
  non-authoritative evaluation evidence. Evidence: `PRD.md:83`,
  `FOUNDATION_LOCK.md:43`, `src/quant_strategies/evaluation/config.py:130`,
  `src/quant_strategies/evaluation/_pipeline.py:640`.
- **Missing decision record**: row-order ownership needs a durable decision:
  upstream-preserved order versus local canonical order.
- **Missing trust-boundary note**: backend injection needs explicit policy:
  public extension point, private test seam, or custom evidence class.
- **Stale active docs**: row-order claims in `README.md`,
  `FOUNDATION_LOCK.md`, and `docs/foundation-surfaces.md` contradict
  `core/data_loader.py`.

## Action Map

| No. | Status | Action class | Finding / recommendation | Rationale |
|---:|---|---|---|---|
| 1 | Addressed | Add | Add validation exposure/admissibility gates for `target_weight > 1.0` and aggregate gross exposure above 1.0 before validation policy. | Prevent false mechanical evidence from levered trade-activity sums. |
| 2 | Open | Refactor | Resolve row-order ownership: remove local sorting or declare canonical local ordering everywhere. | Strategy input, hashes, and replay identity must share one truth. |
| 3 | Addressed | Add | Add evaluation observation/readiness requirements for frozen-candidate evidence. | Portfolio metrics without declared observations are not audit-grade. |
| 4 | Addressed | Refactor | Make validation/evaluation backend injection private/test-only or emit explicit custom-backend evidence semantics. | Prevent public Python consumers from bypassing official evidence assumptions. |
| 5 | Addressed | Add | Reject or normalize positive `max_drawdown` at the evaluation adapter boundary. | Preserve metric sign semantics and downstream ratio correctness. |
| 6 | Addressed | Retire | Remove silent legacy `[data].start/end` discard in validation/evaluation configs. | No-legacy contract requires stale configs to fail clearly. |
| 7 | Open | Add | Add a minimal real `quant_data` contract smoke for loader shape, ordering, `available_at`, funding, and quote fields. | The upstream data boundary is central and currently tested mostly with fakes. |
| 8 | Addressed | Add | Update `PRD.md` benchmark-relative language to match implemented evidence-only metrics. | Avoid product intent drifting behind current accepted code. |

Addressed notes, 2026-06-04:

- Item 1 was fixed at the executable/admissibility boundary:
  `engine.executable.base_unsupported_semantics()` classifies
  `leveraged_target_weight`, and validation uses a shared exposure helper before
  backend scenarios. Regression coverage:
  `tests/test_engine_executable.py`,
  `tests/test_validation_runner.py::test_run_validation_fails_before_backend_on_leveraged_target_weight`,
  and
  `tests/test_validation_runner.py::test_run_validation_fails_before_backend_on_overlapping_gross_exposure`.
- Item 3 was fixed with shared decision-readiness logic in `core`, reused by
  validation and evaluation. Evaluation now fails opaque decisions before
  portfolio backend execution. Regression coverage:
  `tests/test_evaluation_runner.py::test_run_evaluation_fails_before_portfolio_on_missing_decision_observations`.
- Item 5 was fixed with a shared required drawdown metric guard that rejects
  positive `max_drawdown` values. Regression coverage:
  `tests/test_evaluation_backend.py::test_portfolio_metrics_fail_when_max_drawdown_is_positive`
  and
  `tests/test_evaluation_backend.py::test_perp_ledger_metrics_fail_when_max_drawdown_is_positive`.
- Item 4 was fixed by keeping backend injection in private test helpers
  (`_run_validation` / `_run_evaluation`) while public APIs expose only official
  backend selection. Regression coverage:
  `tests/test_result_success_contract.py::test_public_validation_and_evaluation_apis_do_not_accept_backend_injection`.
- Item 6 was fixed by removing the legacy windowed `[data].start/end` discard;
  validation/evaluation configs now reject those stale fields. Regression
  coverage:
  `tests/test_validation_config.py::test_load_validation_config_rejects_legacy_data_window_dates`
  and
  `tests/test_evaluation_config.py::test_load_evaluation_config_rejects_legacy_data_window_dates`.
- Item 8 was fixed by updating `PRD.md` to describe benchmark-relative metrics
  as advisory evaluation evidence only, not deferred work.

## Preservation Constraints

- Keep exactly three public jobs in user vocabulary: quick run, validation run,
  evaluation run.
- Keep `quant_strategies.engine` internal to quick-run/validation internals.
- Keep one shared execution kernel; do not re-fork execution logic per surface.
- Keep strategy modules flat and pure.
- Keep validation advisory; never add promotion/paper/live authority.
- Keep evaluation separate from validation and from the quick-run hot path.
- Keep engine trade-activity sums named as non-NAV evidence.
- Keep evaluation portfolio/NAV metrics separate and unit/base tagged.
- Keep generated artifacts under ignored output roots and regenerate instead of
  preserving compatibility with old artifact shapes.
- Keep full-grid annualized/risk metric guards and nulling behavior.

## Prioritized Recommendations

| Status / Priority | Action class | Recommendation | Why now | Verify |
|---|---|---|---|---|
| Addressed | Add | Validation exposure/gross-target admissibility gates. | Fixed at executable/admissibility boundaries. | Regression tests cover levered decisions, base overlap, and required-scenario fill-model overlap. |
| P1 | Refactor | Resolve row-order ownership across code, docs, and tests. | Current source contradicts the locked data boundary and can change strategy behavior. | Loader tests plus docs agree; hash/artifact tests prove chosen order. |
| Addressed | Add | Evaluation decision observations/readiness. | Frozen-candidate evidence now requires declared observations before portfolio backend execution. | Evaluation test with empty `observations=()` fails before portfolio backend. |
| Addressed | Refactor | Backend injection trust boundary. | Public APIs no longer accept backend injection; fake backends use private helpers. | Public API signature test confirms no `backend` parameter or exported `EvaluationBackend`. |
| Addressed | Add | Guard drawdown sign convention. | Positive `max_drawdown` values are now rejected. | Fake backend and perp-ledger positive drawdown regressions fail as invalid required metrics. |
| Addressed | Retire | Reject legacy window dates in windowed `[data]`. | Keeps workflow simple and no-legacy. | Config tests expect validation/evaluation errors. |
| P2/P3 | Add | Add real `quant_data` contract smoke. | De-risks the only upstream data boundary. | New targeted command passes in `quant` env. |
| Addressed | Add | Update stale PRD benchmark-relative wording. | Documentation correctness, not run blocker. | PRD no longer says implemented metrics are deferred. |

## NOT In Scope

- Proving any current strategy has alpha.
- Paper-trading or live-trading authorization.
- Building a general backtesting framework.
- Moving data materialization into this repo.
- Rewriting large modules only because they are large.
- Preserving old artifacts or legacy configs.
- Ranking, search memory, stopping rules, or candidate generation.

## Verification Summary

- **Verified locally**:
  - `conda run -n quant pytest -q` -> `991 passed, 2 skipped`.
  - `conda run -n quant env RUN_VECTORBTPRO_SMOKE=1 pytest -q tests/test_evaluation_backend.py::test_vectorbtpro_evaluation_backend_real_smoke_if_installed` -> `1 passed`.
  - `conda run -n quant quant-strategies --help` -> CLI exposes only `run`,
    `validate`, and `evaluate`.
  - `git diff --check` -> clean.
  - Regression coverage now verifies validation exposure admissibility,
    evaluation decision readiness, and positive drawdown rejection.
- **Not verified**:
  - Real `quant_data` source behavior or live loader outputs.
  - Full `quant_autoresearch` consumer integration.
  - Profitability or statistical validity of strategy ideas.
  - Every historical review body.
- **Residual risk**:
  - Multi-symbol strategy behavior and artifact identity remain ambiguous until
    row-order ownership is resolved.
