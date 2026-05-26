# Foundation Reset Design

Date: 2026-05-26
Target: `quant_strategies`
Basis: `docs/reviews/foundation-review-20260526.md`

## Decision

Implement one strict foundation reset that fixes the root trust boundaries
without expanding the project into a larger framework.

The clean target is:

```text
generate_decisions(rows, params) -> list[StrategyDecision]
```

`StrategyDecision` is the only serious strategy output contract. Runner output
is smoke evidence only. Validation output is advisory mechanical evidence until
a stronger promotion policy exists. Active docs describe current source truth
only. Code should not preserve old setup through compatibility layers, legacy
adapters, or public artifact fields.

## Goals

- Remove stale active documentation that describes superseded strategy or runner
  contracts.
- Keep the modular monolith: `runner`, `engine`, `decisions`, and `validation`
  remain separate focused packages.
- Enforce observation lineage for validation-ready researched strategies.
- Prevent current validation language from implying paper/live or promotion
  readiness.
- Make smoke and funding metric names match their accounting semantics.
- Define one canonical researched package contract for validation handoff.
- Remove public legacy artifact fields and tests tied to the old signal setup.
- Preserve quick `untested/` iteration without making validation permissive.

## Non-Goals

- No paper trading or live trading support.
- No causal row sandbox in this phase.
- No full portfolio engine rewrite.
- No PSR, DSR, PBO, CPCV, or broad statistical validation stack.
- No broad refactor of `validation/__init__.py` unless needed to remove legacy
  behavior cleanly.
- No new compatibility layer for old `generate_signals` or signal-only
  artifacts.

## Current Foundation Problems

The current code is well tested, but several semantics are too easy to overread:

- Validation can pass a strategy that omits `ObservationRef` dependencies even
  if the strategy used history, funding rows, quotes, or cross-symbol rows.
- `clear_yes` sounds stronger than the current positive-return/min-trades
  validation policy supports.
- Runner return fields are summed smoke scores, not portfolio returns.
- Funding-aware validation adds funding linearly after backend total return.
- `researched/` has no committed canonical handoff package layout.
- Stale docs and deleted tracked docs make it unclear which workflow is
  authoritative.
- Public artifacts still expose legacy names such as `hold_bars` even though
  `ExitPolicy.max_hold_bars` is canonical.

## Architecture

Keep the current package structure and sharpen the contracts inside it.

```text
strategy.generate_decisions(frozen rows, frozen params)
  -> list[StrategyDecision]
  -> decision output validation
  -> validation-readiness checks
       observations complete when required?
       researched manifest/layout present when required?
       params accepted?
  -> runner smoke adapter OR validation backend
  -> artifacts with explicit evidence class and metric semantics
```

### `decisions`

`StrategyDecision` remains the canonical contract.

`observations=()` may still be valid for trivial single-row strategies and early
`untested/` exploration. It is not valid for validation-ready strategies that
use history, cross-section, quotes, funding, or derived features.

Add a validation-readiness check that can answer: for this candidate, did the
decision declare the rows and fields it used?

### `runner`

Runner continues to call `generate_decisions(rows, params)`.

Runner may keep a private smoke-engine adapter, but public artifacts should not
carry legacy signal-era fields. `decision_records.jsonl` is the canonical
strategy output artifact. Smoke-engine artifacts should use current field names
and should label scores as smoke metrics, not portfolio returns.

### `engine`

The engine remains a deterministic smoke evaluator. It should not become a full
portfolio accounting engine in this phase.

Remove public compatibility with old signal semantics where it is only serving
legacy tests or artifacts. Internal names may remain only when they describe a
current engine concept and do not leak into the public contract.

### `validation`

Validation gets a focused readiness gate before backend execution:

- researched package layout and manifest checks,
- decision output validation,
- observation-lineage requirement for validation-ready strategies,
- finite backend metric validation,
- advisory-only policy semantics.

Unsupported backend semantics remain fail-closed: they become advisory or
non-passing results, not approximate evidence.

### `docs`

Active docs should describe the current source truth only:

- `README.md` is the concise user contract.
- this design and its implementation plan are the current change source of
  truth.
- stale superseded plans/specs/reviews should be retired or marked historical,
  not left as active instructions.

## Detailed Requirements

### Documentation Source Of Truth

- Update README so it states:
  - strategies expose `generate_decisions`,
  - `StrategyDecision` is canonical,
  - runner output is smoke evidence,
  - validation output is advisory mechanical evidence,
  - current validation is not paper/live/promotion eligibility.
- Remove or retire active docs that describe old `generate_signals` or
  superseded runner/validation behavior.
- Add a lightweight stale-doc guard for forbidden active-doc phrases such as
  `generate_signals`, except inside explicitly historical notes if such notes
  are intentionally kept.

### Observation Lineage Gate

- Add a small validation-readiness module or function with one responsibility:
  decide whether a set of decisions is allowed to proceed to researched
  validation.
