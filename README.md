# quant_strategies

Strategy library for untested, researched, and tested strategy files, plus an
explicit runner for one config-driven experiment at a time.

Strategy files stay pure: foundation strategies expose
`generate_decisions(rows, params)` and do not call engines, load data, start
loops, or write artifacts. Explicit experiments run through
`quant_strategies.runner`, which loads data through public `quant_data.loader`
APIs and evaluates through the internal `quant_strategies.engine` package.

## Layout

```text
untested/    raw or actively forming strategy ideas
researched/  bench-researched candidates frozen for separate validation
examples/    example or smoke strategies that are not lifecycle-promoted
tested/      strategies that passed the separate validation process
runs/        curated TOML run configs
src/         installable runner package
tests/       tests for strategy timing, side, weight, and edge cases
results/     generated run artifacts, ignored by git
```

Each strategy should be one Python file until it genuinely needs more structure.

`researched/` stores self-contained handoff packages from `quant_autoresearch`.
Each package keeps frozen strategy code, runnable configs, deterministic
selection output, and compact evidence. A researched strategy is ready for the
separate validation process; it is not market validated and should not be moved
to `tested/` until that validation process passes.

## Runner

Run one explicit config:

```bash
conda run -n quant quant-strategies run runs/<experiment>.toml
conda run -n quant quant-strategies run --repo-root "$PWD" runs/<experiment>.toml
```

The Python consumer API is:

```python
from quant_strategies.runner import run_config

result = run_config("runs/<experiment>.toml")
```

`quant_autoresearch` should consume this API instead of owning a separate
runner harness.

The CLI is a repository-checkout workflow. When running from another current
working directory, or from an installed package where the repository root is not
implicit, pass `--repo-root <repo>` so relative config paths resolve against the
intended checkout.

## Validation

The validation workflow is separate from runner smoke evidence.

```bash
conda run -n quant quant-strategies validate researched/<strategy_id-or-variant>
```

Validation candidates must expose:

```python
def generate_decisions(rows, params):
    return []
```

The runner and validation workflows share the same decision contract. The
runner adapts `StrategyDecision` objects to its internal smoke engine request;
strategy files do not emit engine-specific signals. Every emitted
`StrategyDecision.strategy_id` must match the config `strategy_id`; mismatches
fail before decision records or engine artifacts are written.

Validation writes generated artifacts under ignored `validation_results/` and
classifies each run as `hard_no`, `maybe`, or `clear_yes`. A `clear_yes`
recommendation is advisory until Season approves a stronger promotion policy.
`promotion_decision.json` includes `advisory_decision`,
`paper_trade_eligible`, `live_eligible`, and `requires_manual_approval`.

The v1 validation matrix treats `base` as a no-cost gross baseline,
`realistic_costs` as the configured fee/slippage economics, and
`stressed_costs` as doubled configured costs. Parameter perturbation scenarios
regenerate decisions with perturbed params and remain diagnostic unless a later
promotion policy makes them required. For crypto perpetual funding rows, the
VectorBT PRO adapter reports funding-aware metrics for the current v1 supported
shape:
non-overlapping time-held target exposure windows. The reported funding-aware
`net_return` is `price_cost_return + funding_return`; both components are
reported separately. The adapter still rejects unsupported sizing, threshold
exits, overlapping same-symbol windows, and multi-asset target-weight portfolio
semantics rather than approximating them silently.

Validation artifacts include the frozen `validation_config.toml`,
`strategy_snapshot.py`, `decision_schema.json`, `decision_records.jsonl`,
`data_audit.json`, `backend_runs/summary.json`, `robustness_matrix.json`,
`promotion_decision.json`, `validation_report.md`, and
`validation_manifest.json`. `validation_manifest.json` records repository,
package, config, strategy, row-provenance, backend, researched-manifest, and
artifact hash identity. `data_audit.json`
records decision/data availability checks; it is not a proof of complete
lookahead freedom inside strategy code.

Validation passes immutable row and param views into strategies and fresh
immutable row views into each backend scenario. Strategies may define
`validate_params(params)` to reject unknown or invalid TOML params before data
loading and backend execution.

## Config Shape

Run configs are TOML and validated with Pydantic before strategy import or data
loading:

```toml
strategy_path = "tested/example_strategy.py"
strategy_id = "example_strategy_daily"

[data]
kind = "bars"
dataset = "example_dataset"
symbols = ["EXAMPLE"]
start = "2024-01-01"
end = "2024-01-31"
strict = true

[params]
weight = 1.0
hold_bars = 1

[fill_model]
price = "close"
entry_lag_bars = 1
exit_lag_bars = 0
# Optional escape hatch; default is false.
# allow_same_bar_close_fill = true

[cost_model]
fee_bps_per_side = 0.0
slippage_bps_per_side = 0.0

[output]
results_dir = "results"
mode = "validate"
```

Supported data kinds are `bars`, `crypto_perp_funding`, and
`forex_with_quotes`. `strategy_id` is the expected strategy identity emitted by
the strategy's `StrategyDecision` records, not a loose run label.
`strategy_path` and `output.results_dir` must resolve inside this repository.
Relative config paths passed to `run_config(...,
repo_root=...)` resolve against the effective repository root, so automation can
call `run_config("runs/<experiment>.toml", repo_root=repo)` from
another current working directory.

