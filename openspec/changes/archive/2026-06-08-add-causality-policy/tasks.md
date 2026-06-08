## 1. Tests First

- [x] 1.1 Add runner config tests for default strict mode, explicit `off`, explicit `emitted`, explicit `strict`, invalid causality mode, valid strict probe limit, and invalid strict probe limit.
- [x] 1.2 Add causality/runner tests proving existing configs still run strict replay by default.
- [x] 1.3 Add emitted-policy runner tests proving deterministic plus emitted replay can complete engine evaluation while strict suppression remains unverified.
- [x] 1.4 Add off-policy runner tests proving replay is skipped, engine evaluation can complete, and result/artifact evidence is marked causality-unverified.
- [x] 1.5 Add capped-strict tests proving strict probe caps do not report complete strict suppression verification.

## 2. Config And Types

- [x] 2.1 Add public output config fields for `causality_check` and `strict_probe_limit` with strict-preserving defaults.
- [x] 2.2 Extend runner causality evidence value objects to carry selected policy, deterministic replay status, emitted replay status, strict suppression status, skipped probes, and capped/incomplete strict replay status.
- [x] 2.3 Extend causality replay result types or runner-side wrappers so capped strict replay cannot be mistaken for a complete strict pass.

## 3. Runner Behavior

- [x] 3.1 Route `_check_causality` through `config.output.causality_check` without changing the public `run_config` signature.
- [x] 3.2 Implement `emitted` mode by calling hidden-lookahead replay with emitted-decision boundaries only.
- [x] 3.3 Implement `off` mode by skipping replay and producing unverified causality evidence without bypassing row-contract, observation-dependency, data-readiness, or request-build checks.
- [x] 3.4 Implement strict probe limiting so bounded strict replay records capped/incomplete evidence when not all strict probes run.
- [x] 3.5 Preserve current failure behavior when deterministic replay, emitted replay, or complete strict replay detects a violation.

## 4. Artifacts And Evidence Semantics

- [x] 4.1 Update evidence-quality payloads and warnings to distinguish strict, emitted-only, capped, and off-policy runs.
- [x] 4.2 Update `summary.json`, `data_manifest.json`, and diagnostic artifacts to include the selected causality policy and replay evidence dimensions.
- [x] 4.3 Keep compatibility summary fields additive while ensuring they do not imply complete strict evidence for emitted-only, capped, or off-policy runs.
- [x] 4.4 Ensure promotion, paper, live, and eligibility fields remain false when causality replay is off or strict suppression replay is incomplete.

## 5. Verification

- [x] 5.1 Run focused runner, causality, artifact, and config tests for the new policy behavior.
- [x] 5.2 Run the repository formatting/lint target if available.
- [x] 5.3 Run the smallest reliable full Python test command for this change under `conda run -n quant`.
- [x] 5.4 Document downstream integration requirements for `quant_autoresearch`: use emitted mode for Train iteration only after strategy emitted replay passes, and use strict mode or explicit strict-unverified handoff for survivor audits.
