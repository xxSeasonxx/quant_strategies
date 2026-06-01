# Open Foundation TODOs

This file is the current implementation handoff for the foundation finalization
work. Do not restart a broad foundation review before using it. The current
product target and review disposition live in:

- `PRD.md`
- `docs/reviews/2026-05-30-foundation-finalization-plan.md`
- `docs/research-process.md`

If this file and the 2026-05-30 review finalization note differ on PR order or
current target vocabulary, follow this file and `PRD.md`. The review note is
kept as rationale/history plus a current addendum, not as the detailed task list.

The closeout goal is not to make `quant_strategies` perfect. The goal is to make
the research process simple enough to use and honest enough to trust:

```text
quick run      -> diagnose one strategy version and decide whether to keep iterating
validation run -> advisory triage for a retained candidate
```

## Status

- PR 0 is complete as of 2026-05-31. The hard vocabulary cutover was
  implemented with no compatibility aliases, active-surface legacy grep clean,
  full suite passing, and code review completed.
- PR 1 is complete as of 2026-05-31. `diagnostic` is now the default quick-run
  artifact profile, `diagnostics.json` is bounded and schema-whitelisted, sample
  winner/loser counts are configurable in TOML, full replay artifacts remain
  full-profile only, full suite passed on `main`, and code review feedback was
  implemented.
- PR 2 is complete as of 2026-05-31. Runner outputs now expose
  `replayable_from_artifacts` as derived metadata, active output no longer emits
  the legacy replayability field or retired replayability values, compact profiles remain
  non-replayable, full profile remains replayable from emitted artifacts, and
  implementation/docs/tests were updated. Final verification is handled by the
  implementation closeout.
- Next open item: PR 3, Return Surface Honesty And Naming Cleanup.

## PR 0: Project-Wide Research Vocabulary Cleanup (Complete)

**Goal:** remove the engineering term `smoke` from the active project surface and
replace it with quant-research vocabulary that says what the system actually
returns.

**Why this matters:** `smoke` is inherited engineering jargon. It makes quick
runs feel like an internal CI concept instead of a research artifact. The
foundation should speak in terms of quick-run evidence, diagnostic metrics,
trade results, and quick checks.

**Completion note:** implemented as a hard cutover. Active docs/code/tests/configs
use `trade_result`, `quick_check_*`, `quick_run_diagnostic`, and
`execution_kernel`; evidence schema was bumped to v4; `tests/test_readme_contract.py`
was removed by explicit direction.

### Target Vocabulary

Use this mapping unless implementation details force a narrower transitional
alias:

| Existing term | Target term |
| --- | --- |
| `smoke evidence` | `quick-run evidence` |
| `smoke metrics` | `diagnostic metrics` |
| `smoke gates` | `quick checks` |
| `smoke_score` | `trade_result` |
| existing metric paths under `smoke_score.*` | corresponding metric paths under `trade_result.*` |
| `SmokeScore` | `TradeResult` |
| `smoke_score_metric_semantics` | `trade_result_metric_semantics` |
| `runner_smoke` | `quick_run_diagnostic` |
| `smoke_engine` | `execution_kernel` or `trade_result_engine` |
| `smoke_passed` | `quick_check_passed` |
| `smoke_failed` | `quick_check_failed` |
| `smoke_unverified` | `quick_check_unverified` |

Avoid the word `score` for new product-facing names unless it is part of a
temporary compatibility alias. A quick run returns diagnostics and trade-result
metrics; it does not return an objective strategy ranking score.

### Tasks

- **Rename code-level models, fields, and helpers.**
  - `SmokeScore` -> `TradeResult`.
  - `smoke_score` result fields -> `trade_result`.
  - `smoke_score_metric_semantics` -> `trade_result_metric_semantics`.
  - Evidence classes / return models should use quick-run diagnostic language,
    not `runner_smoke`.
  - Engine/backend text should use execution-kernel or trade-result-engine
    language, not `smoke_engine`.

- **Rename quick-run assessment statuses.**
  - Replace `smoke_passed`, `smoke_failed`, and `smoke_unverified` with
    `quick_check_passed`, `quick_check_failed`, and
    `quick_check_unverified`.
  - Keep statuses clearly separate from validation verdicts.
  - Add temporary parsing aliases only if existing configs/artifacts need a
    short compatibility window. Canonical docs, tests, and new artifacts should
    use the new names.

