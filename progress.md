# Progress

Date: 2026-05-28
Goal: Address `review-codex.md` and `review-claude.md` phase by phase, reject false positives, verify, review, and commit.

## Workflow

1. Use office-hours builder style to turn the review into a design artifact.
2. Use a written implementation plan before code changes.
3. Run engineering review before implementation.
4. Execute phase tasks with subagent-driven development where practical.
5. Request code review before commit.
6. Keep this file updated after each phase.

## Current Phase

Phase 26: P2 cache lookahead row visibility.

Design: `docs/superpowers/specs/2026-05-28-foundation-review-p2-lookahead-visibility-cache-design.md`
Plan: `docs/superpowers/plans/2026-05-28-foundation-review-p2-lookahead-visibility-cache.md`

## Finding Triage

| Finding | Status | Notes |
|---|---|---|
| Runner does not enforce hidden-lookahead replay | Confirmed true, Phase 1 | Current runner does not call replay before `smoke_passed`. |
| `paper_candidate` overstates mechanical evidence | Confirmed true, Phase 1 | Rename to `mechanical_review_candidate`. |
| Smoke aggregate `return` names overstate units | Confirmed true, Phase 1 | Rename to activity-sum names. |
| Runner/validation neutral kernel incomplete | Partly true, deferred | Shared execution exists; causality is not shared. Phase 1 extracts causality only. |
| Engine parallel ontology | Confirmed true, Phase 6 | Collapse runner/engine signal path into direct `StrategyDecision` consumption. |
| Validation orchestrator god-function | Confirmed true, Phase 4 | Behavior-preserving split into focused private helpers. |
| Public API re-export mismatch | Partly true, deferred | `AGENTS.md` chooses `quant_strategies.runner.run_config`; treat as PRD/docs reconciliation, not immediate code change. |
| Full G1 ontology support missing | Confirmed true, Phase 2 | Define ontology/capability gates before executing all asset classes. |
| Metric units, bases, and comparability not first-class | Confirmed true, Phase 3 | Scope Phase 3 to runner smoke metric semantics; validation backend metric schema remains deferred. |
| Summary artifacts can look audit-sufficient | Confirmed true, Phase 3 | Add machine-readable artifact trust tiers for summary/full profiles. |
| Full-run artifact determinism not regression-tested | Confirmed true, Phase 3 | Add repeated-run stable artifact hash regression. |
| Decision record JSONL encoding not canonical | Confirmed true, Phase 7 | Replace pydantic-default `model_dump_json()` artifact writes with sorted compact JSON. |
| Validation backend metrics are unstructured | Confirmed true, Phase 5 | Add typed backend metric contract while preserving flat artifacts. |
| Required unsupported backend semantics too soft | Confirmed true, Phase 5 | Required unsupported semantics should be `hard_no`, not `watchlist`. |
| `quant_data` eager import slows runner cold import | Confirmed true, Phase 8 | Lazy-import `quant_data` only when loading data or building a default engine. |
| Duplicate freezing idioms and repeated row deepcopy | Confirmed true, Phase 9 | Use `boundary` as the single recursive freeze helper and reuse frozen execution inputs. |
| Validation capability matrix hard-codes backend identity | Confirmed true, Phase 10 | Move static capability records onto backend implementations and keep observed-semantics extraction centralized. |
| Duplicate `(symbol, decision_time)` decisions can double-count smoke PnL | Confirmed true, Phase 11 | Reject duplicate execution keys at shared decision-output validation. |
| Typed `RunResult` lacks evidence-quality fields | Confirmed true, Phase 12 | Expose `data_availability_status`, `availability_coverage`, `row_contract`, `causality_verified`, and `evidence_quality_warnings` on the stable runner result. |
| Empty-decision strategy is classified as `runner_failed` | Confirmed true, Phase 13 | Strategy tests treat `[]` as a normal no-op output; runner should classify it as completed zero-trade smoke evidence, not infrastructure failure. |
| `quant_data` engine discovery has hidden local `.env` coupling | Confirmed true, Phase 14 | Remove runner-owned discovery of an upstream `quant-data/.env`; `quant_data` owns engine environment configuration. |
| Search pressure is copied but no deflation is evaluated | Confirmed true, Phase 15 | Add explicit `deflation_not_evaluated` reason to search-pressure-backed `mechanical_review_candidate` outputs. |
| `runner/strategy_loader.py` is a pass-through wrapper | Confirmed true, Phase 16 | Retire the wrapper and inline runner-specific exception translation at the execution boundary. |
| `ValidationBackendError` and `ValidationDataError` are unused | Confirmed true, Phase 17 | Retire the unused subclasses and keep only raised validation error classes. |
| Internal Pydantic revalidation across boundaries | Partly true, Phase 18 | Drop `BackendRunResult.model_validate()` for typed backend returns; keep runner config-to-engine `FillModel`/`CostModel` construction as required adaptation. |
| Strategy provenance docstring test under-enforces source specificity | Confirmed true, Phase 19 | Require DOI, SSRN, URL, or `internal_note:` in `Source / provenance:` blocks. |
| Empty docs scaffolds | Partly true, Phase 20 | `docs/superpowers/{plans,specs}` are now populated; add `docs/reviews/README.md` instead of moving active root review inputs. |
| Full-profile runner duplicates input rows as CSV and JSONL | Confirmed true, Phase 21 | Keep `strategy_input_rows.jsonl` only; leave default artifact profile as a separate remaining finding. |
| Runner defaults to full artifact profile | Confirmed true, Phase 22 | Default omitted `artifact_profile` to `summary`; keep explicit `full` for retained/debug runs. |
| Strategy purity is not enforced for arbitrary candidate workspaces | Confirmed true, Phase 23 | Add default-on AST purity check in the canonical strategy loader and reuse it in committed-strategy tests. |
| Crypto perp funding is added as a linear adjustment to generic backend `net_return` | Confirmed true, Phase 24 | Keep `net_return` as backend price/cost return; expose `linear_funding_adjusted_return` and keep policy gates off the linear add-on. |
| Structured stage observability is missing | Confirmed true, Phase 25 | Add optional runner event sink and CLI JSONL stderr events for core runner stages. |
| Validation lookahead replay reparses row visibility per decision | Confirmed true, Phase 26 | Cache parsed row visibility metadata and visible frozen row slices in the shared causality checker. |
| `validation.matrix._FrozenDict` duplicate freezing idiom | Resolved before Phase 16 | Current source no longer contains `_FrozenDict`; earlier single-freezing phase removed it. |

