# P0 Foundation Root Fixes Design

Date: 2026-06-02
Status: Approved design
Owner: Season Yang
Target repo: `quant_strategies`

## Objective

Implement the two P0 root fixes from `review-codex.md` without adding another
layer around the problem:

1. Make causality completeness a shared foundation invariant for validation and
   evaluation.
2. Move ranked research-loop artifacts out of `quant_strategies` so the
   foundation repo contains no active search memory, ranking state, or legacy
   validation-like archive fields.

The implementation must preserve the current simple foundation model:

```text
pure strategy.py + explicit config
  -> StrategyExecutionSpec
  -> quant_data loader
  -> normalized/frozen rows and params
  -> typed decisions
  -> causality and evidence checks
  -> factual artifacts with no promotion authority
```

## Non-Goals

- Do not build a new evidence-policy framework.
- Do not add a loop, ranking system, autonomous research setup, or promotion
  decision.
- Do not preserve compatibility shims for `researched/` paths inside this repo.
- Do not leave a pointer file behind for moved archives.
- Do not rewrite runner, validation, evaluation, or engine orchestration beyond
  the small root-boundary changes needed for P0.
- Do not run or require live VectorBT Pro validation as part of this change.

## Design Summary

Use the existing causality boundary as the single home for usable-evidence
causality completeness. Validation already has the correct behavior locally:
missing deterministic, emitted, or strict suppression replay proof is a
violation. The design lifts that rule into shared code and reuses it from both
validation and evaluation.

Move the entire `researched/` tree out of the repository to
`~/Personal/strategies`. The foundation repo should not keep a pointer,
compatibility import, or archive index. Tests and docs should treat ranked
research artifacts as outside the active foundation context.

## Architecture

### Shared Causality Completeness

Add a small pure helper near the existing causality model, preferably in
`src/quant_strategies/causality.py`:

```python
def causality_completeness_violations(
    lookahead: LookaheadCheckResult,
) -> tuple[str, ...]:
    ...
```

Behavior:

- Return existing `lookahead.violations` when `lookahead.passed` is false.
- When `lookahead.passed` is true, append:
  - `determinism_replay_not_verified` if deterministic replay is incomplete;
  - `emitted_replay_not_verified` if emitted replay is incomplete;
  - `strict_suppression_replay_not_verified` if strict suppression replay is
    incomplete.
- Deduplicate reasons while preserving order.
- Return an empty tuple only when usable evidence causality is complete.

This avoids a new policy package and makes the invariant hard to miss at the
source of truth.

### Validation Integration

Validation currently implements the right rule in a private local helper. Replace
that private duplicate with a call to the shared helper.

Expected behavior after the change:

```text
validation run
  -> check_hidden_lookahead(..., mode="strict")
  -> causality_completeness_violations(lookahead)
  -> any violation makes the data audit fail
```

Validation result shape should stay the same. This is a refactor of ownership,
not a new validation workflow.

### Evaluation Integration

Evaluation already calls `check_hidden_lookahead(..., mode="strict")`, but today
it only fails when `lookahead.passed` is false. Change it to use the shared
helper before scenario expansion or complete artifact publication.

Expected behavior after the change:

```text
evaluation run
  -> execute_strategy_run(...)
  -> check_hidden_lookahead(..., mode="strict")
  -> causality_completeness_violations(lookahead)
  -> any violation returns preflight failure
  -> only complete proof can continue to scenario expansion and manifest success
```

Evaluation should keep its existing result style:

- `failure_stage="preflight"`
- `assessment_status="evaluation_preflight_failed"`
- message containing the shared causality violation reasons
- no `evaluation_complete` result when strict proof is incomplete

This is intentionally stricter than the current warning-only behavior. A
foundation evidence job that did not prove strict causality did not complete.

### Archive Boundary

Move the existing `researched/` directory out of this repo:

```text
from: /Users/Season_Yang/Personal/quant_strategies/researched
to:   /Users/Season_Yang/Personal/strategies/researched
```

If the destination already exists, use a collision-safe timestamped destination
under `~/Personal/strategies`, for example:

```text
~/Personal/strategies/researched-20260602-HHMMSS
```

Do not leave a pointer, README, symlink, import shim, test fixture, or path
compatibility layer inside `quant_strategies`.

Tests and docs should reflect the new boundary:

- active strategy contract discovery covers `tested/`, `untested/`, and examples;
- active docs state that `quant_autoresearch` owns search memory and ranking;
- `quant_strategies` does not host ranked loop artifacts.

## Data Flow

```text
StrategyExecutionSpec
  -> execute_strategy_run
  -> normalized rows + validated params + decisions
  -> check_hidden_lookahead(strict)
  -> causality_completeness_violations
      |
      +-- empty tuple: continue evidence job
      +-- reasons: surface-specific preflight/data-audit failure
```

