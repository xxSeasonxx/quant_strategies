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

Phase 2: P1 decision ontology.

Design: `docs/superpowers/specs/2026-05-28-foundation-review-p1-ontology-design.md`
Plan: `docs/superpowers/plans/2026-05-28-foundation-review-p1-ontology.md`

## Finding Triage

| Finding | Status | Notes |
|---|---|---|
| Runner does not enforce hidden-lookahead replay | Confirmed true, Phase 1 | Current runner does not call replay before `smoke_passed`. |
| `paper_candidate` overstates mechanical evidence | Confirmed true, Phase 1 | Rename to `mechanical_review_candidate`. |
| Smoke aggregate `return` names overstate units | Confirmed true, Phase 1 | Rename to activity-sum names. |
| Runner/validation neutral kernel incomplete | Partly true, deferred | Shared execution exists; causality is not shared. Phase 1 extracts causality only. |
| Engine parallel ontology | Confirmed true, deferred | Larger refactor; not needed to fix P0 labels/causality. |
| Validation orchestrator god-function | Confirmed true, deferred | Split after semantic blockers. |
| Public API re-export mismatch | Partly true, deferred | `AGENTS.md` chooses `quant_strategies.runner.run_config`; treat as PRD/docs reconciliation, not immediate code change. |
| Full G1 ontology support missing | Confirmed true, Phase 2 | Define ontology/capability gates before executing all asset classes. |

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
