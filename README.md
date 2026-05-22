# quant_strategies

Flat strategy library for tested and untested strategy files, plus an explicit
runner for one config-driven experiment at a time.

Strategy files stay pure: they expose `generate_signals(bars, params)` and do
not call engines, load data, start loops, or write artifacts. Explicit
experiments run through `quant_strategies.runner`, which loads data through
public `quant_data.loader` APIs and evaluates through the internal
`quant_strategies.engine` package.

## Layout

```text
untested/   strategy files still under implementation
tested/     strategy files with focused behavior tests
runs/       curated TOML run configs
src/        installable runner package
tests/      tests for strategy timing, side, weight, and edge cases
results/    generated run artifacts, ignored by git
```

Each strategy should be one Python file until it genuinely needs more structure.

## Runner

Run one explicit config:

```bash
conda run -n quant quant-strategies run runs/simple_momentum_spy_daily.toml
conda run -n quant quant-strategies run runs/fx_triangular_residual_quote_smoke.toml
conda run -n quant quant-strategies run --repo-root "$PWD" runs/simple_momentum_spy_daily.toml
```

The Python consumer API is:

```python
from quant_strategies.runner import run_config

result = run_config("runs/simple_momentum_spy_daily.toml")
```

`quant_autoresearch` should consume this API instead of owning a separate
runner harness.

The CLI is a repository-checkout workflow. When running from another current
working directory, or from an installed package where the repository root is not
implicit, pass `--repo-root <repo>` so relative config paths resolve against the
intended checkout.

## Config Shape

Run configs are TOML and validated with Pydantic before strategy import or data
loading:

```toml
strategy_path = "tested/simple_momentum.py"
strategy_id = "simple_momentum_spy_daily"

[data]
kind = "bars"
dataset = "equity_1min"
symbols = ["SPY"]
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
`forex_with_quotes`. `strategy_path` and `output.results_dir` must resolve
inside this repository. Relative config paths passed to `run_config(...,
repo_root=...)` resolve against the effective repository root, so automation can
call `run_config("runs/simple_momentum_spy_daily.toml", repo_root=repo)` from
another current working directory.

`runs/fx_triangular_residual_quote_smoke.toml` is the first real quote-fill
smoke config. It uses `forex_with_quotes`, strict loading, and
`fill_model.price = "quote"` so bid/ask execution is handled by the internal
evaluator.

For close-derived signals, `fill_model.price = "close"` with
`entry_lag_bars = 0` is rejected by default. Set
`allow_same_bar_close_fill = true` only when the config author has explicitly
accepted same-bar close-fill causal responsibility.

## Artifacts

Each run writes a timestamped directory under `results/`:

```text
config.toml
strategy_snapshot.py
strategy_input_rows.csv
strategy_input_rows.jsonl
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
fields, and quote fields in JSON-compatible form. `engine_request.json` is the
exact request passed to `quant_strategies.engine` and intentionally omits fields
not used by the evaluator. `data_manifest.json` records row counts, timestamp
ranges, metadata field coverage, and the strategy-input JSONL hash.
`run_manifest.json` records best-effort code/dependency identity, internal
evidence schema identity, dirty worktree hashes when available, and hashes of
generated run artifacts.

`summary.json` has stable top-level keys: `strategy_id`, `mode`, `success`,
`status`, `stage`, `message`, `artifacts`, `engine`, `run_completed`,
`assessment_status`, and `promotion_eligible`. `success` is the existing
runner/CLI outcome flag. New consumers should use `assessment_status` and
`promotion_eligible` when interpreting research meaning:

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
`funding_return` before including them in `net_return`.

When loaded rows include `available_at`, the runner checks the row used for each
signal decision. By default that is the row matching the signal's symbol and
`decision_time`; a strategy may emit `as_of_time` to state that it decided later
using an earlier completed row. If the as-of row was available only after the
decision time, the run fails at `data_readiness` before engine request
construction. Ingestion and refresh timestamps remain audit metadata in
artifacts and manifests; they are not treated as historical market availability.
This is a direct as-of-row guard, not a full feature-lineage proof.

## Promotion Discipline

Current runner output is useful smoke evidence. It proves that a strategy file,
data adapter, fill model, and internal evaluator can complete a configured run
and produce auditable artifacts. It is not enough to move a real strategy from
`untested/` to `tested/`.

Promotion requires separate research evidence: frozen parameters, realistic
costs, enough trades for the strategy horizon, out-of-sample or walk-forward
checks where applicable, sensitivity or negative-control checks, and explicit
notes about overfit and proxy/data assumptions.
