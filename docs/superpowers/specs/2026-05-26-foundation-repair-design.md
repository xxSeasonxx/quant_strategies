# Foundation Repair Rollout Design

Date: 2026-05-26
Target: `quant_strategies`
Basis: `docs/reviews/2026-05-26-foundation-review.md`

## Decision

Repair the foundation in dependency order, starting from the strategy contract
and evidence semantics before adding richer validation capability.

The clean target is not compatibility with every existing strategy shape. The
clean target is one serious strategy language:

```text
generate_decisions(rows, params) -> list[StrategyDecision]
```

`StrategyDecision` is the canonical contract for researched, validation-ready,
tested, paper-trading, and future live-trading paths. Existing signal-only code
is input evidence and may be migrated, moved to fixtures, or retired. It should
not constrain the target design.

## Goals

- Remove semantic drift between quick research, validation, and future
paper/live follow-up.
- Keep the repo a modular monolith with focused packages.
- Make artifacts unable to overclaim their evidential strength.
- Make validation evidence reproducible from code/config/data/backend identity.
- Keep `quant_autoresearch` on the shared runner by improving the runner after
semantics are honest.
- Fix root contracts before adding portfolio or statistical sophistication.

## Non-Goals

- Do not build a live-trading system in this repo.
- Do not split the repo into services.
- Do not preserve signal-only strategy contracts as a foundation constraint.
- Do not add advanced statistical validation before contract, semantics,
provenance, and mutability risks are fixed.
- Do not build portfolio target-weight support before backend capabilities and
evidence semantics are explicit.

## Rollout Order

The rollout order is:

```text
Contract -> Semantics -> Provenance -> Hardening -> Performance -> Validation depth
```

This order matters because later evidence is only useful if it is produced from
one canonical strategy contract and cannot be read as stronger than it is.

## Phase 1: Contract Reset

Public strategy code should emit `StrategyDecision`.

### Design

- `decisions/` remains the canonical strategy intent model.
- Runner strategy loading should require `generate_decisions`.
- Validation strategy loading should use the same loader or a thin wrapper over
the same contract.
- The smoke engine may keep its existing `Signal` model internally, but the
conversion should be owned by infrastructure:

```text
StrategyDecision -> engine Signal -> engine.screen / engine.validate
```

- `generate_signals` should not be a public foundation contract. Signal-only
strategies can be migrated, treated as test fixtures, or retired.
- Runner artifacts should record `strategy_contract = "decision"`.

### Root Cause Addressed

This removes the two-language problem where quick research optimizes
`generate_signals` but validation tests `generate_decisions`.

### Scope Guard

Do not add a broad compatibility layer that keeps `generate_signals` equal to
`generate_decisions`. A temporary private adapter is acceptable only as an
implementation detail while converting the smoke engine.

## Phase 2: Evidence Semantics

Artifacts should explicitly state what they can and cannot prove.

### Design

Runner summaries and manifests should include:

- `strategy_contract = "decision"`
- `return_model = "sum_weighted_trade_return"`
- funding metrics should state whether they are full cashflow accounting or a
v1 linear additive adjustment
- `promotion_eligible = false`
- `paper_trade_eligible = false`
- `live_eligible = false`
- `requires_manual_approval = true`

Validation artifacts should include explicit eligibility fields:

- `advisory_decision`
- `paper_trade_eligible = false` until Season approves a stronger process
- `live_eligible = false`
- `requires_manual_approval = true`

The current `clear_yes` label should either be renamed to an advisory label or
kept only with explicit non-deployability fields. Imported autoresearch loop
feedback should be wrapped or labeled as non-validation evidence.

Smoke fixtures and examples should not live in lifecycle folders whose names
imply validated strategy status. If a fixture remains in such a folder during
transition, artifacts and docs must mark it as a fixture exception.

### Root Cause Addressed

This prevents smoke or advisory validation artifacts from being read as
portfolio validation, paper-trading approval, or live-trading approval.

## Phase 3: Provenance And Integrity

Validation evidence should be at least as reproducible as runner evidence.

### Design

Add `validation_manifest.json` with:

- repository identity and dirty-state metadata
- `quant-strategies`, `quant-data`, `pydantic`, and backend package versions
- validation config hash
- strategy snapshot hash
- decision-record hash
- row/data manifest hash or data provenance reference
- backend names, statuses, and capability summary
- artifact hashes

Add researched manifest integrity checks:

- hash listed strategy/config files
- fail validation on stale hashes for validation-ready variants
- record whether a variant is `runner_only`, `validation_ready`, or
`validated_for_testing`

### Root Cause Addressed

This makes validation and researched handoff artifacts reproducible and prevents
stale copied packages from producing trusted evidence.

## Phase 4: Boundary Hardening

Make invalid or misleading runs hard to produce.

### Design

- Freeze or deep-copy rows and params before strategy execution.
- Give each validation backend scenario a fresh read-only input view.
- Change backend status from plain `str` to a finite `Literal` or enum.
- Catch expected `Exception` subclasses, not `BaseException`.
- Let `SystemExit`, `KeyboardInterrupt`, and `GeneratorExit` propagate.
- Make runner and validation result-directory allocation atomic by retrying on
`FileExistsError` instead of relying on check-then-create.
- Add per-strategy parameter validation through a simple convention:

