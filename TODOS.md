# Open foundation TODOs

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

(Strict suppression-lookahead replay is the default for both the runner
quick-run and the validation run; see `causality.check_hidden_lookahead` and the
`hidden_lookahead_suppression_detected` regression tests.)
