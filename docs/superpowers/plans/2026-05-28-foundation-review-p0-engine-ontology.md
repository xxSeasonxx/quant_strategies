# Phase 6 Plan: Engine Strategy Ontology Collapse

Date: 2026-05-28
Design: `docs/superpowers/specs/2026-05-28-foundation-review-p0-engine-ontology-design.md`

## Goal

Address the P0 engine parallel-ontology finding by making the smoke engine
consume `StrategyDecision` directly and by removing runner signal-row artifacts.

## Implementation Steps

- [x] **Step 1: Engine request contract**

  Replace `StrategySpec.signals` with `StrategySpec.decisions`, remove
  `Signal`, and update `screen` to derive supported smoke semantics from
  `StrategyDecision`.

  Verify: engine model/screen/evidence tests construct decisions directly.

- [x] **Step 2: Runner request boundary**

  Change `build_request` to accept decisions, remove `decision_adapter`, and
  keep fillability errors at request-build time.

  Verify: runner engine tests cover unsupported intent, instrument, flat target,
  and non-weight sizing through `build_request`.

- [x] **Step 3: Data readiness and artifacts**

  Check decision `as_of_time` directly. Remove `signals.csv` and summary
  `signals` payloads from runner artifacts.

  Verify: runner API/artifact profile tests assert decision-based artifacts.

- [x] **Step 4: Docs/progress, verification, review**

  Update README and `progress.md`; run focused tests, full suite, diff checks,
  compile checks, and subagent code review before commit.

## Verification Commands

```bash
conda run -n quant pytest tests/test_engine_models.py tests/test_engine_screen.py tests/test_engine_validate_and_evidence.py tests/test_runner_engine_runner.py tests/test_data_readiness.py tests/test_runner_artifact_profiles.py tests/test_runner_api_cli.py tests/test_krohn_mueller_whelan_fix_reversal.py tests/test_fx_triangular_residual_reversion.py tests/test_phase5_performance.py tests/test_readme_contract.py -q
conda run -n quant pytest -q
git diff --check
conda run -n quant python -m compileall -q src tests
```

## GSTACK REVIEW REPORT

### Scope Challenge

The tempting narrow fix is to move signal-row conversion from
`decision_adapter` into `engine_runner`, but that preserves the root problem.
This phase removes the semantic duplicate from the engine request. It does not
claim to finish every G3 subfinding; fill/cost config consolidation and engine
gating renames can be handled as follow-up cleanup.

### Architecture Review

Target flow:

```text
StrategyDecision
        |
        v
EvaluationRequest.spec.decisions
        |
        v
engine.screen decision-derived smoke fields
        |
        v
Trade / SmokeScore
```

There is no signal-row execution boundary. Decision artifacts remain the audit
surface.

### Code Quality Review

- Keep unsupported smoke semantics in small helpers with clear errors.
- Do not add compatibility aliases for `Signal`.
- Keep `Bar` focused on normalized OHLC/quote/funding validation.
- Keep artifact removals explicit in tests so stale signal files do not return.

### Test Review

Tests must cover:

- engine screening of long, short, costs, funding, quote fills, and exits from
  decisions;
- runner request-build failures for unsupported decision ontology shapes;
- data readiness using decision `as_of_time`;
- full and summary profiles omitting signal artifacts;
- deterministic artifacts without `signals.csv`.

### Performance Review

Removing the signal-row conversion eliminates one pydantic/dict hop per
decision. The phase should not materially change engine runtime except for
request serialization now carrying full decision payloads.
