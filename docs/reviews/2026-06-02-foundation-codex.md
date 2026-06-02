# Foundation Review: quant_strategies

Date: 2026-06-02
Reviewer: Codex, senior quant researcher lens
Target: repository root

## Review Objective

I reviewed `quant_strategies` to determine whether it is a sound foundation for
Season and downstream `quant_autoresearch` use.

Locked objective: `quant_strategies` should provide a purely foundational,
factual research evidence layer: simple strategy contracts, auditable quick
diagnostics, mechanical evidence checks, and frozen-candidate economic, path,
and portfolio evidence. It should not own loops, autonomous research setup,
candidate generation, search memory, ranking, stopping rules, promotion
decisions, or stateful research orchestration.

Additional concerns reviewed: overengineering, workflow simplicity, layered
design, legacy artifacts, artifact bias from existing output, clear separation
of responsibilities, and whether current code should be rewritten or rerun
rather than preserved for compatibility.

## Executive Verdict

The foundation is **correct with fixes**, not a rewrite candidate. The core
execution model is right-sized: pure strategy files, one neutral execution spec,
`quant_data` as the data boundary, normalized/frozen rows, typed decisions, and
declared metric semantics. The material failures are not in the basic engine
math; they are in boundary discipline and evidence semantics. Evaluation can
complete while strict causality evidence is incomplete, tracked `researched/`
artifacts keep ranked loop memory inside the foundation repo, the purity lint
misses evaluation/VectorBT Pro imports, and validation still contains
promotion-shaped "paper readiness" vocabulary. Fix those root boundaries before
adding more evaluation features.

## Scope And Evidence Inspected

- Source and public surfaces: `src/quant_strategies/runner`,
  `src/quant_strategies/validation`, `src/quant_strategies/evaluation`,
  `src/quant_strategies/engine`, `src/quant_strategies/decisions`,
  `src/quant_strategies/data_contract.py`, `src/quant_strategies/causality.py`.
- Config and package surfaces: `pyproject.toml`, `runs/*.toml`,
  `src/quant_strategies/core/config.py`.
- Strategy and archive state: `untested/`, `tested/`, `researched/`.
- Docs treated as claims: `PRD.md`, `README.md`, `FOUNDATION_LOCK.md`,
  `TODOS.md`, `docs/foundation-surfaces.md`, `docs/vectorbtpro.md`,
  `plans/phase1-p1-trust.md`.
- Tests inspected or run: representative runner, validation, evaluation,
  strategy contract, and doc tests. I ran
  `conda run -n quant pytest tests/test_evaluation_docs.py -q`; it failed
  because the test still requires implementation-specific CLI text in `PRD.md`.
- Lens inputs integrated: onboarding, architecture, senior software
  engineering, adversarial, and quant/math read-only subagent reviews.

Not inspected: downstream `quant_autoresearch` and upstream `quant_data`
repositories, real VectorBT Pro execution, live data loading, and full test
suite runtime. Those gaps matter mostly for consumer-contract verification, not
for the local source-boundary findings below.

## Intended Foundation Model

The minimal correct foundation is:

```text
pure strategy.py + explicit TOML config
  -> neutral StrategyExecutionSpec
  -> quant_data loader only
  -> normalized rows with row-contract summary
  -> frozen rows and frozen params
  -> generate_decisions(rows, params)
  -> typed StrategyDecision list
  -> causality, observation, fill, cost, and row-contract checks
  -> one of three factual jobs:
       quick run diagnostic
       mechanical validation evidence
       frozen-candidate research evaluation
  -> artifacts with declared semantics and no promotion authority
```

Dependency direction should be:

```text
strategy files
  depend on: decisions models only
  do not depend on: runner, validation, evaluation, engine, data, artifacts

runner / validation / evaluation
  adapt config to StrategyExecutionSpec
  call shared execution kernel
  own their own artifact semantics

quant_autoresearch
  calls public surfaces only
  owns candidate generation, memory, ranking, stopping, and iteration policy

quant_data
  owns data materialization, refresh, repair, and joining
```