- **Rename run configs and strategy IDs that include the old term.**
  - Example run config filenames ending in the old term should be renamed.
  - Default `strategy_id` values in strategy modules should use a neutral
    research/run suffix or no suffix.
  - Do not hand-edit frozen generated evidence just to rewrite history. If a
    frozen artifact must stay in the repo and project-wide grep cleanliness is
    required, regenerate it from current code or archive it outside the active
    contract.

- **Update docs and tests project-wide.**
  - `PRD.md`
  - `README.md`
  - `docs/runner.md`
  - `docs/validation.md`
  - `docs/quant-autoresearch-consumer.md`
  - `docs/research-process.md`
  - `src/quant_strategies/evidence_semantics.py`
  - `src/quant_strategies/engine/`
  - `src/quant_strategies/runner/`
  - `src/quant_strategies/validation/`
  - `tests/`
  - `runs/`
  - strategy modules under `untested/` or `tested/`

- **Keep metric honesty unchanged.**
  - The renamed metrics are still linear signed per-trade result sums, not NAV
    returns.
  - Renaming should not change PnL math, fill logic, causality checks, or
    validation policy.
  - `trade_result` should keep explicit units, bases, and semantics.

### Acceptance Criteria

- Active product/docs/code vocabulary no longer uses `smoke`.
- Quick-run metrics are exposed as `trade_result`.
- Quick-run classifications use `quick_check_*` names.
- Validation remains advisory and does not inherit quick-run classification
  language.
- Tests prove the renamed fields/statuses/artifacts are emitted.
- Any remaining old term is either:
  - in an intentionally documented compatibility alias with removal criteria, or
  - inside frozen generated evidence that will be re-created/archived before
    declaring repo-wide vocabulary cleanup complete.

### Suggested Verification

```bash
rg -n "smoke|Smoke" PRD.md README.md docs src tests runs examples untested tested AGENTS.md
conda run -n quant pytest tests/test_engine_screen.py tests/test_engine_validate_and_evidence.py tests/test_runner_api_cli.py tests/test_runner_artifact_profiles.py tests/test_validation_backends_and_policy.py tests/test_validation_engine_backend.py -q
```

Run a full suite before merging because this renames public result fields and
artifact keys:

```bash
conda run -n quant pytest -q
```

## PR 1: Diagnostic Quick Run Profile (Complete)

**Goal:** make the default one-strategy research loop return useful diagnostic
evidence without writing full audit/replay artifacts every time.

**Why this matters:** Season is usually working on one strategy at a time. In
that mode, "rank many candidates" is the wrong mental model. The quick run should
explain the current strategy version's behavior: where PnL came from, what costs
or funding did, whether trades cluster by symbol/window/direction, and which
trades are representative. Current `summary` is too thin for strategy
improvement, while `full` is too large and audit-shaped.

**Completion note:** implemented as a hard root-contract cutover with no legacy
compatibility shim. Omitted `artifact_profile` now defaults to `diagnostic`;
canonical configs explicitly use `artifact_profile = "diagnostic"` and
`diagnostic_sample_trades = 5`; `diagnostics.json` includes bounded aggregate
slices, cost/funding breakdown, concentration, holding-period stats, and
schema-whitelisted largest winner/loser samples. `summary` remains compact,
`full` remains audit/replay output, and diagnostic runs do not write full replay
artifacts.

### Tasks

- **Add a third quick-run artifact profile: `diagnostic`.**
  - Current profiles:
    - `summary`: compact aggregate evidence.
    - `full`: replay/audit artifacts, including full rows/decisions/request/evidence.
  - New profile:
    - `diagnostic`: compact explanation of strategy behavior.
  - Make `diagnostic` the default for active quick-run configs unless backwards
    compatibility makes that too disruptive. If changing the default is too
    risky, add it first and switch canonical configs/docs to `diagnostic`.

- **Keep diagnostic output intentionally small.**
  - Do not write all input rows.
  - Do not write full engine request unless full profile is requested.
  - Do not write every trade unless the trade count is below a small cap.
  - Prefer aggregated slices and bounded samples.

- **Add `diagnostics.json` for quick runs.**
  - Suggested top-level sections:
    - `strategy_id`
    - `artifact_profile = "diagnostic"`
    - `trade_count`
    - `trade_result`
    - `assessment_status`
    - `evidence_quality`
    - `by_symbol`
    - `by_direction`
    - `by_exit_reason`
    - `holding_period`
    - `concentration`
    - `cost_funding_breakdown`
    - `sample_trades`
  - Keep the schema flat and easy to inspect. Avoid a new analytics framework.

