# Codex Foundation Review

Date: 2026-06-03

## Executive Verdict

The foundation shape is directionally right and should not be rewritten. The public workflow is simple: one pure strategy file plus explicit config flows through `run`, `validate`, or `evaluate`. The core boundary is also mostly right: `quant_strategies` produces stateless evidence; `quant_autoresearch` owns candidate generation, search memory, ranking, comparison across strategies, stopping rules, and iteration decisions.

The original review blocked broad retained-candidate validation or evaluation runs on two P0 research-trust issues and one P1 metric-label issue:

1. **P0: Evaluation can complete without the validation decision-row audit.** Evaluation runs the row contract and strict replay, but it does not call the same `audit_decision_rows` check validation uses before portfolio metrics and artifacts are produced. This can let completed evaluation artifacts carry invalid declared lineage or missing/future observation evidence. Evidence: `src/quant_strategies/evaluation/runner.py:174`, `src/quant_strategies/evaluation/runner.py:230`, `src/quant_strategies/validation/__init__.py:361`, `src/quant_strategies/validation/data_audit.py:27`.
2. **P0: Two active `untested/` strategies used future rows while generating signals.** The foundation's strict replay can reject this, which is good, but the strategy code and at least one test previously blessed a future hold-window check as strategy behavior. Evidence at review time: `untested/crypto_perp_autoresearch_ensemble.py:213`, `untested/crypto_perp_autoresearch_ensemble.py:602`, `tests/test_crypto_perp_autoresearch_ensemble.py:228`, `untested/krohn_mueller_whelan_fix_reversal.py:88`.
3. **P1: Evaluation `ending_value` means "last finite value", not final portfolio value.** A trailing NaN or infinity can be silently skipped, so the metric can report a stale NAV under a final-value label. Evidence: `src/quant_strategies/evaluation/backend.py:772`, `src/quant_strategies/evaluation/backend.py:856`, `src/quant_strategies/evaluation/backend.py:1161`.

Current disposition: the identified P0/P1 run-readiness fixes are implemented in the active codebase, and affected generated artifacts should be rerun rather than treated as compatible evidence. I did not find a critical arithmetic/sign/unit error in the inspected shared validation engine semantics; the critical issues were causal/audit integrity and final metric semantics.

## P1 Disposition

Fixed in P1:

- Evaluation `ending_value` now means the actual final portfolio value for both VectorBT Pro-style metrics and `project_perp_ledger_v1`; a missing, NaN, or infinite final sample fails the scenario with `invalid_required_metric:ending_value`.
- All four current `untested/` strategies now expose `validate_params`; `generate_decisions` consumes the same normalized parameter mapping returned by the validator.
- Existing documented aliases are preserved and normalized: `dynamic_threshold_window_hours` for `crypto_perp_multivote_trend_following`, and `zscore_window_minutes` / `attribution_minutes` for `fx_triangular_residual_reversion`.
- P2/P3 review follow-ups are implemented: `make check` now wraps the local foundation check, the crypto perp strategy was renamed by thesis, the minute-bar evaluation example uses minute-bar annualization, and historical review docs are marked as superseded archive context.
- Unknown strategy params fail fast so typo-driven broad-run evidence does not proceed silently.
- Evaluation backend injection now has an explicit `EvaluationBackend` protocol and prepared-backend protocol.
- The downstream `quant_autoresearch` consumer contract is documented and tested against the public `run_config`, `run_validation`, and `run_evaluation` APIs.
- Evaluation configs support optional custom `[[scenarios]]`; when omitted, the default six-scenario matrix is preserved.
- Evaluation configs support optional `[benchmark]` evidence with passive benchmark total return and excess total return per scenario.
- The project perp ledger has a numeric pin covering price PnL plus funding cashflow, and active docs/tests lock bar-sampled threshold-exit semantics.

Not implemented in P1:

- Strategy promotion, renaming, or movement out of `untested/`.
- Ranking, comparison, or search-memory features inside `quant_strategies`.
- Generated artifact compatibility shims or artifact reruns.
- Broader funding/threshold semantic rewrites beyond the current evidence pins and sampled-threshold documentation.

## Scope And Evidence Inspected

Scope:

- Repo: `/Users/Season_Yang/Personal/quant_strategies`.
- Objective source: `PRD.md`, especially the three public jobs and explicit non-goals in `PRD.md:23`, `PRD.md:52`, and `PRD.md:67`.
- Added concern: autoresearch ranking and comparison are not this project's job.
- Artifact requested: this root-level `review-codex.md`.

Evidence inspected:

