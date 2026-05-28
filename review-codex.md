# Foundation Review: `quant_strategies`

Date: 2026-05-28
Reviewer: Codex, senior quant researcher lens
Target: `/Users/Season_Yang/Personal/quant_strategies`

## Review Objective

I reviewed `quant_strategies` to determine whether it is a solid foundation for a small, focused quant research lifecycle where Season and `quant_autoresearch` can write pure strategies, run explicit experiments, produce auditable artifacts, and separate smoke evidence from human-led validation.

The review is optimized for correctness, auditability, reproducibility, maintainability, and reasonably fast research runs. It treats `PRD.md` as the target claim set and source code/tests/configs as primary evidence. It also accounts for Season's additional concerns: avoid over-engineering, evaluate run performance, do not let existing results bias the review, and do not preserve old artifacts/results through compatibility shims. Existing candidates and results can be rewritten and rerun.

### Clarified Scope

- **In scope**: repo foundation, public runner/validation workflows, decision ontology, engine/backend semantics, artifact semantics, test coverage, docs, performance posture.
- **Out of scope**: fixing issues, validating any specific alpha, live/paper trading, `quant_data` internals, `quant_autoresearch` internals, preserving old result artifacts.
- **Evidence-bias rule**: `researched/` and existing outputs were not treated as evidence that the research is correct. They were only relevant as artifact-shape/provenance examples.
- **Assumption**: `PRD.md` is an active target even though the worktree currently shows it as untracked.

## Executive Verdict

`quant_strategies` is a strong early smoke-research harness, but not yet a trustworthy paper-readiness foundation under the PRD. The repo has the right instincts: pure strategy files, explicit TOML runs, Pydantic contracts, advisory-only flags, generated artifacts, and broad tests. The foundation risk is semantic, not test health: the current strategy ontology is narrower than the PRD, metric units/bases are not first-class, summary runs can be useful for speed but are not audit-sufficient, validation can emit overconfident labels, and validation replay/backends will become slow or divergent at realistic scale.

The right direction is not to patch old results. Change the contracts cleanly, retire misleading labels, make metric/artifact trust tiers explicit, and rerun retained candidates under the new contract.

## Scope And Evidence Inspected

- **Instructions**: `AGENTS.md:1-44` and global instructions supplied in chat.
- **Target PRD**: `PRD.md:16-237`.
- **Current docs**: `README.md:1-241`, `docs/quant-autoresearch-consumer.md:1-219`.
- **Package/config**: `pyproject.toml:1-26`, `.gitignore:1-9`, `runs/*.toml`.
- **Decision contract**: `src/quant_strategies/decisions/models.py:13-154`, validators/loaders under `decisions/`.
- **Runner**: `src/quant_strategies/runner/__init__.py:19-367`, `execution.py`, `config.py`, `data_loader.py`, `decision_adapter.py`, `engine_runner.py`, `artifacts.py`, `artifact_profiles.py`.
- **Engine**: `src/quant_strategies/engine/models.py:12-201`, `evaluation.py:42-299`, `evidence.py:8-25`.
- **Validation**: `src/quant_strategies/validation/__init__.py:61-737`, `config.py`, `policy.py`, `lookahead.py`, `vectorbtpro_backend.py`, `manifest.py`.
- **Strategies/tests**: `untested/*.py`, `examples/strategies/simple_momentum.py`, all `tests/`.
- **Independent lenses**: onboarding, architecture, senior software engineering, adversarial, and senior quant/quant math subagents. I reconciled their findings rather than copying them wholesale.
- **Verification run**: `conda run -n quant pytest` -> `460 passed in 26.45s`.
- **Not inspected**: live `quant_data` database behavior, live VectorBT Pro output beyond tests, `quant_autoresearch` source, every nested `researched/` artifact.

## Intended Foundation Model

From first principles, the project should have one clear flow:

```text
strategy.py + experiment.toml
        |
        v
public runner API / CLI
        |
        v
neutral execution kernel
  - load strategy
  - validate params
  - load rows through quant_data
  - freeze inputs
  - generate typed decisions
  - verify causality and row lineage
  - build execution plan
        |
        +--------------------+
        |                    |
        v                    v
smoke engine             validation backend(s)
single-run screening     scenario/window advisory checks
        |                    |
        +---------+----------+
                  v
artifacts with explicit trust tier, metric units, hashes, and audit trail
```

