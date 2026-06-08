## Context

`run_config` currently executes strategy generation, observation dependency
audit, strict hidden-lookahead replay, request building, and engine evaluation
as one public quick-run path. The replay helper already supports `emitted` and
`strict` modes internally, but the runner config does not expose that choice.

Strict replay is high confidence because it probes row-grid no-emission
boundaries and can catch strategies that peek ahead to suppress losing trades.
For large minute panels with sparse decisions, that confidence comes at a high
cost: probe count scales with row-grid timestamps instead of emitted decisions.
Downstream Train loops need a faster public mode for iteration, but the runner
must keep evidence labels honest and preserve strict replay for dedicated
audits.

## Goals / Non-Goals

**Goals:**

- Expose an additive public causality policy under `[output]`.
- Preserve current strict replay behavior for existing configs.
- Let callers select emitted replay for Train iteration without private imports
  or monkeypatching.
- Record deterministic, emitted, and strict suppression evidence separately in
  the in-process result and artifacts.
- Allow strict replay to be bounded without reporting capped evidence as a full
  strict pass.

**Non-Goals:**

- Do not change the `run_config` Python signature.
- Do not add cached/preloaded row execution.
- Do not relax row-contract, observation-dependency, data-readiness, or engine
  request checks.
- Do not fix downstream strategy code that uses future sample availability
  inside `generate_decisions`; downstream consumers must still make strategies
  causal before emitted replay can pass.
- Do not add new runtime dependencies.

## Decisions

### Add `output.causality_check`

Add an `OutputConfig.causality_check` field with values `off`, `emitted`, and
`strict`. The default is `strict`, preserving existing behavior.

Alternatives considered:

- Reuse `quick_checks`: rejected because quick checks currently control engine
  screening mode, not replay semantics. Overloading it would make evidence
  meaning implicit.
- Add only an environment variable: rejected because run artifacts would not
  fully describe the evidence contract.

### Add optional `output.strict_probe_limit`

Add an optional nonnegative integer strict probe limit. It applies only when
`causality_check = "strict"`. If the derived strict boundary count exceeds the
limit, the run checks a bounded set of strict probes and records strict
suppression evidence as incomplete/capped unless all required strict probes were
actually run.

Alternatives considered:

- Make emitted mode the only fast path: rejected because consumers also need a
  bounded strict audit mode for large windows.
- Fail immediately when strict boundaries exceed a limit: rejected because a
  bounded audit can still provide useful partial evidence if it is labeled
  incomplete.

### Keep Replay Policy Inside Runner Config

The policy is part of `RunConfig.output`, not a new argument to `run_config`.
Generated artifacts already snapshot the config, so artifact replay and evidence
inspection can see the selected policy without out-of-band process state.

Alternatives considered:

- Add a `run_config(..., causality_check=...)` argument: rejected because it
  would let code run under evidence semantics that are absent from `config.toml`.

### Expand Causality Evidence Metadata

Extend `RunCausalityEvidence` and evidence payloads so deterministic replay,
emitted replay, strict suppression replay, skipped probes, and capped probes are
visible separately. Existing boolean summary fields can remain as compatibility
aliases, but new fields must carry enough detail to avoid treating emitted-only
evidence as strict evidence.

Alternatives considered:

- Keep a single `causality_verified` flag: rejected because it conflates
  materially different replay guarantees.

### `off` Is Explicitly Unverified

`causality_check = "off"` skips replay and lets the runner continue only with
artifacts and result metadata marking causality replay as unverified. It is for
profiling/debugging, not trusted Train evidence.

Alternatives considered:

- Omit `off`: rejected because users will otherwise keep creating local
  monkeypatches for profiling, which produces less honest artifacts.

## Risks / Trade-offs

- Lighter emitted mode can miss suppression lookahead that strict replay would
  catch -> artifacts and result metadata must make strict suppression replay
  unverified, and downstream survivor audit flows should request strict mode.
- Probe limits can create false comfort if reported poorly -> capped strict
  replay must never set strict suppression evidence to a complete pass.
- New evidence fields can confuse existing consumers -> keep existing fields
  additive and compatibility-oriented, but document the stricter per-dimension
  fields as authoritative.
- `off` mode can be abused -> label it unverified in evidence warnings and keep
  the default as strict.

## Migration Plan

1. Add config parsing fields with defaults so existing TOML files continue to
   load unchanged.
2. Route `_check_causality` through the selected policy.
3. Extend evidence/result payloads and artifact summaries.
4. Add runner tests for strict default, emitted mode, off mode, invalid config,
   capped strict evidence, and artifact metadata.
5. After upstream support lands, downstream consumers such as
   `quant_autoresearch` can materialize `causality_check = "emitted"` for Train
   iteration and request strict mode for survivor audits.

Rollback is straightforward: because the change is additive, callers can omit
the new fields and retain strict behavior.

## Open Questions

None for the initial implementation. Sampling policy beyond a simple cap can be
introduced later if strict bounded audits need a more sophisticated probe
selection strategy.
