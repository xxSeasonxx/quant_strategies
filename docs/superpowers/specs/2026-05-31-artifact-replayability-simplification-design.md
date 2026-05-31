# Artifact Replayability Simplification Design

Date: 2026-05-31
Status: Pending written-spec review
Scope: PR 2 from `TODOS.md`

## Goal

Replace the runner's `artifact_trust_tier` vocabulary with one factual replayability flag:
`replayable_from_artifacts`.

Artifact profiles already answer the operational choice:

- `summary`: compact aggregate quick-run evidence.
- `diagnostic`: bounded behavior diagnostics for active strategy improvement.
- `full`: audit/replay artifacts.

The extra `search_only` / `audit_replayable` tier vocabulary does not add a decision
the researcher should make. The durable fact is whether reported quick-run metrics can
be replayed from emitted artifacts alone.

## Decisions

- Make this a hard public contract cutover.
- Do not keep compatibility aliases, deprecated properties, dual artifact keys, or
  deprecation warnings.
- Keep `artifact_profile` in config and artifacts.
- Replace `artifact_trust_tier` with `replayable_from_artifacts` in the public
  `RunResult` and all active runner artifacts.
- Leave validation's `verdict_replayable` and `verdict_replay_basis` unchanged.

Derived replayability:

| Artifact profile | `replayable_from_artifacts` | Rationale |
| --- | --- | --- |
| `summary` | `false` | Compact output omits the full replay chain. |
| `diagnostic` | `false` | Bounded diagnostics omit the full replay chain. |
| `full` | `true` | Full output writes the row, decision, engine request, and evidence artifacts needed for audit replay. |

If a runner failure happens after config loading, replayability is still derived from
the configured artifact profile. If config loading fails before the profile is known,
`RunResult.replayable_from_artifacts` remains `None`.

## Code Shape

Update the semantics boundary first:

- Replace `ArtifactTrustTier` and `artifact_trust_tier_for_profile()` in
  `src/quant_strategies/evidence_semantics.py`.
- Add `replayable_from_artifacts_for_profile(artifact_profile: str) -> bool`.
- Keep unknown-profile handling strict by raising `ValueError` if the helper receives
  an unsupported profile.

Update runner surfaces:

- Rename `RunResult.artifact_trust_tier` to `RunResult.replayable_from_artifacts`.
- Update runner success and failure result construction to populate the new field.
- Update `summary_payload()`, `write_data_manifest()`, `write_run_manifest()`,
  `summary_profile_payload()`, and `diagnostic_payload()` to emit
  `replayable_from_artifacts`.
- Ensure new `summary.json`, `data_manifest.json`, `run_manifest.json`,
  `diagnostics.json`, and `artifact_profile_summary.json` payloads never emit
  `artifact_trust_tier`, `search_only`, or `audit_replayable`.

No runner behavior, artifact profile selection, pass/fail logic, PnL math, causality
checks, validation verdicts, or row-contract strictness should change.

## Docs And Handoff Updates

Update active documentation and handoff files:

- `TODOS.md`: mark PR 2 complete after implementation and identify PR 3 as the next
  open item, following the existing PR 0 / PR 1 completion-note style.
- `README.md`: describe compact/diagnostic quick-run evidence by default and full
  output for audit replay when needed.
- `docs/runner.md`: replace the trust-tier section with factual replayability wording.
- `docs/research-process.md`: document `RunResult.replayable_from_artifacts` and the
  meaning of true/false.
- `docs/quant-autoresearch-consumer.md`: tell consumers to read
  `result.replayable_from_artifacts` and rerun retained candidates with
  `artifact_profile = "full"` when artifact replay is required.
- `PRD.md`: clean up any stale references found by grep.

Historical design and planning docs under `docs/superpowers/` can remain as process
history. Active product documentation is `README.md`, `PRD.md`, and the non-superpowers
reference docs under `docs/`.

## Tests

Update focused runner tests so they assert:

- Summary-profile `RunResult` and artifacts have `replayable_from_artifacts is False`.
- Diagnostic-profile `RunResult` and artifacts have `replayable_from_artifacts is False`.
- Full-profile `RunResult` and artifacts have `replayable_from_artifacts is True`.
- New output does not contain `artifact_trust_tier`, `search_only`, or
  `audit_replayable`.
- Existing profile behavior remains unchanged: summary and diagnostic stay compact;
  full still writes audit/replay artifacts.

## Verification

Targeted verification:

```bash
rg -n "search_only|audit_replayable|artifact_trust_tier" TODOS.md PRD.md README.md docs src tests --glob '!docs/superpowers/**'
conda run -n quant pytest tests/test_runner_artifact_profiles.py tests/test_runner_api_cli.py -q
```

Final verification before declaring implementation complete:

```bash
conda run -n quant pytest -q
```

## Non-Goals

- No compatibility shim for old `artifact_trust_tier` consumers.
- No validation trust-tier changes.
- No change to validation replayability fields.
- No artifact profile redesign.
- No change to generated historical result artifacts.