The minimal durable foundation is not a general backtester. It is a strict research kernel with one strategy-output ontology, one execution-plan contract, explicit capability declarations for what each backend can execute, and artifacts that make every reported number traceable or explicitly marked as search-only.

## Project Ontology: Concepts, Contracts, Boundaries, Invariants

| Concept / boundary | Responsibility | Key contracts or invariants | Current-code fit |
|---|---|---|---|
| Strategy module | Pure function from rows/params to decisions | No IO, no runner/engine calls, no mutation; docstring states thesis, observables, rule, assumptions, falsifier | Strong for committed strategies via tests; weak for arbitrary candidate workspaces |
| Decision ontology | Express the intended trade in typed form | Instrument, timing, information set, intent, sizing, exits, observations, metadata | Too narrow for PRD; single-leg and target-weight biased |
| Execution kernel | Shared causal work before any backend | Same import, params, data load, freezing, row hashing, decision validation, causality checks | Partly present in `runner.execution`, but runner-owned and validation imports it |
| Execution plan | Backend-independent entry/exit/fill/cost/funding semantics | Same decision should map to auditable fills and costs across backends, or declare unsupported/asymmetric semantics | Missing as first-class contract |
| Smoke engine | Fast search primitive | Deterministic, causal, clearly named non-NAV smoke metrics | Strong speed and naming; causality lineage and weak evidence need stronger machine fields |
| Validation harness | Advisory multi-window/scenario checks | Hidden-lookahead protection, backend capability matrix, no auto-promotion | Directionally strong; labels and artifact traceability overstate current evidence |
| Artifacts | Audit trail and machine interface | Config, strategy snapshot, input rows or reproducible hash, decisions, fills/exits, costs/funding, metrics, manifest hashes | Good for full runner; summary and validation are not fully reconstructable |
| Metrics | Numeric evidence | Unit, base, aggregation, backend semantics, comparability/asymmetry | Underbuilt; mostly raw floats/dicts |
| Data boundary | Use only public `quant_data` loaders | No data platform ownership; structured upstream feedback | Mostly good; hidden `.env` lookup couples to upstream source layout |

## What Already Exists And Should Be Reused

| Existing code/flow | What it does | Reuse / concern |
|---|---|---|
| `quant_strategies.runner.run_config` (`runner/__init__.py:30`) | Small public Python API for one configured experiment | Preserve the public shape unless PRD intentionally changes it |
| TOML `RunConfig` (`runner/config.py:49-142`) | Validates data, fill, cost, output, and paths inside repo root | Preserve and extend carefully |
| Strategy purity tests (`tests/test_strategy_docstrings.py:81-132`) | Enforce docstrings, flat layout, banned imports/calls for committed strategies | Preserve; add candidate-time enforcement if candidates are untrusted |
| Pydantic decision models (`decisions/models.py:18-154`) | Frozen typed decision objects with timezone and metadata validation | Preserve the typed boundary; refactor the ontology |
| Smoke engine (`engine/evaluation.py:42-168`) | Fast deterministic trade screening with fill timing, costs, funding, exits | Preserve as a screening primitive |
| Full runner artifacts (`runner/artifacts.py:40-235`) | Copy config/strategy, write rows, decisions, signals, engine request, evidence, manifest, summary | Preserve for audit runs |
| Validation advisory flags (`evidence_semantics.py:18-37`, `validation/policy.py:16-56`) | Keep promotion/paper/live eligibility false | Preserve |
| Row-contract feedback (`runner/artifacts.py:141-179`) | Reports required fields, timestamps, duplicates, upstream feedback strings | Preserve and make harder to ignore |
| Performance tests (`tests/test_phase5_performance.py:145-173`) | Guard smoke runtime and summary artifact size | Preserve and expand to validation |

## Architecture And Boundary Review

### Finding 1. Decision Ontology Is Too Narrow For The PRD

