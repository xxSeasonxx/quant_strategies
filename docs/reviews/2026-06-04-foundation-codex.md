# Codex Foundation Review

Date: 2026-06-04
Reviewer: Codex, consolidated with `review-claude.md` and independent
onboarding, architecture, senior engineering, adversarial, and senior quant
math lenses.
Artifact status: archived historical review; accepted cleanup findings are
dispositioned by `FOUNDATION_LOCK.md` and current tests/docs.

## Executive Verdict

The foundation is sound enough to begin controlled quick-run, validation, and
evaluation runs. I found no critical math blocker in the inspected execution
kernel, funding sign/window logic, quote fill sidedness, portfolio NAV ledger,
data-audit gates, or current strategy timing tests.

This is not a rewrite case. The workflow is simple at the user boundary:
provide a pure strategy file plus a TOML config, then run one of three public
jobs: `run`, `validate`, or `evaluate`. The internal layering looks heavy in
file size, but most layers are justified boundaries: config parsing, neutral
execution spec, shared execution kernel, row contract/audit, quick-run trade
activity evidence, and portfolio/NAV evaluation evidence each have distinct
reasons to change.

The main risks before scaling repeatable runs are not hidden legacy output
compatibility or a broken math core. They are smaller reproducibility,
contract, and process issues:

1. The numeric evaluation backend is not version-bounded: `quant-data` is
   bounded, but `vectorbtpro` is unconstrained and `pandas`/`pyarrow` are only
   lower-bounded.
2. Windowed validation/evaluation configs carry duplicate date fields, and the
   `[data]` dates are silently overwritten by `[[windows]]`.
3. Evaluation artifact aggregation nulls annualized/risk metrics on cadence
   `warning` but not on cadence `insufficient`, despite docs saying those
   metrics require cadence status `ok`.
4. Crypto perp funding evidence can accrue zero funding without warning when a
   `crypto_perp_funding` window contains no funding events.
5. Validation CLI exit-code taxonomy treats `data_load` differently from
   evaluation.
6. Custom evaluation scenario configs can weaken stress coverage if an
   auto-research caller supplies only optional or cherry-picked scenarios.

Those are fixable without changing the foundation shape. Start controlled runs,
but do not treat quick-run diagnostics, optional scenarios, cross-version
numeric comparisons, or any historical artifacts as stronger evidence than
their contracts say.

## Scope And Evidence Inspected

### Locked Objective

`/Users/Season_Yang/Personal/quant_strategies` should serve Season and
downstream `quant_autoresearch` by enabling auditable strategy definition,
configured experiment runs, validation, evaluation, and artifact review across
a research lifecycle from idea/provenance to executable evidence. A solid
foundation should make it easy to start running strategies with trustworthy
math, clean workflow, clear contracts, and low ceremony, while preventing
critical signal/PnL/timing/data-leakage errors, hidden legacy compatibility
paths, stale artifacts biasing decisions, and layered abstractions that obscure
the research model.

### Evidence

Primary source/test/config evidence:

- Repo instructions: `AGENTS.md`.
- Product intent and contracts: `PRD.md`, `README.md`,
  `docs/foundation-surfaces.md`, `FOUNDATION_LOCK.md`, `TODOS.md`.
- Public entry points: `src/quant_strategies/cli.py`,
  `src/quant_strategies/runner/__init__.py`,
  `src/quant_strategies/validation/_pipeline.py`,
  `src/quant_strategies/evaluation/_pipeline.py`.
- Shared spine: `src/quant_strategies/core/config.py`,
  `src/quant_strategies/core/execution.py`,
  `src/quant_strategies/core/data_loader.py`,
  `src/quant_strategies/core/data_audit.py`.
- Math/evidence boundaries: `src/quant_strategies/engine/evaluation.py`,
  `src/quant_strategies/core/engine_runner.py`,
  `src/quant_strategies/funding.py`,
  `src/quant_strategies/evaluation/vectorbtpro_backend.py`,
  `src/quant_strategies/evaluation/metrics.py`,
  `src/quant_strategies/evidence_semantics.py`,
  `src/quant_strategies/causality.py`.