## Phase 1 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Implement runner causality enforcement.
- [x] Rename validation decision label.
- [x] Rename smoke activity fields.
- [x] Update docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_validation_backends_and_policy.py tests/test_validation_runner.py tests/test_validation_cli.py tests/test_readme_contract.py -q` -> 72 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_engine_screen.py tests/test_runner_artifact_profiles.py tests/test_readme_contract.py -q` -> 29 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py tests/test_validation_lookahead.py tests/test_engine_screen.py tests/test_runner_artifact_profiles.py tests/test_validation_backends_and_policy.py tests/test_validation_runner.py tests/test_validation_cli.py tests/test_readme_contract.py -q` -> 144 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 462 passed.
- 2026-05-28: Code review found that invalid or naive `available_at` values could be counted as complete availability. Fixed by sharing strict aware-datetime parsing with runner evidence quality, adding `available_at_invalid`, and keeping invalid availability from setting `causality_verified`.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py tests/test_validation_lookahead.py -q` -> 45 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 463 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Follow-up code review found invalid `available_at` on the matched decision row could still fail `data_readiness`. Fixed by treating malformed/naive optional `available_at` as evidence-quality-only while preserving fatal late-availability checks.
- 2026-05-28: `conda run -n quant pytest tests/test_data_readiness.py tests/test_runner_api_cli.py::test_run_config_rejects_invalid_available_at_for_causality_claim tests/test_runner_api_cli.py::test_run_config_marks_complete_available_at_coverage tests/test_runner_api_cli.py::test_run_config_marks_partial_available_at_coverage -q` -> 17 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py tests/test_validation_lookahead.py tests/test_data_readiness.py -q` -> 59 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 465 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Follow-up review of the `data_readiness` fix found no blocking issues.

## Phase 2 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Implement decision ontology expression.
- [x] Gate unsupported runner smoke semantics.
- [x] Propagate `decision_id` through engine artifacts.
- [x] Update validation unsupported semantics.
- [x] Update docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 2 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_decision_models.py tests/test_runner_engine_runner.py tests/test_vectorbtpro_backend.py tests/test_validation_capabilities.py tests/test_engine_validate_and_evidence.py -q` -> 135 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py tests/test_runner_execution.py tests/test_validation_lookahead.py tests/test_validation_runner.py tests/test_validation_backends_and_policy.py tests/test_runner_artifact_profiles.py tests/test_engine_screen.py tests/test_engine_validate_and_evidence.py -q` -> 151 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_decision_models.py tests/test_runner_engine_runner.py tests/test_runner_api_cli.py tests/test_vectorbtpro_backend.py tests/test_validation_capabilities.py tests/test_engine_screen.py tests/test_engine_validate_and_evidence.py tests/test_readme_contract.py -q` -> 199 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 485 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found no blocking issues. Residual risks: summary profile remains aggregate-only, richer exit ontology remains PRD debt, and engine parallel ontology cleanup remains deferred.

