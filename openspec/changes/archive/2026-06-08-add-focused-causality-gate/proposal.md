## Why

Autoresearch iteration is blocked by expensive replay-style causality checks that
belong at trust gates, not every scoring run. The root problem is that the
research loop currently has to reason about low-level replay modes (`off`,
`emitted`, `strict`) and can spend minutes or gigabytes proving a candidate is
eligible before it even writes results.

## What Changes

- Add a focused causality gate intended for strategy-development and
  autoresearch iteration.
- Run the focused gate when strategy source changes, cache the result by source
  hash and focused-profile inputs, and reject variants that fail or time out.
- Keep full emitted/strict replay as internal audit/validation/evaluation
  evidence, not as concepts the strategy-writing LLM must choose during the
  inner loop.
- Make quick research scoring able to rely on the focused gate instead of
  running emitted or strict replay for every candidate.
- Preserve existing validation and evaluation strict causality gates for
  survivor/audit workflows.
- Add bounded runtime semantics so focused causality never hangs autoresearch.

## Capabilities

### New Capabilities
- `focused-causality-gate`: Defines the focused source-change causality gate,
  its cache key, timeout/rejection semantics, and non-LLM-facing relationship to
  heavier replay checks.

### Modified Capabilities
- `quick-run-economics`: Quick-run causality policy gains a higher-level
  focused gate suitable for Train/autoresearch iteration; emitted/strict replay
  remain available as internal evidence modes but are no longer the default
  concepts for the research loop.

## Impact

- Affected code:
  - `src/quant_strategies/causality.py`
  - `src/quant_strategies/runner/config.py`
  - `src/quant_strategies/runner/__init__.py`
  - runner artifacts/evidence payloads
  - docs for consumer/autoresearch usage
  - focused tests around policy, timeout, cache key, and evidence status
- Public behavior:
  - Autoresearch-facing quick runs should be able to request a focused causality
    gate without exposing emitted/strict policy choices to the strategy LLM.
  - Focused gate failure or timeout rejects the strategy variant before scoring.
  - Existing explicit `causality_check = "off" | "emitted" | "strict"` configs
    remain supported for lower-level/debug/audit callers.
- Dependencies:
  - No new runtime dependency is expected.