- Strategy modules: `untested/*.py`, `examples/strategies/simple_momentum.py`.
- Config examples: `runs/*.toml`, `examples/strategies/*.toml`.
- Boundary and math-heavy tests under `tests/`.
- Consolidation input: `review-claude.md`, re-checked against source/test
  evidence before any claim was merged here.

The original independent lens agents were explicitly told not to read
`docs/reviews/*` or root `review-*.md` files, which helped reduce echo from
existing review output. This consolidation pass then read `review-claude.md`
as a secondary claim source, not as proof.

### Verification Run

- `conda run -n quant pytest -q tests/test_funding.py tests/test_engine_screen.py tests/test_engine_executable.py tests/test_validation_lookahead.py tests/test_validation_future_poison.py tests/test_validation_data_audit.py tests/test_validation_backends_and_policy.py tests/test_evaluation_backend.py tests/test_evaluation_runner.py tests/test_repository_boundaries.py tests/test_strategy_docstrings.py`
  - Result: 224 passed, 1 skipped.
- `conda run -n quant env RUN_VECTORBTPRO_SMOKE=1 pytest -q tests/test_evaluation_backend.py::test_vectorbtpro_evaluation_backend_real_smoke_if_installed`
  - Result: 1 passed.
- `conda run -n quant pytest -q`
  - Result: 958 passed, 1 skipped.

Not verified:

- I did not inspect `quant_autoresearch` or `quant_data` source.
- I did not run the checked-in strategy TOMLs against live `quant_data`
  datasets.
- I did not validate strategy alpha, capacity, regime robustness, benchmark
  edge, or promotion readiness.

## Intended Foundation Model

The minimal healthy foundation is a stateless evidence producer:

```text
Season / quant_autoresearch
        |
        | supplies strategy.py + explicit TOML
        v
public job: run | validate | evaluate
        |
        | adapts config into StrategyExecutionSpec
        v
shared execution kernel
        |
        | import strategy -> validate params -> load quant_data rows
        | -> normalize row contract -> freeze rows/params
        | -> generate typed StrategyDecision[]
        v
audit boundary
        |
        | row contract + observation lineage + hidden-lookahead replay
        v
quick diagnostics OR validation evidence OR portfolio evaluation evidence
        |
        v
typed result + artifacts
        |
        | consumed externally
        v
ranking / comparison / search memory / promotion outside this repo
```

What should be deliberately deferred:

- Ranking, search memory, stopping rules, and promotion automation.
- Data acquisition, refresh, repair, and joins.
- Paper/live trading concerns.
- Broad refactors of large modules unless touching their responsibilities for a
  real fix.

## Project Ontology

Core actors:

- Season: senior quant researcher and human promotion decision maker.
- `quant_autoresearch`: external candidate generation and iteration owner.
- Strategy author: human or agent writing one flat pure strategy file.
- `quant_data`: upstream data owner.
- `quant_strategies`: stateless evidence producer.

Core concepts:

- Strategy module: one file exposing `generate_decisions(rows, params)` and, for
  validation/evaluation, `validate_params`.
- Params: explicit config values normalized by a strategy-owned validator.
- Rows: normalized point-in-time observations from `quant_data`.
- Decision: typed `StrategyDecision` with instrument, intent, decision time,
  as-of time, target, exit policy, observations, and metadata.
- Execution spec: neutral kernel input with no output/artifact policy.
- Quick run: diagnostic evidence for one strategy version.
- Validation run: retained-candidate mechanical evidence, advisory only.
- Evaluation run: frozen-candidate portfolio/path/economic evidence, advisory
  only.
- Artifact: evidence record, not truth.

Hard invariants:

- Strategies must not load data, call engines, write artifacts, use clocks/RNG,
  or depend on future rows.
- Decisions must not use information unavailable at `decision_time`.
- Validation/evaluation require `validate_params`.
- Quick-run trade activity metrics are not NAV-path portfolio returns.
- Evaluation NAV/path evidence is separate from validation trade-activity sums.
- No result authorizes promotion, paper trading, live trading, or autonomous
  ranking.
- Generated artifacts are disposable and should be rerun after contract fixes.