```python
def validate_params(params: Mapping[str, object]) -> Mapping[str, object]:
    ...
```

- Parameter perturbation scenarios should regenerate decisions. If not, mark
them `decisions_regenerated = false` and exclude them from promotion language.

### Root Cause Addressed

This prevents mutation, process-level exits, unexpected statuses, and parameter
typos from becoming plausible strategy evidence.

## Phase 5: Performance Without Semantic Change

Improve `quant_autoresearch` throughput only after artifacts cannot overclaim.

### Design

- Pre-index bars by `(symbol, timestamp)` once per engine request.
- Reuse the index for fillability and evaluation.
- Skip or pre-index funding scans for non-funding data.
- Add `artifact_profile = "summary"` for quick research:
  - row counts
  - normalized row hash
  - sampled rows
  - signal/decision summary
  - compact scoreable engine metrics
  - no full CSV/JSONL or full engine request by default
- `artifact_profile = "full"` remains the default for manual reruns and curated
candidates.
- Keep full artifacts for curated reruns and promotion candidates.
- Add an autoresearch-scale benchmark with runtime and artifact-byte limits.

### Root Cause Addressed

This keeps the shared runner viable for large loops without changing strategy
meaning or weakening promotion evidence.

## Phase 6: Validation Depth

Only after the foundation is clean, add deeper validation capability.

### Design

- Add typed observation/dependency references to `StrategyDecision`.
Season chose the typed field now so the unified decision contract carries
causality dependencies explicitly instead of hiding them in metadata.
- Add future-poison tests for cross-sectional and FX triangle strategies.
- Add a backend capability matrix and include it in validation artifacts.
- Add portfolio-level target-weight support only if the candidate being
validated requires it.

Implementation plan:
`docs/superpowers/plans/2026-05-26-validation-depth-phase-6.md`.
Tests and backend semantics must remain synthetic/canonical rather than derived
from legacy researched packages.

### Root Cause Addressed

This addresses lookahead and backend capability gaps after the contract and
evidence layers are stable.

## Component Impacts


| Component                       | Change                                                                                                                               |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `decisions/`                    | Remains canonical; owns decision-to-signal helpers if shared outside one runner module                                               |
| `runner/strategy_loader.py`     | Loads `generate_decisions` as the public strategy entrypoint                                                                         |
| `runner/engine_runner.py`       | Converts decisions to internal engine signals and owns timestamp indexing                                                            |
| `runner/artifacts.py`           | Writes contract, return-model, eligibility, and artifact-profile metadata                                                            |
| `validation/strategy_loader.py` | Shares the canonical decision loader                                                                                                 |
| `validation/policy.py`          | Makes advisory/deployability semantics explicit                                                                                      |
| `validation/artifacts.py`       | Writes validation manifest and eligibility fields                                                                                    |
| `validation/backends.py`        | Narrows backend status type and capability reporting                                                                                 |
| `validation/__init__.py`        | Uses immutable inputs and clearer exception boundaries                                                                               |
| `researched/`                   | Gains manifest integrity/status checks; stale packages stop being trusted; imported loop feedback is labeled non-validation evidence |
| `tested/`                       | Contains only validation-passed strategies; smoke fixtures move elsewhere or are explicitly marked during transition                 |
| `tests/`                        | Adds contract, artifact semantics, manifest, mutation, benchmark, and causality tests                                                |


## Testing Strategy

Each phase should land with focused tests:

1. Contract reset:
  - runner accepts `generate_decisions`
  - runner rejects missing decision contract
  - decision-to-signal conversion preserves symbol, timing, direction, weight,
  hold, and metadata needed by the smoke engine
2. Evidence semantics:
  - summaries/manifests include contract and eligibility fields
  - runner return model is explicit
  - validation output cannot imply paper/live approval
3. Provenance:
  - validation manifest hashes required artifacts
  - stale researched manifest hashes block validation
4. Boundary hardening:
  - strategy/backend mutation cannot alter stored evidence
  - `SystemExit` propagates
  - invalid backend status fails model validation
  - unknown params fail for validation-ready strategies
  - parallel result-directory allocation is safe
5. Performance:
  - large synthetic signal set avoids linear decision-time scans
  - summary artifact profile stays under byte limits
6. Validation depth:
  - future-poison tests catch hidden dependency lookahead
  - unsupported backend capabilities remain fail-closed

## Sequencing Notes

- Phase 1 and Phase 2 should be implemented first, before any deeper validation
work.
- Phase 3 should land before trusting new validation results.
- Phase 5 can be split if `quant_autoresearch` is blocked, but it should not
weaken artifact semantics.
- Phase 6 should not start with portfolio target weights unless an end-to-end
validation run proves that is the current blocking semantic.

## Success Criteria

- There is one serious strategy output contract: `StrategyDecision`.
- Runner and validation consume the same strategy intent representation.
- Artifacts tell humans and automation exactly what evidence class they are.
- Validation evidence is reproducible from manifest hashes.
- Strategy/backend execution cannot mutate evidence inputs.
- Broad quick research can use the shared runner without multi-GB default
artifacts.
- Unsupported backend semantics remain explicit and fail-closed.
