## Why

The repository is a solid local foundation for auditable strategy smoke runs, but
the readiness review found several places where clean operational results can be
mistaken for research-quality promotion evidence. This change tightens the
runner contract so strategy assessment remains honest, reproducible, and easy to
consume without adding a second harness or broad framework.

## What Changes

- Add explicit assessment metadata to run results and summaries so callers can
  distinguish runner completion, smoke assessment status, and promotion
  eligibility.
- Write run manifests for every run that creates a result directory, including
  early strategy-import, data-load, and signal-generation failures.
- Add a CLI `--repo-root` option so checkout-local runs and installed-package
  usage have an explicit repository root contract.
- Add lightweight data-readiness checks for generated signals when availability
  metadata is present in matching decision rows.
- Add static strategy-boundary tests that enforce pure strategy modules and flat
  strategy layout.
- Document promotion discipline: current screen/validate output remains smoke
  evidence, while promotion requires a separate checklist and stronger research
  evidence.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `strategy-runner`: clarify assessment semantics, manifest coverage,
  repository-root CLI behavior, data-readiness checks, strategy purity
  enforcement, and promotion discipline.

## Impact

- Affected code: `src/quant_strategies/runner/`, runner tests, strategy
  boundary tests, and README documentation.
- Affected APIs: `RunResult` gains explicit assessment fields while preserving
  the existing `success`, `result_dir`, `notes_path`, and `message` fields.
- Affected artifacts: `summary.json` gains assessment metadata, and early failed
  runs gain `run_manifest.json`.
- Dependencies: no new runtime dependency; data-readiness checks use existing
  row dictionaries and Python standard-library datetime handling.