## What Already Exists And Should Be Reused

- **Three public surfaces.** The CLI exposes only `run`, `validate`, and
  `evaluate` in `src/quant_strategies/cli.py:24-41`; the console script points
  to `quant_strategies.cli:main` in `pyproject.toml`.
- **Narrow public imports.** Current docs tell consumers to use
  `runner.run_config`, `validation.run_validation`, and
  `evaluation.run_evaluation`, not internals.
- **Neutral execution spec.** `StrategyExecutionSpec` is output-policy-free in
  `src/quant_strategies/core/config.py:69-88`.
- **Shared execution kernel.** `execute_strategy_run` owns strategy import,
  param validation, data loading, row normalization, freezing, and decision
  validation in `src/quant_strategies/core/execution.py:74-187`.
- **Strict validation/evaluation preflight.** Validation runs `audit_decision_rows`
  and strict hidden-lookahead replay before scenario backends
  (`src/quant_strategies/validation/_pipeline.py:353-428`). Evaluation runs
  row contract, data audit, and strict causality before portfolio metrics
  (`src/quant_strategies/evaluation/_pipeline.py:189-251`).
- **Explicit evidence semantics.** Quick-run/validation trade metrics are
  labeled "signed target-weighted trade activity; not portfolio NAV" in
  `src/quant_strategies/evidence_semantics.py:42-85`.
- **Generated output isolation.** `.gitignore:6-10` ignores `results/`,
  `validation_results/`, `evaluation_results/`, worktrees, caches, and egg-info.
- **Repository boundary tests.** `tests/test_repository_boundaries.py` asserts
  no research archive directory, no loop-memory markers, generated roots are
  ignored, `quant-data` is version-bounded, and validation/evaluation do not
  import runner internals.
- **Strategy contract tests.** `tests/test_strategy_docstrings.py` checks
  rationale headings, auditable provenance anchors, flat layout, and static
  purity lint for strategy files.

## Architecture And Boundary Review

The public architecture is right-sized.

```text
CLI
 |
 +-- runner.run_config       quick diagnostics
 +-- validation.run_validation mechanical retained-candidate evidence
 +-- evaluation.run_evaluation stateless frozen-candidate evidence
          |
          v
     StrategyExecutionSpec
          |
          v
     execute_strategy_run
          |
          v
 rows + params + decisions + row hashes + evidence quality
```

The main design should be preserved:

- Validation and evaluation adapt into `StrategyExecutionSpec`; neither calls
  the quick-run `RunConfig`.
- The engine package is internal and used by quick run/validation. It is not a
  fourth public workflow.
- Evaluation branches from rows/decisions into portfolio/NAV evidence instead
  of pretending NAV and linear trade-activity sums are interchangeable.
- Backend injection uses explicit Protocols rather than reflection:
  `src/quant_strategies/evaluation/backends.py:15-57`.

One wording caveat from the Claude review is valid: repo docs sometimes say
"one execution kernel." In code, the precise claim is one shared
strategy-decision/spec kernel plus a deliberately forked price path:
quick-run/validation use the engine trade-activity screen, while evaluation
uses portfolio/NAV backends.

The main architecture concern is not "too many layers." It is large module
weight. These central files total about 5,651 lines:

```text
runner/__init__.py                 712
validation/_pipeline.py            999
evaluation/_pipeline.py           1165
evaluation/vectorbtpro_backend.py 1215
data_contract.py                   888
causality.py                       465
core/execution.py                  207
```

That is maintainability drag, but it is not evidence for a rewrite. Split
sub-responsibilities when touching them for real fixes; do not add wrappers for
their own sake.

## Engineering, Testability, And Operability Review

Strengths:

- Full suite is green: 958 passed, 1 skipped.
- Real VectorBT Pro smoke passed when enabled.
- Config schemas use Pydantic with `extra="forbid"` for the main public
  surfaces.
- Strategy params fail fast on unknown keys in current strategy modules.
- Failure results are structured across main stages instead of raw tracebacks.
- CLI exit codes distinguish ordinary failures from data/audit failures for
  quick runs and evaluation.

Operability concerns:

- Validation can return `run_completed=True` with non-null `failure_stage`
  (`src/quant_strategies/validation/_pipeline.py:670-682`). Docs correctly say
  success requires both `run_completed` and `failure_stage is None`, but adding
  a derived `succeeded` field/property would reduce downstream misuse.
- Validation records data-load failures as `failure_stage="data_load"`
  (`src/quant_strategies/validation/_pipeline.py:289-291`), but validation CLI
  exit-code logic does not map `data_load` to exit 3, while evaluation does
  (`src/quant_strategies/cli.py:131-148`).
- The default full test suite reads review-archive disposition files through
  active tests (`tests/test_repository_boundaries.py:185-210`,
  `tests/test_evaluation_docs.py:72-83`). This is not a runtime blocker, but it
  makes "source-only, no prior review artifact" verification harder.

## Domain-Specific Quant Lens Findings

### Correct Core Math And Timing

I did not find a critical sign/unit/timing error in the inspected math core.

- Engine gross return is signed price return times target weight; cost is
  round-trip bps times target weight; net is gross plus funding minus cost:
  `src/quant_strategies/engine/evaluation.py:70-81`.
- Quote fills pay spread in the expected direction: long uses ask on entry and
  bid on exit; short uses bid on entry and ask on exit:
  `src/quant_strategies/engine/evaluation.py:253-263`.
- Funding uses `entry < ts <= exit`, deduplicates matching rates, rejects
  conflicting rates, and applies `sum(-direction * rate) * weight`, so longs
  pay positive funding and shorts receive it:
  `src/quant_strategies/funding.py:24-44`.
- Evaluation perp ledger applies funding cashflows to cash, realizes signed PnL
  at exit, subtracts fees, marks NAV through cash plus open-position PnL, and
  fails on open positions after the ledger:
  `src/quant_strategies/evaluation/vectorbtpro_backend.py:483-581`.
- Required final metrics use the actual final sample, not "last finite":
  `src/quant_strategies/evaluation/vectorbtpro_backend.py:1077-1084`.
- Built-in evaluation metrics use full-grid returns, sample floors, and null
  annualized/risk metrics below `min_annualized_samples`:
  `src/quant_strategies/evaluation/vectorbtpro_backend.py:775-812` and
  `src/quant_strategies/evaluation/vectorbtpro_backend.py:849-890`.

### Quant Finding: Annualized/Risk Metric Nulling Is Incomplete At Pipeline Level

Severity: Important but not a controlled-run blocker with built-in backends.

Action class: Add.

Evidence:

- Docs and metric semantics say annualized/risk metrics require
  `annualization_cadence.status == ok`:
  `src/quant_strategies/evaluation/metrics.py:33-37`,
  `README.md` annualization section, and `docs/foundation-surfaces.md`
  evaluation section.
- `_annualization_cadence_summary` can return `status="insufficient"` when it
  cannot infer cadence from trace tables:
  `src/quant_strategies/evaluation/_pipeline.py:770-792`.
- `_completion_artifact_results` only nulls annualized/risk metrics when status
  is `warning`, not when status is `insufficient`:
  `src/quant_strategies/evaluation/_pipeline.py:745-767`.

Why it matters:

The built-in VectorBT/perp-ledger backends already null those metrics using
return-sample floors, so normal runs are not currently blocked. But the public
`run_evaluation(..., backend=...)` injection path can return completed metrics,
and the artifact writer can preserve non-null annualized/risk metrics even when
the cadence status is not `ok`. That violates the artifact contract and could
mislead a downstream reviewer using a custom backend.

Recommended action:

Null `annualized_return`, `volatility`, `sharpe`, `sortino`, and `calmar`
whenever `annualization_cadence.status != "ok"`, not only when it is
`"warning"`. Add a regression test with a completed backend result whose
`portfolio_path` cannot establish cadence.

## Material Findings

### F1. Windowed Validation/Evaluation Configs Have Two Date Sources

Severity: Important workflow simplicity issue, not a math blocker.

Action class: Simplify.

Evidence:

- `DataConfig` requires `start` and `end`: `src/quant_strategies/core/config.py:23-45`.
- Validation overwrites those dates from the selected window:
  `src/quant_strategies/validation/config.py:259-270`.