- **Minimum useful diagnostic aggregates.**
  - `by_symbol`: count, gross, funding, cost, net.
  - `by_direction`: long/short count and net.
  - `by_exit_reason`: count and net.
  - `holding_period`: min, median, max, average bars or elapsed time if available.
  - `concentration`:
    - top winner contribution;
    - top loser contribution;
    - top 5 winners net;
    - top 5 losers net.
  - `cost_funding_breakdown`:
    - gross;
    - funding;
    - cost;
    - net;
    - cost as fraction of absolute gross where meaningful.
  - `sample_trades`:
    - largest winners, capped;
    - largest losers, capped;
    - optionally first/last few trades.

- **Do not turn diagnostic into validation.**
  - It is still quick-run output.
  - It should reuse the same trade-result engine result.
  - It should not add windows/scenarios.
  - It should not introduce promotion/paper/live eligibility.

- **Update docs and tests.**
  - `src/quant_strategies/runner/config.py`
  - `src/quant_strategies/runner/artifact_profiles.py`
  - `src/quant_strategies/runner/artifacts.py` or a small new
    `runner/diagnostics.py`
  - `tests/test_runner_artifact_profiles.py`
  - `tests/test_runner_api_cli.py`
  - `docs/runner.md`
  - `docs/research-process.md`
  - `README.md`

### Acceptance Criteria

- Quick run supports `artifact_profile = "diagnostic"`.
- Diagnostic output gives enough information to improve one strategy version
  without reading every raw trade.
- Diagnostic output remains bounded in size.
- `summary` remains available for cheap compact runs.
- `full` remains available for audit/replay.
- Quick run still returns `RunResult`; diagnostic data lives in artifacts, not in
  the dataclass.

### Suggested Verification

```bash
conda run -n quant pytest tests/test_runner_artifact_profiles.py tests/test_runner_api_cli.py -q
```

Run the full suite before changing the default profile:

```bash
conda run -n quant pytest -q
```

## PR 2: Artifact Replayability Simplification

**Goal:** remove retired tier labels as product vocabulary and replace the extra
legacy replayability label with one derived replayability flag.

**Why this matters:** artifact profiles already answer the operational question:
compact output for everyday research versus full output for audit. A second
label pair adds vocabulary without adding a decision Season should make. The
only durable fact the system needs to expose is
whether the reported metrics can be replayed from the emitted artifacts alone.

**Completion note:** implemented as a hard public contract cutover. New runner
results and artifacts expose `replayable_from_artifacts` only: `summary` and
`diagnostic` derive `false`, while `full` derives `true`. No compatibility alias
or old replayability key remains in the active surface.

### Tasks

- **Replace legacy replayability labels with factual metadata.**
  - Remove or deprecate the legacy replayability field from public `RunResult` and
    artifact payloads.
  - Add `replayable_from_artifacts: bool` as derived metadata.
  - Suggested mapping:
    - `summary` -> `replayable_from_artifacts = false`
    - `diagnostic` -> `replayable_from_artifacts = false` unless it writes the
      full replay chain
    - `full` -> `replayable_from_artifacts = true`
  - Do not ask the user to choose replayability metadata directly.

- **Remove stale replayability strings from active output.**
  - Stop emitting the retired replayability values in new runner artifacts.
  - Remove the profile-to-replayability-label helper or replace it with a simple replayability
    helper.
  - Update manifests, summaries, profile artifacts, docs, and tests to use
    `replayable_from_artifacts`.

- **Keep the artifact profiles.**
  - `summary`: compact aggregate evidence.
  - `diagnostic`: bounded behavior diagnostics for active strategy improvement.
  - `full`: rows, decisions, engine request, evidence, and any other files
    needed to audit/replay reported runner metrics.
  - Artifact profile remains a reference/config detail, not a daily research
    workflow concept.

- **Keep validation replayability explicit.**
  - Validation already has `verdict_replayable` / `verdict_replay_basis`.
  - Do not introduce a second validation replayability label.
  - If names are aligned, prefer factual replayability fields over tier labels.

- **Update docs and tests.**
  - `PRD.md`
  - `README.md`
  - `docs/runner.md`
  - `docs/research-process.md`
  - `docs/quant-autoresearch-consumer.md`
  - `src/quant_strategies/evidence_semantics.py`
  - `src/quant_strategies/runner/__init__.py`
  - `src/quant_strategies/runner/artifacts.py`
  - `src/quant_strategies/runner/artifact_profiles.py`
  - `tests/test_runner_artifact_profiles.py`
  - `tests/test_runner_api_cli.py`

