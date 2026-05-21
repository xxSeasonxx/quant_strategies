## Context

The current runner has a clean module split, but the readiness review found a
trust gap between the intended research workflow and what the repository can
prove today.

Current flow:

```text
config path
  -> parse TOML
  -> create result dir
  -> copy config and strategy snapshot
  -> load data
  -> import strategy
  -> generate signals
  -> build engine request
  -> run engine
  -> write success artifacts
```

The main weaknesses are root-level rather than feature-level:

- documented curated configs are missing from the working tree
- relative config paths are resolved from the caller's cwd
- artifacts preserve engine bars, not the raw rows seen by the strategy
- failures usually write only `notes.md`
- timing safety depends on convention rather than explicit runner rules
- strategy provenance is required by agent instructions but not reflected in
  current strategy docstrings

## Goals / Non-Goals

**Goals:**

- Make documented CLI/API examples runnable from the current repository state.
- Make `run_config()` stable for downstream callers that pass `repo_root`.
- Preserve raw strategy input rows in both inspectable and type-faithful forms.
- Keep engine input separate from strategy input.
- Write useful artifacts as each run stage completes.
- Make same-bar close-derived fills fail closed by default.
- Keep the runner small and explicit.

**Non-Goals:**

- No strategy registry.
- No autonomous research loop.
- No live-data CI dependency.
- No full dependency/version manifest in this change.
- No CPCV, PBO, DSR, walk-forward, or broader validation framework.
- No wheel-install workflow change unless later needed.
- No runtime ban on scratch configs outside `runs/`.

## Decisions

### 1. Resolve Relative Config Paths Against Repo Root

`run_config("runs/demo.toml", repo_root=repo)` should work regardless of the
process cwd. The config loader will resolve relative config paths against the
effective repo root before reading and copying the config.

Alternative considered: require callers to pass absolute paths. That is simpler
internally but makes the public API brittle for `quant_autoresearch` and other
automation.

### 2. Restore Curated Configs Without Enforcing a Runtime Config Directory

Committed curated configs belong under `runs/`, and tests should verify they
parse. The runner should still allow scratch configs elsewhere when explicitly
called by tests or experiments.

Alternative considered: reject configs outside `runs/`. That is stricter but
adds friction without solving the root trust problem. The trust problem is
whether committed configs are present and valid.

### 3. Use a Small Honest Artifact Contract

Successful runs will write:

```text
config.toml
strategy_snapshot.py
strategy_input_rows.csv
strategy_input_rows.jsonl
signals.csv
engine_request.json
summary.json
notes.md
evidence.json        when engine evidence is available
```

`strategy_input_rows.csv` is the human-readable audit record for what the
strategy saw. `strategy_input_rows.jsonl` is the type-faithful audit record for
datetimes, booleans, nulls, funding fields, and quote fields.
`engine_request.json` is the audit record for what `quant_engine` evaluated.
`summary.json` is the machine-readable result. `notes.md` is human-readable.

Alternative considered: keep `bars.csv`, `screen_summary.json`, and
`validate_summary.json`. That preserves old names but keeps ambiguity and empty
summary files. This change should favor clarity over backward compatibility
because the project is not ready for stable external artifact consumers yet.

### 4. Write Artifacts By Stage

The runner will write available artifacts as soon as each stage completes:

```text
config parsed          -> config.toml, strategy_snapshot.py
data loaded            -> strategy_input_rows.csv, strategy_input_rows.jsonl
signals generated      -> signals.csv
request built          -> engine_request.json
engine completed       -> summary.json, notes.md, optional evidence.json
failure at any stage   -> summary.json, notes.md, plus prior stage artifacts
```

This avoids the current pattern where pre-engine failures lose useful evidence.

Alternative considered: write all artifacts at the end only. That is simpler
but undermines debugging and research auditability.

### 5. Use A Tiny Stable Summary Schema

`summary.json` should be intentionally small and stable. It is the downstream
machine contract; rich engine details stay in `evidence.json`.

The initial schema is:

```json
{
  "strategy_id": "simple_momentum_spy_daily",
  "mode": "validate",
  "success": false,
  "status": "failed",
  "stage": "request_build",
  "message": "exit fill is outside available bars: SPY",
  "artifacts": [
    "config.toml",
    "strategy_snapshot.py",
    "strategy_input_rows.csv",
    "strategy_input_rows.jsonl",
    "signals.csv",
    "summary.json",
    "notes.md"
  ],
  "engine": {
    "passed": null,
    "trade_count": null
  }
}
```

Alternative considered: leave summary shape to the implementer. That keeps the
first patch slightly smaller, but it recreates the trust gap for automation.

### 6. Keep Timing Safety Conservative

Until the data boundary provides a consistent `available_at` contract, the
runner should not allow same-bar fills for close-derived strategy signals.
The first implementation will reject `entry_lag_bars = 0` for close fills unless
the run config explicitly sets `fill_model.allow_same_bar_close_fill = true`.