- Evaluation does the same:
  `src/quant_strategies/evaluation/config.py:167-176`.
- A test confirms mismatched `[data]` dates are accepted and ignored:
  `tests/test_validation_config.py:386-406`.

Why it matters:

The foundation objective says configs should be small, typed, and hard to
misuse for `quant_autoresearch`. Duplicate date fields create a false source
of truth. An agent can mutate `[data].start/end` and think it changed a
validation/evaluation run when the window still controls execution.

Recommended action:

Pick one policy:

- Preferable: remove or make optional `[data].start/end` for windowed
  validation/evaluation configs and derive data windows exclusively from
  `[[windows]]`.
- Smaller compatibility-preserving step: require `[data].start/end` to bound or
  exactly match all configured windows and fail config load on mismatch.

Tradeoff:

Removing the fields is cleaner but changes TOML shape. Bounding/equality checks
are less clean but a smaller migration.

### F2. Numeric Backend Versions Are Not Bounded

Severity: Important reproducibility hygiene, not a math blocker.

Action class: Add.

Evidence:

- `quant-data` is bounded as `quant-data>=0.1.0,<0.2.0`:
  `pyproject.toml:10-13`.
- The optional evaluation dependencies use `pandas>=2.2`, `pyarrow>=16`, and
  bare `vectorbtpro`: `pyproject.toml:16-23`.
- Validation/evaluation artifacts do record runtime package versions in
  `environment.json`, including `pandas`, `pyarrow`, and `vectorbtpro`:
  `src/quant_strategies/validation/manifest.py:63-67` and
  `src/quant_strategies/evaluation/artifacts.py:321-324`.

Why it matters:

This does not make existing math wrong, and it is not invisible in artifacts.
But repeated evaluation over time or across machines can change numeric
behavior after a package upgrade while the project dependency contract permits
the upgrade. That weakens comparability of reruns and candidate rankings.

Recommended action:

Add an evaluation environment constraint or lock policy for `vectorbtpro`,
`pandas`, and `pyarrow`. If hard upper bounds in `pyproject.toml` are
impractical because of private-package distribution, record the supported
evaluation environment in a constraints file or docs and make run comparison
tooling surface version mismatches.

### F3. Crypto Perp Funding Can Be Silently Zero When No Events Exist

Severity: Important data/evidence guard, not a core funding-sign bug.

Action class: Add.

Evidence:

- The row contract requires `has_funding_event` for `crypto_perp_funding`, but
  it does not require at least one row with `has_funding_event = true`:
  `src/quant_strategies/data_contract.py:469-482` and
  `src/quant_strategies/data_contract.py:605-672`.
- Engine funding returns `0.0` when the indexed bars have no funding events:
  `src/quant_strategies/engine/evaluation.py:269-278`.
- The evaluation perp ledger reports `funding_event_count`, so zero funding is
  detectable in evaluation artifacts but not promoted to a warning/failure:
  `src/quant_strategies/evaluation/vectorbtpro_backend.py:622-623`.

Why it matters:

If a `crypto_perp_funding` dataset is mis-loaded, filtered too narrowly, or
missing funding rows, a strategy can appear to avoid carry costs because the
engine accrues zero funding. Real perp datasets should include funding, so this
is a data-coverage guard, not an accounting formula failure.

Recommended action:

Warn or fail when an active `crypto_perp_funding` trade/evaluation window spans
no funding events for the traded symbol. Add a regression test covering a
non-empty price window, an active perp position, and zero funding events.

### F4. Validation CLI Misclassifies Data-Load Failures

Severity: Important operability issue, not a research-math blocker.

Action class: Refactor.

Evidence:

- Validation sets `state.failure_stage = "data_load"` on data-load failures:
  `src/quant_strategies/validation/_pipeline.py:289-291`.
- `_validation_exit_code` maps only `_DATA_FAILURE_STAGES` to exit 3; that set
  omits `data_load`: `src/quant_strategies/cli.py:16-21` and
  `src/quant_strategies/cli.py:131-140`.