### Acceptance Criteria

- New runner outputs no longer contain retired tier values.
- Public result/artifact metadata exposes `replayable_from_artifacts`.
- `summary` and `diagnostic` outputs remain compact by default.
- `full` output remains sufficient to trace reported runner metrics from
  artifacts alone.
- User-facing docs explain only:
  - quick run returns compact/diagnostic evidence by default;
  - full output is available when audit replay is needed.

### Suggested Verification

Implementation closeout also runs the active retired-vocabulary grep from the
implementation plan.

```bash
conda run -n quant pytest tests/test_runner_artifact_profiles.py tests/test_runner_api_cli.py -q
```

Run the full suite before merging because this changes public result and artifact
metadata:

```bash
conda run -n quant pytest -q
```

## PR 3: Return Surface Honesty And Naming Cleanup

**Status:** complete. Focused PR3 tests and the full suite pass after the
hard cutover.

**Implemented contract:**

- Runner configs use `[output] quick_checks = true | false`, defaulting to
  `false`; the previous output-mode key is rejected.
- Runner summaries and auxiliary artifacts expose `quick_checks`, not a run mode.
  Diagnostic-only runs report `assessment_status = "diagnostics_complete"`, and
  successful runner summaries use `status = "completed"`.
- Validation uses `mechanical_complete` as the weak mechanical verdict. It remains
  advisory only and does not imply promotion, paper trading, or live eligibility.
- Validation writes `cost_fill_sensitivity.json` for cost/fill scenario evidence.
- Validation scenario configs vary cost/fill/data settings only; parameter-axis
  decision re-generation is intentionally not part of PR 3.
- Backend summaries, sensitivity artifacts, and manifests no longer emit dead
  decision-generation metadata.

**Verification before closeout:**

```bash
conda run -n quant pytest tests/test_runner_config.py tests/test_runner_api_cli.py tests/test_validation_backends_and_policy.py tests/test_validation_runner.py tests/test_validation_manifest.py tests/test_validation_config.py tests/test_validation_matrix.py -q
# Run the PR3 literal leak check from the implementation plan.
conda run -n quant pytest -q
```
- Validation remains advisory: no paper/live/promotion eligibility is introduced.

### Suggested Verification

```bash
conda run -n quant pytest tests/test_runner_config.py tests/test_runner_api_cli.py tests/test_validation_backends_and_policy.py tests/test_validation_runner.py tests/test_validation_manifest.py -q
```

Run the full suite before merging if labels/artifact filenames change broadly:

```bash
conda run -n quant pytest -q
```

## PR 4: Research Workflow Simplification

**Goal:** make the daily research process feel like two actions, not a vocabulary
exam.

**Why this matters:** The foundation can be technically correct and still fail
Season's workflow if the researcher must keep too many terms in working memory.
The public on-ramp should be "quick run" and "validation run"; detailed terms
belong in reference docs and artifacts.

### Tasks

- **Promote `docs/research-process.md` as the operator-level process doc.**
  - Link it from `README.md` under documentation or usage.
  - Keep it short and top-down. It should explain what to do, what each result
    means, and what not to infer.

- **Simplify the README on-ramp.**
  - Keep the two-step language:
    - quick run: diagnose/compare/discard/retain
    - validation run: advisory triage for retained candidates
  - Move detailed terms to reference docs:
    - `screen` / `gate`
    - artifact profile internals
    - replayability metadata
    - `row_contract`
    - `agreement_oracle`
    - `metric_semantics`
    - replay flags
    - backend artifact names

- **Add one canonical validation-ready example.**
  - Strategy defines both:
    - `generate_decisions(rows, params)`
    - `validate_params(params)`
  - Include:
    - quick-run config
    - validation config with at least two windows
    - explicit `[search_pressure]`
    - minimal readiness fields
  - The example should be runnable in tests without live market infrastructure,
    or clearly marked as a template if it requires `quant_data`.

- **Clarify the retained-candidate checklist.**
  - Before validation:
    - pure strategy
    - real `validate_params`
    - validation windows
    - search-pressure disclosure
    - output directory under generated artifacts
    - human willingness to inspect trades

