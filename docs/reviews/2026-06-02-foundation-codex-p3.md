# Foundation Review: `quant_strategies`

Date: 2026-06-02
Reviewer: Codex, senior quant researcher / foundation reviewer
Target: repository root

## Review Objective

I understand the project objective as: `quant_strategies` should serve
`quant_autoresearch`, Season as senior quant researcher/auditor, and future
strategy authors by enabling pure strategy expression, diagnostic quick runs,
mechanical evidence validation, and stateless frozen-candidate research
evaluation. A solid foundation should make math semantics, causality,
auditability, deterministic artifacts, and simple public workflows easy, and
prevent lookahead, ambiguous metrics, legacy compatibility drift, overbuilt
layers, and evidence that implies promotion or live trading. It must respect
the constraints that `quant_data` owns data, strategy files stay pure and flat,
generated artifacts are ignored evidence rather than truth, legacy shims are
not carried, and trading-system features are out of scope.

This review accounts for Season's additional concerns: over-engineering,
workflow simplicity, layered design, legacy code/artifact bias, and willingness
to rewrite/rerun instead of preserving old output.

## Executive Verdict

The foundation is conditionally solid. It is not a rewrite case. The public
workflow is simple enough: `run`, `validate`, and `evaluate` are distinct, and
the code has a real shared spine for strategy import, param validation, data
loading, row normalization, decision generation, and causality checks. The
strong pieces should be preserved.

The project is not yet fully trustworthy as a quant research foundation because
the evaluation surface can emit clean-looking portfolio/path evidence for
economic objects that are weaker than the validation evidence. The most
important examples are crypto perp funding being accepted by evaluation while
the portfolio backend models only price plus fees/slippage, threshold exit
fields being named like intrabar stop/take/trailing orders while implemented as
bar close/quote threshold checks, and evaluation metrics being allowed to
complete with nulls after accessor failures. These are targeted foundation
fixes, not evidence for a broad rewrite.

## Scope And Evidence Inspected

Primary target: full repo at `/Users/Season_Yang/Personal/quant_strategies`.

Evidence inspected:

- `PRD.md`, `README.md`, `FOUNDATION_LOCK.md`, `TODOS.md`,
  `docs/foundation-surfaces.md`, `docs/vectorbtpro.md`, `AGENTS.md`.
- `pyproject.toml`, `.gitignore`, `runs/`, `examples/strategies/`.
- Public surfaces: `runner.run_config`, `validation.run_validation`,
  `evaluation.run_evaluation`, and `runner/cli.py`.
- Core contracts: `core/config.py`, `decisions/*`, `data_contract.py`,
  `causality.py`, `observation_dependencies.py`, `boundary.py`.
- Execution/math: `engine/*`, `runner/engine_runner.py`,
  `validation/*`, `evaluation/*`, `funding.py`, `evidence_semantics.py`.
- Tests covering strategy purity/docstrings, row contracts, hidden lookahead,
  engine math, validation policy/artifacts, evaluation config/backend/artifacts,
  CLI/API behavior, and repository boundary rules.
- Required lens subagents: onboarding, architecture, senior software
  engineering, adversarial, and quant math/code review. I reconciled their
  findings instead of copying them uncritically.

Verification performed:

```bash
conda run -n quant pytest -q
```

Result: `847 passed, 1 skipped`. The skipped test is the real VectorBT Pro
smoke test gated by `RUN_VECTORBTPRO_SMOKE=1`.

Not inspected:

- `quant_data` internals.
- `quant_autoresearch` call sites.
- Live external data or real VectorBT Pro smoke execution.
- Generated historical `results/` artifacts.

## Intended Foundation Model

The minimal correct foundation from first principles is:

```text
pure strategy.py
  generate_decisions(rows, params)
        |
        v
StrategyExecutionSpec
  strategy_path, strategy_id, data, params, fill/cost assumptions
        |
        v
shared execution kernel
  import -> validate params -> load via quant_data -> normalize/freeze rows
  -> typed decisions -> observation audit -> strict causal replay
        |
        +--> quick run
        |     engine trade ledger -> diagnostic evidence/profile artifacts
        |
        +--> validation run
        |     windows x scenarios -> engine ledger -> advisory mechanical verdict
        |
        +--> evaluation run
              frozen candidate -> portfolio/path backend -> Parquet trace evidence
```

Correct dependency direction:

