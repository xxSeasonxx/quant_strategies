# Phase 5 — P3 Auditability & Misuse Prevention (F16/F17/F18/F19)

## Status: COMPLETED

All four findings closed, on branch `phase5-p3-hardening` (one commit per
sub-step plus a follow-up and a review-fixes commit):

- **5a (F17)** purity lint extended to data-loading reads + best-effort docs + escape tests.
- **5b (F19)** artifact init/final/failure-path writes routed to structured `failure_stage`
  results; CLI `OSError` backstop. (Residual: mid-pipeline success-path writes — see `TODOS.md`.)
- **5c (F18)** validation requires `validate_params` (`hard_no`/`param_validation`); quick-run
  flags `param_contract` (`validated`/`unvalidated_passthrough`/`unknown`).
- **5d (F16)** engine per-trade ledger emitted per scenario (`backend_runs/trade_ledgers/*.jsonl`),
  hash-pinned; verdict `net_return` recomputable as `sum(trade.net_return)`; manifest
  `verdict_replayable`. Replay test asserts the multi-trade summation invariant.

A `/code-review` pass on the phase diff drove a follow-up commit: a multi-trade
replay test (the original was single-trade/tautological), guarded `_failure_result`
writes on both sides, a purity over-ban trim (`read_sql`/`read_table`), consumer-doc
failure-stage enumeration, and a shared `_write_scenario_jsonl` helper.

Suite green throughout; final `643 passed`. Pre-existing `ruff` F401s in unrelated
files (`extended_ontology.py`, two unrelated test files) were left untouched.

## Context

`review-claude.md` §15 item #9 (priority **P3**) bundles the last four open
findings. P0–P2 are done (Phases 1–4c): one PnL contract (F1), strict
suppression-replay (F3), funding-aware net (F2), workflow de-convolution (F6),
god-module/seam subtraction (F9–F12). What remains is **auditability + misuse
prevention** — the gaps that let *silent* wrongness through a trust foundation:

- **F16** the validation verdict number can't be recomputed from artifacts.
- **F17** the purity lint misses obvious data-loading escapes.
- **F18** params with no `validate_params` pass through as a raw dict — typos vanish.
- **F19** artifact I/O errors crash the CLI instead of becoming structured results.

**Re-audit vs the review's snapshot (these changed the work):**

- **F16 is now cheap, not the biggest item.** Post-F1 the *engine* is the verdict
  kernel; vbt is only an agreement oracle. `engine.screen()` already returns a full
  typed per-trade ledger — `ScreeningResult.trades: tuple[Trade, ...]`
  (`engine/models.py:141-146`) — and the gated number is exactly
  `net_return = sum(t.net_return for t in trades)` (`engine/evaluation.py:112`).
  But `EngineBackend.run()` (`validation/engine_backend.py:51-60`) **discards
  `result.trades`**, keeping only 5 scalars. So F16 = *emit the trades that already
  exist*, plus a replay test. The review's "start with a vbt ledger" is obsolete.
- **F17/F18/F19 confirmed unchanged** and accurately described.

**Approved scope decisions:**
- **F16** → emit the engine per-trade ledger **in the validation run only** (bounded
  to the verdict path); runner full-profile mirror is an explicit non-goal here.
- **F18** → **require `validate_params` on the validation run** (fail-fast `hard_no`);
  quick-run still allows passthrough but flags it. Mostly non-breaking.
- **F17** → **extend the denylist** to close the data-loading escapes (root-cause:
  AGENTS.md forbids data loading) **and** document purity as best-effort lint **and**
  add tests.

**Goal:** Make the validation verdict arithmetic-replayable, close the purity
data-loading holes, gate schema-less strategies out of validation, and route
artifact I/O failures through the existing structured-failure path — small,
bounded, mostly-non-breaking changes. No new engines, no sandbox, no abstraction
layers.

## Conventions (binding, per AGENTS.md + phase-doc precedent)