- **Severity**: Critical
- **Action class**: Refactor
- **Evidence**: PRD requires intent/action, buy/sell, futures/options, multi-leg structures, target contracts, risk sizing, and richer exits (`PRD.md:80-96`). Current literals cover only `equity_or_etf`, `fx_pair`, `crypto_perp`, `long/short/flat`, and `target_weight/notional` (`decisions/models.py:13-15`). `StrategyDecision` is single-instrument (`decisions/models.py:120-128`). The smoke adapter rejects `flat` and non-`target_weight` (`runner/decision_adapter.py:12-20`).
- **Why it matters**: A quant research foundation must make intended exposure explicit. If spreads, rolls, option/future details, close/rebalance actions, or risk sizing are forced into metadata, the engine cannot audit or reject them correctly.
- **Root cause**: Ontology and execution capability are mixed. The decision type currently reflects what the smoke engine can execute, not the larger strategy language the PRD requires.
- **Recommendation**: Define a single richer strategy-output ontology first, then add backend capability gates. Do not build full futures/options/multi-leg execution immediately unless needed; make unsupported semantics explicit and fail/mark unsupported cleanly.
- **Tradeoff**: This is the largest design change, but it avoids accumulating adapters and metadata hacks.

### Finding 2. Runner And Validation Do Not Yet Share A Neutral Execution Kernel

- **Severity**: High
- **Action class**: Refactor
- **Evidence**: PRD calls for one ontology, one execution-model contract, and one causal-invariant kernel (`PRD.md:108-116`). Validation imports `runner.execution` (`validation/__init__.py:16`) and builds `RunConfig` via validation config (`validation/config.py:186-203`). VectorBT Pro independently rebuilds windows and funding adjustment logic (`validation/vectorbtpro_backend.py:182-236`, `380-411`) while smoke has separate fill/funding logic (`engine/evaluation.py:52-79`, `276-299`).
- **Why it matters**: Backend disagreement should be a declared asymmetry, not an accidental result of duplicated execution semantics.
- **Root cause**: Shared code exists, but it is runner-owned and stops before a backend-independent execution plan.
- **Recommendation**: Extract a neutral kernel package that owns strategy execution, row hashing, causality checks, and decision-to-execution-plan mapping. Runner and validation should adapt to that kernel, not to each other.
- **Tradeoff**: Keep `runner.run_config` stable if possible; do not preserve old artifacts through compatibility code.

### Finding 3. Validation Orchestration Is Too Concentrated

- **Severity**: Medium
- **Action class**: Simplify
- **Evidence**: `run_validation` handles config resolution, backend selection, per-window execution, data audit, hidden-lookahead replay, readiness, matrix expansion, scenario regeneration, backend execution, policy, and artifact writing in one long function (`validation/__init__.py:61-346` and `391-737`). PRD forbids orchestrator god-functions (`PRD.md:108-116`).
- **Why it matters**: Adding richer ontology, metric schemas, and performance instrumentation will be risky if all stages are interleaved.
- **Root cause**: The pipeline was kept simple by putting orchestration in one place; it has outgrown that shape.
- **Recommendation**: Split into typed stage functions: `prepare_validation`, `run_window`, `audit_window`, `expand_scenarios`, `run_backend_scenario`, `classify`, `write_artifacts`.
- **Tradeoff**: This is not a rewrite of the workflow. It is a boundary cleanup around the existing pipeline.

### Finding 4. Public Consumer Contract Disagrees Between PRD And Docs

- **Severity**: Medium
- **Action class**: Refactor
- **Evidence**: PRD says the public consumer surface is re-exported and Protocol-typed (`PRD.md:118-125`). Consumer docs intentionally require imports from `quant_strategies.runner` and say the package root does not re-export them (`docs/quant-autoresearch-consumer.md:54-58`). Package root only contains a docstring (`src/quant_strategies/__init__.py:1`).
- **Why it matters**: `quant_autoresearch` needs one stable surface. Disagreement between PRD and docs is a misuse vector.
- **Root cause**: Target contract and implemented contract diverged.
- **Recommendation**: Decide the surface explicitly. My bias: preserve `quant_strategies.runner.run_config` as the stable public surface unless there is a strong reason to add a top-level facade. Update the PRD or code accordingly.
- **Tradeoff**: Simpler import paths are nice, but avoiding a broad top-level API keeps misuse lower.