## Project Ontology: Concepts, Contracts, Boundaries, Invariants

| Concept / boundary | Responsibility | Key contracts or invariants | Current fit |
|---|---|---|---|
| Strategy module | Express one strategy rule | Flat file, pure `generate_decisions(rows, params)`, no data loading, no engine calls, no artifacts | Mostly matches; purity lint has a missing denylist for evaluation/VectorBT Pro imports |
| Strategy params | Make parameter states explicit | `validate_params` optional for quick run, required for validation/evaluation | Correct in execution path, unclear in visible quick-run strategies |
| Data boundary | Load market data | Only public `quant_data` loaders, then local normalization | Good |
| Row contract | Define what data was available and auditable | Timestamps, availability, required fields, duplicate checks, funding fields | Good |
| Execution kernel | Shared source of strategy execution truth | Import, param validation, load data, freeze rows/params, validate decisions | Strong preserve |
| Quick run | Diagnose one strategy version | Fast factual diagnostic, not validation or promotion | Good |
| Validation | Mechanical evidence integrity | Advisory; no paper/live/promotion authority | Mostly good, but "paper readiness" vocabulary leaks promotion shape |
| Evaluation | Frozen-candidate portfolio/path/economic evidence | Stateless evidence only, no loop ownership, strict causal preflight | Needs causality gate parity and observability parity |
| Artifacts | Evidence trail | Generated, ignored where appropriate, semantics explicit, not truth | Mixed; current archive carries old ranking/score memory |
| Downstream consumer | Drive iteration | Uses public APIs only; owns selection and stopping policy | Intended boundary is clear in docs, not enforced by consumer tests |

Critical invariants:

- No usable evidence is complete unless causal replay is fully verified or the
  artifact explicitly says it is incomplete.
- No strategy file can import execution, validation, evaluation, data, or
  artifact machinery.
- No artifact field should imply promotion, validation, or ranking authority
  unless that is the actual product contract.
- Quick-run engine returns are linear signed trade-activity sums, not NAV path
  returns.
- Validation and evaluation are factual evidence jobs. Neither decides paper
  trading, live trading, ranking, or promotion.

## What Already Exists And Should Be Reused

| Existing code / flow | Evidence | Reuse / concern |
|---|---|---|
| Shared execution kernel | `src/quant_strategies/runner/execution.py:74` imports the strategy, validates params, loads rows, normalizes, freezes inputs, and validates decisions | Preserve. This is the correct core boundary. |
| Neutral execution spec | `src/quant_strategies/core/config.py:68` defines `StrategyExecutionSpec` with no output/artifact policy | Preserve. It prevents runner/validation/evaluation from owning each other. |
| Param validator contract | `src/quant_strategies/decisions/params.py:9` requires a validator when requested | Preserve, but make quick-run-only strategy state explicit. |
| Row contract | `src/quant_strategies/data_contract.py:406` returns row-contract status and issues | Preserve. This is the factual data-quality boundary. |
| Causality replay result flags | `src/quant_strategies/causality.py:206` returns deterministic, emitted, and strict suppression verification flags | Preserve, but enforce consistently. |
| Engine return semantics | `src/quant_strategies/evidence_semantics.py:42` states trade metrics are signed target-weighted trade activity, not NAV | Preserve. This is good quant hygiene. |
| Validation eligibility flags | `src/quant_strategies/validation/policy.py:21` keeps promotion/paper/live eligibility false | Preserve, but rename surrounding readiness policy. |
| Evaluation artifact semantics | `src/quant_strategies/evaluation/artifacts.py:270` labels evaluation as research evidence and not authority | Preserve, with stronger causality payload. |

## Architecture And Boundary Review

### Finding 1: Evaluation can complete with incomplete strict causality proof