- Repo instructions: `AGENTS.md`.
- Product and foundation docs: `PRD.md`, `README.md`, `FOUNDATION_LOCK.md`, `docs/foundation-surfaces.md`.
- Public surfaces: `src/quant_strategies/cli.py`, `src/quant_strategies/runner/__init__.py`, `src/quant_strategies/validation/__init__.py`, `src/quant_strategies/evaluation/runner.py`.
- Shared execution spine: `src/quant_strategies/core/config.py`, `src/quant_strategies/core/execution.py`.
- Math and audit boundaries: `src/quant_strategies/evidence_semantics.py`, `src/quant_strategies/causality.py`, `src/quant_strategies/data_contract.py`, `src/quant_strategies/validation/data_audit.py`, `src/quant_strategies/evaluation/backend.py`, `src/quant_strategies/evaluation/metrics.py`.
- Strategy examples and active untested strategies under `examples/strategies/` and `untested/`.
- Tests for boundary, causality, validation, evaluation, funding, and repository discipline.
- Independent read-only lenses: onboarding, architecture, senior engineering, adversarial, and quant math.

Verification not performed:

- I did not inspect `quant_autoresearch` or `quant_data` source.
- I did not run live VectorBT Pro smoke tests.
- I did not audit existing generated result artifacts. Any artifacts produced before P0 fixes should be treated as disposable and rerun.

Current implementation verification:

- Full suite was run after the P1 implementation and review fixes:
  `conda run -n quant pytest -q`.
- Live VectorBT Pro smoke remains opt-in via `RUN_VECTORBTPRO_SMOKE=1`.

## Intended Foundation Model

From first principles, this project should be a narrow, stateless evidence engine:

- It accepts a pure strategy module and explicit config.
- It loads and normalizes data from upstream `quant_data`.
- It validates params at the boundary when the workflow needs mechanical evidence.
- It generates typed strategy decisions from only rows and params available to the strategy.
- It checks row lineage, observation availability, and hidden lookahead before evidence is trusted.
- It emits artifacts that make the assumptions and units explicit.
- It never ranks strategies, chooses winners, updates search memory, decides stopping rules, or promotes anything to paper/live trading.

The simplest healthy shape is:

```text
quant_autoresearch or Season
        |
        | supplies frozen strategy.py + explicit TOML
        v
quant_strategies public job
        |
        | shared execution spec + shared execution kernel
        v
point-in-time rows -> pure strategy -> typed decisions
        |
        | audit + strict replay
        v
quick-run diagnostics OR validation evidence OR evaluation evidence
        |
        v
artifacts and typed result object
        |
        | consumed externally
        v
ranking / comparison / iteration / promotion decisions outside this repo
```

## Project Ontology

Core actors:

- `quant_autoresearch`: external loop owner. It generates candidates, remembers search state, ranks/compares variants, sets stopping rules, and decides iteration.
- Season: senior quant reviewer and promotion decision maker.
- Strategy author: human or agent writing one pure strategy file.
- `quant_data`: upstream data owner.
- `quant_strategies`: stateless evidence producer.

Core concepts:

- Strategy module: one file with rationale/provenance and `generate_decisions(rows, params)`.
- Params: explicit config values, optionally validated by `validate_params`.
- Rows: normalized point-in-time observations with availability metadata.
- Decision: typed output with instrument, direction/state, target, decision time, as-of time, exit controls, and metadata.
- Execution spec: neutral input to the shared kernel, with no artifact policy.
- Quick run: diagnostic evidence for one strategy version.
- Validation run: mechanical retained-candidate evidence, advisory only.
- Evaluation run: stateless frozen-candidate NAV/path/economic evidence, advisory only.
- Artifact: evidence record, not truth.

Hard invariants:

- Strategies must not load data, write artifacts, call engines, use clocks/RNG, or depend on future rows.
- A decision's information set must be available no later than its decision time.
- Validation and evaluation require `validate_params`; quick run may flag schema-less exploratory runs.
- Quick-run `net_return` is linear signed trade activity, not NAV.
- Evaluation owns NAV/path evidence and should not be forced behind the same PnL semantics as validation.
- No result from this repo authorizes promotion, paper trading, live trading, or ranking across strategies.
- Generated artifacts can be rerun. Compatibility with stale outputs should not shape the foundation.

## What Already Exists And Should Be Reused

Preserve these pieces:

- **The three public CLI/API surfaces.** `quant-strategies run`, `validate`, and `evaluate` are the only public commands in `src/quant_strategies/cli.py:24`. That is the right user-facing vocabulary.
- **The shared execution spine.** `StrategyExecutionSpec` is a neutral contract with no artifact policy in `src/quant_strategies/core/config.py:58`; `execute_strategy_run` owns import, param validation, data loading, normalization, freezing, and decision validation in `src/quant_strategies/core/execution.py:74`.
- **The public/private boundary.** `docs/foundation-surfaces.md:18` says `quant_strategies.engine` is internal, not a fourth public API.
- **The autoresearch boundary.** `FOUNDATION_LOCK.md:39` correctly states that `quant_autoresearch` owns generation, memory, ranking, stopping rules, and iteration decisions.
- **The archive boundary tests.** `tests/test_repository_boundaries.py:79` and `tests/test_repository_boundaries.py:94` help keep research archives and loop memory out of the foundation.
- **Explicit evidence semantics.** `src/quant_strategies/evidence_semantics.py:42` labels quick-run/validation trade activity as not portfolio NAV.
- **Funding-inclusive validation tests.** `tests/test_validation_backends_and_policy.py:294` checks that mechanical policy gates use funding-inclusive engine net return.
- **Tiered artifacts.** Summary, diagnostic, and full profiles are a good fit for quick iteration versus audit replay.

## Architecture And Boundary Review

The public architecture is stronger than the internal shape looks at first glance. The layered appearance is mostly a real boundary, not arbitrary abstraction:

```text
CLI/API
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
     rows + decisions + hashes + evidence quality
```

What is right-sized:

- One shared execution kernel avoids divergent data loading, params, and decision-generation paths.
- Validation and evaluation adapt directly into `StrategyExecutionSpec` instead of calling runner config.
- Evaluation is separate from validation, which is correct because NAV/path evidence is not the same object as linear trade-activity evidence.
- Strategy files stay flat and pure, which is exactly the right default for autonomous candidate generation.

Current residual gaps and fixed notes:

- **Fixed in P1: evaluation now runs the validation audit boundary.** Evaluation runs `audit_decision_rows` before causality checks, portfolio metrics, and scenario artifacts are trusted.
- **Fixed in P1: evaluation backend injection has an explicit contract.** The runner types injected backends against a small evaluation protocol and keeps prepare-once fanout as an explicit prepared-backend seam.
- **Large facade modules are maintainability hotspots.** `runner/__init__.py`, `validation/__init__.py`, `evaluation/runner.py`, `evaluation/backend.py`, and `data_contract.py` total about 4,800 lines. This is not a rewrite trigger, but future edits should split stable sub-responsibilities rather than add more wrappers.
- **Output-root policy is partly conventional.** Validation and evaluation resolve output dirs inside the config directory (`src/quant_strategies/validation/config.py:93`, `src/quant_strategies/evaluation/config.py:79`). That supports candidate-local workspaces, but it is looser than "generated artifacts under ignored roots" in `PRD.md`.

## Engineering, Testability, And Operability Review

Strengths:

- The tests are unusually contract-oriented for a research repo: boundary tests, causality tests, validation runner tests, funding tests, and evaluation backend tests all exist.
- The docs have converged on a compact current-state map in `docs/foundation-surfaces.md`.
- The result objects expose failure stages and typed status enough for downstream automation to avoid parsing logs.
- Strict hidden-lookahead replay is a real guardrail, not a README promise.

Current material gaps and fixed notes:

- **Fixed in P1: current `untested/` strategies now have validator contracts.** All four current `untested/*.py` modules expose `validate_params` and keep `generate_decisions` on the same normalized params returned by the validator. They remain under `untested/`; this does not promote them.
- **Quick-run success semantics are easy to misuse.** A quick-run failure after artifact initialization returns `RunOutcome.completed=True` with `failure_stage` set (`src/quant_strategies/runner/__init__.py:615`). The docs correctly say success requires both completed and no failure stage (`docs/foundation-surfaces.md:64`), but downstream code can still read `completed` incorrectly. A derived `succeeded` helper or future rename would reduce misuse.
- **Fixed in P2: a single executable check target exists.** `make check` refreshes the editable install, runs the installed CLI help smoke, and runs `pytest -q`; `make check-vectorbtpro-smoke` keeps the real VectorBT Pro smoke opt-in.
- **Fixed in P3: prior reviews remain archived but dispositioned.** `docs/reviews/README.md` marks historical reviews as superseded by `FOUNDATION_LOCK.md` and current tests/docs.

## Domain-Specific Quant Lens Findings

What I would preserve:

- The validation engine's `net_return` semantics are explicit: signed, target-weighted, linear trade activity, not NAV. That is the right choice for quick diagnostics and mechanical validation.
- Funding timing appears deliberately tested. Funding-inclusive net return is the policy source for perp validation, which avoids a common false-positive where price/cost PnL looks good but funding destroys the economics.
- Separating validation evidence from portfolio/NAV evaluation avoids pretending that all "returns" are interchangeable.