Curated smoke configs live under `runs/`. Examples include
`runs/simple_momentum_spy_daily.toml`,
`runs/crypto_perp_funding_crowding_reversal_smoke.toml`, and
`runs/fx_triangular_residual_quote_smoke.toml`. They are examples of executable
runner configurations and smoke evidence, not strategy-promotion evidence.

For close-derived signals, `fill_model.price = "close"` with
`entry_lag_bars = 0` is rejected by default. Set
`allow_same_bar_close_fill = true` only when the config author has explicitly
accepted same-bar close-fill causal responsibility.

Decisions may include optional exit controls: `take_profit_bps`,
`stop_loss_bps`, and `trailing_stop_bps`. Exit triggers are confirmed from the
configured fill price on completed bars; this runner does not simulate intrabar
stop or target touches. `exit_lag_bars` controls whether the exit fills on the
trigger bar or a later bar. The decision `exit_policy.max_hold_bars` controls
the max-hold exit.

## Artifacts

Each run writes a timestamped directory under `results/`:

```text
config.toml
strategy_snapshot.py
strategy_input_rows.csv
strategy_input_rows.jsonl
decision_records.jsonl
data_manifest.json
signals.csv
engine_request.json
run_manifest.json
summary.json
notes.md
evidence.json    when engine evidence is available
```

`strategy_input_rows.csv` is the human-readable record of what the strategy saw.
`strategy_input_rows.jsonl` preserves datetimes, booleans, nulls, funding
fields, and quote fields in JSON-compatible form. `decision_records.jsonl` is
the canonical strategy output record. `signals.csv` is an internal smoke-engine
adapter artifact generated from decisions. `engine_request.json` is the exact
request passed to `quant_strategies.engine` and intentionally omits fields not
used by the evaluator. `data_manifest.json` records row counts, timestamp
ranges, metadata field coverage, and the strategy-input JSONL hash.
`run_manifest.json` records best-effort code/dependency identity, internal
evidence schema identity, dirty worktree hashes when available, and hashes of
generated run artifacts.

Runner artifacts are smoke evidence. They include `evidence_class`,
`strategy_contract`, `return_model`, `funding_model`, `promotion_eligible`,
`paper_trade_eligible`, `live_eligible`, and `requires_manual_approval` so
automation and humans do not overread a quick run.

Trade records in `evidence.json` include `exit_reason`, one of `max_hold`,
`take_profit`, `stop_loss`, or `trailing_stop`. Strategy decision metadata is
preserved in `decision_records.jsonl`, carried through internal signal
`metadata` in `engine_request.json`, and copied into each trade as
`signal_metadata`.

`summary.json` has stable top-level keys: `strategy_id`, `mode`, `success`,
`status`, `stage`, `message`, `artifacts`, `engine`, `run_completed`,
`assessment_status`, `evidence_class`, `strategy_contract`, `return_model`,
`funding_model`, `promotion_eligible`, `paper_trade_eligible`,
`live_eligible`, and `requires_manual_approval`. `success` is the existing
runner/CLI outcome flag. New consumers should use `assessment_status` and the
eligibility fields when interpreting research meaning:

```text
screen       -> assessment_status = "screened", promotion_eligible = false
validate pass -> assessment_status = "smoke_passed", promotion_eligible = false
validate fail -> assessment_status = "smoke_failed", promotion_eligible = false
runner error -> assessment_status = "runner_failed", promotion_eligible = false
```

`notes.md` is human-readable and treats internal evaluator screen/validation
output as runner smoke evidence, not promotion evidence or market robustness. In
screen mode, `status = "screened"` means the evaluator completed a screen; it is
not a validation pass. In validation mode, `status = "passed"` or
`status = "failed"` reflects the validation gates returned by the evaluator.

For FX quote runs, bid and ask fields are preserved in raw strategy input
artifacts and the engine request; execution semantics remain owned by
`quant_strategies.engine`.

For `crypto_perp_funding` runs, funding fields may be used by the strategy and
preserved in raw inputs. Internal evaluator requests include supplied funding
events, and evaluator evidence reports funding cashflows separately as
`funding_return` before including them in `net_return`. When an exit trigger
closes a trade before max hold, funding cashflows are computed only over the
actual entry-to-exit interval.

When loaded rows include `available_at`, the runner checks the row used for each
strategy decision. `StrategyDecision.as_of_time` names the row timestamp used for
the decision. If the as-of row was available only after the decision time, the
run fails at `data_readiness` before engine request
construction. Ingestion and refresh timestamps remain audit metadata in
artifacts and manifests; they are not treated as historical market availability.
This is a direct as-of-row guard, not a full feature-lineage proof.

`results/` is generated and ignored. To clear local run artifacts and Python
caches after confirming you do not need the ignored files, use:

```bash
git clean -fdX
```

## Promotion Discipline

Current runner output is useful smoke evidence. It proves that a strategy file,
data adapter, fill model, and internal evaluator can complete a configured run
and produce auditable artifacts. It is not enough to move a real strategy from
`untested/` to `tested/`.

Promotion requires separate research evidence: frozen parameters, realistic
costs, enough trades for the strategy horizon, out-of-sample or walk-forward
checks where applicable, sensitivity or negative-control checks, and explicit
notes about overfit and proxy/data assumptions.