- Severity: Critical
- Action class: Refactor
- Evidence:
  - `src/quant_strategies/causality.py:206` returns `passed=True` while
    `strict_suppression_verified` is false when strict probes are skipped.
  - `src/quant_strategies/evaluation/runner.py:107` runs strict lookahead, but
    `src/quant_strategies/evaluation/runner.py:115` only fails when
    `lookahead.passed` is false.
  - `src/quant_strategies/evaluation/runner.py:262` returns
    `assessment_status="evaluation_complete"`.
  - `src/quant_strategies/validation/__init__.py:417` converts missing
    deterministic, emitted, or strict suppression proof into violations.
- Why it matters: frozen-candidate portfolio/path evidence is more likely to be
  read as durable than quick-run output. It cannot have weaker causality
  completeness than validation.
- Root cause: shared causality result exists, but the "usable evidence" gate is
  duplicated by surface instead of owned once.
- Recommendation: extract one shared causality gate used by validation and
  evaluation. Evaluation should fail preflight unless deterministic, emitted,
  and strict suppression replay are all verified. Persist the full lookahead
  audit payload in evaluation artifacts.
- Tradeoff: this may reject some evaluations that currently complete with
  warnings. That is correct for a factual foundation; incomplete proof should
  be explicit and non-complete.

### Finding 2: `researched/` keeps ranked loop memory inside the foundation repo

- Severity: High
- Action class: Retire
- Evidence:
  - `README.md:12` says candidate generation, search memory, ranking, stopping
    rules, and iteration decisions remain outside this repo.
  - `FOUNDATION_LOCK.md:28` assigns those responsibilities to
    `quant_autoresearch`.
  - `researched/.../manifest.json:22` records a ranking method version.
  - `researched/.../manifest.json:57` records variant ranks and rerun scores.
  - `researched/.../selection/new_15_rerun_summary.json:3` stores top variants.
  - `researched/.../score.json:12` includes `passed_validation: true`.
  - The directory currently contains 204 files and about 26M of tracked content.
- Why it matters: agents and humans are biased by nearby outputs. A foundation
  repo that contains ranks, loop scores, and old validation-like labels will
  keep encouraging promotion-by-artifact even if docs say not to.
- Root cause: archive and active foundation contexts are mixed.
- Recommendation: move ranked search-memory packages to `quant_autoresearch` or
  external cold storage. Do not keep a pointer, checksum note, compatibility
  path, symlink, or archive index in this repo. Add an audit that active
  foundation paths cannot contain rank, top-variant, `passed_validation`, or
  loop-feedback scoring fields.
- Tradeoff: less convenient local historical context. The gain is a cleaner,
  less biased foundation.

### Finding 3: Strategy purity lint misses evaluation and VectorBT Pro imports

- Severity: High
- Action class: Add
- Evidence:
  - `src/quant_strategies/decisions/purity.py:19` bans `quant_data`,
    `quant_strategies.engine`, `quant_strategies.runner`, and
    `quant_strategies.validation`, but not `quant_strategies.evaluation` or
    `vectorbtpro`.
  - `docs/vectorbtpro.md:107` says strategy purity forbids calling VectorBT Pro
    inside strategy files.
  - `tests/test_decision_strategy_loader.py:73` tests banned imports for
    `quant_data` and runner imports, not evaluation or VectorBT Pro.
- Why it matters: the strategy boundary is the project foundation. A strategy
  that imports evaluation or VectorBT Pro can smuggle execution assumptions into
  the decision rule.
- Root cause: denylist did not evolve with the new evaluation surface.
- Recommendation: add `quant_strategies.evaluation` and `vectorbtpro` to the
  purity denylist and add direct tests. Keep documenting that the lint is not a
  sandbox.
- Tradeoff: may reject some convenience imports. That is appropriate for
  strategy purity.

### Finding 4: Validation policy still uses promotion-shaped readiness vocabulary

- Severity: High
- Action class: Simplify
- Evidence:
  - `src/quant_strategies/validation/config.py:116` defines
    `PaperReadinessConfig`, enabled by default.
  - `src/quant_strategies/validation/policy.py:12` includes decisions such as
    `watchlist` and `mechanical_review_candidate`.
  - `src/quant_strategies/validation/policy.py:323` names
    `_PAPER_READINESS_GATES`.
  - `src/quant_strategies/validation/policy.py:460` returns
    `mechanical_review_candidate`.
  - `src/quant_strategies/evidence_semantics.py:102` correctly keeps
    promotion, paper, and live eligibility false.