```text
decisions/core/data_contract/causality
      ^
      |
runner, validation, evaluation public workflows
      |
      v
artifacts and human/agent consumers
```

The foundation must make these invalid states hard to represent:

- A strategy can produce untyped or duplicate decisions.
- A strategy can use future rows without replay catching it.
- Validation can compute a verdict from one number while artifacts expose
  another number.
- Evaluation can claim portfolio/economic evidence for an economic object it
  did not model.
- Generated artifacts become source-of-truth or tracked legacy state.
- A validation/evaluation result label implies promotion, paper trading, or
  live trading authority.

## Project Ontology: Concepts, Contracts, Boundaries, Invariants

| Concept / boundary | Responsibility | Key contracts or invariants | Current-code fit |
|---|---|---|---|
| Strategy module | Express thesis as pure decision function | Flat file, `generate_decisions(rows, params)`, optional/required `validate_params` by surface, docstring provenance | Strong |
| Decision ontology | Typed strategy output | Narrow default executable vocabulary; extended ontology opt-in; stable decision IDs; timezone-aware times | Strong |
| Data boundary | Consume `quant_data` only | No CSV/API loading in strategies; row contract validates schema, timestamps, availability, funding/quote fields | Strong |
| Execution spec | Neutral input to shared kernel | No artifact policy; public workflows adapt into it | Good, but implementation lives under `runner.execution` |
| Causality kernel | Detect lookahead/suppression | Deterministic replay, emitted replay, strict no-emission replay, availability-aware rows | Strong |
| Engine PnL | Quick-run and validation trade ledger | Linear signed trade-activity result, not NAV; funding/cost semantics explicit | Strong with naming caveat for threshold exits |
| Validation | Mechanical evidence for retained candidates | Requires params validator, row contract, causal replay, scenario matrix, advisory verdict, no promotion authority | Good with duplicate-window artifact risk |
| Evaluation | Stateless frozen-candidate portfolio/path evidence | Explicit assumptions, portfolio/NAV metrics, trace artifacts, no promotion authority | Useful but currently under-specified for funding and metric completeness |
| Artifacts | Evidence and audit trail | Immutable result dirs, hashes, replayability metadata, profile-specific output | Good on success; weak for evaluation failures |
| Docs/current state | Orient users and agents | PRD owns intent; reference docs own commands/schemas; no stale active history | Mixed; main docs are good, phase plans remain confusing |

## What Already Exists And Should Be Reused

| Existing code/flow | What it does | Reuse / concern |
|---|---|---|
| `decisions/models.py:14-18`, `135-192` | Narrow typed decision contract with generated IDs and immutable metadata | Preserve |
| `decisions/extended_ontology.py:23-130` | Futures/options/multi-leg vocabulary behind explicit import | Preserve |
| `decisions/purity.py:1-10`, `19-91` | Best-effort AST lint for strategy purity and side-effect/data-loading bans | Preserve, do not overstate as sandbox |
| `core/config.py:58-77` | Neutral `StrategyExecutionSpec` shared by workflows | Preserve, consider moving execution implementation next to it |
| `runner/execution.py:74-187` | Shared import/params/data/normalization/decision generation path | Preserve/refactor namespace only |
| `data_contract.py:157-346`, `406-446` | Immutable normalized rows, row contract summary, evidence quality | Preserve |
| `causality.py:72-229`, `310-369` | Strict replay with suppression detection | Preserve |
| `engine/evaluation.py:43-116` | Single engine trade ledger and linear activity math | Preserve semantics; fix threshold-exit naming/implementation |
| `validation/manifest.py:16-56`, `71-119` | Validation manifest hashes ledger artifacts and marks verdict replayability | Preserve |
| `evaluation/artifacts.py:234-309`, `385-545` | Evaluation manifest validates Parquet table metadata and scenario coverage | Preserve |
| Tests | 847 passing tests cover many foundation boundaries | Preserve, add targeted tests for findings |

## Architecture And Boundary Review

### Finding A1: Evaluation accepts funding data but portfolio evidence excludes funding

- Severity: High
- Action class: Refactor
- Evidence:
  - `core/config.py:11` includes `crypto_perp_funding` in shared `DataKind`.
  - `evaluation/config.py:94`, `130-139` accepts the shared data config and adapts it into evaluation execution.
  - `evaluation/backend.py:182-225` builds only a close-price frame.
  - `evaluation/backend.py:386-399` calls `Portfolio.from_signals` with fees/slippage and no funding cashflow.
  - `evaluation/metrics.py:24` says evaluation metrics exclude funding.
