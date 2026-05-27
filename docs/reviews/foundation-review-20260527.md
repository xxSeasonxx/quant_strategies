# Consolidated Foundation Review: quant_strategies

Date: 2026-05-27
Reviewer: Codex
Inputs reviewed:
- `foundation-review-20260527.md`
- `docs/reviews/foundation-claude-review.md`

## Purpose

This document consolidates the two foundation review drafts into one source-of-truth
review. I treated both drafts as claims, then checked the material claims against
source, tests, docs, and researched artifacts. The goal is not to maximize findings;
it is to keep only issues that are defensible and decision-relevant.

## Executive Verdict

`quant_strategies` has a solid core: pure strategy files, strict
`StrategyDecision` output models, immutable strategy inputs, explicit TOML runs,
a deterministic smoke engine, advisory validation semantics, and focused tests.
That foundation should be preserved.

The main foundation risk is not general architecture. It is contract mismatch and
evidence quality at the validation/researched boundary:

1. The researched package validator expects a flat package layout, while the
   only researched package in the repo is a family/variant tree. This is the
   most concrete breakage.
2. Strategy causality is still partly declaration-based. Validation checks
   declared `ObservationRef` lineage, but it cannot prove a strategy did not
   read undeclared future rows from the full row window.
3. Runner smoke artifacts can be consumed without a first-class machine-readable
   data availability/causality status.
4. Validation works, but it reaches into runner internals and uses untyped
   scenario config shapes. This is a maintainability issue, not a rewrite trigger.

The right response is a short sequence of boundary and artifact-contract fixes.
Do not rewrite the project, do not build a full portfolio/research platform here,
and do not add compatibility adapters for old strategy contracts.

## What To Preserve

- `decisions.models`: strict, frozen `StrategyDecision`, `ObservationRef`,
  `PositionTarget`, `ExitPolicy`.
- `boundary.frozen_rows` and `frozen_params`: simple mechanical purity guard.
- `runner.run_config`: readable public runner entry point for TOML experiments.
- `engine`: pure deterministic smoke evaluator with no data loading or IO.
- `evidence_semantics`: advisory flags remain false for runner and validation
  evidence.
- `validation.vectorbtpro_backend`: fail-closed capability handling for unsupported
  semantics.
- Focused tests around strategy contracts, input freezing, data readiness, engine
  math, validation policy, and legacy contract rejection.

## Consolidated Findings

### P1. Researched Package Layout Contract Contradicts The Actual Researched Tree

Action class: Refactor

Evidence:
- `README.md` documents canonical researched packages as
  `researched/<package>/{manifest.json,strategy.py,validation.toml}`.
- `validation.research_manifest._canonical_layout_violations` requires
  `package_dir / "validation.toml"` and `package_dir / "strategy.py"`.
- `tests/test_validation_runner.py::test_run_validation_blocks_invalid_researched_layout`
  enforces nested validation configs as invalid.
- The actual researched package is
  `researched/crypto_perp_funding_crowding_reversal_stateful_rebalance/families/.../variants/rank_*/{config.toml,strategy.py}`.
  Its manifest has variant directories and `config_sha256`/`code_sha256`, not the
  flat `validation_config_sha256`/`strategy_sha256` shape expected by the validator.

Impact:
The code and docs say researched validation is flat, while the only real
researched artifact is variant-tree shaped. Calling validation on the package path
will look for a missing top-level `validation.toml`; calling it on a variant config
is rejected as `research_manifest_invalid_layout`. This is not theoretical.

Recommendation:
Pick one researched package shape and make code, tests, README, and manifest schema
agree. The smallest honest fix is either:
- promote exactly one selected variant into a flat validation package before
  running `validate`, or
- make variants first-class in `research_manifest.py` and accept
  `families/.../variants/.../{config.toml,strategy.py}` with typed variant fields.

Do not support both shapes indefinitely.

### P1. Causality Is Audited By Declarations, Not Proven By The Strategy Input Boundary

Action class: Add

Evidence:
- `runner.run_config` calls `generate_decisions(frozen_rows(loaded.rows), ...)`.
- `validation.run_validation` also passes the loaded row window to the strategy.
- `frozen_rows` prevents mutation, but it does not restrict the time range or
  record what rows were read.
- `validation.data_audit` and `validation.dependencies` check decision
  `as_of_time`, `available_at`, and declared `ObservationRef`s.

Impact:
A strategy can read future or cross-symbol rows and omit those dependencies from
`observations`. The current audit catches bad declarations, not hidden reads.
That is the highest silent quant-bias risk for retained candidates.

