# Phase 2 — P1 Workflow De-convolution (F6 + F13) Plan

**Goal:** Remove the workflow convolution the review flagged (concern #2): a verbosity
knob silently changing pass/fail, an implicit loader contract, and overloaded "validate"
vocabulary.

**Re-audit (current tree, post Phase 1):**
- F6 coupling **OPEN**: `runner/__init__.py:_runner_row_contract_mode` maps `artifact_profile` (`full→VALIDATION`, `summary→SEARCH`) → row-contract *strictness*. A verbosity knob changes pass/fail.
- F13 **OPEN**: `runner/execution.py:_load_data` uses `inspect.signature(load_data)` to decide whether to pass `row_contract_mode`, to tolerate 1-arg test mocks (58 of them).
- "two validates": runner TOML `[output] mode = "screen"|"validate"` (engine `screen` vs `gate_screen`) vs the `quant-strategies validate` CLI (validation package). The `validate` literal is baked into engine models `ScreeningResult.mode`, `GatingReport.mode`, `EvidencePacket.mode`.
- `artifact_trust_tier` (`search_only|audit_replayable`) is *derived* from `artifact_profile` — a second name, not a third user-set axis; leave as-is.

## Sub-steps (each kept green; one commit after code review)

### 2a — F13: typed loader contract, delete reflection
- Define a `DataLoader` Protocol in `runner/data_loader.py` (or reuse a `Callable`), `load_data(config, *, row_contract_mode)` keyword-only.
- `runner/execution.py:_load_data` always calls `load_data(config, row_contract_mode=contract_mode)`; delete the `inspect.signature` branch and the `from inspect import signature` import.
- Update the 58 test mocks: `lambda config: LoadedData(...)` → `lambda config, **_kwargs: LoadedData(...)` (and the few `def fake(config):` doubles → accept `**_kwargs`). Bulk per-file `replace_all` on the exact `lambda config: LoadedData` shape, then fix stragglers.
- Verify: `pytest -q` green.

### 2b — F6: decouple row-contract strictness from artifact_profile
- Add explicit `row_contract: Literal["search","validation"] = "search"` to `RunConfig` (top-level; it is a run policy, not output verbosity). Quick-run default is `search`.
- `_runner_row_contract_mode(config)` returns `RowContractMode(config.row_contract)`; remove the `artifact_profile`-derived strictness.
- `artifact_profile` stays purely about which artifacts/verbosity (+ derived `artifact_trust_tier`).
- Migrate tests that relied on `full→VALIDATION` strictness (those asserting invalid/partial `available_at` *fails* the run) to set `row_contract = "validation"` in their config. Identify via the row-contract error/`smoke_unverified` assertions.
- Verify: `pytest -q` green; add a focused test that `artifact_profile="full"` with default `row_contract` does NOT enforce VALIDATION strictness (decoupled), and that `row_contract="validation"` does.

### 2c — Docs: side-by-side vocab table (F6 d)
- Update `README.md` and `docs/quant-autoresearch-consumer.md` with a single table distinguishing: quick-run (`run` / `run_config`, engine `screen`|`validate` gating, `row_contract` strictness, `artifact_profile` verbosity, `artifact_trust_tier`) vs the validation run (`validate` / `run_validation`). Explicitly call out that runner `mode="validate"` is *engine smoke-gating*, not the validation package.

### 2d — F6 mode rename — DONE in Phase 4a (was deferred, then completed)

**UPDATE:** completed in Phase 4a (`validate`→`gate` across engine/runner/tests/docs
+ 15 frozen `researched/` configs migrated). The deferral rationale below is kept
for history; Season directed "finish the goal," so it was executed.

**Decision: not executed overnight.** Renaming the runner/engine `validate` mode to
`gate` would change the `mode` literal in `EvidencePacket`/`GatingReport`/`ScreeningResult`,
which is serialized into `evidence.json` and `summary.json` — a **breaking change to the
consumer-facing artifact contract** that `quant_autoresearch` parses. Making a breaking,
outward-facing contract change unilaterally (and choosing the public name) is the product
owner's call and warrants coordination with the consumer, so it is deferred rather than
forced overnight.

Concern #2 (workflow convolution) is addressed without it: 2b removed the only real
footgun (verbosity silently flipping pass/fail), and 2c's vocab table explicitly
disambiguates the two senses of "validate" for consumers.

**Ready-to-run recommendation for Season** (≈1 mechanical change if approved):
rename the mode value `validate`→`gate` across `engine/models.py` (`GatingReport.mode`,
`EvidencePacket.mode` literals), `engine/evidence.py:14`, `runner/engine_runner.py`
(`EngineMode`), `runner/config.py` (`RunMode`), the ~25 test assertions on `mode`, and
the docs — yielding engine quick-run modes `screen` | `gate`, cleanly distinct from the
`quant-strategies validate` validation package. Treat as a consumer-contract version bump.

## Verification gate
- `conda run -n quant pytest -q` fully green after each sub-step.
- `/code-review` on the phase diff; ruff clean; report line counts.