- What is wrong or risky: A crypto perp candidate can be validated on
  funding-inclusive engine evidence, then evaluated on NAV/path evidence that
  excludes funding. The artifacts may be internally honest, but the workflow
  compares different economic objects.
- First-principles reason it matters: A strategy's edge can be dominated by
  funding. Portfolio/path evidence without that cashflow is not the same
  hypothesis.
- Root cause: Boundary/contract mismatch between shared data kind and
  evaluation backend capability.
- Recommendation: Either make evaluation reject `crypto_perp_funding` with
  `unsupported_semantics` until funding is modeled, or add a portfolio funding
  cashflow contract and tests. Do not let the same data kind silently mean
  "funding-aware" in validation and "price-only" in evaluation.
- Tradeoff: Rejecting funding is faster and safer. Modeling funding is more
  useful but requires clear NAV cashflow semantics.
- Verification needed: Add a crypto-perp evaluation test that asserts either
  hard unsupported status or funding-inclusive portfolio/path metrics.

### Finding A2: Shared kernel implementation is still namespaced under `runner`

- Severity: Medium
- Action class: Refactor
- Evidence:
  - `validation/__init__.py:20-23` imports `execute_strategy_run` from `runner.execution`.
  - `evaluation/runner.py:30-34` imports the same runner module.
  - `validation/engine_backend.py:9` imports `runner.engine_runner`.
  - `pyproject.toml:26` exposes the global CLI through `quant_strategies.runner.cli:main`.
- What is wrong or risky: The code mostly has a neutral execution model, but
  the namespace still says the quick-run surface owns the shared kernel and
  global CLI.
- First-principles reason it matters: Public workflows should depend on a
  neutral kernel, not on a sibling workflow package. Naming affects future
  design pressure.
- Root cause: Boundary/naming debt, not behavior.
- Recommendation: Move `runner.execution` and engine-request adaptation into a
  neutral `kernel` or `core.execution` namespace when touching this area next.
  Move the CLI to `quant_strategies.cli` as a thin dispatcher.
- Tradeoff: Mechanical imports/test churn; no urgent behavior fix.
- Verification needed: Boundary tests should assert validation/evaluation do
  not import quick-run-owned modules except compatibility exports.

### Finding A3: Evaluation backend extension is weaker than validation backend extension

- Severity: Medium
- Action class: Add
- Evidence:
  - `validation/backends.py:185-195` defines an explicit `ValidationBackend` protocol.
  - `evaluation/runner.py:47-54`, `66-72`, `299-306`, `351-363` accepts `Any` and branches on `hasattr`.
- What is wrong or risky: With only VectorBT Pro this is tolerable, but the
  weakest type boundary is on the most complex surface.
- First-principles reason it matters: An evaluation backend must either prepare
  inputs and run prepared scenarios, or run scenarios directly; those are real
  contracts.
- Root cause: Contract under-specification.
- Recommendation: Add a small evaluation backend protocol before adding any
  second real backend. Keep it minimal; do not build a plugin framework.
- Tradeoff: Slight type surface now, less duck-typing later.
- Verification needed: Type/test fake backends against the protocol.

## Engineering, Testability, And Operability Review

### Finding E1: Evaluation failures after artifact initialization are not durable artifacts

- Severity: High
- Action class: Add
- Evidence:
  - `evaluation/runner.py:91-101` creates a result dir and writes initial artifacts.
  - Post-init failures return `_failure_result`, e.g. `evaluation/runner.py:171-178`, `231-237`, `374-380`.
  - `_failure_result` only returns an `EvaluationRunResult` at `evaluation/runner.py:550-565`.
  - Durable completion artifacts are written only at `evaluation/runner.py:423-477`.
- What is wrong or risky: A failed evaluation can leave a result directory with
  only config/snapshot and no durable failure reason, notes, scenario summary,
  or manifest. `quant_autoresearch` can lose the reason if it only has artifacts.
- First-principles reason it matters: Evidence workflows need failure evidence
  too. A missing failure artifact is a reproducibility gap.
- Root cause: Artifact contract gap.
- Recommendation: Write `evaluation_failure.json` and `notes.md` for every
  post-init failure. Include failure stage, status, message, data windows
  reached, expected/completed scenarios when available, and environment/source
  context if cheap.