- Why it matters: the flags say "not authority," but the vocabulary still looks
  like triage toward paper trading or promotion. That is exactly the wrong bias
  for a factual evidence foundation.
- Root cause: a useful mechanical threshold policy is named as readiness.
- Recommendation: rename this layer to mechanical evidence thresholds or move
  review-candidate classification downstream. Keep factual gate outputs; remove
  paper-readiness language from foundation-owned policy.
- Tradeoff: downstream consumers may need a field-name migration. Prefer
  regeneration/rerun over compatibility shims.

### Finding 5: Same-bar open/quote fills have no field-level availability contract

- Severity: Medium
- Action class: Refactor
- Evidence:
  - `src/quant_strategies/core/config.py:47` allows fill prices `open`,
    `close`, and `quote`.
  - `src/quant_strategies/core/config.py:55` only blocks same-bar close fills
    unless explicitly allowed.
  - `src/quant_strategies/engine/evaluation.py:55` fills at
    `decision_index + entry_lag_bars`.
  - `src/quant_strategies/engine/evaluation.py:253` accepts open, close, or
    bid/ask quotes.
  - `src/quant_strategies/causality.py:420` gates visible rows by row-level
    timestamps, not field-level intrabar availability.
- Why it matters: if a strategy sees same-row close/high/low information and
  fills at the same-row open or quote, that is temporal inversion unless the row
  contract explicitly defines intrabar field timestamps.
- Root cause: fill model and row availability model are at different
  granularities.
- Recommendation: default-reject `entry_lag_bars=0` for all fill prices, or add
  an explicit intrabar field-availability policy and tests for zero-lag open and
  quote fills.
- Tradeoff: stricter defaults may reject some valid bar-open strategies unless
  their information set is modeled explicitly.

### Finding 6: The internal engine is public-looking and competes with the three-surface contract

- Severity: Medium
- Action class: Refactor
- Evidence:
  - `docs/foundation-surfaces.md:7` defines the three public jobs: quick run,
    validation run, and evaluation run.
  - `src/quant_strategies/engine/__init__.py:23` exports `screen`,
    `gate_screen`, models, and evidence helpers via `__all__`.
  - `docs/vectorbtpro.md:95` describes quick run and validation as using the
    internal engine path, while evaluation uses VectorBT Pro.
- Why it matters: downstream consumers should not bypass the public surfaces and
  treat `engine` as a fourth product API.
- Root cause: implementation internals are packaged like a public surface.
- Recommendation: document `engine` as internal/stable-for-tests only, or create
  a deliberate deprecation path if direct imports are historical compatibility.
  Do not expand it as a consumer API.
- Tradeoff: keeping it importable is fine for internal tests; the risk is
  consumer coupling.

## Engineering, Testability, And Operability Review

### Finding 7: Docs/tests still encode stale PRD responsibility boundaries

- Severity: Medium
- Action class: Refactor
- Evidence:
  - `PRD.md:16` says the PRD owns intent, goals, non-goals, and constraints, not
    command schemas or package facts.
  - `tests/test_evaluation_docs.py:13` requires `README.md`, `PRD.md`,
    `FOUNDATION_LOCK.md`, `docs/foundation-surfaces.md`, and
    `docs/vectorbtpro.md` to all contain exact implementation terms including
    `quant-strategies evaluate`, `run_evaluation`, `Parquet`, and `pyarrow`.
  - Running `conda run -n quant pytest tests/test_evaluation_docs.py -q`
    currently fails because `PRD.md` intentionally no longer contains
    `quant-strategies evaluate`.
- Why it matters: the test now conflicts with the improved document boundary.
  It will push future edits back toward implementation-specific PRD text.
- Root cause: doc tests pin duplicated strings instead of each document's
  responsibility.
- Recommendation: rewrite doc tests to assert PRD product intent and reference
  docs implementation facts separately.