## Phase 3 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Add artifact trust tier contract.
- [x] Add smoke metric semantics contract.
- [x] Thread trust and semantics through runner artifacts and result object.
- [x] Add deterministic artifact regression.
- [x] Update docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 3 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_runner_artifact_profiles.py tests/test_runner_api_cli.py tests/test_readme_contract.py -q` -> 47 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 486 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found three valid issues: semantics keys drifted from `comparability`/`tolerance`, the deterministic artifact test did not prove a successful full-profile run, and the Phase 3 plan checklist was stale. Fixed all three.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_artifact_profiles.py tests/test_runner_api_cli.py tests/test_readme_contract.py -q` -> 47 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 486 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Follow-up code review found the three prior findings closed and no new Critical/Important Phase 3 issues.

## Phase 4 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Add private context/state helpers.
- [x] Extract window execution handling.
- [x] Extract audit/readiness/scenario stages.
- [x] Run focused validation tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 4 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_validation_runner.py tests/test_validation_backends_and_policy.py tests/test_validation_artifacts.py tests/test_validation_lookahead.py tests/test_validation_capabilities.py -q` -> 84 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 486 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found accidental public-name drift (`StrategyExecutionResult`, `field`, `MIN_VALIDATION_TRADES`) and stale Phase 4 plan/progress entries. Fixed by using private aliases/type-check-only imports, renaming the constant, moving Phase 3 verification entries, and marking the plan steps complete.
- 2026-05-28: `conda run -n quant pytest tests/test_validation_runner.py tests/test_validation_backends_and_policy.py tests/test_validation_artifacts.py tests/test_validation_lookahead.py tests/test_validation_capabilities.py -q` -> 84 passed.
- 2026-05-28: `conda run -n quant python -c 'import quant_strategies.validation as v; leaked=[name for name in ("StrategyExecutionResult","field","MIN_VALIDATION_TRADES","TYPE_CHECKING") if hasattr(v,name)]; assert not leaked, leaked; print("public leak check passed")'` -> passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 486 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Follow-up code review found the public-name finding closed and no new Critical/Important Phase 4 issues. One remaining minor progress-log placement issue was fixed before commit.

## Phase 5 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Add typed backend metric contract.
- [x] Use typed metrics in policy.
- [x] Harden required unsupported semantics to hard_no.
- [x] Update docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 5 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_validation_backends_and_policy.py tests/test_validation_runner.py tests/test_validation_capabilities.py tests/test_vectorbtpro_backend.py tests/test_readme_contract.py -q` -> 141 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 489 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found no Critical/Important issues. One P3 docs/progress issue was fixed by marking the Phase 5 plan checklist complete.

## Phase 6 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Replace engine `Signal` with direct `StrategyDecision` consumption.
- [x] Remove runner signal-row execution boundary and artifacts.
- [x] Update docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 6 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_engine_models.py tests/test_engine_screen.py tests/test_engine_validate_and_evidence.py tests/test_runner_engine_runner.py tests/test_data_readiness.py tests/test_runner_artifact_profiles.py tests/test_runner_api_cli.py tests/test_krohn_mueller_whelan_fix_reversal.py tests/test_fx_triangular_residual_reversion.py tests/test_phase5_performance.py tests/test_readme_contract.py -q` -> 146 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 485 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found one valid issue: evidence payload fields changed from `signal_metadata` to `decision_metadata` while the engine evidence schema remained v2. Fixed by bumping the evidence schema to `quant_strategies.engine.evidence/v3` and updating manifest/test expectations.
- 2026-05-28: `conda run -n quant pytest tests/test_engine_validate_and_evidence.py tests/test_runner_api_cli.py tests/test_runner_engine_runner.py tests/test_engine_screen.py -q` -> 90 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: `conda run -n quant pytest tests/test_engine_models.py tests/test_engine_screen.py tests/test_engine_validate_and_evidence.py tests/test_runner_engine_runner.py tests/test_data_readiness.py tests/test_runner_artifact_profiles.py tests/test_runner_api_cli.py tests/test_krohn_mueller_whelan_fix_reversal.py tests/test_fx_triangular_residual_reversion.py tests/test_phase5_performance.py tests/test_readme_contract.py -q` -> 146 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 485 passed.

## Phase 7 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Canonicalize runner decision-record JSONL.
- [x] Canonicalize validation decision-record JSONL.
- [x] Update docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 7 Verification Log

- 2026-05-28: `rg "model_dump_json\\(" src` -> no matches.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_writes_success_artifacts tests/test_runner_api_cli.py::test_repeated_runner_artifacts_are_byte_deterministic tests/test_validation_runner.py::test_run_validation_writes_watchlist_artifacts_for_one_positive_window tests/test_readme_contract.py -q` -> 4 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py tests/test_validation_runner.py tests/test_readme_contract.py -q` -> 73 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 485 passed.
- 2026-05-28: Code review found no blocking issues. Non-blocking note: empty validation JSONL payloads still write a newline through `write_text_artifact`, preserving prior behavior.

## Phase 8 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Add lazy `quant_data` import helpers.
- [x] Preserve data adapter behavior.
- [x] Update docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 8 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_runner_data_loader.py -q` -> 8 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_data_loader.py tests/test_runner_api_cli.py tests/test_readme_contract.py -q` -> 50 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 486 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found one valid robustness issue: partial monkeypatches of the lazy loader proxy did not fall back to real `quant_data.loader` methods for unpatched attributes. Fixed by resolving unset proxy attributes through the real loader at call time and adding a focused regression test.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_data_loader.py tests/test_runner_api_cli.py tests/test_readme_contract.py -q` -> 51 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 487 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Follow-up code review confirmed the partial-monkeypatch fallback finding is closed and found no blocking issues. Its only new note claimed the Phase 8 plan Step 3 was unchecked; local inspection showed Step 3 is checked, so this was treated as stale-read noise.