- Tradeoff: A little more artifact code; much better agent/debug ergonomics.
- Verification needed: Tests for param validation, preflight, backend failed,
  backend unavailable, scenario coverage, and artifact-write failures should
  assert durable failure artifacts when `result_dir` exists.

### Finding E2: Evaluation scenario backend exceptions can escape the public workflow

- Severity: Medium
- Action class: Refactor
- Evidence:
  - Input preparation catches dependency/value/unexpected exceptions at `evaluation/runner.py:289-331`.
  - Scenario execution calls `run_prepared` / `run` without a guard at `evaluation/runner.py:344-364`.
  - Validation wraps backend exceptions into failed results at `validation/__init__.py:503-520`.
- What is wrong or risky: A backend exception during scenario execution can
  bypass `EvaluationRunResult`, events, and failure artifact handling.
- First-principles reason it matters: Public workflow APIs should fail through
  their typed result contract unless the process is truly unrecoverable.
- Root cause: Boundary error-handling inconsistency.
- Recommendation: Wrap scenario backend execution like input preparation.
  Map dependency failures to `portfolio_backend_unavailable` and other
  exceptions to `portfolio_evaluation_failed`; emit a failed stage event and
  durable failure artifact.
- Tradeoff: Slightly broader exception handling at the backend boundary.
- Verification needed: Add a fake backend whose `run_prepared` raises.

### Finding E3: Validation duplicate window IDs can collide before policy catches them

- Severity: Medium
- Action class: Add
- Evidence:
  - `validation/config.py:72-89` validates each window but has no cross-window uniqueness validator.
  - `evaluation/config.py:123-128` does have a duplicate-window check.
  - `validation/matrix.py:43-66` derives scenario IDs from `window_id`.
  - Validation writes scenario artifacts under sanitized scenario IDs at
    `validation/__init__.py:825-857` and window rows at `validation/__init__.py:861-870`.
  - Policy can reject duplicate scenario IDs later at `validation/policy.py:193-211`.
- What is wrong or risky: Duplicate windows can overwrite row/scenario artifacts
  before the late policy layer reports a mechanical failure.
- First-principles reason it matters: Artifact identity must be unique at the
  config boundary, before any evidence is written.
- Root cause: Config contract gap.
- Recommendation: Add `ValidationConfig` validator for unique window IDs and
  sanitized path collision checks.
- Tradeoff: Small breaking change only for invalid configs.
- Verification needed: Add validation config tests matching evaluation duplicate-window tests.

### Finding E4: Validation config-load behavior is inconsistent with the other public APIs

- Severity: Medium
- Action class: Simplify
- Evidence:
  - `run_config` catches config errors and returns `RunResult` at `runner/__init__.py:62-76`.
  - `run_evaluation` catches `EvaluationConfigError` and returns `EvaluationRunResult` at `evaluation/runner.py:73-89`.
  - `run_validation` performs config load without catching `ValidationConfigError` at `validation/__init__.py:100-108`.
  - CLI catches `ValidationError` at `runner/cli.py:70-87`.
- What is wrong or risky: Python consumers must special-case validation, even
  though all three surfaces are supposed to be narrow public jobs.
- First-principles reason it matters: A simple public workflow should expose a
  consistent failure contract.
- Root cause: Public API contract inconsistency.
- Recommendation: Either align validation to return `ValidationRunResult` for
  config-load failures, or document validation as intentionally exception-first.
  Prefer result-object consistency.
- Tradeoff: Tests expecting raises need updating; CLI behavior can remain the same.
- Verification needed: Public API tests for invalid TOML/path/schema across all three surfaces.

### Finding E5: Candidate-local evaluation output is not ignored by default

- Severity: Medium
- Action class: Add
- Evidence:
  - `.gitignore:6-7` ignores `results/` and `validation_results/`, but not `evaluation_results/`.
  - `evaluation/config.py:79-85` allows any `results_dir` inside the config directory.
  - Evaluation config tests use `evaluation_results/demo` at `tests/test_evaluation_config.py:60-75`.
  - `docs/foundation-surfaces.md:181` documents candidate-local evaluation `results_dir`.
- What is wrong or risky: Candidate-local evaluation artifacts can be written
  under `evaluation_results/` and accidentally tracked. That creates exactly the
  legacy-output bias the PRD rejects.
- First-principles reason it matters: Generated evidence should be easy to
  regenerate and hard to mistake for source.