Recommendation:
Keep the fast runner permissive. Add a retained-candidate validation check such as
future-poison/truncated replay or a lightweight read-tracking row proxy. The check
should fail if decisions change when rows after the candidate information set are
removed or poisoned. Put this in validation, not in strategy modules and not in
the smoke runner.

### P1. Runner Smoke Evidence Needs Explicit Data Availability Status

Action class: Add

Evidence:
- `runner.data_readiness` only fails when `available_at` exists and is after the
  decision time.
- Missing `available_at` is allowed in runner readiness.
- `data_manifest.json` records metadata field coverage only when metadata fields
  appear, but `summary.json` has no first-class evidence-quality status.

Impact:
`quant_autoresearch` can rank smoke results where row availability is unknown.
That may be acceptable for search, but it must be visible to machine consumers.

Recommendation:
Add explicit fields to runner artifacts, for example:
- `data_availability_status`: `complete`, `partial`, `missing`, `late_rows_found`
- `availability_coverage`
- `causality_verified`: `false` for runner smoke
- `evidence_quality_warnings`

Do not make missing availability fatal by default for search runs. Make the
uncertainty explicit.

### P2. Validation Reaches Into Runner Internals And Builds Untyped Scenario Configs

Action class: Refactor

Evidence:
- `validation.config` imports `runner.config._resolve_inside_repo`.
- `validation.__init__` imports `runner.data_loader` directly.
- `_scenario_config` returns nested `SimpleNamespace` objects.
- `ValidationBackend.run(..., config: Any)` relies on duck typing.

Impact:
This is a real maintainability boundary issue, but it is not a reason to rewrite
validation now. The current capabilities are real and covered by tests.

Recommendation:
When the next validation change touches this area, extract one boundary:
- move shared config/path helpers out of `runner.config`, or make the helper public,
- introduce a small typed `ScenarioRunConfig`,
- type `ValidationBackend.run` against that model.

Avoid a broad validation rewrite as standalone cleanup.

### P2. `paper_candidate` Is Advisory, But The Evidence Inputs Are Still Thin

Action class: Add

Evidence:
- `ValidationDecision` includes `paper_candidate`.
- `PaperReadinessConfig` defaults to two windows and 30 total realistic-cost trades.
- `ValidationPolicyDecision.overfit_controls` reserves `trial_count`,
  `deflated_sharpe`, and `monte_carlo`, but they are always `None`.
- Parameter stress currently perturbs only the first numeric parameter and those
  scenarios are diagnostic, not required.
- README correctly says validation is advisory and eligibility flags remain false.

Impact:
This is not market validation, and the docs mostly say that. The label
`paper_candidate` can still be overread unless artifacts carry the missing search
pressure context.

Recommendation:
Do not add PSR/DSR/PBO or a heavy statistics layer yet. First add the input
contract needed for those checks:
- search/candidate count,
- selected trial count,
- parameter search space,
- selection rule,
- split/window identity.

Until those inputs exist, keep `paper_candidate` explicitly advisory/manual-review
only.

### P2. Default VectorBT Pro Backend Is Operationally Ambiguous

Action class: Add

Evidence:
- `ValidationConfig.backend` defaults to `"vectorbtpro"`.
- `pyproject.toml` does not declare `vectorbtpro` or `pandas`.
- `VectorBTProBackend.run` returns `status="unavailable"` when imports fail.
- Policy maps unavailable required backends to `watchlist`.

Impact:
On a clean install, a missing optional backend can look like a validation outcome
instead of an environment/setup status.

Recommendation:
Declare an optional extra and make missing backend setup explicit, for example
`quant-strategies[vectorbtpro]`. If `backend = "vectorbtpro"` is configured and
the import fails, prefer a clear setup failure or environment-status artifact over
a research-looking `watchlist`.

### P2. Data-Kind Row Contracts Are Implicit

Action class: Add

Evidence:
- `runner.data_loader` adapts `quant_data` frames/lists into dict rows.
- Required OHLC/quote/funding fields are discovered later in engine or backend
  request building.
- Manifests include row counts/hashes and metadata coverage, but not named
  schema/freshness/null/duplicate-key statuses per data kind.

Impact:
Schema drift or missing availability/freshness metadata becomes a local failure
or weak artifact detail instead of actionable feedback to `quant_data`.

Recommendation:
Add a small row-contract status layer per `data.kind`. Keep it light:
required fields, timestamp awareness, duplicate key count, availability coverage,
null policy violations, and `quant_data_feedback`. Do not move data materialization,
repair, backfill, or joins into this repo.

### P3. Public Consumer Surface Needs A Decision, Not Necessarily More Code

Action class: Add