## Engineering, Testability, And Operability Review

### Finding 5. Summary Runs Are Fast But Not Audit-Sufficient

- **Severity**: High
- **Action class**: Add
- **Evidence**: Summary profile is recommended for large sweeps (`docs/quant-autoresearch-consumer.md:172-176`) and ranking reads `summary.json` (`docs/quant-autoresearch-consumer.md:191-198`). Summary mode omits input rows, decision records, signals, engine request, and evidence (`runner/__init__.py:71-159`; tests lock this at `tests/test_runner_api_cli.py:282-297` and `tests/test_phase5_performance.py:156-173`). PRD requires every metric to be reproducible/auditable from artifacts (`PRD.md:98-106`, `127-135`).
- **Why it matters**: Search sweeps need speed, but retained results need traceability. A search-only score should not masquerade as audit-ready evidence.
- **Root cause**: Artifact profile is used as a size/performance choice, not a trust-tier contract.
- **Recommendation**: Add machine-readable `artifact_trust_tier`: `search_only` for summary, `audit_replayable` for full. Require retained candidates and validation handoff to rerun under `full`; do not repair old summary artifacts.
- **Verification needed**: Tests that summary runs are explicitly marked non-auditable and full reruns contain all reconstructability inputs.

### Finding 6. Runner Success Can Be Too Easy To Rank

- **Severity**: High
- **Action class**: Add
- **Evidence**: `RunResult` has `success`, `run_completed`, and `assessment_status` but no evidence-quality fields (`runner/__init__.py:19-27`). Screen success is unconditional after engine completion (`runner/__init__.py:323-326`). Evidence quality records missing/partial `available_at` and `runner_causality_not_verified` as warnings (`runner/artifacts.py:114-138`). Docs tell consumers to filter on those fields (`docs/quant-autoresearch-consumer.md:195-200`), but the typed return object does not force it.
- **Why it matters**: An autonomous search loop can rank on `success` plus smoke score and ignore weak causality/data evidence.
- **Root cause**: Evidence quality is artifact-only rather than part of the typed result contract.
- **Recommendation**: Add evidence-quality fields to `RunResult` or a typed `RunSummary` result object: row-contract status, availability status, causality status, and rankability/trust tier.
- **Tradeoff**: More fields in the public API, but they are exactly the fields a search loop must not ignore.

### Finding 7. Strategy Purity Is Not Enforced For Arbitrary Candidate Workspaces

- **Severity**: Medium
- **Action class**: Add
- **Evidence**: Loader imports any configured Python file and checks only for callable `generate_decisions` plus optional callable `validate_params` (`decisions/strategy_loader.py:48-66`). Static purity tests scan committed `tested/`, `untested/`, `researched/.../strategy.py`, and examples (`tests/test_strategy_docstrings.py:51-69`, `103-132`). Consumer docs say candidates should not load data, call engines, write artifacts, or mutate inputs (`docs/quant-autoresearch-consumer.md:81-92`, `204-216`).
- **Why it matters**: `quant_autoresearch` candidates are the primary workflow. If candidate-time purity is only documented, a generated strategy can load data or write files during ranking.
- **Root cause**: Purity enforcement lives in repo tests, not in the runtime boundary that loads candidate strategies.
- **Recommendation**: Add an optional AST purity check during strategy load, enabled by default for runner/validation candidate workspaces. Keep it focused on forbidden imports/calls, not a sandbox.
- **Tradeoff**: Static checks can false-positive. That is acceptable for generated candidate workflows if errors are clear.

### Finding 8. Structured Stage Observability Is Missing

- **Severity**: Medium
- **Action class**: Add
- **Evidence**: PRD requires structured logging at stage boundaries (`PRD.md:178-179`). Source search found no logger usage in `src/`; CLI prints only result path or failure text (`runner/cli.py:25-45`).
- **Why it matters**: Autonomous loops and slow validation runs need live stage timing, counts, backend status, and result directory without opening artifacts after the fact.
- **Root cause**: Artifacts are treated as the only observability surface.
- **Recommendation**: Add structured events for `config_loaded`, `data_loaded`, `decisions_generated`, `causality_checked`, `request_built`, `engine_evaluated`, `artifacts_written`, with durations and counts.
- **Tradeoff**: Keep logs minimal and machine-readable; do not add a dashboard.