## Phase 9 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Add boundary idempotence tests.
- [x] Make boundary freezing idempotent.
- [x] Freeze execution inputs once.
- [x] Reuse frozen execution inputs in runner and validation.
- [x] Collapse validation matrix freezing onto `boundary`.
- [x] Update docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 9 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_boundary.py -q` -> failed as expected before implementation; idempotence regression failed under the old deep-copy implementation.
- 2026-05-28: `conda run -n quant pytest tests/test_boundary.py -q` -> 3 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_boundary.py tests/test_validation_matrix.py tests/test_runner_api_cli.py::test_runner_blocks_strategy_row_mutation tests/test_runner_api_cli.py::test_runner_blocks_strategy_param_mutation tests/test_validation_runner.py::test_run_validation_blocks_strategy_row_mutation tests/test_validation_runner.py::test_run_validation_blocks_strategy_param_mutation -q` -> 16 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_boundary.py tests/test_runner_api_cli.py tests/test_validation_runner.py tests/test_validation_matrix.py -q` -> initially found one expected assertion drift: validation now reuses one frozen row tuple per window across scenarios. Updated the test to assert freeze-once reuse.
- 2026-05-28: `conda run -n quant pytest tests/test_boundary.py tests/test_runner_api_cli.py tests/test_validation_runner.py tests/test_validation_matrix.py -q` -> 84 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 490 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found one valid issue: treating any external `MappingProxyType` as already frozen could leak later mutations from its backing dict. Fixed by replacing the raw mapping-proxy alias with boundary-owned `FrozenMapping` and copying external proxies before freezing.
- 2026-05-28: `conda run -n quant pytest tests/test_boundary.py tests/test_validation_matrix.py tests/test_runner_api_cli.py::test_runner_blocks_strategy_row_mutation tests/test_runner_api_cli.py::test_runner_blocks_strategy_param_mutation tests/test_validation_runner.py::test_run_validation_blocks_strategy_row_mutation tests/test_validation_runner.py::test_run_validation_blocks_strategy_param_mutation -q` -> 17 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_boundary.py tests/test_runner_api_cli.py tests/test_validation_runner.py tests/test_validation_matrix.py -q` -> 85 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 491 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Follow-up code review found one valid issue: `FrozenMapping._data` could be reassigned after construction. Fixed by making `FrozenMapping` attribute-immutable and adding a regression test.
- 2026-05-28: `conda run -n quant pytest tests/test_boundary.py tests/test_runner_api_cli.py tests/test_validation_runner.py tests/test_validation_matrix.py -q` -> 86 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 492 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Final follow-up code review confirmed the `_data` reassignment finding is closed and found no blocking issues. Residual risk is only Python introspection bypass via `object.__setattr__`, which is outside normal consumer behavior.

