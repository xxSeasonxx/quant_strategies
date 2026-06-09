## 1. Replay Harness

- [x] 1.1 Add replay-scope result fields and private replay workspace structures in `causality.py`.
- [x] 1.2 Implement micro replay planning without full row-grid enumeration.
- [x] 1.3 Optimize replay prefix construction with frozen-row storage and an availability-filtering fallback.
- [x] 1.4 Add bounded replay helpers that reuse the replay workspace.

## 2. Quick Run

- [x] 2.1 Add quick-run config support for `causality_check = "micro"` and micro probe/timeout settings.
- [x] 2.2 Integrate non-blocking micro replay into quick-run causality preparation.
- [x] 2.3 Expose micro replay evidence in `RunResult`, `summary.json`, `data_manifest.json`, and diagnostics.
- [x] 2.4 Update committed quick-run configs and consumer docs to recommend `micro` for autoresearch iteration.

## 3. Validation And Evaluation

- [x] 3.1 Add validation config support for complete default replay and explicit bounded replay.
- [x] 3.2 Add evaluation config support for complete default replay and explicit bounded replay.
- [x] 3.3 Route validation and evaluation causality preflights through the configured replay scope.
- [x] 3.4 Record bounded replay scope and probe metadata in validation/evaluation artifacts or result evidence.

## 4. Tests

- [x] 4.1 Add causality unit tests for micro probe selection, no full row-grid enumeration, timeout, and workspace prefix reuse.
- [x] 4.2 Add quick-run tests proving micro replay pass/failure/timeout still produces scored economics when engine evaluation succeeds.
- [x] 4.3 Add validation and evaluation config/pipeline tests for complete defaults and explicit bounded replay.
- [x] 4.4 Add regression tests for availability filtering under the replay workspace fast path.

## 5. Verification

- [x] 5.1 Run focused causality, runner, validation, and evaluation test slices.
- [x] 5.2 Run `openspec validate causality-replay-performance --strict`.
- [x] 5.3 Run `git diff --check`.
- [x] 5.4 Run the repo's final verification target appropriate for source/API changes.