### Finding 9. Validation Lookahead Replay Will Not Scale Cleanly

- **Severity**: Medium
- **Action class**: Refactor
- **Evidence**: Hidden-lookahead check loops every baseline decision, filters all rows, freezes rows, and reruns the full strategy per decision (`validation/lookahead.py:33-70`). Freezing deep-copies rows and params (`boundary.py:12-18`). Existing performance tests cover smoke engine and summary artifact size only (`tests/test_phase5_performance.py:145-173`).
- **Why it matters**: Runtime scales poorly as decisions, windows, and symbols grow. This is likely the first real performance wall in validation.
- **Root cause**: Correctness-first replay was implemented directly rather than with indexed visible slices or batched replay.
- **Recommendation**: Pre-index visible row slices, avoid repeated deep copies where safe, and add validation performance budgets. Do not weaken causality checks for speed.
- **Tradeoff**: More implementation complexity is justified here because validation runtime is a core workflow.

### Finding 10. `quant_data` Engine Discovery Has Hidden Local Coupling

- **Severity**: Medium
- **Action class**: Refactor
- **Evidence**: `_default_engine()` discovers a `.env` by walking from `quant_data.loader.__file__` and passing it into `quant_data.config.DataConfig` (`runner/data_loader.py:121-125`). This is tested behavior. The repo rule says to use public `quant_data` loader APIs and give feedback on limitations (`AGENTS.md:23-26`).
- **Why it matters**: Reproducibility should not depend on a local checkout layout of an upstream package.
- **Root cause**: Convenience environment discovery is embedded in this repo instead of being explicit config or upstream-owned.
- **Recommendation**: Prefer explicit `quant_data` environment configuration, dependency injection, or documented upstream config. Record data engine/source identity in manifests where available.
- **Tradeoff**: Slightly more setup friction; better reproducibility.

## Domain-Specific Lens Findings

### Finding 11. `paper_candidate` Overstates The Evidence

- **Severity**: Critical
- **Action class**: Retire
- **Evidence**: PRD explicitly says no `paper_candidate` without statistical evidence and no overclaiming metric names (`PRD.md:98-106`). Policy emits `paper_candidate` when mechanical gates pass (`validation/policy.py:461-466`). Overfit controls include `deflated_sharpe` and `monte_carlo` but always set them to `None` (`validation/policy.py:142-153`). Eligibility flags stay false, which is good (`validation/policy.py:42-56`).
- **Domain risk**: In quant research, labels shape behavior. A label that sounds paper-ready can cause selection bias and false confidence even if flags stay false.
- **Root cause**: Naming/decision policy, not math implementation.
- **Recommendation**: Rename to `review_candidate`, `validation_candidate`, or `mechanical_review_candidate` unless real statistical evidence is added. Because old results are disposable, do not carry a compatibility alias unless Season explicitly wants one.

### Finding 12. Metric Units, Bases, And Comparability Are Not First-Class

- **Severity**: High
- **Action class**: Add
- **Evidence**: Engine `Trade` and `SmokeScore` expose raw floats (`engine/models.py:144-165`). Validation backends return free-form metric dicts (`validation/backends.py:17-24`). Evidence semantics names the runner return model string but does not attach unit/base to every numeric (`evidence_semantics.py:18-28`). PRD requires unit/base for every numeric and declared cross-backend tolerance/asymmetry (`PRD.md:98-106`).
- **Domain risk**: `smoke_score.sum_weighted_trade_net_return` and VectorBT Pro `net_return` can be compared as if they are the same return. They are not necessarily the same measurement.
- **Root cause**: Metrics are values first and semantics second.
- **Recommendation**: Add typed metric records: `name`, `value`, `unit`, `base`, `aggregation`, `backend`, `return_path_model`, `comparable_to`, and `tolerance/asymmetry`.

### Finding 13. Crypto Perp Funding Is Added As A Linear Adjustment To Portfolio Return