## Phase 10 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Add backend capability contract.
- [x] Move VectorBT Pro capability records to backend.
- [x] Reduce capability matrix assembly.
- [x] Thread backend object through validation artifacts.
- [x] Update docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 10 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_validation_capabilities.py -q` -> 5 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_validation_runner.py -q` -> 31 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_validation_capabilities.py tests/test_validation_runner.py tests/test_validation_backends_and_policy.py tests/test_vectorbtpro_backend.py -q` -> 140 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 492 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Added fallback coverage for injected custom backends without `capability_records()`.
- 2026-05-28: `conda run -n quant pytest tests/test_validation_capabilities.py tests/test_validation_runner.py tests/test_validation_backends_and_policy.py tests/test_vectorbtpro_backend.py -q` -> 141 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 493 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found no blocking issues. Residual risk: capability records remain plain dictionaries, so malformed future custom backend records are not schema-validated before artifact writing.

## Phase 11 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Add duplicate execution-key regression.
- [x] Implement shared output validation.
- [x] Update docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 11 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_decision_models.py::test_validate_decision_output_rejects_duplicate_symbol_decision_time -q` -> failed as expected before implementation; duplicate same-symbol same-time decisions were both accepted.
- 2026-05-28: `conda run -n quant pytest tests/test_decision_models.py::test_validate_decision_output_rejects_duplicate_symbol_decision_time tests/test_decision_models.py::test_validate_decision_output_rejects_duplicate_decision_id -q` -> 2 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_decision_models.py tests/test_runner_api_cli.py tests/test_validation_runner.py -q` -> 108 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 494 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found no blocking issues. Residual note: allowed edge cases were documented but not directly tested. Added positive coverage for same symbol at different decision times and different symbols at the same decision time.
- 2026-05-28: `conda run -n quant pytest tests/test_decision_models.py tests/test_runner_api_cli.py tests/test_validation_runner.py -q` -> 109 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 495 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.

## Phase 12 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Add `RunResult` API regression.
- [x] Add typed evidence-quality fields and population helper.
- [x] Update consumer docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 12 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_writes_success_artifacts -q` -> failed as expected before implementation; `RunResult` lacked `data_availability_status`.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_writes_success_artifacts tests/test_runner_api_cli.py::test_run_config_writes_data_failure_summary tests/test_runner_api_cli.py::test_cli_reports_failure_with_notes -q` -> 3 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py tests/test_runner_execution.py tests/test_readme_contract.py -q` -> 49 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 495 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found no blocking issues. Residual risk: `RunResult.availability_coverage` and `RunResult.row_contract` preserve artifact-shaped mutable dict payloads as shallow copies.
- 2026-05-28: Committed Phase 12.

## Phase 13 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Add engine no-op regressions.
- [x] Add runner no-op regressions.
- [x] Implement engine request contract fix.
- [x] Update docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 13 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_engine_screen.py::test_screen_accepts_empty_decision_set_as_zero_trade_result tests/test_engine_validate_and_evidence.py::test_validate_empty_decision_set_fails_smoke_gates_not_inputs tests/test_runner_engine_runner.py::test_build_request_accepts_zero_decisions_as_no_op tests/test_runner_api_cli.py::test_run_config_treats_empty_decisions_as_zero_trade_smoke_result -q` -> failed as expected before implementation; `StrategySpec` and `build_request()` rejected empty decisions, and runner summary stage was `request_build`.
- 2026-05-28: `conda run -n quant pytest tests/test_engine_screen.py::test_screen_accepts_empty_decision_set_as_zero_trade_result tests/test_engine_validate_and_evidence.py::test_validate_empty_decision_set_fails_smoke_gates_not_inputs tests/test_runner_engine_runner.py::test_build_request_accepts_zero_decisions_as_no_op tests/test_runner_api_cli.py::test_run_config_treats_empty_decisions_as_zero_trade_smoke_result -q` -> 4 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_engine_screen.py tests/test_engine_validate_and_evidence.py tests/test_runner_engine_runner.py tests/test_runner_api_cli.py tests/test_readme_contract.py -q` -> 94 passed before adding runner screen-mode empty-decision coverage.
- 2026-05-28: `conda run -n quant pytest -q` -> 498 passed before adding runner screen-mode empty-decision coverage.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found no blocking issues. Residual note: runner-level screen-mode empty-decision coverage was missing; added a focused regression.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py::test_screen_mode_empty_decisions_complete_as_zero_trade_result tests/test_runner_api_cli.py::test_run_config_treats_empty_decisions_as_zero_trade_smoke_result -q` -> 2 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_engine_screen.py tests/test_engine_validate_and_evidence.py tests/test_runner_engine_runner.py tests/test_runner_api_cli.py tests/test_readme_contract.py -q` -> 95 passed after adding screen-mode empty-decision coverage.
- 2026-05-28: `conda run -n quant pytest -q` -> 499 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Follow-up code review found no blocking issues. The only finding was stale progress counts; fixed before commit.
- 2026-05-28: Committed Phase 13.