- **Optionally reduce visible verdict labels.**
  - If PR 3 renames `mechanical_complete`, consider making the operator-facing set:
    - `hard_no`
    - `watchlist`
    - `review_candidate`
  - Internal labels can remain if needed, but the daily process should not force
    a researcher to understand every intermediate state.

### Acceptance Criteria

- A new agent or human can understand the process from `README.md` plus
  `docs/research-process.md` without reading the full runner/validation
  references.
- The process doc says clearly:
  - quick run is not validation;
  - validation is not market proof;
  - promotion is outside this foundation.
- The canonical example demonstrates the handoff from quick run to validation.
- Reference docs still preserve precise details for debugging and artifact audit.

### Suggested Verification

```bash
conda run -n quant pytest tests/test_simple_momentum.py tests/test_validation_config.py tests/test_validation_runner.py -q
```

Run a docs grep before merging:

```bash
rg -n "quick run|validation run|mechanical_complete|cost_fill_sensitivity|cost_fill_sensitivity|replayable_from_artifacts" README.md docs tests
```

## PR 5: Foundation Lock And Review Hygiene

**Goal:** prevent future review churn from re-raising known accepted debt as new
issues.

**Why this matters:** Repeated blind reviews have been useful, but the project is
now past that phase. Future reviews should be honest and disposition-aware:
raise regressions and new issues, but do not rediscover every known tradeoff.

### Tasks

- **Create `FOUNDATION_LOCK.md` or equivalent.**
  - State locked contracts:
    - two main workflows: quick run and validation run;
    - strategies are flat pure files;
    - validation requires `validate_params`;
    - engine computes linear signed per-trade result, not NAV;
    - validation is advisory and never promotion authority;
    - `quant_data` owns data acquisition/materialization;
    - generated artifacts are evidence, not truth.
  - State accepted debt:
    - large facade modules are not immediate blockers;
    - full NAV/portfolio accounting is deferred;
    - VectorBT agreement is single-trade/optional only;
    - runtime sandboxing is deferred unless strategy code becomes untrusted.

- **Update review protocol.**
  - `docs/reviews/README.md` already says future reviews should be
    disposition-aware delta reviews by default. Expand if needed.
  - Future reviews should classify findings as:
    - `new`
    - `regression`
    - `fixed`
    - `accepted_debt`
    - `deferred_until_trigger`
    - `false_positive`
    - `superseded`

- **Keep process-artifact assertions out of broad contract tests.**
  - Do not recreate the deleted README contract test file just to encode review
    artifact location rules.
  - Root-level `review-*.md` files should remain working notes only; archive or
    delete them before completion.

- **Optional cleanup after PRs 1-2 only if still valuable.**
  - Move the shared execution kernel to a neutral package if the validation
    -> runner dependency continues to confuse implementation.
  - Split validation artifact writing/payload shaping out of
    `validation/__init__.py` if the module still blocks safe changes.
  - Trim `extended_ontology.py` to explicit rejection markers plus a design note
    if it continues to look like executable capability.

### Acceptance Criteria

- A future session can read `FOUNDATION_LOCK.md`,
  `docs/reviews/2026-05-30-foundation-finalization-plan.md`, and this file to
  know what to implement and what not to reopen.
- Broad foundation reviews are no longer the default.
- Known accepted debt is not reported as a new P1 unless it regressed or a
  documented trigger occurred.

### Suggested Verification

```bash
conda run -n quant pytest -q
```

## Deferred Residuals

- **F19 residual (low priority):** artifact I/O failures on the *mid-pipeline
  success-path* writes — per-window rows, per-scenario decision/trade-ledger
  records, and data manifests written while a run is progressing — still raise to
  a direct API caller (the CLI backstops them as a clean exit `1`). The
  result-directory creation, final artifact write, and all `_failure_result`
  paths are routed to structured `failure_stage` results. Closing the residual
  means wrapping those loop writes (or adding an outer guard); deferred as
  low-frequency (disk-full mid-run).

- **VectorBT Pro agreement residual (low priority):** Phase 3 keeps the optional
  single-trade agreement check. It should not be treated as multi-trade
  validation confidence unless it is rebuilt around trade-ledger or path-level
  comparison.

- **Validation source output residual (low priority):** validation configs
  still anchor `output.results_dir` beside the config so candidate-local
  workspaces keep working. Revisit rejecting outputs under source directories
  only if validation config paths are redesigned.

Strict suppression-lookahead replay is the default for both the runner quick-run
and the validation run; see `causality.check_hidden_lookahead` and the
`hidden_lookahead_suppression_detected` regression tests.