- **Severity**: High
- **Action class**: Refactor
- **Evidence**: VectorBT Pro gets portfolio total return (`validation/vectorbtpro_backend.py:321-333`), then `_funding_adjusted_metrics` adds summed funding to `net_return` (`validation/vectorbtpro_backend.py:380-411`). Funding itself is a simple event-rate sum times direction and weight (`validation/funding.py:21-59`). Smoke engine uses a similar linear funding return inside per-trade returns (`engine/evaluation.py:70-79`, `276-299`).
- **Domain risk**: A NAV-path total return plus a linear cashflow approximation should not be relabeled as a generic `net_return` without declaring the base and aggregation.
- **Root cause**: Missing metric schema and shared execution-plan/cashflow model.
- **Recommendation**: Either model funding inside the execution/NAV path or label the result as `linear_funding_adjusted_return` with explicit base. Keep policy gates off ambiguous `net_return`.

### Finding 14. Validation Artifacts Do Not Fully Reproduce Backend Metrics

- **Severity**: High
- **Action class**: Add
- **Evidence**: PRD requires traceability to rows, decisions, fills/exits, funding/cost contributions, and config (`PRD.md:127-135`). Validation records aggregate backend metrics and scenario decision hashes (`validation/__init__.py:638-695`), while data provenance stores row count and row hash (`validation/__init__.py:443-467`) and manifest core hashes omit input rows and fills (`validation/manifest.py:112-124`).
- **Domain risk**: A reviewer cannot reconstruct backend metrics from validation artifacts alone.
- **Root cause**: Validation artifact schema is summary-oriented.
- **Recommendation**: For validation, write row artifacts or a reproducible row snapshot reference, per-scenario execution/fill/trade records, and funding/cost contribution records. Old validation artifacts can be discarded and rerun.

## Unknown Unknowns And Assumption Risks

| Assumption | Why it may be wrong | How to test or de-risk |
|---|---|---|
| `quant_autoresearch` will correctly filter evidence warnings | It may rank on `success` plus smoke score | Add typed rankability/evidence fields and consumer contract tests |
| Current smoke performance extrapolates to real sweeps | Tests cover synthetic engine runtime, not real loader/strategy/validation replay | Add benchmark configs with realistic symbol/window/decision counts |
| `available_at` coverage is good enough upstream | Runner often treats missing availability as non-fatal warnings | Track availability coverage by dataset; require validation to fail on missing lineage |
| VectorBT Pro backend semantics match smoke for supported cases | Execution paths are independently implemented | Add cross-backend equivalence tests on simple supported strategies |
| PRD's broad instrument ontology is immediately required | Building full futures/options/multi-leg execution now may be over-engineering | Define ontology/capabilities now; implement execution support only for active research needs |
| Candidate strategy runtime is well behaved | Loader executes arbitrary Python modules | Add runtime purity checks and stage timeout policy if needed |

## Overbuilt, Underbuilt, And Right-Sized Areas

- **Overbuilt**: `paper_candidate` as a label is too strong for mechanical gates. Multiple freezing idioms (`boundary.py`, decision metadata freezing, validation `_FrozenDict`) add local complexity without a clear shared policy. The PRD's full instrument list would be overbuilt if implemented as full execution support immediately.
- **Underbuilt**: strategy-output ontology, metric schemas, validation artifact reconstructability, candidate-time purity enforcement, structured logging, validation replay performance, backend equivalence tests.
- **Right-sized**: flat strategy files, pure function strategy contract, TOML configs, public `runner.run_config`, advisory eligibility flags, full runner artifact profile, row-contract feedback, smoke engine as a fast screening primitive, focused tests.

## Missing Docs, PRD, ADR, Or Decision Records

- **PRD/code mismatch**: public API export policy (`PRD.md:118-125` vs `docs/quant-autoresearch-consumer.md:54-58`).
- **Missing ADR**: strategy ontology and backend capability model.
- **Missing ADR**: metric schema and return semantics, especially smoke score vs NAV-path returns.
- **Missing ADR**: artifact trust tiers (`search_only` vs `audit_replayable`) and rerun policy for retained candidates.
- **Missing ADR**: validation backend equivalence/asymmetry policy.
- **Missing ADR**: `quant_data` environment configuration and reproducibility metadata.
- **Docs status**: `PRD.md` is currently untracked; if it is the source of truth, it should be committed or clearly marked as draft outside the repo contract.

