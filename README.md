# quant_strategies

Flat strategy library for tested and untested strategy files, plus an explicit
runner for one config-driven experiment at a time.

Strategy files stay pure: they expose `generate_signals(bars, params)` and do
not call engines, load data, start loops, or write artifacts. Explicit
experiments run through `quant_strategies.runner`, which loads data through
public `quant_data.loader` APIs and evaluates through `quant_engine` Python
APIs.

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
```

The Python consumer API is:

```python
from quant_strategies.runner import run_config

result = run_config("runs/simple_momentum_spy_daily.toml")
```

`quant_autoresearch` should consume this API instead of owning a separate
runner harness.

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
`fill_model.price = "quote"` so bid/ask execution is handled by `quant_engine`.

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
signals.csv
engine_request.json
summary.json
notes.md
evidence.json    when engine evidence is available
```

`strategy_input_rows.csv` is the human-readable record of what the strategy saw.
`strategy_input_rows.jsonl` preserves datetimes, booleans, nulls, funding
fields, and quote fields in JSON-compatible form. `engine_request.json` is the
exact request passed to `quant_engine` and intentionally omits fields not used by
the engine.

`summary.json` has stable top-level keys: `strategy_id`, `mode`, `success`,
`status`, `stage`, `message`, `artifacts`, and `engine`. `notes.md` is
human-readable and treats `quant_engine` screen/validation output as runner
smoke evidence, not promotion evidence or market robustness.

`fill_model.price = "quote"` depends on `quant_engine` quote-fill support. For
FX quote runs, bid and ask fields are preserved in raw strategy input artifacts
and the engine request; execution semantics remain owned by `quant_engine`.
