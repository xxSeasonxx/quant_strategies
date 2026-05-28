# Phase 3 Design: Metric Semantics And Artifact Trust

Date: 2026-05-28
Mode: Builder
Source reviews: `review-codex.md`, `review-claude.md`

## Problem

Phase 1 fixed the most dangerous runner causality overclaim and renamed the
smoke activity fields. Phase 2 made the decision ontology expressive enough to
state unsupported semantics honestly. The remaining runner artifact problem is
that a fast summary-profile run can still look too similar to an audit-ready
full-profile run, and smoke metrics still lack first-class unit/base/aggregation
metadata.

The PRD requires numeric quantities to declare unit, base, aggregation,
backend semantics, and comparability. It also requires deterministic artifacts.
The reviews correctly identify these as schema issues, not math issues.

## Assignment

Add a machine-readable trust tier to runner artifacts and typed smoke metric
semantics for the `smoke_score.sum_signed_trade_activity_*` fields. Preserve
the existing scalar smoke scores for simple ranking, but make their meaning and
limitations explicit in `summary.json`, `run_manifest.json`,
`data_manifest.json`, and summary-profile artifacts.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 3:

- `artifact_profile = "summary"` maps to `artifact_trust_tier = "search_only"`.
- `artifact_profile = "full"` maps to
  `artifact_trust_tier = "audit_replayable"`.
- Keep scalar smoke score fields stable; add semantics beside them instead of
  replacing values with `{name, value, semantics}` records in this phase.
- Scope metric semantics to runner smoke metrics only. Backend agreement
  tolerance and validation metric schemas remain separate work.
- Add deterministic artifact regression coverage by comparing repeated run
  artifact hashes with deterministic inputs.

## Scope

- Add a typed artifact trust tier mapping for runner artifact profiles.
- Add typed metric semantics for all smoke score fields:
  unit, base, aggregation, backend, return path model, comparability, tolerance,
  and asymmetry.
- Include trust tier and metric semantics in runner summary, run manifest, data
  manifest, and summary-profile artifact payloads.
- Expose trust tier on `RunResult` so downstream consumers do not need to parse
  artifacts just to decide whether a result is audit replayable.
- Update README, consumer docs, and `progress.md`.
- Add focused tests for trust tier, smoke metric semantics coverage, and
  deterministic repeated runner artifacts.

## Not In Scope

- Replacing scalar smoke scores with full metric-value records.
- Validation backend metric schema and cross-backend agreement tolerance.
- Validation row/fill/trade/cost/funding artifact expansion.
- Structured stage events.
- Engine parallel ontology collapse.
- Changing the default artifact profile.

## Success Criteria

- Every runner artifact profile has a declared trust tier.
- Summary-profile artifacts are explicitly `search_only`; full-profile artifacts
  are explicitly `audit_replayable`.
- Every smoke score field emitted by the runner has a matching semantics record.
- Semantics state that smoke score fields are signed trade-activity sums, not
  NAV-path or portfolio returns.
- Re-running the same deterministic config with the same data produces matching
  artifact bytes for the stable artifact set.