- Root cause: Repo artifact policy gap.
- Recommendation: Add `evaluation_results/` to `.gitignore` and consider
  rejecting source-like output names for validation/evaluation configs.
- Tradeoff: Ignore-only fix is cheap; stricter validation is a small workflow constraint.
- Verification needed: Repository boundary test that documented generated roots are ignored.

## Domain-Specific Lens Findings

### Finding Q1: Threshold exit fields sound like intrabar barrier orders but use bar close/quote checks

- Severity: High
- Action class: Refactor
- Evidence:
  - Decision model names `stop_loss_bps`, `take_profit_bps`, `trailing_stop_bps` at `decisions/models.py:121-125`.
  - Engine trigger loop computes threshold return from `_fill_price` at `engine/evaluation.py:207-214`.
  - `_fill_price` uses only `open`, `close`, or bid/ask, not high/low, at `engine/evaluation.py:253-263`.
- What is wrong or risky: A quant will normally read stop/take/trailing as
  intrabar barrier semantics. The engine implements close/quote-sampled
  threshold semantics.
- Domain risk: Fills/exits are core PnL assumptions. A mislabeled exit rule can
  materially change results and strategy conclusions.
- Root cause: Ontology/naming mismatch.
- Recommendation: Either rename/document these controls as bar-close/quote
  threshold exits, or implement explicit OHLC barrier semantics with tests for
  intrabar breach/no-breach and ambiguous same-bar stop/take ordering.
- Tradeoff: Renaming is honest and simple; true barrier logic is more realistic
  but needs an ordering assumption.
- Verification needed: Golden tests for stop/take/trailing behavior using OHLC
  paths where close does not breach but high/low does.

### Finding Q2: Evaluation metric completeness and annualization coverage are under-specified

- Severity: High
- Action class: Refactor
- Evidence:
  - `_attribute_value_or_none` swallows accessor exceptions and returns `None` at `evaluation/backend.py:578-586`.
  - `_portfolio_metrics` emits nullable core metrics at `evaluation/backend.py:402-451`.
  - Evaluation treats a scenario as completed when status is completed and trace tables exist at `evaluation/runner.py:365-391`.
  - `_observed_returns` drops non-finite returns at `evaluation/backend.py:637-639`.
  - Annualized return uses `total_return` divided by `len(observed_returns)` at `evaluation/backend.py:426-433`.
- What is wrong or risky: VectorBT API drift or shape errors can become null
  metrics inside `evaluation_complete`. Non-finite periods can be dropped from
  the denominator while total return still spans the whole NAV path.
- Domain risk: Annualization, Sharpe, Sortino, and drawdown metrics are only
  meaningful when the sample and coverage are explicit.
- Root cause: Metric contract and data-quality semantics.
- Recommendation: Define required core evaluation metrics. Distinguish
  legitimate nulls from accessor/backend failures. Add coverage metadata for
  return samples, and either null/fail annualized metrics on non-finite
  post-initial returns or annualize over explicit elapsed periods.
- Tradeoff: Stricter evaluation will fail more often, but failures are better
  than clean-looking incomplete evidence.
- Verification needed: Tests where backend accessors raise and where returns
  contain `NaN`/infinite values.

### Finding Q3: Same-timestamp portfolio rotations can be rejected as leverage

- Severity: Medium
- Action class: Refactor
- Evidence:
  - Evaluation validates gross target weight by sorting events `(timestamp, event_order, weight)` at `evaluation/backend.py:295-313`.
  - Entry events use order `0` and exit events use order `1` at `evaluation/backend.py:299-302`, so entries are applied before exits at the same timestamp.
- What is wrong or risky: A 100% position exiting at `t` and another 100%
  position entering at `t` can be seen as 200% gross and rejected, even though
  a same-bar rotation may be a valid target schedule.
- Domain risk: Cross-asset rotations are common in portfolio research.
- Root cause: Portfolio event model.
- Recommendation: Process exits before entries at the same timestamp, or net
  all target changes by timestamp before enforcing gross exposure.
- Tradeoff: Needs explicit semantics for simultaneous exit/entry ordering.
- Verification needed: Cross-asset rotation test with equal exit/entry timestamps.

### Finding Q4: Observation lineage is declared but not mechanically complete

- Severity: Medium
- Action class: Add
- Evidence:
  - README says typed output includes `ObservationRef` lineage for consumed rows at `README.md:80-83`.
  - `validation/data_audit.py:39-74` checks as-of rows and declared observation existence/availability.
  - `validation/readiness.py:17-29` checks only declared observation count and required field names.