- conda env `quant`: `conda run -n quant pytest -q` green after **each** sub-step; ruff clean.
- One commit per sub-step, after `/code-review` on its diff.
- Report changed-line counts at completion, separating **source / tests / docs**.
- **Doc-freshness is mandatory**: every sub-step that changes behavior, the artifact
  set, the consumer contract, or agent rules updates the relevant doc *in the same
  commit*. Primary docs: `README.md`, `AGENTS.md`, `docs/quant-autoresearch-consumer.md`.
- Order is least-coupled → most-coupled: **5a (purity) → 5b (I/O failures) →
  5c (param gate) → 5d (ledger)**. 5d touches the verdict path most and goes last.

---

## Sub-steps (each green; one commit after code review)

### 5a — F17: extend purity denylist + best-effort-lint docs + escape tests

**Root cause:** `decisions/purity.py` bans writes/`open`/network/`__import__` but not
reads. AGENTS.md says strategies must not load data; reads *are* data loading.

- `src/quant_strategies/decisions/purity.py`
  - Add to `BANNED_CALL_ATTRIBUTES`: `read_text`, `read_bytes`, and the common
    dataframe readers `read_csv`, `read_parquet`, `read_json`, `read_excel`,
    `read_feather`, `read_pickle`, `read_hdf`, `read_sql`, `read_table`. (Attribute-form
    bans are alias-proof — they catch `pd.read_csv(...)`, `pandas.read_csv(...)`, and
    `Path(...).read_text()` alike, matching how `write_text`/`read`-siblings are already
    handled.)
  - Add to `BANNED_MODULE_CALLS`: `("importlib", "*")` and `("urllib", "*")`. The
    existing `_import_aliases`/`_call_name` machinery already resolves
    `from importlib import import_module` and `import urllib.request`; the `"*"`
    (prefix) form is robust to the dotted-import alias quirk that an exact
    `("urllib.request","urlopen")` tuple would miss.
  - Keep it honest: a static AST denylist is **best-effort**, not exhaustive
    (`getattr`/computed access still escapes) and **not a sandbox**.
- **Pre-check (no committed strategy may trip the new bans):** the existing
  `tests/test_strategy_docstrings.py:87-92` already asserts every committed strategy
  (`tested/`, `untested/`, `researched/`, `examples/`) passes purity. Run the full
  suite; if a committed strategy now fails, it genuinely loads data — fix the
  strategy (or, if a false positive, narrow the ban). Do **not** weaken the ban to
  paper over a real violation.
- Tests — `tests/test_decision_strategy_loader.py` (extend the alias-aware block at
  lines 114-128): assert each escape is now caught — `Path("x").read_text()`,
  `import pandas as pd; pd.read_csv("x")`, `import importlib; importlib.import_module("os")`,
  `from urllib.request import urlopen; urlopen("...")`. Add one negative case proving a
  legit pandas *compute* call (e.g. `pd.DataFrame(...).rolling(3).mean()`) still passes.
- Docs (doc-freshness): add a "purity is best-effort static lint, not a runtime
  sandbox" caveat to the Strategy Contract section of `README.md` and a one-line note
  in `AGENTS.md`.

### 5b — F19: route artifact I/O failures through structured results

**Root cause:** the structured `failure_stage` mechanism exists
(`RunResult`/`ValidationRunResult.failure_stage`, `_failure_result`, exit-code mapping
in `cli.py:76-94`) but artifact init/write calls aren't wrapped, and the CLI only
catches `ValidationError`.

- `src/quant_strategies/validation/__init__.py`
  - The final `_write_validation_artifacts(...)` (lines 170-184) is **unguarded** —
    wrap in `try/except OSError` → return `_failure_result(..., failure_stage="artifact_write")`
    (verdict already computed; preserve the original exception text in the message).
  - The `artifact_initialization` block (lines 116-122) emits a stage event but does
    **not** route failures — wrap `create_validation_result_dir` +
    `_write_static_validation_artifacts` in `try/except OSError`. If the dir itself
    can't be created (`result_dir` is None), return a minimal `ValidationRunResult`
    directly (`result_dir=None`, `failure_stage="artifact_initialization"`) rather than
    attempting a failure-artifact write.
