# Foundation Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement task-by-task. This plan includes `/plan-eng-review` decisions and replaces the earlier exhaustive script with a compact, decision-complete plan.

## Summary

Reset `quant_strategies` around one clean contract:

```text
generate_decisions(rows, params) -> list[StrategyDecision]
```

Keep the current package boundaries: `decisions` owns strategy output, `runner` owns smoke execution, `engine` remains deterministic smoke evaluation, and `validation` owns researched-package gates plus backend evidence. Do not add compatibility for old signal-era contracts.

```
strategy.py
  └─ generate_decisions(frozen rows, frozen params)
       └─ validate_decision_output
            └─ validation readiness
                 ├─ researched manifest/layout gate
                 ├─ dependency metadata gate
                 ├─ observation lineage gate
                 └─ data availability audit
                      └─ backend run -> advisory validation decision
```

## Key Changes

- **Validation language:** Replace `clear_yes` / `PromotionDecision` with advisory-only `mechanical_pass` / `ValidationPolicyDecision`. Keep `promotion_eligible`, `paper_trade_eligible`, and `live_eligible` false.
- **Researched package contract:** Require `researched/<family>/<variant>/strategy.py`, `validation.toml`, and matching `manifest.json` hashes before backend execution.
- **Readiness metadata:** Add a minimal `[readiness]` config for validation-ready packages:

```toml
[readiness]
min_observations_per_decision = 1
required_observation_fields = ["close"]
```

  Validation must fail before backend execution when any decision has fewer observations than the minimum or lacks required observed fields. Keep exact row/symbol completeness in strategy-family tests, not a generic dependency DSL.
- **Observation lineage:** Keep `audit_decision_rows` responsible for declared-row availability. Add exact FX and crypto lineage tests so current nontrivial strategies must emit complete `ObservationRef` rows for the data they use.
- **Metric semantics:** Split validation backend metrics into `backend_native_net_return`, optional `linear_funding_adjustment`, and optional `linear_adjusted_net_return`. Policy may gate on `linear_adjusted_net_return` when present, otherwise backend-native return.
- **Artifacts:** Rename `promotion_decision.json` to `validation_decision.json` everywhere, including `validation_manifest.json` core hashes and tests.
- **Legacy cleanup:** Remove public `hold_bars` fields and params. Use only `max_hold_bars` in engine model, runner adapter, configs, tests, and artifacts.
- **Runner smoke scores:** Expose runner summary/evidence totals under `smoke_score.sum_weighted_trade_*`, not top-level return names.
- **README:** Rewrite the root README as a generic project contract. Do not mention named strategies, named run configs, or strategy-specific explanations.
- **Validation runner cleanup:** Add one small local helper for early hard-no artifact writes. Do not split the validation runner broadly.

## Test Plan

Use `conda run -n quant pytest` for final verification. Add focused tests first, then implement.

```
CODE PATHS                                           COVERAGE REQUIRED
validation policy
  ├─ hard_no / maybe / mechanical_pass                unit tests
  ├─ advisory-only eligibility fields                 unit tests
  └─ invalid/non-finite backend metrics               unit tests

researched validation
  ├─ missing manifest/layout -> no backend call        integration tests
  ├─ stale manifest hash -> no backend call            integration tests
  ├─ missing readiness metadata/observations           integration tests
  ├─ scenario-regenerated missing observations         integration tests
  └─ manifest core hash uses validation_decision.json  integration tests

strategy lineage
  ├─ FX triangle observations include all legs         strategy tests
  ├─ crypto funding observations include history/fund  strategy tests
  └─ late/missing observed rows fail data audit        data audit tests

runner smoke
  ├─ no public hold_bars in signals/request/artifacts  runner + engine tests
  ├─ max_hold_bars required and enforced               engine tests
  └─ smoke_score names in summary/evidence             artifact tests

docs
  ├─ banned legacy terms absent                        docs test
  └─ README has no named strategies/run configs        docs test
```

Add or update these test families:

- `tests/test_validation_backends_and_policy.py`: advisory outcome, metric key selection, non-finite metric rejection.
- `tests/test_validation_runner.py`: canonical researched package, manifest failures, readiness metadata failures, no backend calls on gate failure, `validation_decision.json` manifest hashes.
- `tests/test_validation_readiness.py`: metadata and observation checks.
- `tests/test_fx_triangular_residual_reversion.py` and `tests/test_crypto_perp_funding_crowding_reversal.py`: exact emitted observation lineage for current strategy families.
- `tests/test_runner_engine_runner.py`, `tests/test_engine_models.py`, `tests/test_engine_screen.py`, `tests/test_runner_api_cli.py`: `max_hold_bars` only and smoke score artifacts.
- `tests/test_active_docs_current_contract.py`: active docs contain no legacy terms and README contains no named strategy/run-config examples.

## Implementation Tasks

Synthesized from `/plan-eng-review`. Each task derives from a specific finding or accepted scope decision.

- [ ] **T1 (P1, human: ~3h / CC: ~25min)** — Validation readiness — Add minimal dependency metadata and exact lineage tests.
  - Surfaced by: Architecture D3 and TODO D14.
  - Files: validation config/readiness, validation runner, FX/crypto strategy tests.
  - Verify: `conda run -n quant pytest tests/test_validation_readiness.py tests/test_validation_runner.py tests/test_fx_triangular_residual_reversion.py tests/test_crypto_perp_funding_crowding_reversal.py -q`.