Disposition after P1:

- **Fixed in P1:** evaluation runs `audit_decision_rows` before portfolio metrics or scenario artifacts are trusted.
- **Fixed in P1:** future-row fillability checks were removed from active strategy signal generation and covered with causality/data-audit tests.
- **Fixed in P1:** final NAV semantics now require the actual final portfolio value to be finite; `_last_finite` is no longer used for required `ending_value`.
- **Fixed in P1:** evaluation now supports custom scenario matrices and optional benchmark-relative evidence metrics.
- **Fixed in P1:** the perp ledger has a combined price-PnL plus funding-cashflow numeric pin, and threshold exits are documented/tested as bar-sampled.
- **Fixed in P2:** the evaluation example no longer teaches daily annualization for minute bars. `examples/strategies/simple_momentum_spy_daily_evaluation.toml` keeps `dataset = "equity_1min"` and uses `annualization_periods_per_year = 525949`.

Not found in inspected evidence:

- I did not find a critical sign inversion in the funding-inclusive validation policy.
- I did not find evidence that this repo currently ranks or compares strategies as a foundation responsibility.
- I did not find tracked generated Python cache or egg-info artifacts; those are ignored by `.gitignore`.

## Unknown Unknowns And Assumption Risks

- `quant_autoresearch` was not inspected. This review assumes it can consume narrow typed surfaces and own ranking/comparison outside this repo.
- `quant_data` was not inspected. Row-contract failures may reveal upstream data limitations that belong there.
- VectorBT Pro behavior was not smoked live in this session.
- The optional VectorBT Pro agreement check is documented as single-trade only; do not infer multi-trade validation confidence from it.
- Strategy alpha, benchmark-relative edge, regime robustness, capacity, slippage realism, and portfolio construction quality are outside this foundation review.
- Existing generated artifacts may encode old bugs or assumptions. After P0 fixes, rerun rather than preserving compatibility.

## Overbuilt, Underbuilt, And Right-Sized Areas

Right-sized:

- Three public jobs: quick run, validation run, evaluation run.
- Flat pure strategy modules.
- Shared execution spec and kernel.
- Advisory-only validation and evaluation language.
- Artifact profiles that distinguish compact diagnostics from replayable audit output.
- Tests that ban research archive pointers and loop-memory markers.
- Evaluation decision-row audit.
- Strategy-specific hidden-lookahead tests for active candidate strategies.
- Final-value metric strictness in evaluation.
- Explicit evaluation backend protocol.
- Minimal custom scenario matrices and benchmark-relative evidence metrics.

Underbuilt:

- Lifecycle marker for strategies that are quick-run-only versus validation/evaluation-ready.

Overbuilt or at risk of becoming overbuilt:

- Large facade modules make local reasoning harder, but splitting them now without a touched use case would be churn.
- Do not add a ranking layer, scoring service, strategy registry, search memory adapter, or compatibility shim for old result archives. Those would violate the project boundary.
- Do not add more wrappers around the runner/validation/evaluation surfaces to hide status ambiguity. Fix the result contract at the boundary when needed.

## Missing Docs, PRD, ADR, Or Decision Records

Needed:

- A decision record for evaluation audit parity: validation and evaluation must both run row lineage and observation dependency audit before evidence is trusted.
- A decision record or doc line for evaluation output-root policy: either enforce ignored roots or explicitly accept config-local outputs for candidate workspaces.
- Example docs should state that annualization periods must match data cadence, and examples should model that correctly.

Not needed:

- A broad architecture rewrite proposal.
- A general-purpose backtesting framework design doc.
- A strategy ranking methodology inside this repo.

## Lifecycle Diagrams

Public workflow:

```text
strategy.py + experiment.toml
        |
        v
quant-strategies run
        |
        v
diagnostic quick-run evidence for one version

strategy.py + validation.toml
        |
        v
quant-strategies validate
        |
        v
mechanical retained-candidate evidence, advisory only

strategy.py + evaluation.toml
        |
        v
quant-strategies evaluate
        |
        v
stateless frozen-candidate NAV/path/economic evidence, advisory only
```

Required trust chain:

```text
load rows from quant_data
        |
        v
normalize row contract and availability
        |
        v
validate params
        |
        v
generate decisions from frozen rows/params
        |
        v
audit decision rows and observation dependencies
        |
        v
strict hidden-lookahead replay
        |
        v
write artifacts and typed result
```

Autoresearch boundary:

```text
quant_autoresearch
  owns: candidate generation, search memory, ranking, comparison,
        stopping rules, iteration decisions
        |
        | supplies frozen inputs
        v
quant_strategies
  owns: pure strategy contract, execution, audit, evidence artifacts
        |
        | returns typed evidence only
        v
quant_autoresearch / Season
  decide what the evidence means
```

## Preserve / Refactor / Simplify / Add / Retire Action Map

| Priority | Status | Finding | Evidence | Recommended action |
| --- | --- | --- | --- | --- |
| P0 | Fixed in P1 | Evaluation lacked decision-row audit parity with validation. | `evaluation/runner.py`, `validation/data_audit.py` | No open code action; rerun affected artifacts produced before the fix. |
| P0 | Fixed in P1 | Two `untested/` strategies used future rows in signal generation. | `crypto_perp_multivote_trend_following.py`, `krohn_mueller_whelan_fix_reversal.py` | No open code action; keep fillability/execution feasibility in the engine/evaluation layer. |
| P1 | Fixed in P1 | Evaluation `ending_value` skipped trailing non-finite values. | `evaluation/backend.py` | No open code action; completed scenarios now require finite final portfolio value. |
| P1 | Fixed in P1 | Active `untested/` strategies lacked `validate_params`. | `untested/*.py` | No open code action; keep validators current if params change. |
| P1 | Fixed in P1 | Evaluation backend injection had no explicit contract. | `evaluation/runner.py`, `evaluation/backends.py` | No open code action; keep backend injection narrow and test-oriented. |
| P1 | Fixed in P1 | Autoresearch consumer contract needed an explicit public-surface contract. | `docs/foundation-surfaces.md`, `tests/test_repository_boundaries.py` | No open code action; keep ranking, strategy comparison, search memory, and stopping rules outside this repo. |
| P1 | Fixed in P1 | Evaluation lacked user-defined scenario matrices and benchmark-relative evidence. | `evaluation/config.py`, `evaluation/scenarios.py`, `evaluation/runner.py` | No open code action; keep benchmark metrics evidence-only. |
| P2 | Dispositioned | Output-root policy is partly convention, partly PRD promise. | `validation/config.py:93`, `evaluation/config.py:79`, `PRD.md:183` | Candidate-local validation/evaluation outputs remain accepted; generated roots are ignored and artifacts should be rerun. |
| P2 | Fixed in P2 | No single local check target. | `Makefile`, `docs/foundation-surfaces.md` | `make check` wraps editable install, CLI help, and tests; VectorBT Pro smoke remains opt-in. |
| P2 | Fixed in P2 | `crypto_perp_autoresearch_ensemble.py` name blurred strategy thesis with process owner. | `untested/crypto_perp_multivote_trend_following.py` | Renamed by thesis; autoresearch remains external process vocabulary. |
| P3 | Fixed in P3 | Old review docs can distract future agents. | `docs/reviews/README.md` | Historical reviews are marked superseded by `FOUNDATION_LOCK.md` and current tests/docs. |

## Prioritized Recommendations

1. **Rerun, do not preserve, old artifacts.** Any existing outputs affected by audit, lookahead, validator, or metric fixes should be regenerated.
2. **Keep the autoresearch consumer contract explicit.** The three supported Python entry points and success checks are documented and tested; ranking/comparison/stopping stay external.
3. **Keep strategy readiness explicit.** Current `untested/` strategies now have validators and tests, but promotion or renaming remains a separate Season decision.
4. **Do not rewrite the foundation.** Pay down large orchestrators only when touching them for a real boundary fix. The completed P0/P1 fixes did not require a broad refactor.
5. **Use the repeatable check command.** Keep it boring: `make check`, with optional `make check-vectorbtpro-smoke`.
6. **Keep the evaluation-backend contract narrow.** The protocol is a runner seam, not a general plugin framework.

## NOT In Scope

- Ranking or comparing strategies.
- Candidate search memory.
- Iteration/stopping policy.
- Statistical alpha validation or benchmark-relative strategy selection.
- Capacity modeling.
- Live trading, paper trading, or order routing.
- Data acquisition, refresh, backfill, repair, or source joining.
- Compatibility with stale generated artifacts.
- Turning this into a general-purpose backtesting framework.

## Final Assessment

This is not over-engineered at the public workflow level. The three-job surface is simple and the shared execution spine is justified. The internal modules are heavier than ideal, but most of the complexity is serving auditability, causality, and artifact discipline rather than speculative abstraction.

The next move should stay targeted, not sweeping: rerun affected outputs and keep ranking/comparison outside this repo where they belong. After the completed P1/P2/P3 fixes, this is usable as the stateless evidence foundation beneath `quant_autoresearch`.
