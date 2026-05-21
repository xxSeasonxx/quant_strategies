## Why

The runner already has the right boundaries, but a few outputs can mislead a
researcher during normal use. The root problem is semantic: first-run artifacts
must clearly distinguish runner completion, screen evidence, validation gates,
and the data/code identity needed to inspect a result later.

## What Changes

- Correct the FX residual strategy timing so its emitted decision time matches
  the configured next-bar quote-fill intent, or explicitly encode and test any
  intended extra lag.
- Change screen-mode summaries and notes so a completed screen is not labeled
  as strategy `passed` unless explicit screen gates exist.
- Preserve minimal reproducibility metadata in run artifacts: code/dependency
  identity, strategy-input digest, row counts, and timestamp ranges.
- Pass crypto-perp funding events into the internal evaluator and label strategy
  evidence as funding-aware when evaluator evidence includes funding cashflows.
- Tighten focused tests around timing, artifact semantics, and manifest content
  without adding broad frameworks or autonomous research workflows.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `strategy-runner`: Correct run-result semantics, FX timing, and minimal
  reproducibility artifacts for strategy evidence.

## Impact

- Affected source: `src/quant_strategies/runner/`, strategy files under
  `untested/`, and focused tests under `tests/`.
- Affected artifacts: `summary.json`, `notes.md`, and new manifest files in
  generated result directories.
- Affected docs: `README.md`, `PRODUCT_REQUIREMENTS.md`, and stale design/spec
  wording where artifact semantics change.
- External systems: the internal evaluator accepts supplied funding events and
  reports `funding_return`; no `quant_data` API change is required.