## Preserve / Refactor / Simplify / Add / Retire Action Map

| Action class | Findings / recommendations | Rationale |
|---|---|---|
| Preserve | Pure strategy files, TOML run configs, `runner.run_config`, advisory flags, full artifact profile, row-contract feedback, smoke engine, existing focused tests | These are right-sized for a disciplined research harness |
| Refactor | Richer decision ontology with capability gates; neutral execution kernel; validation orchestration; validation replay performance; `quant_data` environment boundary; funding metric semantics | Capabilities are needed, but current boundaries will drift or overstate semantics |
| Simplify | Split validation orchestrator; consolidate freezing idioms; avoid implementing full futures/options/multi-leg execution until needed | Reduces accidental complexity without weakening the core |
| Add | Artifact trust tiers; typed evidence fields in result object; candidate-time purity checks; structured stage logs; typed metric schemas; validation reconstructability artifacts; cross-backend equivalence tests | Missing contracts directly affect trustworthiness |
| Retire | `paper_candidate` label without statistical evidence; compatibility shims for old artifacts/results | Misleading labels and legacy preservation fight the PRD |

## Prioritized Recommendations

| Priority | Action class | Recommendation | Why now | Verify |
|---|---|---|---|---|
| P1 | Retire | Rename `paper_candidate` to a non-overclaiming advisory label, or add real statistical evidence before using it | Prevents false confidence in quant workflow | Policy tests updated; no eligibility flags change |
| P1 | Refactor | Define the single decision ontology and backend capability model | Avoids metadata hacks and adapter sprawl | Schema tests for intent, side, instruments, sizing, multi-leg unsupported gates |
| P1 | Add | Add typed metric schemas with unit/base/aggregation/backend semantics | Prevents comparing unlike returns | Artifact tests assert every numeric metric has semantics |
| P1 | Add | Add artifact trust tiers and require retained candidates to rerun `full` | Keeps sweep performance without pretending summary is auditable | Summary marked `search_only`; full marked `audit_replayable` |
| P2 | Refactor | Extract neutral execution kernel and execution-plan contract | Aligns runner/validation and backend semantics | Runner and validation import kernel, not each other |
| P2 | Add | Make evidence quality/rankability part of typed runner result | Prevents autonomous loops from ignoring weak evidence | Consumer tests fail if row contract/causality warnings are ignored |
| P2 | Add | Add validation row/fill/trade/cost/funding artifacts | Makes validation numbers auditable | Reconstructability test from artifacts |
| P2 | Refactor | Optimize hidden-lookahead replay and add validation performance budgets | Prevents validation from becoming the bottleneck | Benchmark with realistic decisions/windows |
| P3 | Add | Structured stage logging | Improves operability for long runs and agents | CLI/API stage event tests |
| P3 | Refactor | Remove hidden `quant_data` `.env` discovery or document/record it explicitly | Improves reproducibility | Manifest records data environment identity where possible |

## NOT In Scope

- Backward compatibility for old strategy/result shapes. Existing candidates can be rewritten and rerun.
- Market validation or live/paper-trading readiness.
- Building a general-purpose composable backtester.
- Implementing complete futures/options/multi-leg execution immediately.
- Data acquisition, repair, refresh, or source joining inside this repo.
- Statistical research corrections unless Season explicitly decides to add them.
- UI/dashboard/notebook workflows.

## Verification Summary

- **Verified**: CodeGraph index healthy; source/docs/tests/configs inspected; `conda run -n quant pytest` passed with `460 passed in 26.45s`.
- **Not verified**: live `quant_data` data loads, real database-backed run performance, live VectorBT Pro portfolio internals beyond tests, `quant_autoresearch` integration behavior, every nested `researched/` artifact.
- **Residual risk**: The test suite proves current contracts are internally consistent. It does not prove the contracts are sufficient for PRD paper-readiness, metric comparability, or large validation runs.
