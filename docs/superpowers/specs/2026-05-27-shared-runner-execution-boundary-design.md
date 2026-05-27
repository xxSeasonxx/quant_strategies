# Shared Runner Execution Boundary Design

Date: 2026-05-27

## Goal

Extract the duplicated runner/validation strategy execution path into one small
internal boundary. The boundary should make runner and validation use the same
strategy loading, parameter validation, data loading, decision generation,
decision validation, signal conversion, row hashing, and evidence-quality
calculation.

This is a refactor. It should preserve behavior and artifact semantics.

## Non-Goals

- Do not make a new public downstream API.
- Do not make validation call `runner.run_config`.
- Do not move validation audit, hidden-lookahead replay, readiness checks,
  matrix expansion, backend execution, or policy classification into runner.
- Do not move smoke engine request building or engine evaluation into the shared
  boundary.
- Do not add legacy `researched/` package accommodation.

## Current Problem

`runner.run_config` and `validation.run_validation` both perform the same core
execution steps:

1. Load the strategy function.
2. Validate or normalize params.
3. Load rows through the runner data loader and public `quant_data` APIs.
4. Freeze rows and params before calling the strategy.
5. Call `generate_decisions(rows, params)`.
6. Validate `StrategyDecision` output.

The two callers then diverge:

- Runner converts decisions to signals, checks runner data readiness, builds the
  smoke-engine request, evaluates the engine, and writes runner artifacts.
- Validation audits decision/data causality, runs hidden-lookahead replay,
  checks readiness metadata, expands scenario matrix runs, calls validation
  backends, and classifies advisory policy.

The duplicated setup path makes behavior drift likely and keeps validation
reaching into runner internals one dependency at a time.

## Design

Add `src/quant_strategies/runner/execution.py` as an internal shared module.

Expose one main function:

```python
def execute_strategy_run(
    config: RunConfig,
    *,
    repo_root: Path,
) -> StrategyExecutionResult:
    ...
```

`StrategyExecutionResult` is a frozen dataclass containing:

- `generate_decisions`
- `validated_params`
- `loaded_rows`
- `decisions`
- `signals`
- `normalized_rows_sha256`
- `evidence_quality`

The result intentionally excludes artifact paths. Artifact writing remains owned
by `runner.run_config` and validation artifact writers.

## Error Model

The execution boundary should report the stage that failed without hiding the
underlying message. Use a small typed exception such as:

```python
class StrategyExecutionError(RunnerError):
    stage: Literal[
        "strategy_import",
        "param_validation",
        "data_load",
        "decision_generation",
    ]
```

Stage meanings:

- `strategy_import`: loading `generate_decisions` failed.
- `param_validation`: `validate_params` failed or returned an invalid mapping.
- `data_load`: row loading failed.
- `decision_generation`: strategy execution failed or returned invalid
  `StrategyDecision` output.

Keep runner and validation user-facing messages as stable as practical. Runner
can continue to map `stage` into its summary stage. Validation can map the same
stage into existing audit/failure artifacts.

## Runner Flow

`runner.run_config` should:

1. Resolve and load `RunConfig`.
2. Create the result directory and initialize static snapshots.
3. Call `execute_strategy_run(config, repo_root=effective_repo_root)`.
4. Write data manifest, strategy input rows, decision records, and signals from
   the result according to `artifact_profile`.
5. Continue with runner data readiness, engine request building, engine
   evaluation, evidence writing, summary-profile writing, notes, run manifest,
   and summary.

Runner stays the owner of all runner artifacts and smoke-engine semantics.

## Validation Flow

`validation.run_validation` should use `ValidationConfig.to_run_config(...)` for
each window, then call `execute_strategy_run(run_config, repo_root=path_base)`.

For each successful window, validation uses:

- `result.loaded_rows` for data provenance, data audit, lookahead replay, and
  backend rows.
- `result.decisions` for all base-window validation checks.
- `result.validated_params` and `result.generate_decisions` for hidden-lookahead
  replay and parameter scenario regeneration.

Validation remains the owner of:

- data audit artifacts,
- hidden-lookahead and readiness failures,
- scenario matrix expansion,
- backend runs,
- validation manifest, robustness matrix, and policy decision.

## Module Boundary

`runner.execution` may depend on:

- `runner.config.RunConfig`
- `runner.data_loader`
- `runner.strategy_loader`
- `runner.artifact_profiles.normalized_rows_sha256`
- `runner.artifacts.evidence_quality`
- `runner.decision_adapter.decisions_to_signal_rows`
- `decisions.validate_strategy_params`
- `decisions.validate_decision_output`
- `boundary.frozen_rows` and `boundary.frozen_params`

It must not depend on:

- `runner.engine_runner`
- runner artifact writers,
- validation modules,
- CLI modules,
- `researched/` layout conventions.

## Tests

Add focused tests for `runner.execution`:

- success returns loaded rows, validated params, decisions, signals, row hash,
  and evidence quality.
- strategy import failure reports `stage = "strategy_import"`.
- param validation failure reports `stage = "param_validation"`.
- data load failure reports `stage = "data_load"`.
- invalid decision output reports `stage = "decision_generation"`.

Update existing runner tests only where assertions need the new internal call
path. Runner artifact expectations should remain unchanged.

Update validation tests to ensure:

- data-load failures still write the same audit/provenance failure artifacts,
- strategy import and param validation failures still include structured
  `failure_details`,
- per-window scenario configs still carry window-scoped `data.start` and
  `data.end`,
- hidden-lookahead and readiness behavior are unchanged.

Run focused tests first, then the full suite.

## Acceptance Criteria

- `runner.run_config` and `validation.run_validation` both use
  `execute_strategy_run` for the shared execution path.
- No active validation code special-cases `researched/`.
- Runner artifacts remain stable except for intentional metadata already
  introduced before this refactor.
- Validation artifacts preserve existing failure reasons, audit payloads, and
  policy behavior.
- Full test suite passes with `conda run -n quant pytest -q`.