- `src/quant_strategies/runner/__init__.py`: wrap `create_result_dir` (line ~76) +
  `initialize_run_artifacts` (line ~77) and the later artifact writes the same way,
  returning the runner's structured failure result with
  `failure_stage="artifact_initialization"` / `"artifact_write"` (mirror the existing
  `RunResult(failure_stage=...)` construction used for other stages).
- `src/quant_strategies/runner/cli.py`: add a defense-in-depth backstop — also catch
  `OSError` around the `run_config` (lines 40-46) and `run_validation` (lines 57-65)
  call sites; print a clean one-line message and return exit 1 so a raw traceback
  never escapes. (Root-cause fix is the wrapping above; this is the safety net.)
- Exit codes need **no** table change: `_run_exit_code`/`_validation_exit_code`
  already map any non-data `failure_stage` to exit 1 — confirm `artifact_write` /
  `artifact_initialization` are **not** added to `_DATA_FAILURE_STAGES` (they're infra,
  not data, failures).
- Tests — extend `tests/test_validation_artifacts.py` (reuse its monkeypatch pattern,
  lines 23-76) and add a runner equivalent: monkeypatch a writer / `mkdir` to raise
  `PermissionError`; assert `run_validation`/`run_config` **return** a structured result
  with the expected `failure_stage` (not raise) and that `main([...])` returns exit 1
  (no traceback).
- Docs: add `artifact_write` to the failure-stage list in
  `docs/quant-autoresearch-consumer.md` (and README if it enumerates stages).

### 5c — F18: require `validate_params` on validation; flag passthrough on quick-run

**Root cause:** `validate_strategy_params` (`decisions/params.py:13-15`) silently
returns `dict(params)` when no validator exists; the shared `execute_strategy_run`
path can't distinguish "validated" from "passthrough", and validation imposes no
higher bar than quick-run.

- `src/quant_strategies/decisions/params.py`: change `validate_strategy_params` to
  report whether a validator ran and to enforce when required — e.g. signature
  `validate_strategy_params(generate_decisions, params, *, require_validator: bool = False)`
  returning `(validated: dict, had_validator: bool)`; when `require_validator and not
  had_validator` → raise `ValueError("strategy defines no validate_params; required for
  validation runs")`. Passthrough path is unchanged when not required.
- Thread the flag through the **neutral** `StrategyExecutionSpec` (added in Phase 4b,
  in `core/`): add `require_param_validator: bool`. Validation's `to_execution_spec`
  sets it `True`; the runner's adapter sets it `False`. `execute_strategy_run`
  (`runner/execution.py`, ~line 88) passes it into `validate_strategy_params` and on the
  required-but-absent case raises `StrategyExecutionError("param_validation", ...)` —
  the stage already exists (cf. `test_execute_strategy_run_maps_param_validation_failure`),
  so validation maps it to `hard_no` with no new wiring.
- Surface the quick-run marker: carry `had_validator` into `StrategyExecutionResult`
  and emit `param_contract: "validated" | "unvalidated_passthrough"` in the runner
  `summary_payload` (`runner/artifacts.py:339-367`) and the evidence warnings, so a
  schema-less quick-run is visibly exploratory. (Eligibility is already locked `False`,
  so this is honesty, not a new gate.)
- Tests:
  - `tests/test_runner_execution.py` — add the **missing** passthrough case (no
    validator → quick-run completes, `param_contract == "unvalidated_passthrough"`), and
    the required-but-absent case (→ `StrategyExecutionError("param_validation")`).
  - validation test — a schema-less strategy → `run_validation` returns `hard_no`,
    `failure_stage="param_validation"`.
- Docs: `README.md` Strategy Contract + `docs/quant-autoresearch-consumer.md` —
  `validate_params` is optional for quick-run (exploratory, flagged) but **required**
  for validation runs; document the `param_contract` field. `AGENTS.md` — add the rule.

### 5d — F16: emit the engine per-trade ledger in validation + replay test

**Root cause:** `EngineBackend.run()` throws away `result.trades`; no artifact lets a
human re-sum the gated `net_return`.

