# Evidence Honesty v1 Design

## Goal

Make current runner and validation evidence harder to overread without turning
`quant_strategies` into a portfolio platform or research database. This design
addresses three remaining foundation-review findings as one small bundle:

- validation-only hidden-lookahead protection,
- runner evidence-quality fields for availability and causality uncertainty,
- structured validation failure details.

## Scope

In scope:

- Add a validation-only replay check that detects strategies whose decisions
  change when rows beyond each decision information set are removed.
- Add machine-readable runner evidence-quality fields to `summary.json` and
  `data_manifest.json`.
- Add structured validation failure details while preserving existing policy
  reason strings.

Out of scope:

- `researched/` package or variant support.
- VectorBT Pro packaging/setup changes.
- Typed scenario backend config refactors.
- Data materialization, repair, backfill, joins, or `quant_data` changes.
- `paper_candidate` policy thresholds or search-pressure statistics.
- Public API facade changes or typed artifact readers.
- Archiving historical docs/evidence.

## Architecture

### Validation Hidden-Lookahead Check

Create a focused validation module, likely
`src/quant_strategies/validation/lookahead.py`.

The check runs inside `validation.run_validation` after base decisions pass
`validate_decision_output` and before backend scenarios. It uses the same frozen
rows and frozen params discipline as normal strategy execution.

For each validation window:

1. Generate baseline decisions from the full loaded window.
2. For each baseline decision, build a truncated row set containing only rows
   that are in the decision information set:
   - first require `timestamp <= decision.as_of_time`;
   - if `available_at` is present and valid, also require
     `available_at <= decision.decision_time`;
   - if `available_at` is missing or invalid, fall back to the timestamp rule
     only for replay filtering. Separate data-audit checks still report
     declared rows with bad availability metadata.
3. Re-run `generate_decisions` on the truncated rows.
4. Normalize and compare decision fingerprints for the same `strategy_id`.

If the fingerprint differs, the data audit for that window fails with
`hidden_lookahead_detected`. If the replay raises, the window fails with
`hidden_lookahead_check_failed: <type>: <message>`.

This is deliberately validation-only. The runner remains permissive and fast for
search loops.

### Runner Evidence Quality

Add a small helper for runner evidence quality, either in
`runner/artifacts.py` or a focused runner module if that keeps the code clearer.

Compute from loaded rows:

- `data_availability_status`: `complete`, `partial`, or `missing`.
- `availability_coverage`: `{present, total, fraction}` for non-null
  `available_at`.
- `causality_verified`: always `false` for runner smoke.
- `evidence_quality_warnings`: short machine-readable strings.

Rules:

- all rows have non-null `available_at` -> `complete`;
- some rows have non-null `available_at` -> `partial`;
- no rows have non-null `available_at` -> `missing`.

Runner behavior does not become fatal when availability is partial or missing.
The uncertainty is recorded in `summary.json` and `data_manifest.json`.

### Validation Failure Details

Preserve stable policy reasons such as `strategy_import_failed`,
`backend_selection_failed`, and `param_validation_failed`.

Add structured failure detail where validation catches `Exception`:

```json
{
  "stage": "strategy_import",
  "type": "ValidationStrategyLoadError",
  "message": "strategy file does not exist: ..."
}
```

Expose these details in machine-readable validation artifacts. Prefer adding
them to `validation_decision.json` and `robustness_matrix.json`; keep
`validation_report.md` concise.

## Data Flow

Runner flow:

```text
load rows
  -> compute normalized row hash
  -> compute evidence quality from row availability
  -> write data_manifest.json
  -> generate decisions
  -> evaluate smoke engine
  -> write summary.json with evidence quality
```

Validation flow:

```text
load rows
  -> generate base decisions
  -> validate StrategyDecision output
  -> audit declared observation lineage
  -> run hidden-lookahead replay
  -> if audits pass, expand backend scenarios
  -> write validation artifacts with optional failure_details
```

## Tests

Add or update focused tests:

- Lookahead validation:
  - as-of-only strategy passes;
  - future-dependent strategy fails with `hidden_lookahead_detected`;
  - replay exception fails with `hidden_lookahead_check_failed`;
  - existing validation runner behavior remains green.
- Runner evidence quality:
  - full `available_at` coverage writes `complete`;
  - partial coverage writes `partial` and a warning;
  - no coverage writes `missing` and a warning;
  - both `summary.json` and `data_manifest.json` expose the fields;
  - runner still succeeds for missing availability when existing readiness rules
    allow it.
- Validation failure details:
  - strategy import failure records structured type/message;
  - backend selection failure records structured type/message;
  - existing policy reason strings remain unchanged.

Required verification:

```bash
conda run -n quant pytest tests/test_validation_runner.py tests/test_validation_future_poison.py tests/test_runner_api_cli.py -q
conda run -n quant pytest -q
```

## Non-Goals And Constraints

- Do not reintroduce `researched/` as a validation ontology.
- Do not add compatibility adapters for old strategy output contracts.
- Do not make runner smoke evidence look like market validation.
- Do not make missing `available_at` fatal in runner search flows.
- Keep the implementation small and delete/replace local bad code when a root
  fix is cleaner than layering guards.

## Acceptance Criteria

- Validation catches hidden future-row dependence for retained candidates.
- Runner artifacts explicitly report availability coverage and
  `causality_verified = false`.
- Validation artifacts preserve useful exception type/message without changing
  policy reason names.
- Full test suite passes under `conda run -n quant`.