## Phase 14 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Add `quant_data` environment-boundary regression.
- [x] Remove hidden `.env` discovery.
- [x] Update docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 14 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_runner_data_loader.py::test_default_engine_uses_public_quant_data_engine_factory_without_env_discovery -q` -> failed as expected before implementation; `_default_engine()` constructed `DataConfig(_env_file=...)`.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_data_loader.py::test_default_engine_uses_public_quant_data_engine_factory_without_env_discovery tests/test_runner_data_loader.py::test_importing_data_loader_does_not_import_quant_data -q` -> 2 passed.
- 2026-05-28: `rg "_env_file|_quant_data_env_file|_data_config_type|quant_data\\.config|DataConfig" src/quant_strategies/runner/data_loader.py tests/test_runner_data_loader.py` -> no runner source matches; remaining matches are the regression's forbidden `DataConfig` sentinel.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_data_loader.py tests/test_runner_api_cli.py tests/test_readme_contract.py -q` -> 53 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 499 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found no blocking issues. Residual risk is the intentional contract shift that `quant_data` or explicit `engine=` injection owns environment configuration.
- 2026-05-28: Committed Phase 14.

## Phase 15 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Add policy and artifact regressions.
- [x] Add deflation-not-evaluated policy reason.
- [x] Update docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 15 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_validation_backends_and_policy.py::test_policy_records_search_pressure_inputs_for_mechanical_review_candidate tests/test_validation_runner.py::test_run_validation_writes_mechanical_review_candidate_artifacts_for_two_robust_windows -q` -> failed as expected before implementation; search-pressure-backed `mechanical_review_candidate` reasons were empty.
- 2026-05-28: `conda run -n quant pytest tests/test_validation_backends_and_policy.py::test_policy_mechanical_review_candidate_when_all_paper_gates_pass tests/test_validation_backends_and_policy.py::test_policy_records_search_pressure_inputs_for_mechanical_review_candidate tests/test_validation_runner.py::test_run_validation_writes_mechanical_review_candidate_artifacts_for_two_robust_windows -q` -> 3 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_validation_backends_and_policy.py tests/test_validation_runner.py tests/test_readme_contract.py -q` -> 70 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 499 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found no blocking issues. Residual note: no artifact-level no-search-pressure `mechanical_review_candidate` test; policy-level regression preserves that core contract.
- 2026-05-28: Committed Phase 15.

## Phase 16 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Move loader tests to canonical decisions API.
- [x] Inline runner exception translation.
- [x] Retire wrapper imports and files.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 16 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_decision_strategy_loader.py -q` -> 2 passed.
- 2026-05-28: `rg "quant_strategies\\.runner\\.strategy_loader|from quant_strategies.runner.strategy_loader|execution\\.load_strategy|runner/strategy_loader\\.py" src tests docs README.md progress.md` -> no source/test matches; remaining matches were Phase 16 docs/progress.
- 2026-05-28: `test ! -e src/quant_strategies/runner/strategy_loader.py && conda run -n quant pytest tests/test_decision_strategy_loader.py tests/test_runner_config.py tests/test_runner_execution.py tests/test_validation_runner.py::test_run_validation_records_strategy_import_failure_details -q` -> 27 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_validation_runner.py -q` -> 31 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_decision_strategy_loader.py tests/test_runner_config.py tests/test_runner_execution.py tests/test_validation_runner.py -q` -> 57 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 499 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found no blocking issues. Residual risk: direct external imports of retired `quant_strategies.runner.strategy_loader` now fail by design.
- 2026-05-28: Committed Phase 16.

## Phase 17 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Add error-surface regression.
- [x] Delete unused validation error subclasses.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 17 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_validation_errors.py -q` -> failed as expected before implementation; `ValidationBackendError` and `ValidationDataError` were still public error classes.
- 2026-05-28: `rg -n "ValidationBackendError|ValidationDataError" src tests` -> no matches.
- 2026-05-28: `conda run -n quant pytest tests/test_validation_errors.py tests/test_validation_config.py tests/test_validation_cli.py tests/test_validation_runner.py -q` -> 62 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 500 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found no blocking issues. Residual risk: direct external imports of retired `ValidationBackendError` or `ValidationDataError` now fail by design.
- 2026-05-28: Committed Phase 17.

## Phase 18 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Add no-revalidation regression.
- [x] Replace Pydantic revalidation with Protocol-type handling.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 18 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_validation_runner.py::test_run_validation_trusts_backend_run_result_without_pydantic_revalidation -q` -> failed as expected before implementation; conforming backend results were still revalidated into `invalid_backend_result` when `BackendRunResult.model_validate` was monkeypatched to raise.
- 2026-05-28: `rg -n "BackendRunResult\\.model_validate" src` -> no matches.
- 2026-05-28: `conda run -n quant pytest tests/test_validation_runner.py::test_run_validation_trusts_backend_run_result_without_pydantic_revalidation tests/test_validation_runner.py::test_run_validation_writes_failure_artifacts_for_malformed_backend_result tests/test_validation_runner.py::test_run_validation_rejects_invalid_backend_status -q` -> 3 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_validation_runner.py tests/test_validation_backends_and_policy.py tests/test_validation_capabilities.py -q` -> 76 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 501 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found no blocking issues. Residual risk: nonconforming injected backends that return dicts are no longer parsed for field-specific diagnostics; they now fail the Protocol type guard.
- 2026-05-28: Committed Phase 18.