- [ ] **T2 (P1, human: ~45min / CC: ~8min)** — Validation artifacts — Rename validation decision artifact through manifest identity.
  - Surfaced by: Architecture D4.
  - Files: validation artifact writer, validation manifest, validation runner tests.
  - Verify: `conda run -n quant pytest tests/test_validation_runner.py tests/test_validation_artifacts.py -q`.

- [ ] **T3 (P1, human: ~45min / CC: ~10min)** — README/docs — Rewrite README as generic contract and add strict docs guard.
  - Surfaced by: Code Quality D6 and Test D10.
  - Files: `README.md`, active-docs test.
  - Verify: `conda run -n quant pytest tests/test_active_docs_current_contract.py -q`.

- [ ] **T4 (P2, human: ~1h / CC: ~12min)** — Validation runner — Add one local early-failure helper.
  - Surfaced by: Code Quality D8.
  - Files: validation runner and existing validation runner tests.
  - Verify: `conda run -n quant pytest tests/test_validation_runner.py -q`.

- [ ] **T5 (P1, human: ~1 day / CC: ~60min)** — Legacy cleanup — Remove public and internal `hold_bars` compatibility.
  - Surfaced by: accepted strict cleanup scope.
  - Files: engine model/evaluation, runner adapter/request/artifacts, run configs, engine/runner/strategy tests.
  - Verify: `rg -n '\bhold_bars\b' src runs README.md` has no matches; `conda run -n quant pytest tests/test_engine_models.py tests/test_engine_screen.py tests/test_runner_engine_runner.py tests/test_runner_api_cli.py -q`.

- [ ] **T6 (P1, human: ~2h / CC: ~25min)** — Metric semantics — Rename validation and smoke metrics.
  - Surfaced by: foundation review and accepted broad scope.
  - Files: validation policy/backends/vectorbtpro, runner summary, engine evidence serialization, related artifact tests.
  - Verify: `conda run -n quant pytest tests/test_validation_backends_and_policy.py tests/test_vectorbtpro_backend.py tests/test_runner_artifact_profiles.py tests/test_engine_validate_and_evidence.py -q`.

- [ ] **T7 (P1, human: ~30min / CC: ~10min)** — Final verification — Run full suite and line-count accounting.
  - Surfaced by: project AGENTS contract.
  - Files: all touched source/tests/docs/configs.
  - Verify: `conda run -n quant pytest`, `git diff --numstat`, and `git status --short`.

## NOT In Scope

- Paper trading or live trading setup: explicitly outside this foundation reset.
- Full portfolio engine rewrite: runner/engine remain smoke evidence only.
- PSR/DSR/PBO/CPCV/statistical validation stack: valuable later, not required to make current contracts honest.
- Full dependency DSL: rejected in favor of minimal readiness metadata plus exact strategy tests.
- Separate examples doc: rejected for now to keep docs surface small and current.
- Broad `validation/__init__.py` split: rejected; add only one local helper.

## What Already Exists

- `validate_decision_output` already enforces `StrategyDecision` output shape and strategy id.
- `audit_decision_rows` and `audit_observation_dependencies` already verify declared observation rows, `available_at`, `as_of_time`, and `decision_time`.
- `check_research_manifest` already hashes strategy/config files; tighten it instead of replacing it.
- `BackendRunResult` already centralizes backend status/metrics; add finite metric validation there.
- `runner.run_config` already freezes rows/params and writes artifacts; rename public fields rather than adding a second runner.
- `quant_autoresearch` should continue consuming `quant_strategies.runner.run_config`; do not add another harness.

## Failure Modes

- Missing or stale researched manifest: covered by integration tests; validation returns hard-no before backend.
- Missing readiness metadata or incomplete observations: covered by readiness and strategy lineage tests; validation returns hard-no before backend.
- Backend emits NaN/Inf metrics: covered by model and artifact tests; validation fails before non-standard JSON.
- Artifact rename misses manifest hash: covered by validation manifest test; manifest must hash `validation_decision.json`.
- README drifts back to strategy catalog: covered by active docs guard.
- Very large validation packages become slow: no current performance work; revisit with profiling if package size grows.

## Parallelization

| Workstream | Modules touched | Depends on |
|---|---|---|
| Validation gates | `validation/`, strategy tests | — |
| Runner/engine legacy cleanup | `engine/`, `runner/`, configs | — |
| Docs cleanup | root docs, docs tests | — |
| Metric semantics | `validation/`, `runner/`, `engine/` | validation and runner touched surfaces |
| Final verification | all | all workstreams |

Parallel lanes:

- Lane A: Validation gates -> validation artifact manifest updates.
- Lane B: Runner/engine `max_hold_bars` cleanup.
- Lane C: README/docs guard.
- Lane D: Metric semantics, after Lane A/B APIs settle.

Conflict flags: Lane A and Lane D both touch `validation/`; Lane B and Lane D both touch `runner/` and `engine/`. Run A/B/C in parallel only if each uses separate worktrees and D waits for merges.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | not run | Existing foundation review and brainstorming spec used instead |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | not run | Outside voice skipped |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | issues resolved in plan | 6 issues, 0 critical gaps after accepted decisions |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | not applicable | Backend/library/docs cleanup only |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | not run | README cleanup covered by eng review |

- **UNRESOLVED:** 0.
- **VERDICT:** ENG REVIEW COMPLETE — ready to implement after Plan Mode exits.
