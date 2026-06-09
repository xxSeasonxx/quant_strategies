## Why

Downstream `quant_autoresearch` full-baseline runs are blocked because focused
quick-run causality replay can spend minutes replaying large row prefixes before
any diagnostic economics are produced. Quick run is an iteration surface, so
causality replay should annotate diagnostic evidence cheaply rather than prevent
the research loop from seeing a score.

## What Changes

- Add a quick-run `micro` causality policy for autoresearch iteration.
- Make `micro` replay non-blocking: quick-run engine scoring still completes
  when micro replay fails or times out, with causality evidence marked
  unverified.
- Add shared replay-scope vocabulary for `micro`, `bounded`, `complete`, and
  `off` evidence.
- Add explicit bounded replay options for validation and evaluation while
  preserving complete replay as their default.
- Improve replay harness performance by selecting micro probes directly,
  reusing a replay workspace, and avoiding repeated prefix refreezing where
  possible.
- Keep strategy-module optimization out of scope.
- Do not add replay parallelism in this change.

## Capabilities

### New Capabilities

- `causality-replay-policy`: Shared replay-scope semantics and bounded replay
  behavior for quick run, validation, and evaluation.

### Modified Capabilities

- `quick-run-economics`: Add `causality_check = "micro"`, micro replay evidence,
  and non-blocking quick-run scoring semantics.
- `focused-causality-gate`: Reclassify focused causality as an advanced/legacy
  quick-run mode while `micro` becomes the recommended autoresearch policy.

## Impact

- Affected code: `src/quant_strategies/causality.py`, quick-run config/result
  evidence, validation config/pipeline, evaluation config/pipeline, artifact
  payloads, consumer docs, and focused performance tests.
- Public API impact: additive config values and additive result/artifact
  evidence fields. Existing `run_config`, `run_validation`, and
  `run_evaluation` function signatures remain unchanged.
- Dependency impact: no new runtime dependency.
- Operational impact: downstream autoresearch can receive quick-run economics
  even when micro replay fails or times out, while validation/evaluation
  provenance exposes whether replay was complete or bounded.