- `_evaluation_exit_code` explicitly maps `data_load` to exit 3:
  `src/quant_strategies/cli.py:143-148`.

Why it matters:

For automation, a data-load failure should be distinguishable from generic
infrastructure failure. The evaluation surface already treats it that way.
Validation should be consistent, especially because validation is the retained
candidate mechanical evidence workflow.

Recommended action:

Centralize failure-stage to exit-code mapping and include `data_load` in the
validation data-failure taxonomy. Add a CLI test for validation data-load
failure.

### F5. Custom Evaluation Scenario Coverage Can Be Weakened By Config

Severity: Important assumption risk for automated frozen-candidate evaluation;
not a blocker for human-controlled runs.

Action class: Add.

Evidence:

- Custom `[[scenarios]]` replace the default six-scenario matrix:
  `src/quant_strategies/evaluation/scenarios.py:27-49`.
- Each custom scenario can be `required = false`:
  `src/quant_strategies/evaluation/config.py:92-99`.
- Optional scenario failures are non-blocking:
  `src/quant_strategies/evaluation/_pipeline.py:562-572` and
  `tests/test_evaluation_runner.py:527-540`.

Why it matters:

This is correct flexibility for explicit human use, but it is dangerous if
`quant_autoresearch` can generate evaluation configs. A custom config with only
optional or cherry-picked scenarios can emit `evaluation_complete` while
omitting the default stress coverage that a reviewer expects.

Recommended action:

Define a frozen-candidate evaluation policy:

- Require at least one required scenario.
- Optionally require the default six-scenario matrix unless an explicit
  `scenario_policy = "custom"` declaration is present.
- Surface `scenario_coverage.required_count` prominently to downstream
  consumers.

### F6. Evaluation Backend Module Fuses VectorBT Adapter And Project Perp Ledger

Severity: Moderate maintainability issue.

Action class: Refactor.

Evidence:

- `VectorBTProEvaluationBackend` reports `project_perp_ledger_v1` for
  `crypto_perp_funding`: `src/quant_strategies/evaluation/vectorbtpro_backend.py:55-61`.
- The same class prepares inputs for both VectorBT and project ledger paths:
  `src/quant_strategies/evaluation/vectorbtpro_backend.py:63-86`.
- `run_prepared` dispatches to `_run_perp_ledger` in the same module:
  `src/quant_strategies/evaluation/vectorbtpro_backend.py:123-164`.
- `_run_perp_ledger` starts at
  `src/quant_strategies/evaluation/vectorbtpro_backend.py:459`.

Why it matters:

The current behavior is defensible and tested, but the name hides two different
accounting contexts. If another portfolio backend or another project-owned
ledger appears, this file will become the wrong abstraction boundary.

Recommended action:

When this area is next touched, split into an explicit backend selector plus
separate `VectorBTProPortfolioBackend` and `ProjectPerpLedgerBackend`. Do not
split only for aesthetics.

### F7. Active Verification Still Knows About Review Archives

Severity: Moderate process/noise issue.

Action class: Retire.

Evidence:

- Active tests assert review archive disposition content:
  `tests/test_repository_boundaries.py:185-210`.
- Active docs tests require a specific archived review disposition file:
  `tests/test_evaluation_docs.py:72-83`.

Why it matters:

The tests are trying to ensure old reviews are marked superseded, which is
reasonable. But for a "fresh, source-first, do not bias by prior output" review,
the default test suite still reads prior review artifacts.

Recommended action:

Move archive-content assertions to an opt-in docs/archive maintenance check, or
reduce default tests to checking that active docs point to `FOUNDATION_LOCK.md`
and that archived files are dated. This is not a strategy-run blocker.

## Unknown Unknowns And Assumption Risks

- `quant_data` was not inspected. Loader API compatibility is bounded in
  package metadata, but real data quality and availability remain upstream
  risks.
- `quant_autoresearch` was not inspected. The foundation is safe only if the
  external loop respects public surfaces and treats quick runs, validation, and
  evaluation according to their advisory semantics.
- Runtime package versions are recorded in validation/evaluation
  `environment.json`, but the evaluation numerical stack is not bounded in the
  dependency contract. Cross-time comparisons assume environment discipline.