- `src/quant_strategies/validation/backends.py`: add a typed ledger to
  `BackendRunResult` (lines 151-158) — `trades: tuple[Trade, ...] = ()` (import `Trade`
  from `engine.models`). fake/vbt leave it empty; only the engine backend populates it.
- `src/quant_strategies/validation/engine_backend.py`: in `run()` (lines 51-65) pass
  `trades=result.trades` into the returned `BackendRunResult` (the data is already in
  hand — a one-line change).
- Per-scenario ledger file: mirror the existing
  `ScenarioBackendRunResult.decision_records_path/decision_records_sha256` precedent
  (`backends.py:172-173`) — add `trade_ledger_path: str | None` and
  `trade_ledger_sha256: str | None`; write the ledger to
  `backend_runs/trade_ledgers/<scenario_id>.jsonl` where the scenario result is built
  (in `validation/__init__.py`, alongside `_write_scenario_decision_records`).
- `src/quant_strategies/validation/artifacts.py`: add a `write_trade_ledger(...)`
  writer reusing the canonical-JSONL + sha256 helper already used for decision/window
  records (each line = `trade.model_dump(mode="json")`).
- Manifest: include the ledger paths + sha256 in `validation_manifest.json` (the
  manifest builder inside `_write_validation_artifacts`) so the ledger is hash-pinned
  like every other artifact.
- Replayability marker (honest, not a new tier): add `verdict_replayable: true` /
  `verdict_replay_basis: "engine_trade_ledger"` to the validation manifest (or
  `validation_evidence_semantics()` in `evidence_semantics.py:103-110`) stating the
  gated `net_return` is recomputable from the emitted ledger; note vbt agreement-oracle
  ledgers remain out of scope.
- **Acceptance test (the F16 gate)** — new `tests/test_validation_replay.py` (or extend
  `test_validation_artifacts.py`): run a tiny validation, read the emitted ledger
  JSONL, assert `sum(t.net_return) == backend net_return` within `1e-9` **and**
  `len(ledger) == trade_count` for each scenario.
- Docs: rewrite the `README.md:344-346` admission ("…ledgers … not emitted yet") to
  state the engine verdict trade ledger **is** now emitted per scenario and the verdict
  `net_return` is arithmetic-replayable from it; update the artifact list in
  `docs/quant-autoresearch-consumer.md`.

---

## Reused building blocks (do not re-invent — AGENTS.md "no new layer")

| Need | Reuse |
|---|---|
| JSONL + sha256 writer | `runner/artifacts.write_jsonl` / `canonical_row_line`; validation `artifacts.py` writers |
| per-scenario file ref pattern | `ScenarioBackendRunResult.decision_records_path/sha256` (`backends.py:172-173`) |
| structured failure path | `_failure_result`, `*.failure_stage`, `_run_exit_code`/`_validation_exit_code` (`cli.py:76-94`) |
| purity AST + alias resolution | `_import_aliases` / `_call_name` / `BANNED_*` (`purity.py`) |
| neutral execution input | `StrategyExecutionSpec` (core, Phase 4b); `StrategyExecutionError("param_validation", …)` |
| param entry point | `validate_strategy_params` (`decisions/params.py`) |

## Verification (end-to-end, after all sub-steps)

1. `conda run -n quant pytest -q` — full suite green (incl. the new purity, I/O,
   param-gate, and replay tests).
2. `conda run -n quant ruff check .` clean.
3. Real run: execute an existing `runs/*.toml` validation config end-to-end; confirm
   `backend_runs/trade_ledgers/*.jsonl` are emitted, the manifest hashes them, and the
   replay test passes against the real artifacts (re-sum == gated `net_return`).
4. Misuse paths fail cleanly: a strategy that calls `pd.read_csv` is rejected at load;
   a schema-less strategy returns `hard_no`/`param_validation` from `validate`; an
   unwritable results dir yields exit 1 with a one-line message (no traceback).
5. Report line-count deltas (source / tests / docs separately).
6. Update `TODOS.md` (currently "No open foundation TODOs") to reflect P3 closed, and
   sync this plan's status.