- For validation-ready researched packages, require non-empty observations when
  a strategy uses any nontrivial data dependency:
  - lookback/history,
  - cross-symbol or cross-sectional data,
  - quotes,
  - funding,
  - derived features from rows other than the traded instrument as-of row.
- Validate declared observations against row availability:
  - matching row must exist,
  - `available_at` must exist,
  - `available_at <= decision_time`,
  - observation timestamp must be at or before `as_of_time`.
- Do not require observation lineage for early `untested/` runner smoke unless
  the run is explicitly marked validation-ready.

### Validation Decision Language

- Current validation must not expose a promotion-sounding decision.
- Replace or downgrade `clear_yes` semantics to a mechanical/advisory result.
  Acceptable public names are `mechanical_pass`, `advisory_pass`, or equivalent
  wording that cannot be read as paper/live ready.
- Keep these fields false for current validation:
  - `promotion_eligible`,
  - `paper_trade_eligible`,
  - `live_eligible`.
- Keep `requires_manual_approval = true`.
- CLI exit codes may still reflect mechanical pass/fail for automation, but CLI
  text should not imply promotion.

### Metric Semantics

- Runner smoke metrics must be renamed or nested so they are not read as
  portfolio returns.
- Prefer a structure like:

```json
{
  "smoke_score": {
    "sum_weighted_trade_gross_return": 0.0,
    "sum_weighted_trade_funding_return": 0.0,
    "sum_weighted_trade_cost_return": 0.0,
    "sum_weighted_trade_net_return": 0.0
  }
}
```

- Validation funding metrics must separate:
  - backend-native return,
  - linear funding adjustment,
  - linear adjusted return.
- Do not use the linear funding-adjusted value as if it were exact portfolio
  accounting.
- Backend metric floats must be finite, or artifact writing must fail closed
  before writing non-standard JSON such as `NaN`.

### Researched Package Contract

Define one canonical researched package layout for validation handoff. The
minimal validation-ready package should include:

```text
researched/<strategy-family>/<variant>/
  strategy.py
  validation.toml
  manifest.json or parent manifest entry
```

The manifest must identify:

- lifecycle status,
- strategy file hash,
- validation config hash,
- upstream autoresearch run identity when available,
- variant id or directory.

Validation of a researched package should fail closed if the package is missing
the required layout, missing the matching manifest entry, or has stale hashes.

### Legacy Removal

- Remove public `hold_bars` artifact fields when `max_hold_bars` is the
  canonical field.
- Delete or rewrite tests that only assert legacy compatibility.
- Do not add adapters that accept old signal-only strategy contracts.
- Do not preserve stale docs as active workflow references.

## Error Handling

- Missing or incomplete observation lineage in validation-ready packages fails
  before backend execution.
- Missing researched manifest/layout fails before backend execution.
- Unsupported backend semantics remain advisory/non-passing and are recorded in
  artifacts.
- Non-finite backend metrics fail validation/artifact serialization rather than
  writing non-standard JSON.
- Runner smoke failure remains a runner failure, not strategy evidence.

## Testing Strategy

Add focused tests that prove the reset removes root risks:

- Real strategy future-poison/readiness tests:
  - FX triangle strategy fails validation-readiness when synthetic-leg rows are
    omitted from observations.
  - Crypto funding strategy fails validation-readiness when funding/history or
    cross-sectional rows are omitted from observations.
- Positive lineage tests:
  - complete `ObservationRef` dependencies pass readiness,
  - late `available_at` on any declared observation fails.
- Researched package tests:
  - missing manifest/layout fails,
  - matching manifest/hash/status passes the package gate.
- Artifact schema tests:
  - runner artifacts do not expose public `hold_bars`,
  - smoke metrics use smoke-score names,
  - validation funding metrics separate native return, adjustment, and adjusted
    return,
  - non-finite backend metrics cannot be serialized.
- Policy tests:
  - current validation cannot imply promotion, paper, or live eligibility,
  - CLI/artifacts use advisory/mechanical wording.
- Docs tests:
  - active docs do not mention superseded `generate_signals` workflow.

Primary verification command:

```bash
conda run -n quant pytest
```

## Rollout Notes

This phase intentionally changes artifact schemas and tests. That is acceptable
because Season explicitly prefers strict legacy cleanup over compatibility.

Implementation should avoid a broad rewrite. Touch the smallest files necessary
to make the clean contract true end to end. When a legacy concept blocks the
clean contract, delete or rename it rather than layering a compatibility
adapter around it.

## Acceptance Criteria

- Full test suite passes with `conda run -n quant pytest`.
- Active docs describe only the current `StrategyDecision` workflow.
- Validation-ready researched packages cannot pass without required observation
  lineage.
- Current validation cannot produce paper/live/promotion-sounding output.
- Runner smoke metrics cannot be mistaken for portfolio returns.
- Funding-adjusted validation metrics are explicitly labeled as linear
  adjustments.
- Public artifacts no longer expose old signal-era compatibility fields.
- Researched package validation requires the canonical layout and hash
  manifest.
