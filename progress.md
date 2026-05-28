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

Phase 11: P1 duplicate decision execution keys.

Design: `docs/superpowers/specs/2026-05-28-foundation-review-p1-duplicate-decision-key-design.md`
Plan: `docs/superpowers/plans/2026-05-28-foundation-review-p1-duplicate-decision-key.md`

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