- Row hashes are order-sensitive because rows are consumed as ordered strategy
  input. That is acceptable only if `quant_data` order is stable or this repo
  explicitly normalizes row order before both hashing and strategy execution.
- The checked-in `runs/*.toml` files are quick-run diagnostic configs with zero
  costs. They are not frozen-candidate validation/evaluation evidence.
- `crypto_perp_funding` assumes funding events are present when perp positions
  are active. Missing events currently look like zero carry unless a reviewer
  notices `funding_event_count`.
- Strategy alpha, capacity, benchmark-relative edge, slippage realism, and
  regime robustness are outside this foundation review.
- Purity lint is intentionally best-effort, not a sandbox
  (`src/quant_strategies/decisions/purity.py:1-9`). This is acceptable for
  trusted local strategy code; untrusted generated code would require a
  sandbox/subprocess policy.
- Generated caches and `src/quant_strategies.egg-info` are present on disk but
  ignored and untracked. They are noise, not foundation evidence.

## Overbuilt, Underbuilt, And Right-Sized Areas

Right-sized:

- Three public jobs: quick run, validation run, evaluation run.
- Flat pure strategy modules.
- Shared `StrategyExecutionSpec` and `execute_strategy_run`.
- Strict validation/evaluation preflight before evidence.
- Separate quick-run/validation trade-activity evidence and evaluation NAV/path
  evidence.
- Advisory-only promotion language.
- Tiered quick-run artifact profiles.
- Generated artifact roots ignored by git.

Underbuilt:

- Evaluation dependency/version policy is too loose for cross-time numeric
  comparability.
- Windowed config date ownership is not explicit enough.
- Perp funding event coverage is not promoted to warning/failure.
- Evaluation scenario coverage policy is too permissive for autonomous config
  generation.
- Validation CLI failure taxonomy is inconsistent with evaluation for
  `data_load`.
- Row-order ownership is implicit in the upstream `quant_data` contract.
- There is no single `succeeded` field/property across public result types.

Overbuilt or at risk:

- Central orchestrator/backend files are large. Split when a touched
  responsibility has a clear new home; avoid churn-only refactors.
- The validation backend registry has only one implementation. It is not
  harmful, but it is a trim candidate if validation backend ownership is next
  touched.
- VectorBT helper code is duplicated across validation/evaluation in small
  leaf routines. Hoist only when touching that area for real work.
- Active tests know too much about review archives.
- Do not add ranking, search memory, candidate registries, compatibility shims,
  or old artifact readers to this repo.

## Missing Docs, PRD, ADR, Or Decision Records

Add or update durable docs only for decisions that affect future behavior:

- Date-source policy for windowed validation/evaluation configs.
- Evaluation dependency/version policy for `vectorbtpro`, `pandas`, and
  `pyarrow`.
- Row-order policy: upstream guarantee versus local normalization before both
  hashing and execution.
- Funding event coverage policy for `crypto_perp_funding` windows.
- Frozen-candidate scenario coverage policy.
- Metric semantics note for the Sortino denominator convention and for the
  engine funding basis versus evaluation ledger funding basis.
- "No lookahead" note: the replay proves point-in-time causality, not
  out-of-sample validity or freedom from in-sample parameter fitting.
- Architecture wording: "one shared decision/spec kernel plus forked price
  evidence path" is more precise than blanket "one execution kernel."
- Evaluation backend ownership if/when `ProjectPerpLedgerBackend` is split from
  the VectorBT adapter.
- CLI failure-stage taxonomy if centralized.

The PRD is otherwise unusually clear and should remain the product-intent
source of truth.

## Consolidation Self-Review

I re-checked `review-claude.md` against source before merging it. Findings
carried forward:

- Numeric backend version policy is underbuilt. This is a reproducibility issue,
  not a hidden math error, because validation/evaluation artifacts already
  record runtime package versions.
- Zero-funding-event handling is a real data-coverage guard for
  `crypto_perp_funding`, not a funding sign or window bug.
- Docs should be more precise about "one execution kernel," Sortino convention,
  funding bases, and what the lookahead replay does and does not prove.

