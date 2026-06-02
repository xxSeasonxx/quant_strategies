# Foundation Lock

This file records the locked foundation contracts for `quant_strategies`. Use it
as the disposition anchor for future reviews: raise regressions and new issues,
but do not reopen accepted tradeoffs unless a documented trigger occurs.

## Locked Contracts

- **Implemented public surfaces:** the project currently exposes quick run,
validation run, and evaluation run. Quick run is diagnostic; validation run is
mechanical evidence validation; evaluation run is stateless frozen-candidate
portfolio, path, and economic evidence.
- **Internal engine boundary:** `quant_strategies.engine` is an internal
execution kernel for quick-run and validation internals/tests, not a fourth
public user surface.
- **Strategy shape:** strategies are flat, single-file, pure strategy modules.
- **Strategy rationale:** each strategy module docstring states thesis,
observables, rule, assumptions, provenance, and falsifier.
- **Quick run:** quick run diagnoses one strategy version and returns quick-run
evidence. It is not validation.
- **Validation run:** validation requires `validate_params` and returns advisory
retained-candidate mechanical evidence. It is not quant strategy evaluation.
- **Evaluation run:** evaluation uses
`quant-strategies evaluate candidate/evaluation.toml` or
`quant_strategies.evaluation.run_evaluation` and returns
`EvaluationRunResult`. It writes detailed trace artifacts as Parquet through
`pyarrow`.
- **Promotion boundary:** validation does not authorize paper trading, live
trading, or promotion. Promotion remains outside this foundation.
- **Evaluation boundary:** evaluation is not validation and does not authorize promotion, paper trading, or live trading. Benchmark-relative metrics are deferred.
- **Causality boundary:** complete deterministic, emitted, and strict
suppression replay proof is the shared minimum for validation and evaluation
evidence.
- **Archive boundary:** ranked research handoff archives and search-loop records
do not live in this repository. This repo keeps no pointer, symlink,
compatibility path, or archive index for moved research records.
- **Auto-research boundary:** `quant_autoresearch` owns candidate generation,
search memory, variant ranking, stopping rules, and iteration decisions.
`quant_strategies` evaluates supplied strategies and configs.
- **Data boundary:** `quant_data` owns data acquisition, materialization,
refresh, backfill, repair, and source joining.
- **Artifact boundary:** generated artifacts are evidence, not truth. Compact  
quick-run artifacts are intentionally not full replay chains.

## Accepted Debt

- Large facade modules are not immediate foundation blockers.
- Full NAV and portfolio accounting belong to the evaluation surface; they are
not quick-run or validation metrics.
- The VectorBT Pro agreement check is optional and single-trade only; it should
not be treated as multi-trade validation confidence.
- Runtime sandboxing is deferred unless strategy code becomes untrusted.

## Approved Next Direction

- Preserve the clarified contract: docs should distinguish quick run,
mechanical evidence validation, and research evaluation without renaming
current code, CLI commands, package paths, artifact names, or public APIs.
- Keep research evaluation as the term for stateless frozen-candidate evidence;
do not use it to mean the auto-research loop.
- Keep the stateless research evaluation surface separate from validation and  
quick-run hot paths.

## Deferred Until Trigger

- **Mid-pipeline artifact I/O failures:** per-window rows, per-scenario
decision/trade-ledger records, and data manifests written while a validation
run is progressing still raise to direct API callers. Revisit if these writes
become a practical reliability issue or if validation artifact durability
requirements tighten.
- **VectorBT Pro agreement scope:** rebuild around trade-ledger or path-level
comparison before treating agreement evidence as multi-trade validation
confidence.
- **Validation source output paths:** validation configs still anchor
`output.results_dir` beside the config so candidate-local workspaces keep
working. Revisit source-directory rejection only if validation config paths are
redesigned.

## Review Protocol

Future foundation reviews should be disposition-aware delta reviews by default.
Classify findings as one of:

- `new`
- `regression`
- `fixed`
- `accepted_debt`
- `deferred_until_trigger`
- `false_positive`
- `superseded`

Run a fresh broad blind foundation review only when Season explicitly asks for
one.
