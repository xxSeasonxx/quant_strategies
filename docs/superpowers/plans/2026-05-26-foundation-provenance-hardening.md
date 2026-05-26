# Foundation Provenance And Boundary Hardening Plan

Date: 2026-05-26
Spec: `docs/superpowers/specs/2026-05-26-foundation-repair-design.md`
Scope: Phase 3 and Phase 4

## Current State

Phase 1 and Phase 2 are landed:

- `generate_decisions(rows, params) -> list[StrategyDecision]` is the runner
  and validation strategy contract.
- Runner and validation share decision-output validation.
- Runner and validation artifacts expose advisory and non-deployable evidence
  semantics.

The workspace still has unrelated tracked deletions under `researched/` and
`openspec/`, plus local docs/untracked files. Do not include those in phase
commits unless Season explicitly asks to retire them.

## Phase 3: Provenance And Integrity

Goal: make validation artifacts reproducible enough to trust as validation
evidence.

Implementation:

1. Add shared provenance helpers for SHA-256 file/text hashing, package
   versions, git identity, and recursive artifact hashing.
2. Write `validation_manifest.json` after validation artifacts are written.
3. Include:
   - repository commit and dirty-state hash metadata,
   - Python and package versions for `quant-strategies`, `quant-data`,
     `pydantic`, and backend-relevant packages,
   - validation config and strategy snapshot hashes,
   - decision records, data audit, backend summary, robustness matrix, promotion
     decision, and report artifact hashes,
   - per-window row provenance with stable row-input hashes,
   - backend scenario statuses and unsupported-semantics summary.
4. Add researched-manifest integrity checks for packages with a parent
   `manifest.json`:
   - locate the manifest variant matching the validation config path,
   - record variant lifecycle status as `runner_only`, `validation_ready`, or
     `validated_for_testing` when present,
   - fail validation only when a validation-ready variant has stale listed
     strategy/config hashes.

Tests:

- Validation success writes `validation_manifest.json` with expected hashes.
- Failure paths still write the manifest after result dir exists.
- A temp researched package with stale validation-ready manifest hashes fails
  validation before backend execution.

Review:

- Do not restore or delete legacy `researched/` files as part of this phase.
- Do not require every temp validation package to have a researched manifest.
- Keep manifest fields factual; no promotion language.

## Phase 4: Boundary Hardening

Goal: make invalid or misleading runs hard to produce.

Implementation:

1. Freeze/deep-copy rows and params before strategy execution.
2. Give every backend scenario a fresh immutable row view and a fresh decision
   list.
3. Add optional strategy param validation convention:

   ```python
   def validate_params(params: Mapping[str, object]) -> Mapping[str, object]:
       ...
   ```

4. Change backend status from plain string to finite status literals.
5. Catch `Exception`, not `BaseException`; let `SystemExit`,
   `KeyboardInterrupt`, and `GeneratorExit` propagate.
6. Make runner and validation result-directory allocation atomic by retrying
   `mkdir` on `FileExistsError`.
7. Regenerate decisions for parameter perturbation scenarios. Record
   `decisions_regenerated = true` for those scenarios and keep non-required
   parameter scenarios diagnostic.

Tests:

- Strategy row/param mutation fails before evidence inputs can be mutated.
- Backend scenario receives read-only fresh rows.
- Invalid backend status fails model validation and becomes a failed backend
  scenario.
- `SystemExit` from strategy import/generation and backend execution propagates.
- Strategy `validate_params` rejects unknown or invalid params.
- Parameter scenarios regenerate decisions with scenario params.
- Atomic validation result directory allocation handles collisions.

Review:

- Keep the backend protocol narrow; do not add portfolio support here.
- Keep parameter validation opt-in at the strategy boundary. Pydantic schemas can
  come later if multiple strategies need shared structure.
- Do not make parameter scenarios promotion-required. They remain diagnostic
  unless a later phase changes validation policy.

## Commit Plan

1. Commit Phase 3 as `feat: add validation provenance manifest`.
2. Commit Phase 4 as `fix: harden validation boundaries`.

Each commit should include focused tests and a changed-line count.
