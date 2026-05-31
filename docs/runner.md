# Runner reference (quick run)

`quant-strategies run path/to/config.toml` executes one TOML experiment config —
the fast, deterministic "quick run" used for ranking and iteration. See the
[README](../README.md) for the overall design and the strategy contract.

The runner loads rows, calls the pure `generate_decisions(rows, params)`, validates
the `StrategyDecision` contract, runs hidden-lookahead replay keyed by `decision_id`,
checks decision row availability, builds an engine request from supported decisions,
and writes result artifacts.

Rows are normalized once at the data-load boundary through the neutral
`quant_strategies.data_contract.NormalizedRows` contract. Strategies still receive
plain mapping rows typed as `Sequence[Mapping[str, Any]]`; they do not receive row
model objects.

## Modes

**`[output] mode = "screen"`** — the engine simulates entries and exits from the
decisions, fill model, cost model, and exit policy. It reports `trade_count` plus
`trade_result.sum_signed_trade_activity_gross`, `sum_signed_trade_activity_funding`,
`sum_signed_trade_activity_cost`, and `sum_signed_trade_activity_net`. A completed
screen has `assessment_status = "screened"`. If a strategy returns no decisions, the
screen still completes with `trade_count = 0` and zero trade-result metrics — a
zero-opportunity search signal, not an infrastructure failure.

**`[output] mode = "gate"`** — the engine runs the same screen and applies quick
checks: `valid_inputs`, `min_trades >= 1`, `positive_gross`, and `positive_net`.
Passing checks produce `assessment_status = "quick_check_passed"` only when hidden-lookahead
replay passes and all rows carry `available_at`. Passing checks with missing or
partial `available_at` produce `assessment_status = "quick_check_unverified"`. Invalid
`available_at` is a row contract failure. A `gate` run with no decisions completes
normally but fails as `quick_check_failed` because `min_trades` is not met. These checks are
mechanical checks only; they do not test statistical significance, regime robustness,
capacity, or execution quality.

## Decision support

Quick-run diagnostic execution supports only single-leg equity/ETF, FX, and crypto-perp
`open` decisions with non-flat `target_weight` sizing. Explicitly extended decisions
are rejected by unsupported quick-run or backend paths instead of approximating their
PnL — the extended vocabulary (futures, options, multi-leg instruments, buy/sell book
side, close/adjust/roll actions, and `target_notional`, `target_contracts`, or
`target_vol` sizing) lives behind explicit imports from
`quant_strategies.decisions.extended_ontology`.

## Live progress events

Callers that need live progress can pass an `event_sink` callback to `run_config()`.
The callback receives structured `runner_stage` dictionaries for stage start,
completion, and failure, with UTC timestamps and `duration_ms` on terminal events.
The CLI equivalent is `quant-strategies run --events-jsonl ...`, which preserves
stdout as the result directory and writes JSONL stage events to stderr. Validation
callers can pass the same shape of callback to `run_validation()`; those events use
`event = "validation_stage"` (`quant-strategies validate --events-jsonl ...`).

## Exit codes

CLI exit codes are part of the public contract:

| Code | Meaning |
|---|---|
| `0` | structured usable evidence produced |
| `1` | infrastructure or execution failed |
| `2` | validation completed with `hard_no` |
| `3` | data readiness or audit failed |

Programmatic callers should use `run_completed`, `failure_stage`,
`assessment_status`, verdicts, replayability, causality/data fields, row contract,
and trade-result metrics rather than any single completion flag.

Artifact I/O errors are routed to structured results rather than raw exceptions:
result-directory creation, the final artifact write, and failure-result writes return
a `failure_stage` of `artifact_initialization` or `artifact_write` (exit `1`). The CLI
additionally backstops any remaining filesystem error as a clean exit `1`. (A residual
on mid-pipeline success-path writes is tracked in `TODOS.md`.)

## Evidence quality

Runner summaries and data manifests include evidence-quality fields:
`data_availability_status`, `availability_coverage`, `row_contract`,
`causality_verified`, `emitted_replay_verified`, `strict_no_emission_verified`, and
`evidence_quality_warnings`.