- What is wrong or risky: A strategy can use a cross-section, funding field, or
  proxy series while declaring only minimal `close` observations. The artifact
  can look auditable without representing the full information set.
- Domain risk: Strategy audit depends on what data was actually consumed.
- Root cause: Contract gap between declared observables and mechanical proof.
- Recommendation: Add strategy-level observation coverage rules or a stronger
  declaration contract per strategy family. Do not promise complete lineage
  until the contract can prove it.
- Tradeoff: Full automatic provenance is hard; explicit per-strategy coverage
  rules are a pragmatic middle step.
- Verification needed: Tests that a strategy with funding/cross-sectional
  required observables cannot satisfy readiness with only one `close` ref.

## Unknown Unknowns And Assumption Risks

| Assumption | Why it may be wrong | How to test or de-risk |
|---|---|---|
| `quant_data` loaders provide stable, complete `available_at` semantics | This repo validates rows but does not control upstream materialization | Run integration tests against real `quant_data` datasets and record row-contract feedback |
| VectorBT Pro metrics/accessors behave like the fake tests | The real smoke test was skipped unless `RUN_VECTORBTPRO_SMOKE=1` | Run real smoke in CI or scheduled local validation for evaluation changes |
| `quant_autoresearch` consumes result objects and artifacts correctly | This review did not inspect downstream code | Audit `quant_autoresearch` against the documented three public APIs |
| Candidate-local workspaces are outside this repo | Tests use temp dirs, but real users may create candidates inside repo | Enforce/ignore generated roots and provide templates |
| Strategy-declared observations approximate consumed data | Strategies can under-declare observables | Add per-strategy or per-family observable contracts |

## Overbuilt / Underbuilt / Right-Sized

Overbuilt:

- `validation/__init__.py` is a large facade that mixes orchestration, failure
  mapping, artifact writing, scenario execution, and report text. It is not a
  blocker because it has helper modules and tests, but future changes should
  split by responsibility instead of adding more local helpers.
- Some historical phase plans remain in `plans/` and include stale "OPEN" or
  implementation-history language. They are not code debt, but they are agent
  context debt.
- The package namespace is still runner-centric (`runner.cli`,
  `runner.execution`) relative to the current three-job ontology.

Underbuilt:

- Evaluation funding semantics for crypto perps.
- Evaluation failure artifacts.
- Evaluation metric completeness/coverage semantics.
- Validation duplicate-window/collision checks.
- Ignored generated roots for candidate-local evaluation output.
- Evaluation config/template docs.
- Observation lineage proof.

Right-sized:

- Flat pure strategy files.
- Narrow default decision ontology with explicit extended imports.
- `StrategyExecutionSpec` as a neutral execution input.
- Pydantic at external/config/decision boundaries.
- Strict hidden-lookahead replay including suppression checks.
- Advisory validation vocabulary and forced false promotion/live flags.
- Tiered quick-run artifacts and replayability metadata.
- Validation ledger replayability and artifact hashing.
- Avoiding legacy compatibility shims.

## Documentation And Decision Gaps

- Add an ADR or decision record for evaluation funding semantics:
  unsupported-until-modeled vs portfolio funding cashflow support.
- Add an ADR or decision record for threshold exit semantics:
  close/quote-sampled thresholds vs intrabar OHLC barriers.
- Add reference docs for path anchoring and `--repo-root` behavior. Quick runs
  resolve relative paths repo-root-first; validation/evaluation configs are
  candidate-local and relative CLI paths depend on CWD unless `--repo-root` is used.
- Add a checked-in evaluation TOML template. The docs describe evaluation as a
  first-class workflow, but concrete config examples currently live in tests.
- Collapse or archive historical phase plans so active docs optimize for a new
  session's current state rather than implementation chronology.

## ASCII Architecture / Lifecycle Diagrams

Current boundary fit:

```text
                         +----------------------+
                         |  PRD / locked intent |
                         +----------+-----------+
                                    |
                                    v
+------------+     +-----------------------------+     +------------------+
| strategy.py | --> | shared execution spine      | --> | typed decisions  |
| pure file   |     | load/freeze/validate/replay |     | + row evidence   |
+------------+     +--------------+--------------+     +--------+---------+
                                  |                         |
              +-------------------+-------------------------+------------------+
              |                                             |                  |
              v                                             v                  v
        quick run                                    validation run       evaluation run
   diagnostic engine evidence                    advisory mechanical     portfolio/path
   summary/diagnostic/full                       evidence + verdict      evidence
```

