## Context

`quant_strategies` already has the right high-level boundaries: strategy files
stay pure, data comes from public `quant_data` loaders, evaluation goes through
the internal evaluator, and each run writes inspectable artifacts. The readiness
review found that the remaining risk is not a missing framework. It is that
generated artifacts can imply a stronger conclusion than they actually support.

The root causes are:

- screen-mode completion is labeled like a strategy pass;
- the FX residual strategy emits a decision timestamp that adds one unintended
  bar before the configured entry lag;
- artifacts do not capture the basic code, dependency, and data identity needed
  to inspect a result later;
- funding-based crypto strategies need supplied funding events to reach
  the internal evaluator so evidence can distinguish price return, funding
  return, and net return.

## Goals / Non-Goals

**Goals:**

- Make runner summaries distinguish runner completion, screen evidence, and
  validation pass/fail.
- Correct the FX residual decision-time/fill-lag mismatch with focused tests.
- Add minimal run and data manifests using metadata already available from the
  repo, installed packages, generated artifacts, and loaded rows.
- Pass crypto-perp funding events into the engine request and label funding
  strategy evidence as funding-aware.

**Non-Goals:**

- Do not build a promotion workflow, strategy registry, or autonomous research
  system.
- Do not implement portfolio accounting, margin, or capital constraints.
- Do not change `quant_data` APIs.
- Do not make generated `results/` directories tracked by default.

## Decisions

### 1. Keep screen mode as completion evidence, not pass evidence

For `mode = "screen"`, the runner will treat successful engine execution as a
completed screen. `summary.status` should be `screened`, and `summary.engine`
should not claim `passed: true` unless explicit screen gates exist. Validation
mode remains the only path that can produce validation pass/fail status.

Alternative considered: make `screen` fail when gross or net return is
negative. That would silently introduce validation gates into a mode whose
purpose is lower-level inspection. Explicit status semantics are simpler and
less misleading.

### 2. Add minimal manifests instead of a provenance system

`summary.json` already has a stable top-level schema. Keep that schema stable
and add separate `run_manifest.json` and `data_manifest.json` files. The summary
artifact list will include them when present.

The first version should capture only what Season needs to tell whether two
runs used the same code and rows: git identity when available, Python/package
versions, hashes for the config/strategy/input/request artifacts, row counts,
and timestamp ranges. Do not add catalog joins, archival workflows, or upstream
snapshot APIs in this change.

Alternative considered: build a full provenance layer with catalog revisions,
availability enforcement, publication workflows, and archival semantics. That is
more than the current goal requires and would delay making the project usable.

### 3. Preserve available metadata, but do not enforce a new timing model

`quant_data` loaders already return useful fields for some datasets, including
`available_at`, ingestion timestamps, and joined refresh timestamps. The runner
should preserve these fields in raw inputs and optionally summarize coverage in
the data manifest. Missing metadata should be reported as absent, not fabricated.

Alternative considered: enforce `available_at <= decision_time` generally. That
is correct long term, but it needs strategy-level observable declarations. For
this change, preserve metadata and fix the observed timing bug.

### 4. Correct strategy timing at the strategy/config boundary

The FX residual strategy should emit the timestamp at which the decision is
made from completed observables, then rely on the configured fill lag for entry.
The implementation should add a direct test for residual event time, signal
decision time, engine entry time, and exit time.

Alternative considered: document the current two-bar delay. That would preserve
behavior but keep a mismatch between the strategy rationale and smoke config.

### 5. Keep funding accounting explicit and narrow

The internal evaluator accepts funding event fields already present in loaded
rows and reports `funding_return` separately from price `gross_return`. The
runner passes those fields through and labels crypto-perp funding evidence as
funding-aware. The accounting rule stays narrow: positive funding is paid by
longs and received by shorts for events inside the engine-held interval.

Alternative considered: implement a broader derivative accounting layer with
contract multipliers, margin, and portfolio constraints. That would widen the
change beyond the current evidence-semantics problem.

## Risks / Trade-offs

- Existing automation may expect `screen` summaries to say `passed`.
  Mitigation: keep `success` as runner-completion success for screen mode, but
  change `status` and `engine.passed` to remove the false research implication.
- Manifest fields can be incomplete when upstream rows lack metadata.
  Mitigation: keep manifest fields minimal and hash the actual raw input
  artifact instead of fabricating source metadata.
- Git and package-version capture can fail outside a normal checkout.
  Mitigation: make manifest capture best-effort and include errors as manifest
  fields rather than failing an otherwise valid run.
- The FX timing fix changes generated signals.
  Mitigation: update tests and run configs together, and document the behavioral
  correction in notes/docs.
