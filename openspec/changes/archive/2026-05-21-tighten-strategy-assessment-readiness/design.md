## Context

The readiness review found that the runner is structurally sound but can still
let weak evidence look stronger than it is. The current flow already has the
right core pieces: config validation, strategy import before data loading, raw
input artifacts, evaluator evidence, summaries, and run manifests. The gap is
mostly semantic and contract-level:

- `RunResult.success` and `summary.success` are easy for downstream automation to
  mistake for research promotion evidence.
- early failures after result-directory creation do not always receive a
  `run_manifest.json`.
- strategy purity is documented but not enforced by tests.
- availability metadata is preserved but not checked against emitted signal
  decision rows.
- CLI relative-path behavior is clear for editable checkout use but weak for
  installed-package or non-cwd usage.

The implementation should tighten these contracts inside the existing runner.
No separate harness, no new dependency, and no broad evaluator rewrite.

Current execution flow:

```text
TOML config
  |
  v
load_config -> load_strategy -> load_data -> generate_signals
                                      |              |
                                      v              v
                              raw input artifacts  signals.csv
                                                     |
                                                     v
                                      data readiness checks
                                                     |
                                                     v
                                      build_request -> evaluate_request
                                                     |
                                                     v
                                        notes + evidence + summary
```

## Goals / Non-Goals

**Goals:**

- Make runner completion, smoke assessment, and promotion eligibility explicit
  in `RunResult` and `summary.json`.
- Ensure every run that creates a result directory has a best-effort
  `run_manifest.json`, including early failures.
- Add `quant-strategies run --repo-root <path>` and document when to use it.
- Add signal-level data-readiness checks for decision rows when availability or
  ingestion metadata is present.
- Enforce flat, pure strategy modules with static tests over `tested/` and
  `untested/`.
- Document that current screen/validate outputs are smoke evidence only, and
  promotion requires a separate research checklist.

**Non-Goals:**

- Do not build a full research promotion engine in this change.
- Do not replace `quant_data` loaders or add data materialization behavior here.
- Do not change strategy APIs away from `generate_signals(bars, params)`.
- Do not refactor the internal evaluator fillability checks unless required by
  the above contracts.
- Do not package `runs/`, `tested/`, or `untested/` into the wheel in this
  change; the CLI remains a repository-checkout workflow with an explicit root.

## Decisions

### 1. Add explicit assessment fields instead of renaming `success`

Keep the existing `success` field for compatibility, but add explicit fields:

- `run_completed`: true when runner execution reached a terminal stage and wrote
  terminal artifacts for that run.
- `assessment_status`: one of `runner_failed`, `screened`, `smoke_passed`, or
  `smoke_failed`.
- `promotion_eligible`: always false for current runner outputs.

Alternative considered: change `success` to mean only operational completion.
That would be cleaner but more disruptive to existing callers and CLI tests. The
smallest safe fix is to preserve `success` and add fields that downstream
automation can key on without guessing.

### 2. Centralize failure finalization

Pass `repo_root` into `_failure_result()` and have that function write
`notes.md`, `run_manifest.json`, and `summary.json` in one place. This removes
stage-dependent manifest behavior without adding another finalizer abstraction.

Alternative considered: write the manifest immediately after result-directory
initialization. That captures early identity but misses later artifacts unless
rewritten anyway. Centralizing failure finalization is simpler and keeps
manifest hashes tied to the artifacts available at the terminal stage.

### 3. Keep data-readiness checks lightweight and signal-scoped

Add a small runner helper that checks matching decision rows after signal
generation:

```text
rows + signals
  |
  v
for each signal:
  find rows where symbol == signal.symbol and timestamp == decision_time
  inspect availability fields:
    available_at
    bar_ingested_at
    quote_ingested_at
    funding_ingested_at
    joined_refreshed_at
  fail if any present value is after decision_time
```

This is intentionally not a full lineage engine. It catches the most direct
causal contradiction: a strategy emits a decision at a timestamp whose matching
row says the relevant data was not available yet.

Alternative considered: inspect every historical row that might have influenced
each signal. The runner cannot know strategy internals without a declared
observable lineage contract, so that would be both over-strict and still
incomplete.

### 4. Enforce purity with static tests, not runtime sandboxing

Add AST-based tests that fail when strategy modules import runner/engine/data
packages, use subprocess/network/file-writing primitives, or when strategy
directories contain nested Python strategy modules. Runtime sandboxing would be
heavier, less transparent, and outside the repo's current simple-test style.

### 5. CLI root stays explicit

Add `quant-strategies run --repo-root <path> <config>` and route it to
`run_config(..., repo_root=...)`. This solves installed-package and alternate-cwd
usage without changing config resolution rules for existing callers.

## Risks / Trade-offs

- `success` remains potentially ambiguous for old consumers -> Mitigation:
  document the new fields and add tests asserting `promotion_eligible = false`
  for screen and smoke validation outputs.
- Signal-scoped readiness checks do not prove all historical data was available
  -> Mitigation: document this as a direct decision-row guard, not full causal
  lineage; leave broader lineage as a future promotion requirement.
- Static purity tests can miss dynamic import tricks -> Mitigation: this repo is
  a research codebase with trusted strategy files; the tests catch accidental
  boundary violations, not malicious code.
- Adding summary keys changes exact summary-shape tests -> Mitigation: update
  the stable summary schema and test helper in the same change.

## Migration Plan

1. Add or update runner tests first for new summary fields, early failure
   manifests, CLI `--repo-root`, data-readiness rejection, and strategy purity.
2. Implement the smallest runner changes to satisfy those tests.
3. Update README and OpenSpec tasks/specs to match the new contract.
4. Run `conda run -n quant pytest`.
5. Smoke parse committed configs. Live data smoke runs remain optional because
   they depend on local `quant_data` state.

Rollback is straightforward: revert this change. It does not alter persisted
input data, external databases, or strategy source format.

## Open Questions

None for this change. Broader promotion criteria, such as out-of-sample splits,
drawdown limits, and sensitivity tests, should be designed separately after the
runner no longer confuses smoke evidence with promotion evidence.