## Phase 19 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Add provenance anchor regression.
- [x] Add missing internal-note provenance anchor.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 19 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_strategy_docstrings.py::test_strategy_docstrings_include_auditable_provenance_anchor -q` -> failed as expected before fixture update; `examples/strategies/simple_momentum.py` lacked DOI, SSRN, URL, or `internal_note:`.
- 2026-05-28: `conda run -n quant pytest tests/test_strategy_docstrings.py -q` -> 5 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 502 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found no blocking issues. Residual risk: the provenance anchor check is syntactic and does not verify external citation reachability.
- 2026-05-28: Committed Phase 19.

## Phase 20 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Add review archive README.
- [x] Run focused checks.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 20 Verification Log

- 2026-05-28: `test -s docs/reviews/README.md` -> passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 502 passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found no blocking issues. Residual risk: root review inputs remain active files until the overall review workflow is archived.
- 2026-05-28: Committed Phase 20.

## Phase 21 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Update artifact expectations.
- [x] Remove CSV row artifact writing.
- [x] Update docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 21 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_writes_success_artifacts tests/test_runner_api_cli.py::test_raw_inputs_preserve_quote_and_funding_fields_in_engine_request tests/test_runner_api_cli.py::test_request_build_failure_preserves_prior_stage_artifacts -q` -> failed as expected before implementation; full-profile runs still wrote `strategy_input_rows.csv`.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_writes_success_artifacts tests/test_runner_api_cli.py::test_raw_inputs_preserve_quote_and_funding_fields_in_engine_request tests/test_runner_api_cli.py::test_request_build_failure_preserves_prior_stage_artifacts -q` -> 3 passed.
- 2026-05-28: `rg -n "write_csv|csv\\.DictWriter|import csv" src tests` -> no matches.
- 2026-05-28: `rg -n "strategy_input_rows\\.csv" src README.md docs/quant-autoresearch-consumer.md` -> no matches.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py tests/test_runner_artifact_profiles.py tests/test_readme_contract.py -q` -> 49 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 502 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found no blocking issues. Residual risk: frozen historical researched artifacts may still include old CSV row outputs, but current runner output no longer writes them.
- 2026-05-28: Committed Phase 21.

## Phase 22 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Update config default expectations.
- [x] Flip runner default to summary.
- [x] Update docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 22 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_runner_config.py::test_valid_run_config_is_accepted tests/test_runner_config.py::test_committed_run_configs_default_to_summary_profile -q` -> failed as expected before implementation; omitted `artifact_profile` still resolved to `full`.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_config.py tests/test_readme_contract.py -q` -> 20 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py tests/test_runner_artifact_profiles.py tests/test_phase5_performance.py tests/test_runner_config.py tests/test_readme_contract.py -q` -> 70 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 504 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found no blocking issues. Residual risk: validation `to_run_config()` also inherits summary, but validation uses `execute_strategy_run()` rather than runner artifact writing.
- 2026-05-28: Committed Phase 22.

## Phase 23 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Add loader purity regressions.
- [x] Implement shared purity checker.
- [x] Reuse checker in committed strategy tests.
- [x] Update docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 23 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_decision_strategy_loader.py::test_load_decision_strategy_rejects_side_effect_calls_before_import tests/test_decision_strategy_loader.py::test_load_decision_strategy_rejects_banned_imports_before_import -q` -> failed as expected before implementation; impure strategies imported without `DecisionStrategyLoadError`.
- 2026-05-28: `conda run -n quant pytest tests/test_decision_strategy_loader.py tests/test_strategy_docstrings.py -q` -> 9 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_execution.py tests/test_validation_runner.py tests/test_decision_strategy_loader.py tests/test_strategy_docstrings.py tests/test_readme_contract.py -q` -> 49 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> failed; `test_strategy_path_directory_failure_writes_summary` exposed a directory path escaping loader error translation after the new pre-import read.
- 2026-05-28: Fixed the directory-path regression with an explicit loader file check and added a focused loader regression.
- 2026-05-28: `conda run -n quant pytest tests/test_decision_strategy_loader.py tests/test_runner_api_cli.py::test_strategy_path_directory_failure_writes_summary -q` -> 7 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_execution.py tests/test_validation_runner.py tests/test_decision_strategy_loader.py tests/test_strategy_docstrings.py tests/test_readme_contract.py -q` -> 50 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 507 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found no loader/checker correctness issues. Valid bookkeeping finding: Phase 23 progress was stale; fixed before commit.
- 2026-05-28: Added the explicit `quant_data` banned-import regression to align tests with the Phase 23 plan.
- 2026-05-28: `conda run -n quant pytest tests/test_decision_strategy_loader.py tests/test_strategy_docstrings.py -q` -> 11 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 508 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Committed Phase 23.