- Tradeoff: slightly more nuanced tests. The gain is preventing PRD drift.

### Finding 8: Active planning docs contradict current handoff state

- Severity: Medium
- Action class: Retire
- Evidence:
  - `plans/phase1-p1-trust.md:18` still labels strict suppression replay as
    open.
  - `TODOS.md:20` says there are no open foundation-finalization PRs and
    `FOUNDATION_LOCK.md` is the disposition anchor.
- Why it matters: a new agent or engineer can restart closed work or treat an
  old implementation plan as active product direction.
- Root cause: historical implementation plans live in active navigation space.
- Recommendation: move completed plans to an archive clearly marked as history,
  or collapse them into durable decision records and delete active checklists.
- Tradeoff: less implementation chronology in the active tree. Git already
  preserves the history.

### Finding 9: Evaluation lacks stage-event observability parity

- Severity: Medium
- Action class: Add
- Evidence:
  - `src/quant_strategies/runner/__init__.py:54` accepts `event_sink`.
  - `src/quant_strategies/validation/__init__.py:89` accepts `event_sink`.
  - `src/quant_strategies/evaluation/runner.py:39` has no equivalent event sink.
  - `PRD.md:315` requires structured logging at stage boundaries.
- Why it matters: evaluation is the long-running, dependency-heavy path. It
  needs at least the same stage-boundary observability as quick run and
  validation.
- Root cause: evaluation was added as a new surface but did not inherit the
  observability contract.
- Recommendation: add evaluation stage events and CLI events JSONL parity.
- Tradeoff: small API addition. Keep it stage-level; do not add a monitoring
  subsystem.

### Finding 10: Large facade modules are debt, but not the current bottleneck

- Severity: Low
- Action class: Preserve
- Evidence:
  - `src/quant_strategies/validation/__init__.py` is 988 lines.
  - `src/quant_strategies/data_contract.py` is 888 lines.
  - `src/quant_strategies/evaluation/backend.py` is 708 lines.
  - `src/quant_strategies/runner/__init__.py` is 652 lines.
  - `FOUNDATION_LOCK.md:38` already accepts large facade modules as non-blocking
    debt.
- Why it matters: the code is layered, but most of the present risk is not line
  count. The urgent issues are incorrect boundaries and names.
- Root cause: orchestration and artifact policies grew in facade modules.
- Recommendation: do not do a broad rewrite. After P1 boundary fixes, split by
  responsibility only where it removes real complexity: preflight, execution,
  artifact publication, and policy classification.
- Tradeoff: defers cleanup, but avoids churn before correctness fixes.

## Domain-Specific Quant Lens Findings

### Finding 11: Engine math is mostly disciplined, but validation gates compare portfolio-like floors to activity sums

- Severity: High
- Action class: Refactor
- Evidence:
  - `src/quant_strategies/engine/evaluation.py:71` computes net return as a
    linear target-weighted per-trade contribution.
  - `src/quant_strategies/evidence_semantics.py:44` states the base is signed
    target-weighted trade activity, not portfolio NAV.
  - `src/quant_strategies/validation/policy.py:367` sets `-0.02` floor
    thresholds.
  - `src/quant_strategies/validation/policy.py:388` sums `metrics.net_return`
    across realistic scenarios.
  - `src/quant_strategies/evaluation/backend.py:295` enforces gross target
    exposure constraints for portfolio evaluation; validation does not.
- Domain risk: a threshold that reads like a portfolio-percent drawdown or loss
  floor is being applied to a linear activity sum whose scale changes with
  overlap, trade count, and leverage.
- Recommendation: either enforce target-weight and overlap/gross exposure
  constraints in validation, or rename these gates as activity-sum diagnostics
  and remove portfolio-percent interpretation.

### Finding 12: No gross sign/cost/funding formula blocker found in inspected engine path