Evidence:
- Package root `quant_strategies.__init__` exports nothing.
- `runner.__all__` exposes `RunResult` and `run_config`.
- `docs/quant-autoresearch-consumer.md` tells consumers to import
  `from quant_strategies.runner import run_config`.
- Consumers are expected to read `summary.json` directly.

Impact:
The Claude draft overstated this as "no public API." There is a documented
subpackage API. The real gap is that the repo has not clearly declared whether
`quant_strategies.runner.run_config` and raw `summary.json` are the stable
consumer contracts.

Recommendation:
Make one explicit decision:
- keep `quant_strategies.runner.run_config` as the stable public API and document
  it as such, or
- re-export a small top-level API from `quant_strategies.__init__`.

Add typed artifact readers only if `quant_autoresearch` starts duplicating JSON
parsing logic. This is useful, but not P1.

### P3. Validation Failure Reasons Drop Useful Exception Detail

Action class: Add

Evidence:
- Several `validation.run_validation` `except Exception as exc` branches return
  fixed reasons such as `backend_selection_failed` or `strategy_import_failed`
  without including the exception details in artifacts.

Impact:
Artifacts can hide whether a failure was a missing file, bad import, bad symbol,
or setup problem.

Recommendation:
Include `exc!r` or structured `{type, message}` in validation artifacts. This is a
small observability fix.

### P3. Historical Docs And Legacy Evidence Should Be Marked Clearly

Action class: Retire

Evidence:
- `docs/superpowers/*` contains historical planning language, including old
  `maybe` wording.
- Researched variants include `evidence/legacy_selection` artifacts.
- Source loaders reject old `generate_signals` contracts.

Impact:
The source is strict, which is good. The risk is that agents or humans may treat
historical plans or legacy evidence as active contracts.

Recommendation:
Add archive headers or move historical plans/evidence under a clearly archived
path. Do not add compatibility layers for old strategy outputs.

## Softened Or Rejected Draft Claims

- "No public API" is overstated. `quant_strategies.runner.run_config` is a
  documented subpackage API with `runner.__all__`. The issue is lack of an
  explicit stability decision or top-level facade, not total absence of API.
- Same-bar entry fills are not a current runner/validation default bug.
  `FillModelConfig` rejects close-price same-bar entries unless
  `allow_same_bar_close_fill = true`. The lower-level engine model still permits
  `entry_lag_bars = 0`, but direct engine use is not the documented consumer path.
- "Eligibility flags can be laundered" is not a useful foundation finding. Python
  callers can forge objects or JSON if they try. The model validator sets the
  advisory flags false in normal construction, and these flags are not a security
  boundary.
- The strategy loader wrappers and validation error hierarchy are cleanup items,
  not material architecture risks. Collapse them only when touching that area.
- Smoke returns, flat round-trip costs, close-based stops, and additive smoke
  totals are known limitations of a smoke engine. They should stay clearly named;
  this repo should not grow a full portfolio engine to fix a naming problem.
- `results/` vs `validation_results/` is not a material issue by itself. They are
  configured output roots. Document only if users are confused.
- `validation/__init__.py` is large, but a standalone rewrite would be churn.
  Extract boundaries only alongside real validation changes.

## Priority Order

1. Decide and fix researched package layout/schema so the actual researched tree
   can be validated or intentionally cannot.
2. Add validation-only hidden-lookahead protection for retained candidates.
3. Add runner evidence-quality fields for availability/causality status.
4. Make VectorBT Pro backend setup explicit.
5. Add light data-kind row contract statuses and `quant_data_feedback`.
6. Clarify `paper_candidate` with search-pressure inputs before adding statistics.
7. Tighten validation config/backend typing when next touching validation.
8. Make the public consumer API decision and add typed readers only if needed.
9. Improve validation failure details.
10. Archive or mark historical docs/evidence.

## Verification Performed

- Read both review drafts.
- Checked project instructions and foundation-review workflow guidance.
- Verified CodeGraph index was available: 79 files, 1473 symbols, 2058 edges.
- Inspected source for runner, engine, decisions, validation, data loading,
  manifests, policy, matrix, VectorBT Pro backend, and strategy loaders.
- Inspected README, consumer docs, superpowers docs, researched package manifest,
  researched package layout, and tests around validation layout/policy.
- Confirmed local generated bytecode exists under `src/quant_strategies`, but it
  is ignored/untracked and not a source correctness issue.

Not verified:
- Real `quant_data` upstream freshness/availability guarantees.
- Downstream `quant_autoresearch` implementation details.
- Real VectorBT Pro runtime behavior beyond source-level inspection.
- Profitability or market validity of current strategies.
