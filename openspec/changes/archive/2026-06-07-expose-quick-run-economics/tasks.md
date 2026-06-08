## 1. Typed value objects (D2)

- [x] 1.1 In `runner/economic_metrics.py`, define frozen public dataclasses: `RunTrade` (fields `symbol`, `side`, `weight`, `decision_time`/`entry_time`/`exit_time` as tz-aware `datetime`, `entry_price`, `exit_price`, `exit_reason`, `gross_return`, `funding_return`, `cost_return`, `net_return`, `decision_id`) and `RunEconomics` (a `tuple[RunTrade, ...]` ledger + the summary scalars + by-symbol/by-direction/by-exit-reason slices + a schema/basis marker).
- [x] 1.2 Export `RunEconomics` and `RunTrade` from the runner public surface (alongside `RunResult`/`RunOutcome`/`RunEvidence`).

## 2. Economics builder — one computation, two sinks (D1, D3)

- [x] 2.1 Add `build_run_economics(engine_run) -> RunEconomics` to `runner/economic_metrics.py`: read the per-trade ledger from the in-memory engine summary (always present via the hardcoded `include_diagnostics=True`), parse ISO trade timestamps to tz-aware `datetime`, and assemble the typed records.
- [x] 2.2 Compute the summary scalars (reuse `summary_metrics`) and the by-symbol/by-direction/by-exit-reason slices (reuse `diagnostic_slices`) inside the builder, so the slices are produced unconditionally — not only under the `diagnostic` profile.
- [x] 2.3 Keep the existing dict payloads (`summary_metrics` output, `diagnostic_slices` output) derivable from / equal to the typed object so the on-disk `economic_metrics` and `economic_slices` are byte-stable.

## 3. Wire into run_config / RunResult (D1, D5)

- [x] 3.1 Add an additive `economics: RunEconomics | None = None` field to the `RunResult` dataclass (`runner/__init__.py`); leave `succeeded` and the `run_config` signature unchanged.
- [x] 3.2 In `run_config`, after `_evaluate_engine_request` succeeds, call `build_run_economics(engine_run)` once and attach the result to the completed `RunResult` (both the success path at `runner/__init__.py:216` and the `artifact_write`-failure path at `:209`).
- [x] 3.3 Refactor `_write_completion_artifacts` to consume the prebuilt `RunEconomics` (instead of computing economics inline at `:476-484`); verify `summary.json` and the diagnostic/summary-profile artifacts are unchanged.

## 4. Tests

- [x] 4.1 In `tests/test_runner_economic_metrics.py`, assert a completed run's `RunResult.economics` carries one `RunTrade` per engine trade, in order, with tz-aware times and the after-cost decomposition (`net_return == gross + funding - cost`).
- [x] 4.2 Assert the in-process summary scalars equal the `economic_metrics` payload written to `summary.json` for the same run (single-computation parity).
- [x] 4.3 Assert profile-independence: `artifact_profile = "summary"` still yields the full ledger + scalars + slices, identical to `diagnostic`/`full` for the same inputs.
- [x] 4.4 Assert additive/non-breaking: a pre-engine failure (`config_load` / `data_load`) leaves `economics is None`; a completed run populates it; `succeeded` semantics unchanged.
- [x] 4.5 Add a dependency-wall guard test: importing/exercising the quick-run path (`runner`, `engine`, `core`) does not import `vectorbtpro`, `pandas`, `numpy`, or `quant_strategies.evaluation`.

## 5. Docs

- [x] 5.1 Update `docs/consumer/reference.md`: add `economics` to the `RunResult` field table and document the `RunEconomics`/`RunTrade` shapes.
- [x] 5.2 Update `docs/consumer/usage-guide.md`: note the in-process economics under "Surface 1 — Quick run" and in the "Programmatic consumer" section (read the after-cost trade sample in-process, no artifact scraping; trade-unit scope).

## 6. Verification

- [x] 6.1 Run the repo format/lint target (`make fix` or nearest) — no hand-formatting.
- [x] 6.2 Run focused tests (`conda run -n quant python -m pytest tests/test_runner_economic_metrics.py tests/test_runner_api_cli.py`) and report changed-line counts (source/tests/docs separated).
- [x] 6.3 Validate the change: `openspec validate expose-quick-run-economics --strict`.