- Severity: Positive finding
- Action class: Preserve
- Evidence:
  - `src/quant_strategies/engine/evaluation.py:70` applies long/short direction.
  - `src/quant_strategies/engine/evaluation.py:80` applies round-trip bps cost.
  - `src/quant_strategies/evidence_semantics.py:61` declares funding as a linear
    additive adjustment.
- Domain risk: none found at this review depth. The engine's limitation is
  semantic scope, not an obvious formula bug.
- Recommendation: preserve the explicit distinction between engine activity
  sums and evaluation portfolio/NAV path metrics.

## Unknown Unknowns And Assumption Risks

| Assumption | Why it may be wrong | How to test or de-risk |
|---|---|---|
| `quant_autoresearch` ignores advisory labels safely | It may consume `mechanical_review_candidate`, rank fields, or old `passed_validation` fields mechanically | Add downstream consumer contract tests or inspect `quant_autoresearch` call sites |
| Candidate-local validation/evaluation outputs are always ignored | Source-tree artifacts can still leak into review context or git if ignore rules drift | Add an artifact-location test and/or move outputs under ignored roots |
| Current `quant_data` availability semantics are enough for all fill models | Row-level `available_at` may not encode intrabar field availability | Add explicit field-availability policy or reject zero-lag fills by default |
| Evaluation artifacts are replayable enough for audit | Current artifacts do not clearly persist the full lookahead audit payload | Add artifact schema checks for causality fields |
| Old `researched/` artifacts are harmless because docs warn against them | Agents optimize around local evidence and file names, not just docs | Remove or quarantine the archive from active repo context |

## Overbuilt / Underbuilt / Right-Sized

- Overbuilt: tracked ranked research archive inside the foundation repo;
  promotion-shaped validation readiness vocabulary; duplicated doc assertions
  that force implementation details into every document.
- Underbuilt: evaluation causality gate parity; evaluation stage observability;
  purity denylist coverage for evaluation/VectorBT Pro; intrabar availability
  policy for zero-lag fills; consumer contract checks proving downstream uses
  only public surfaces.
- Right-sized: flat pure strategy contract; `StrategyExecutionSpec`; shared
  execution kernel; row contract; declared trade-activity metric semantics;
  separate quick-run, validation, and evaluation jobs.

## Documentation And Decision Gaps

- PRD boundary: `PRD.md:16` is now directionally correct: product intent belongs
  in PRD; command/API/artifact inventories belong in reference docs. The stale
  doc test should follow that boundary.
- Foundation lock gap: `FOUNDATION_LOCK.md:65` accepts validation source output
  paths as deferred debt. This should become either a narrow explicit exception
  or be closed by moving generated artifacts under ignored output roots.
- Historical-plan gap: `plans/phase1-p1-trust.md` should not remain in active
  planning space with open checkboxes and obsolete status.
- ADR gap: there should be a durable decision record for "foundation repo does
  not store search memory or ranked loop artifacts." That decision is stated in
  docs but violated by repository contents.
- Consumer contract gap: document and test that `quant_autoresearch` consumes
  only `runner.run_config`, `validation.run_validation`, and
  `evaluation.run_evaluation`, not internals or archive artifacts.

## ASCII Lifecycle Diagram

```text
                 upstream data owner
                       quant_data
                           |
                           v
strategy.py + config -> StrategyExecutionSpec -> execute_strategy_run
                           |
             +-------------+-------------+
             |                           |
       NormalizedRows              StrategyDecision[]
       row contract                typed decisions
             |                           |
             +-------------+-------------+
                           |
                 causality / observation checks
                           |
          +----------------+----------------+
          |                |                |
       quick run       validation       evaluation
       diagnostic      mechanical       frozen-candidate
       evidence        evidence         portfolio/path evidence
          |                |                |
          +----------------+----------------+
                           |
              evidence artifacts, no authority
                           |
                    human / downstream review

Not owned here:
candidate generation, loop memory, ranking, stopping rules, promotion.
```

## Preserve / Refactor / Simplify / Add / Retire Action Map

