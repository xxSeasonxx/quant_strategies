## 1. Config And Data Contract

- [x] 1.1 Add `CapacityModelConfig` to shared core config with required explicit declaration in quick-run, validation, and evaluation configs.
- [x] 1.2 Thread `capacity_model` through quick-run, validation scenario configs, evaluation scenarios, and spine backend prepared inputs.
- [x] 1.3 Update committed quick-run, validation, and evaluation TOML configs to declare the capacity model explicitly.
- [x] 1.4 Extend row-contract/preflight validation for capacity-enabled supported data kinds so required volume inputs are preserved and invalid capacity inputs fail before scored success.
- [x] 1.5 Add unsupported FX capacity semantics so `forex_with_quotes` with ADV/impact pricing fails closed instead of treating tick count as notional volume.

## 2. Book Walk Capacity Model

- [x] 2.1 Add capacity feasibility reasons and execution-event dataclasses to the shared portfolio foundation module.
- [x] 2.2 Add causal per-symbol volume/ADV helpers to `_RowIndex`, using prior rows only and excluding the current execution row from ADV history.
- [x] 2.3 Compute normalized notional, real notional, bar participation, ADV participation, base cost, impact cost, and total cost for every non-zero executed delta.
- [x] 2.4 Charge impact cost inside `_apply_decision` and `_flatten` so the authoritative NAV path includes market impact.
- [x] 2.5 Enforce capacity-disabled, unsupported-volume, missing-volume, insufficient-history, and participation-limit fail-closed verdicts without clamping or resizing orders.
- [x] 2.6 Preserve round-trip/NAV reconciliation while adding impact-cost attribution as a component of total transaction cost.

## 3. Public Results And Artifacts

- [x] 3.1 Add compact capacity diagnostics to quick-run foundation scenario/full-train payloads and summary/diagnostic artifacts.
- [x] 3.2 Extend typed quick-run economics records, summaries, and slices with impact-cost attribution while preserving total `cost_return` semantics.
- [x] 3.3 Expose capacity-aware validation backend metrics from the same book walk without creating a second scoring path.
- [x] 3.4 Add evaluation execution-event trace tables and serialize them through the existing Parquet artifact flow.
- [x] 3.5 Update public docs and active handoff docs for the new capacity envelope, evidence semantics, and O15 status.

## 4. Tests

- [x] 4.1 Add config tests proving missing `capacity_model` is rejected and explicit capacity modes validate.
- [x] 4.2 Add book-walk unit tests for impact cost reducing NAV, execution events matching cash updates, causal ADV history, and zero-trade capacity behavior.
- [x] 4.3 Add fail-closed tests for capacity disabled on traded books, unsupported FX semantics, missing volume, insufficient ADV history, and bar/ADV participation breaches.
- [x] 4.4 Add quick-run integration tests for capacity diagnostics and typed economics impact attribution.
- [x] 4.5 Add validation and evaluation tests proving the shared spine surfaces capacity-aware results and evaluation writes execution-event traces.
- [x] 4.6 Update candidate/config fixture tests for the explicit capacity envelope.

## 5. Verification And Cleanup

- [x] 5.1 Run `openspec validate capacity-adv-market-impact --strict`.
- [x] 5.2 Run focused pytest targets covering config, data contract, portfolio foundation, quick-run economics, validation, and evaluation.
- [x] 5.3 Run `make check` and `git diff --check`.
- [x] 5.4 Report changed-line counts separated by source, tests, docs/specs, and config updates.