This is intentionally blunt. It prevents the most common leakage mode without
building a larger event-time model prematurely.

Alternative considered: add a full availability-time system now. That is the
right long-term model only if `quant_data` consistently exposes availability
metadata. It is too broad for this readiness change.

### 7. Load Strategy Before Data

After config validation and artifact initialization, the runner should import
the strategy before loading data. A broken strategy file should fail before a
database or data-readiness issue can mask the real problem.

Alternative considered: keep loading data first. That avoids importing broken
strategy files when data is unavailable, but it makes the basic authoring loop
worse and contradicts the existing design document.

### 8. Keep Artifact Code Small

Use focused helper functions in `artifacts.py` rather than a new artifact model
or a large inline block in `run_config()`:

```text
write_strategy_input_rows()
write_jsonl()
write_engine_request()
write_summary()
```

The root problem is artifact clarity, not a need for a new artifact framework.

Alternative considered: introduce a dataclass or registry for artifact writers.
That would be cleaner only after multiple independent artifact producers exist.

### 9. Provenance Is Documentation First, Lint Later

This change should update strategy docstrings to include exact required section
headings. The test should check headings only, not parse semantic quality.

Required headings:

```text
Source / provenance:
Market rationale:
Required observables:
Signal rule:
Assumptions:
Falsifier:
```

Alternative considered: introduce a complex strategy metadata parser. That
would be overbuilt for the current flat-file strategy library.

## What Already Exists

- `run_config()` already centralizes config parsing, data loading, strategy
  execution, engine request construction, and artifact writing. The change
  should refactor this existing flow rather than create a parallel runner.
- `artifacts.py` already owns result directories, snapshots, CSV writing, and
  notes. The change should extend this module with small helpers.
- `engine_runner.py` already strips non-engine fields while building
  `quant_engine` requests. The change should preserve that boundary and expose
  it through `engine_request.json`.
- Existing tests cover many validation and request-building paths. The change
  should add missing edge tests, not replace the test structure.

## NOT In Scope

- Strategy registry or discovery framework: not needed for one explicit config
  at a time.
- Autonomous research loop: belongs in `quant_autoresearch`, consuming
  `run_config()`.
- Full event-time availability model: requires upstream `quant_data`
  availability metadata.
- Broad statistical validation framework: useful later, but not required to
  make runner artifacts honest.
- Dependency/version manifest: valuable for reproducibility, but can follow
  after the runner artifact contract is stable.

## Failure Modes To Cover

```text
config path -> parse -> result dir -> strategy import -> data load
    -> raw input artifacts -> signals -> signal artifact
    -> engine request -> engine artifact -> engine run -> summary/notes
```

- Config path cannot be read: no result directory, error identifies the resolved
  attempted path.
- Strategy import fails: result directory contains config, snapshot when
  possible, `summary.json`, and `notes.md`; no data loader is called.
- Data load fails: result directory contains config, strategy snapshot,
  `summary.json`, and `notes.md`; no signal generation occurs.
- Signal generation fails: prior artifacts remain and summary stage is
  `signal_generation`.
- Request build fails: raw input artifacts and `signals.csv` remain, summary
  stage is `request_build`.
- Engine evaluation fails: prior artifacts remain, summary stage is
  `engine_evaluation`.

## Parallelization Strategy

| Step | Modules touched | Depends on |
|------|-----------------|------------|
| Config readiness and timing validation | `src/quant_strategies/runner/`, `tests/` | - |
| Staged artifact contract | `src/quant_strategies/runner/`, `tests/` | - |
| Strategy docstring contract | `tested/`, `untested/`, `tests/` | - |
| Docs and curated configs | `README.md`, `PRODUCT_REQUIREMENTS.md`, `runs/` | artifact contract decisions |

Lane A: config readiness and timing validation.

Lane B: staged artifact contract.

Lane C: strategy docstrings.

Lane D: docs and curated configs after A and B land.

Conflict flag: Lanes A and B both touch `src/quant_strategies/runner/`, so they
can be parallel only with clear file ownership. Otherwise keep them sequential.

## Risks / Trade-offs

- Artifact filename changes may break ad hoc consumers -> mark the change as
  breaking and update README/product requirements in the same change.
- Rejecting `entry_lag_bars = 0` for close fills by default may block legitimate
  same-bar strategies -> allow only explicit opt-in and keep the causal burden
  visible in config.
- Writing both CSV and JSONL creates one extra file -> acceptable because the
  files serve different users: humans inspect CSV, automation consumes JSONL.
- A single `summary.json` may omit rich engine details -> keep `evidence.json`
  when engine evidence exists and treat `summary.json` as the stable overview.
- Restored curated configs may still fail on live data availability -> committed
  config tests should parse configs without requiring live data; live smoke can
  remain manual until data readiness is stable.