| Action class | Findings / recommendations | Rationale |
|---|---|---|
| Preserve | Shared execution kernel, neutral execution spec, row contract, explicit engine metric semantics, false promotion/paper/live eligibility flags | These are the core foundation concepts and should not be rewritten |
| Refactor | Shared usable-evidence causality gate; same-bar fill availability policy; engine public-looking API; validation portfolio-like gates over activity sums; doc tests by document responsibility | Keep capabilities, change boundaries and contracts |
| Simplify | Rename or move validation "paper readiness" classification; reduce duplicated implementation wording in PRD tests | Remove semantics that encourage promotion or stale implementation coupling |
| Add | Purity bans for `quant_strategies.evaluation` and `vectorbtpro`; evaluation stage events; evaluation causality artifact payload; consumer contract tests | These are missing trust and boundary checks |
| Retire | Ranked `researched/` archive from active repo; obsolete active plans/checklists | These preserve old loop/research state and bias future work |

## Prioritized Recommendations

| Priority | Action class | Recommendation | Why now | Verify |
|---|---|---|---|---|
| P0 | Refactor | Apply one strict causality completeness gate to validation and evaluation; fail evaluation on skipped strict probes | Prevent frozen-candidate evidence from completing with incomplete causal proof | Add evaluation skipped-probe regression test |
| P0 | Retire | Move or quarantine `researched/` ranked loop artifacts outside active foundation context | Remove artifact bias and responsibility drift | Add repo audit for rank/top-variant/`passed_validation` fields in active evidence paths |
| P1 | Add | Ban strategy imports of `quant_strategies.evaluation` and `vectorbtpro` | Close strategy purity boundary hole | Add loader purity tests |
| P1 | Simplify | Rename or move `PaperReadinessConfig` and `mechanical_review_candidate` policy semantics | Keep validation factual and non-promotional | Update policy tests and artifact schema expectations |
| P1 | Refactor | Clarify same-bar open/quote fill policy | Avoid intrabar lookahead ambiguity | Add zero-lag open/quote config tests |
| P1 | Refactor | Rewrite doc tests so PRD owns product requirements and reference docs own commands/APIs | Avoid reintroducing implementation details into PRD | `tests/test_evaluation_docs.py` passes under the new boundary |
| P2 | Add | Add evaluation `event_sink` and CLI event JSONL parity | Evaluation should satisfy structured stage observability | Add evaluation event tests |
| P2 | Refactor | Mark `engine` as internal or intentionally supported | Avoid a fourth public surface | Add docs/API boundary test |
| P3 | Refactor | Split large facades after boundary fixes only where it removes real complexity | Improve maintainability without churn | Focused tests continue to pass |

## NOT In Scope

- Building or modifying the auto-research loop.
- Adding ranking, stopping rules, promotion criteria, live trading, or paper
  trading authority.
- Full statistical alpha validation, benchmark-relative metrics, or capacity
  analysis.
- Rewriting the engine or evaluation backend wholesale.
- Preserving old artifacts for compatibility when regeneration/rerun is cleaner.
- Auditing `quant_data` internals or real VectorBT Pro behavior.

## Verification Summary

Verified:

- Read source, tests, configs, docs, and selected archived artifacts.
- Integrated five read-only lens reviews: onboarding, architecture, senior SWE,
  adversarial, and quant/math.
- Ran `conda run -n quant pytest tests/test_evaluation_docs.py -q`.

Observed verification result:

```text
1 failed, 2 passed
FAILED tests/test_evaluation_docs.py::test_public_docs_describe_evaluate_surface_without_promotion_authority
AssertionError: PRD.md
assert 'quant-strategies evaluate' in PRD.md
```

Interpretation: this is a stale doc-test boundary after PRD cleanup, not a
reason to put CLI implementation details back into the PRD.

Not verified:

- Full test suite.
- Downstream `quant_autoresearch` consumption.
- Live `quant_data` data loads.
- Real VectorBT Pro run behavior.

Residual risk:

- Some findings assume downstream consumers may overread local labels and
  artifacts. That is exactly the risk a foundation repo should design against,
  but it should be validated with `quant_autoresearch` call-site tests before
  finalizing any field migration.
