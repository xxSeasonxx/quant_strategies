## Why

Large sparse-decision Train loops can become unusable because public
`run_config` always performs strict row-grid hidden-lookahead replay. The
runner needs an explicit causality policy so iteration can use honest
emitted-replay evidence while strict suppression replay remains available for
dedicated audits.

## What Changes

- Add a public quick-run causality policy under `[output]` with supported modes
  for skipped, emitted-decision, and strict replay.
- Preserve strict replay as the default public runner behavior unless a caller
  explicitly selects a lighter policy.
- Expose deterministic, emitted, and strict suppression evidence dimensions
  separately in `RunResult` and runner artifacts.
- Support bounded strict replay so capped/incomplete strict evidence is recorded
  as incomplete rather than silently treated as passed.
- Keep quick-run economics and engine evaluation available for emitted-policy
  Train iteration when deterministic and emitted replay pass.
- No breaking changes: existing configs without the new fields keep current
  strict replay semantics.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `quick-run-economics`: Public `run_config` quick runs gain configurable
  causality policy and explicit replay-evidence metadata as part of the typed
  in-process result and artifact semantics.

## Impact

- Affected code: runner config parsing, quick-run causality preparation,
  causality replay helpers, evidence-quality/artifact payloads, and runner API
  tests.
- Public API: additive `[output]` config fields and additive result/evidence
  fields; no `run_config` signature change.
- Downstream consumers: `quant_autoresearch` can materialize
  `causality_check = "emitted"` for Train iteration once this upstream support
  exists, while final survivor audits can request strict evidence.
- Dependencies: no new runtime dependency.