Findings not carried forward as action items:

- The adversarial "end-of-history lookahead" claim is not supported by the
  inspected code. The replay truncates to causally available rows and enforces
  `as_of_time <= decision_time`. What remains is ordinary in-sample fitting
  risk, already outside this foundation's promise.
- "Sort normalized rows before hashing" is not accepted as a standalone fix.
  Row order is part of strategy input semantics; changing only the hash would
  be wrong. The real decision is whether row order is owned upstream or locally
  normalized before both hashing and execution.
- Low-level rename/docstring/type-style notes were left out of the action map
  unless they affect a contract, math interpretation, or workflow. They are not
  important enough to compete with early-run fixes.
- Quick-run `assessment_status = diagnostics_complete` remains a preserve
  boundary, not an action item.

## Action Map

| No. | Status | Severity | Action | Area | Recommendation |
| --- | --- | --- | --- | --- | --- |
| 1 | Open | P2 | Add | Evaluation metrics | Null annualized/risk metrics whenever `annualization_cadence.status != "ok"`; add a custom-backend/insufficient-cadence regression test. |
| 2 | Open | P2 | Simplify | Validation/evaluation config | Remove duplicate `[data].start/end` for windowed jobs or validate that they bound/equal all windows. |
| 3 | Open | P2 | Refactor | CLI operability | Include validation `data_load` in data-failure exit-code taxonomy and centralize mapping. |
| 4 | Open | P2 | Add | Evaluation policy | Define minimum required scenario coverage for frozen-candidate/custom evaluation configs. |
| 5 | Deferred | P3 | Refactor | Evaluation backend | Split VectorBT portfolio adapter from project perp ledger when this area is next touched for real work. |
| 6 | Deferred | P3 | Retire | Review archive tests | Move review-archive content assertions out of default foundation tests if source-only verification is required. |
| 7 | Deferred | P3 | Add | Result ergonomics | Add a derived `succeeded`/terminal status helper across public result types. |
| 8 | Open | P2 | Add | Reproducibility | Add an evaluation dependency/version constraint or lock policy for `vectorbtpro`, `pandas`, and `pyarrow`; surface version mismatches when comparing runs. |
| 9 | Open | P2 | Add | Perp funding audit | Warn or fail when an active `crypto_perp_funding` window has zero funding events for the traded symbol; add a regression test. |
| 10 | Deferred | P3 | Add | Row-order policy | Decide whether `quant_data` owns stable row order or this repo normalizes rows before both hashing and execution. |
| 11 | Deferred | P3 | Add | Documentation semantics | Clarify shared decision kernel versus forked price path, Sortino denominator convention, funding bases, and no-lookahead versus in-sample fitting. |

## Preservation Constraints

These are not action items. They are current foundation boundaries that should
remain stable unless Season intentionally changes the product model:

- Keep `run`, `validate`, and `evaluate` as the only public jobs.
- Keep all surfaces adapting into `StrategyExecutionSpec` and
  `execute_strategy_run`.
- Keep validation trade activity separate from evaluation NAV/path evidence.

## Prioritized Recommendations

1. Start controlled runs, but pin or otherwise lock the evaluation numeric
   environment before relying on cross-time or cross-machine comparisons.
2. Fix the annualization cadence `insufficient` nulling gap. It is small and
   protects artifact semantics.
3. Decide the windowed config date policy before `quant_autoresearch` depends
   on generated validation/evaluation TOML shapes.
4. Add the perp zero-funding-event guard if `crypto_perp_funding` runs are in
   scope for early evaluation.
5. Fix validation `data_load` CLI exit-code classification.
6. Add a frozen-candidate scenario coverage policy if auto-generated
   evaluation configs are in scope.
7. Treat existing generated artifacts as disposable and rerun after any
   contract-level fix.

## NOT In Scope

- Promotion out of `untested/`.
- Paper/live trading readiness.
- Strategy alpha assessment.
- Capacity, execution venue realism, borrow/margin/risk limits.
- `quant_autoresearch` architecture or code.
- `quant_data` architecture or code.
- Rewriting the project or refactoring large files without a touched root cause.
