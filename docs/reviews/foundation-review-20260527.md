# Foundation Review Current Status: quant_strategies

Date: 2026-05-27
Reviewer: Codex
Inputs reviewed:
- `foundation-review-20260527.md`
- `docs/reviews/foundation-claude-review.md`
- Current source, tests, README, consumer docs, and researched handoff artifacts

## Purpose

This document is the current source-of-truth review after re-checking the two
draft reviews against the code. The goal is to preserve real findings, retire
false positives and stale items, and avoid adding compatibility for legacy
layouts.

## Current Verdict

`quant_strategies` has a sound foundation: pure strategy files, explicit TOML
configs, strict `StrategyDecision` outputs, immutable strategy inputs,
deterministic smoke runs, advisory validation, and ignored generated artifacts.

The biggest earlier risks at the validation/research boundary have now been
addressed. Validation is based on an explicit TOML file plus its referenced
`strategy.py`; it does not inspect or bless `researched/` layouts. Runner
artifacts expose evidence-quality fields. Validation performs hidden-lookahead
replay checks. Fatal validation setup failures include structured
`failure_details`.

The remaining work is evidence-context metadata, not a platform rewrite.

## Resolved Findings

### Resolved: Researched Package Layout Contract

The original finding was real when the review was written: code expected a flat
researched package while the actual handoff was a family/variant tree. That is
now fixed at the root. `validation/research_manifest.py` was removed and
validation accepts only an explicit TOML file path. README and consumer docs say
the validator does not special-case `researched/`, package manifests, or
family/variant directories.

No legacy layout adapter should be added back.

### Resolved: Hidden Lookahead Protection

Validation now runs a hidden-lookahead replay check before backend scenarios.
It compares baseline decisions with decisions generated from rows available
inside each decision's information set. Mismatches become
`hidden_lookahead_detected`; replay errors become
`hidden_lookahead_check_failed`.

This is intentionally validation-only. The fast runner remains permissive and
labels output as smoke/search evidence.

### Resolved: Runner Evidence-Quality Fields

Runner `summary.json` and `data_manifest.json` now include
`data_availability_status`, `availability_coverage`, `causality_verified`, and
`evidence_quality_warnings`. Missing availability remains non-fatal for search,
but machine consumers can filter it explicitly.

### Resolved: Validation Failure Details

`validation_decision.json` and `robustness_matrix.json` now include structured
`failure_details` for fatal setup failures caught by validation, including the
stage, exception type, and message.

### Resolved: Shared Runner/Validation Execution Boundary

Runner and validation now share `runner.execution.execute_strategy_run` for
strategy import, parameter validation, data loading, frozen strategy execution,
decision validation, normalized row hashing, and evidence-quality context.
Validation no longer imports or calls the runner data loader directly.
Runner-only smoke-engine signal conversion remains in `runner.run_config`.

The validation-specific strategy-loader wrapper was also retired. Active
strategy loading now flows through the shared execution boundary instead of a
parallel validation loader and validation-specific strategy-load error path.

## Addressed In This Cleanup

### VectorBT Pro Setup Is Explicit

The default validation backend remains `vectorbtpro`, but setup is now explicit:
`pyproject.toml` declares a `vectorbtpro` optional dependency group. If a
required backend returns `status = "unavailable"`, policy classifies the result
as `hard_no` with `backend_unavailable` instead of a research-looking
`watchlist`.

`watchlist` is reserved for unsupported semantics or positive evidence that
misses paper-readiness gates.

### Paper-Candidate Artifacts Carry Search Pressure

Validation configs can now include `[search_pressure]` metadata:
`candidate_count`, `trial_count`, `parameter_search_space`, `selection_rule`,
and `split_ids`. These values are written into `overfit_controls` in validation
artifacts.

This does not add DSR/PBO/Monte Carlo statistics. That would be premature until
the upstream search loop supplies enough context consistently.

### Runner Data-Kind Row Contracts Are Visible

Runner evidence now includes `row_contract` with the configured data kind,
required row fields, missing required-field counts, timestamp-awareness status,
duplicate symbol/timestamp key counts, conditional funding-event field gaps,
freshness status, and `quant_data_feedback`.

This keeps data repair upstream in `quant-data` while making local failures and
schema drift machine-readable.

### Validation Scenario Config Is Typed

Validation no longer invents nested `SimpleNamespace` scenario configs for
backend runs. Matrix scenarios now produce a typed `ScenarioRunConfig` using the
same runner config models for data, fill model, and cost model.

This addresses the most concrete typing issue without rewriting validation.

### Public Consumer Surface Is Declared

The stable Python consumer API is `quant_strategies.runner.run_config` and
`quant_strategies.runner.RunResult`. The package root intentionally does not
re-export a facade. Downstream systems should import from the `runner`
subpackage and read structured artifacts, not private modules.

### Historical Plans And Researched Evidence Are Marked As Archives

`docs/superpowers/` now has an archive notice. The researched handoff package
has an `ARCHIVE.md` and explicit README/HANDOFF language stating that
family/variant artifacts and `legacy_selection` evidence are historical handoff
context, not active validation contracts or promotion evidence.

## Remaining Findings

### Statistical Honesty Still Depends On Upstream Inputs

Search-pressure metadata is now supported, but the repo still does not compute
deflated Sharpe, PBO, Monte Carlo robustness, capacity, or regime statistics.
That is the correct current scope. The label `paper_candidate` remains advisory;
all eligibility flags stay false and manual approval is required.

Add heavier statistics only after the upstream search loop provides stable
candidate counts, trial definitions, selection rules, parameter spaces, and split
identities for retained candidates.

### Data Freshness Is Reported As Not Evaluated

The new row contract records schema, timestamp, duplicate-key, and conditional
funding-event issues. It deliberately reports
`freshness_status = "not_evaluated"` because this repo does not own source
refresh/backfill policy.
Freshness SLAs should be defined upstream in `quant-data` before this repo gates
on them.

## Rejected Or Softened Claims

- "No public API" was overstated. The runner subpackage API is now explicitly
  documented as stable.
- Same-bar entry fills are not a current default bug. Config validation rejects
  close-price same-bar entries unless `allow_same_bar_close_fill = true`.
- Eligibility flag laundering is not a useful finding. The model sets advisory
  flags false in normal construction, and these flags are not a security
  boundary.
- Smoke returns, flat round-trip costs, close-based stops, and additive smoke
  totals are known smoke-engine limitations. They should stay clearly labeled,
  not turn this repo into a full portfolio engine.
- `results/` versus `validation_results/` is not material; both are configured
  ignored artifact roots.

## Current Priority Order

1. Keep validation TOML + `strategy.py` as the only active validation input.
2. Keep `researched/` frozen as upstream archive context only.
3. Keep the shared runner/validation execution boundary small and avoid growing
   validation-specific loader or data-loading paths.
4. Add heavier statistical controls only when upstream search-pressure data is
   complete enough to support them honestly.
5. Push data freshness/backfill/source joining requirements upstream to
   `quant-data`; keep this repo's row-contract feedback explicit.

## Verification Performed

- Re-checked review claims against current source, tests, README, consumer docs,
  and researched artifacts.
- Confirmed active validation no longer has `research_manifest` logic.
- Confirmed hidden-lookahead, evidence-quality, and failure-detail tests exist.
- Confirmed public runner API is documented at `quant_strategies.runner`.
- Confirmed runner and validation share the internal execution boundary.
- Confirmed the validation-specific strategy-loader wrapper was removed.