## Phase 24 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Add funding metric regressions.
- [x] Implement semantic metric separation.
- [x] Update docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 24 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_vectorbtpro_backend.py::test_vectorbtpro_backend_adds_funding_return_for_crypto_perp_rows -q` -> failed as expected before implementation; `net_return` was overwritten with the linear funding adjustment.
- 2026-05-28: `conda run -n quant pytest tests/test_vectorbtpro_backend.py tests/test_validation_backends_and_policy.py tests/test_validation_runner.py -q` -> failed; policy regression expected `watchlist`, but current policy correctly stops at `mechanical_pass` with `no_positive_realistic_cost_evidence` when required net evidence is not positive.
- 2026-05-28: Fixed the policy test expectation to assert the actual no-positive-net gate behavior.
- 2026-05-28: `conda run -n quant pytest tests/test_vectorbtpro_backend.py tests/test_validation_backends_and_policy.py tests/test_validation_runner.py -q` -> 137 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 509 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found no blocking issues. Residual risk: backend metric semantics advertise optional funding metrics globally even when a backend result does not emit them, matching the Phase 24 design.
- 2026-05-28: Committed Phase 24.

## Phase 25 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Add runner event regressions.
- [x] Implement runner event surface.
- [x] Update docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 25 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_emits_structured_stage_events tests/test_runner_api_cli.py::test_cli_run_events_jsonl_writes_events_to_stderr -q` -> failed as expected before implementation; `run_config` did not accept `event_sink` and CLI rejected `--events-jsonl`.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_emits_structured_stage_events tests/test_runner_api_cli.py::test_cli_run_events_jsonl_writes_events_to_stderr -q` -> 2 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py tests/test_readme_contract.py -q` -> failed; CLI passed `event_sink=None` to a test monkeypatch with the old `run_config` signature.
- 2026-05-28: Preserved CLI monkeypatch/backward compatibility by passing `event_sink` only when `--events-jsonl` is set.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py tests/test_readme_contract.py -q` -> 46 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 511 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found a valid issue: causality failures returned by `_check_causality()` emitted a completed `causality_check` event because they did not raise. Fixed by letting stage contexts emit explicit semantic failures and adding a hidden-lookahead event regression.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_emits_structured_stage_events tests/test_runner_api_cli.py::test_cli_run_events_jsonl_writes_events_to_stderr tests/test_runner_api_cli.py::test_runner_catches_hidden_lookahead_before_request_build -q` -> 3 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_runner_api_cli.py tests/test_readme_contract.py -q` -> 46 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 511 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Follow-up code review found the causality event issue closed and no new blocking issues.
- 2026-05-28: Committed Phase 25.

## Phase 26 Checklist

- [x] Create design artifact.
- [x] Create implementation plan.
- [x] Complete engineering review in the plan.
- [x] Add lookahead scaling regressions.
- [x] Implement visibility cache.
- [x] Update docs.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Request code review and fix findings.
- [x] Commit.

## Phase 26 Verification Log

- 2026-05-28: `conda run -n quant pytest tests/test_validation_lookahead.py::test_hidden_lookahead_parses_row_visibility_once_per_check tests/test_validation_lookahead.py::test_hidden_lookahead_reuses_visible_rows_for_shared_decision_boundary -q` -> failed as expected before implementation; row visibility datetimes were parsed per decision and shared decision boundaries got distinct visible row tuples.
- 2026-05-28: `conda run -n quant pytest tests/test_validation_lookahead.py tests/test_runner_api_cli.py::test_runner_catches_hidden_lookahead_before_request_build -q` -> 8 passed.
- 2026-05-28: `conda run -n quant pytest tests/test_validation_lookahead.py tests/test_runner_api_cli.py tests/test_validation_runner.py -q` -> 84 passed.
- 2026-05-28: `conda run -n quant pytest -q` -> 513 passed.
- 2026-05-28: `git diff --check` -> passed.
- 2026-05-28: `conda run -n quant python -m compileall -q src tests` -> passed.
- 2026-05-28: Code review found no causality correctness issues. Valid bookkeeping finding: Phase 25 verification entries were misplaced under Phase 26; fixed before commit.
- 2026-05-28: Committed Phase 26.