Strict suppression replay runs by default; only a strict run sets
`strict_no_emission_verified` (and therefore `causality_verified`), while
`emitted_replay_verified` records the weaker subset check — so a run never claims
verification it did not perform. If strict suppression probes are skipped, the run can
continue only as unverified evidence: `strict_no_emission_verified` and
`causality_verified` remain false. Hidden-lookahead replay and deterministic full-replay
failures stop the run as `runner_failed`. Missing or partial availability is recorded as
uncertainty with `quick_check_unverified` and does not set `causality_verified`.

## Row contract

Row-contract strictness is set explicitly by `row_contract = "search" | "validation"`
(default `search`) and is independent of `artifact_profile`. Missing `available_at` in
search mode is warning evidence; under `row_contract = "validation"` it is a row
contract failure. Invalid `available_at` is a row contract failure regardless of
strictness.

`row_contract` reports the loaded row schema status for the configured `data.kind`,
including missing required fields, timestamp awareness, duplicate symbol/timestamp
keys, and `quant_data_feedback` strings for upstream data fixes. Stable issue reasons:
`row_missing_required_field`, `row_invalid_timestamp`, `row_invalid_numeric_field`,
`row_invalid_ohlc_order`, `row_duplicate_symbol_timestamp`, `row_invalid_available_at`,
`row_missing_available_at`, `row_missing_quote_field`, and `row_invalid_funding_fields`.
Artifacts may sample or compact `row_contract.issues`, while `issue_count` and
`issue_reasons` preserve complete counts and reason summaries. Search-mode missing
`available_at` warnings are excluded from `quant_data_feedback`.

## Replayability and artifacts

Runner artifacts declare `replayable_from_artifacts`. Diagnostic-profile runs are
the default and set `replayable_from_artifacts = false`: useful for one-strategy
iteration, but not enough to replay every reported number from artifacts alone.
Summary-profile runs also set `replayable_from_artifacts = false` and keep compact
sweep output. Full-profile runs (`artifact_profile = "full"`) set
`replayable_from_artifacts = true`: they include the row, decision, engine-request,
and evidence artifacts needed for audit replay of runner trade-result metrics.

Artifacts are written under ignored result directories. `output.results_dir` must stay
inside the repository and outside source/input roots such as `src/`, `tests/`, `docs/`,
`runs/`, `examples/`, `tested/`, `untested/`, and `researched/`; write generated output
under `results/` instead. After config loading succeeds, result dirs include
`config.toml`; `strategy_snapshot.py` is copied when the strategy file is available.
Runs that reach data loading include `data_manifest.json` and, for
`artifact_profile = "full"`, `strategy_input_rows.jsonl` even if decision generation
later fails (a JSON-safe canonical serialization of the normalized projection; non-finite
ancillary values are written as `null`, and its file hash matches
`normalized_rows_sha256`). Failures still write `run_manifest.json`, `environment.json`,
`summary.json`, and `notes.md`. Successful diagnostic runs write `diagnostics.json`;
successful summary runs write `artifact_profile_summary.json`; completed `full` runs
that reach engine request construction also write `decision_records.jsonl`,
`engine_request.json`, and `evidence.json`.

`run_manifest.json` keeps deterministic research identity (source commit, config, data,
decisions, artifact hashes); Python version, package versions, git dirty status, and
tracked diff hashes go to `environment.json` (excluded from manifest artifact hashes).
V1 row, decision, and trade-ledger artifacts use deterministic JSONL. Columnar storage
is not a current runner artifact format.

## Engine and execution boundary

Database engine creation and environment configuration are owned by `quant_data`; the
runner does not discover upstream `.env` files. Tests and specialized callers can inject
an explicit engine at the data-loader boundary; otherwise the runner reuses one default
`quant_data` engine per Python process.

Runner and validation share one internal execution boundary for strategy import,
parameter validation, data loading, frozen strategy execution, decision validation, row
hashing, and evidence-quality context. The runner remains the owner of execution-kernel
request construction and engine artifacts.

Stop-loss, take-profit, and trailing-stop thresholds are evaluated on the engine's
selected fill price series (`open`, `close`, or quote side from the fill model). The
engine does not simulate intrabar high/low stop paths.
