# Phase 3 Plan: Metric Semantics And Artifact Trust

Date: 2026-05-28
Design: `docs/superpowers/specs/2026-05-28-foundation-review-p2-metric-trust-design.md`

## Goal

Address PRD G2 and NFR-DETERMINISM for runner smoke artifacts without expanding
the phase into validation backend schemas or engine ontology cleanup.

## Implementation Steps

- [x] **Step 1: Add typed semantics contracts**

  Add artifact trust tier mapping and typed smoke metric semantics. The public
  payload should include unit, base, aggregation, backend, return path model,
  comparable-to targets, tolerance, and asymmetry.

  Verify: unit tests assert all four smoke score fields have semantics and that
  every semantics record is JSON-safe and schema-stable.

- [x] **Step 2: Thread trust and semantics through runner artifacts**

  Include `artifact_trust_tier` in `RunResult`, `summary.json`,
  `data_manifest.json`, `run_manifest.json`, and
  `artifact_profile_summary.json`. Include `metric_semantics` in summary and
  run manifest evidence.

  Verify: runner API tests assert full is `audit_replayable`, summary is
  `search_only`, and both artifact profiles expose smoke metric semantics.

- [x] **Step 3: Add deterministic artifact regression**

  Run the same deterministic config twice with identical loaded rows and compare
  stable artifact content hashes. Keep the test focused on generated artifacts,
  not result directory names.

  Verify: focused runner test fails if JSON key ordering or artifact payloads
  become nondeterministic.

- [x] **Step 4: Docs and progress**

  Update README, autoresearch consumer docs, and `progress.md`.

  Verify: README contract tests cover the new trust-tier and metric-semantics
  language.

## Verification Commands

```bash
conda run -n quant pytest tests/test_runner_artifact_profiles.py tests/test_runner_api_cli.py tests/test_readme_contract.py -q
conda run -n quant pytest -q
git diff --check
conda run -n quant python -m compileall -q src tests
```

## GSTACK REVIEW REPORT

### Scope Challenge

This phase deliberately avoids the P0 engine parallel ontology and the larger
validation backend metric schema. Both are real findings, but coupling them to
runner artifact trust would make the phase too broad and harder to verify.

The minimal useful version is a schema change: tell downstream consumers whether
an artifact set is search-only or audit replayable, and tell them what the smoke
numbers mean before they rank on them.

### Architecture Review

Current runner payload flow:

```text
engine.SmokeScore
  -> runner compact engine summary
  -> summary.json
  -> run_manifest.evidence
  -> optional artifact_profile_summary.json
```

Phase 3 adds semantics beside the scalar values. It does not change engine math
or the decision adapter. The trust-tier mapping belongs at the artifact profile
boundary because profile choice controls which audit inputs are written.

### Code Quality Review

- Keep the trust mapping as a small pure function, not config duplication.
- Keep metric semantics centralized so new smoke fields cannot be added without
  updating the contract.
- Do not infer audit replayability from file existence at read time; write the
  declared tier when artifacts are produced.

### Test Review

Coverage must prove:

- summary profile means `search_only`;
- full profile means `audit_replayable`;
- every smoke score key has semantics;
- repeated deterministic runs produce byte-identical stable artifacts.

Regression diagram:

```text
same config + same rows
        |
        v
two result dirs with different names
        |
        v
stable artifact bytes match
```

### Performance Review

The added payloads are small static dictionaries. They should not touch row
iteration or backend execution. The deterministic test uses monkeypatched data
loading and a tiny row set to avoid turning artifact determinism into a slow
end-to-end benchmark.

### Not In Scope

- Backend metrics schema.
- Cross-backend tolerance policy.
- Full validation artifact replayability.
- Structured logging events.
- Any migration shim for old artifacts.