Recommended dependency direction:

```text
quant_strategies.core / kernel
  config, execution, data contract, causality, engine request builder
        ^
        |
  +-----+----------+----------------+
  |                |                |
runner         validation       evaluation
quick run      mechanical       frozen-candidate
surface        evidence         portfolio evidence
```

## Preserve / Refactor / Simplify / Add / Retire Action Map

| Action class | Findings / recommendations | Rationale |
|---|---|---|
| Preserve | Strategy contract, row contract, strict causality, validation ledger replayability, no-promotion fields, public three-job vocabulary | These are right-sized and aligned with the PRD |
| Refactor | A1 funding/evaluation semantics, A2 runner-owned kernel namespace, Q1 threshold exits, Q2 metric completeness, Q3 same-timestamp rotations, E2 scenario exception boundary | These keep the capability but move the model/contract to the right boundary |
| Simplify | E4 align validation config-load behavior with typed result contract; keep CLI a thin neutral dispatcher | Reduces special cases for `quant_autoresearch` and users |
| Add | A3 evaluation backend protocol, E1 failure artifacts, E3 duplicate-window checks, E5 ignored evaluation output root, Q4 stronger observation coverage, evaluation config template | Missing contracts/artifacts needed for trustworthy use |
| Retire | Stale active phase-plan context and any future compatibility shims for old output shapes | Prevents implementation history and legacy artifacts from biasing future work |

## Prioritized Recommendations

| Priority | Action class | Recommendation | Why now | Verify |
|---|---|---|---|---|
| P1 | Refactor | Decide and enforce evaluation funding semantics for `crypto_perp_funding` | Avoids portfolio evidence for the wrong economic object | Crypto perp evaluation unsupported or funding-inclusive test |
| P1 | Refactor | Fix threshold-exit naming or implement OHLC barrier semantics | Current labels can mislead PnL interpretation | Intrabar breach/no-breach tests |
| P1 | Refactor | Make evaluation metric completeness/coverage explicit | Prevents `evaluation_complete` with broken/null core metrics | Accessor-error and non-finite-return tests |
| P1 | Add | Write durable evaluation failure artifacts after result-dir creation | Agents need artifact-level failure evidence | Tests for post-init failure artifacts |
| P2 | Add | Reject duplicate validation window IDs and sanitized path collisions | Prevents artifact overwrite before policy classification | Validation config collision tests |
| P2 | Add | Ignore or constrain `evaluation_results/` | Prevents tracked generated evidence and legacy bias | `.gitignore`/boundary test |
| P2 | Simplify | Align validation config-load API behavior with runner/evaluation | Simplifies public consumer contract | Invalid config API tests |
| P2 | Add | Strengthen observation coverage rules | Improves auditability of real strategy inputs | Readiness tests for required observables |
| P3 | Refactor | Move shared execution implementation out of `runner` namespace | Improves dependency direction without changing behavior | Boundary import tests |
| P3 | Add | Add evaluation TOML template and path anchoring docs | Faster onboarding, fewer config mistakes | Docs test or example config load test |
| P3 | Retire | Archive/collapse historical phase plans | Reduces stale context for agents | Stale-reference grep |

## NOT In Scope

- No implementation changes were made in this review.
- No market validation, statistical proof, benchmark-relative metrics, capacity
  modeling, paper trading, live trading, order routing, or dashboards.
- No review of `quant_data` internals.
- No review of `quant_autoresearch` internals.
- No generated artifact audit of old `results/` directories.

## Verification Summary

Verified:

- Full local test suite: `847 passed, 1 skipped`.
- CodeGraph project index was healthy: 119 indexed files.
- Public surfaces, config loaders, execution kernel, causality, engine PnL,
  validation/evaluation artifact paths, docs, tests, and repository boundaries
  were inspected.
- Required review lenses were run independently and reconciled.

Not verified:

- Real VectorBT Pro smoke test.
- Real `quant_data` database integration.
- `quant_autoresearch` downstream behavior.

Residual risk:

- The foundation is strong enough to keep building on, but not strong enough to
  treat evaluation evidence as fully trustworthy for all supported data kinds
  until the P1 evaluation semantics issues are fixed.