Validation and evaluation keep their existing surface-specific result objects.
The shared helper owns only the invariant, not orchestration, artifacts, or user
messaging.

## Error Handling

### Causality

The shared helper should be pure and non-throwing. Each caller maps violations
into its existing failure path.

Validation:

- appends causality reasons to the audit payload;
- marks the data audit as failed;
- preserves current validation failure semantics.

Evaluation:

- returns `_failure_result(...)` from preflight;
- includes shared reasons in the message;
- does not proceed to scenario expansion or completion artifacts.

### Archive Move

The file move should be explicit and collision-safe:

- create `~/Personal/strategies` if needed;
- fail rather than overwrite an existing archive path;
- use a timestamped destination if `~/Personal/strategies/researched` already
  exists;
- report moved file count and size.

The implementation should not delete the only copy of the record. It should move
the directory in the filesystem and let git record removal from this repo.

## Testing Plan

### Causality Helper Tests

Add focused unit tests for the shared helper:

- returns no violations when `passed=True` and all replay verification flags are
  true;
- returns existing lookahead violations when `passed=False`;
- returns `determinism_replay_not_verified` when deterministic proof is missing;
- returns `emitted_replay_not_verified` when emitted proof is missing;
- returns `strict_suppression_replay_not_verified` when strict suppression proof
  is missing;
- deduplicates reasons while preserving order.

### Validation Tests

Update validation tests so validation still rejects incomplete strict proof
through the shared helper. The test should not assert on a validation-local
private function.

### Evaluation Tests

Add or update an evaluation regression test proving:

- an evaluation with skipped strict probes returns
  `assessment_status="evaluation_preflight_failed"`;
- `failure_stage="preflight"`;
- the message contains `strict_suppression_replay_not_verified`;
- no successful `evaluation_complete` manifest semantics are written for that
  failed run.

### Archive Boundary Tests

Update strategy contract discovery so it no longer depends on `researched/`.

Add a lightweight audit test that scans active foundation paths and fails if
ranked loop-memory markers appear outside allowed test fixtures. Markers include:

- `ranking_method_version`
- `"top_variants"`
- `"passed_validation"`
- `"rerun_score"`
- rank-based selection fields that represent loop memory

The audit should avoid scanning `.git`, cache directories, and external archive
destinations.

## Documentation Updates

Update only docs whose current claims change:

- `FOUNDATION_LOCK.md`: record shared causality completeness as a foundation
  invariant for validation and evaluation; record that ranked research archives
  no longer live in this repo.
- `README.md` or `docs/foundation-surfaces.md`: remove language that implies
  `researched/` may hold active frozen packages here.
- `TODOS.md`: update only if a residual remains. Prefer closing P0 without
  adding new active TODOs.
- Tests should enforce document responsibilities: PRD owns product intent;
  reference docs own exact command/API/package facts.

## Verification Commands

Use focused checks first:

```bash
conda run -n quant pytest \
  tests/test_validation_lookahead.py \
  tests/test_validation_runner.py \
  tests/test_evaluation_runner.py \
  tests/test_strategy_docstrings.py \
  tests/test_decision_strategy_loader.py \
  -q
```

Add the new archive-boundary test file to the command once created.

Also run:

```bash
git diff --check
```

Full suite is optional unless focused tests expose wider breakage.

## Implementation Sequence

1. Add shared causality completeness helper and unit tests.
2. Replace validation-local completeness logic with the shared helper.
3. Use the shared helper in evaluation preflight and add evaluation regression
   coverage.
4. Move `researched/` to `~/Personal/strategies` with collision-safe handling.
5. Update strategy discovery tests and docs for the new archive boundary.
6. Add loop-memory marker audit test.
7. Run focused verification and report changed-line counts by source, tests,
   docs, and moved artifacts.

## Acceptance Criteria

- Validation and evaluation use the same shared causality completeness rule.
- Evaluation cannot return `evaluation_complete` when strict suppression replay
  is incomplete.
- `researched/` no longer exists in `quant_strategies`.
- No pointer, symlink, compatibility shim, or archive index remains in this repo.
- The research record exists under `~/Personal/strategies` after the move.
- Active strategy contract tests no longer depend on `researched/`.
- A repo audit catches ranked loop-memory markers if they return under active
  foundation paths.
- Focused tests and `git diff --check` pass, or any failures are clearly
  reported with root cause.

## Open Decisions

None. Season approved:

- both P0s are in scope;
- option 1, shared root-policy cleanup;
- the archive should move out of this project to `~/Personal/strategies`;
- no pointer should remain in `quant_strategies`;
- one shared hard causality-completeness gate should preserve simplicity.
