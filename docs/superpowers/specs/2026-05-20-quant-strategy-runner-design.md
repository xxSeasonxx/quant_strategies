# Quant Strategy Runner Design

## Decision

Add a package-style runner inside `quant_strategies`.

`quant_strategies` will own strategy files, runnable strategy experiment
configuration, artifact writing, and the public API consumed by
`quant_autoresearch`. `quant_engine` remains a deterministic evaluator that
accepts explicit bars, signals, fill assumptions, and cost assumptions.

```text
quant-data        market data access and readiness guards
quant_engine      deterministic evaluation foundation
quant_strategies  strategy files plus runnable experiment API
quant_autoresearch consumer of quant_strategies, not a runner owner
```

## Goals

- Run one explicit strategy against one explicit symbol set and time window.
- Keep strategy files pure and flat.
- Support both CLI use and Python API use.
- Make it straightforward to add asset-class data adapters.
- Preserve deterministic engine artifacts for review.
- Avoid registries, discovery loops, promotion logic, and paper-trading approval.

## Non-Goals

- Do not move runner behavior into `quant_engine`.
- Do not keep a separate runner in `quant_autoresearch`.
- Do not create per-strategy folders.
- Do not introduce a strategy registry or plugin framework.
- Do not implement autonomous strategy selection.
- Do not claim market robustness from a single run.

## Repository Shape

```text
quant_strategies/
  tested/
    simple_momentum.py
  untested/
    fx_triangular_residual_reversion.py

  runs/
    simple_momentum_spy_daily.toml

  results/

  src/
    quant_strategies/
      runner/
        __init__.py
        cli.py
        config.py
        strategy_loader.py
        data_loader.py
        engine_runner.py
        artifacts.py
```

The existing `tested/`, `untested/`, and `tests/` layout remains the canonical
strategy library. The runner package is infrastructure around that library, not
a replacement for it.

## Public Interfaces

CLI:

```bash
conda run -n quant quant-strategies run runs/simple_momentum_spy_daily.toml
```

Python API:

```python
from quant_strategies.runner import run_config

result = run_config("runs/simple_momentum_spy_daily.toml")
```

`quant_autoresearch` should consume the Python API or shell out to the CLI. It
should not own its own data loader, engine request builder, or artifact writer.

## Run Config

Use one TOML file per runnable experiment.

```toml
strategy_path = "tested/simple_momentum.py"
strategy_id = "simple_momentum_spy_daily"

[data]
kind = "bars"
dataset = "equity_daily"
symbols = ["SPY"]
start = "2024-01-01"
end = "2024-12-31"
strict = true

[params]
weight = 1.0
hold_bars = 3

[fill_model]
price = "close"
entry_lag_bars = 1

[cost_model]
fee_bps_per_side = 1.0
slippage_bps_per_side = 2.0

[output]
results_dir = "results"
mode = "validate"
```

`strategy_path` is a file path, not a registry key. This keeps strategy identity
explicit and avoids framework behavior.

## Data Flow

```text
run config
  -> parse and validate config
  -> load strategy module by file path
  -> load market data through quant_data
  -> convert data rows to strategy bar dictionaries
  -> call generate_signals(bars, params)
  -> build quant_engine EvaluationRequest
  -> screen and optionally validate
  -> write artifacts
```

The strategy receives bar dictionaries that include the columns returned by the
selected data adapter. The engine request receives only engine-compatible OHLC
bars plus generated signals.

## Initial Data Adapters

Start with three explicit adapter kinds:

```text
bars
  generic OHLC data through load_bars or load_universe_bars

crypto_perp_funding
  crypto perpetual bars plus funding fields through
  load_crypto_perp_bars_with_funding

forex_with_quotes
  FX bars plus executable quote fields through load_fx_bars_with_quotes
```

Adapters must use `quant_data.loader` and catalog/readiness metadata as the
source of truth. Strict mode must fail closed; the runner must not silently
fallback from strict to non-strict data.

## Component Responsibilities

`config.py`:

- Parse TOML.
- Validate required fields.
- Normalize dates, paths, mode, fill model, cost model, params, and data block.

`strategy_loader.py`:

- Import one strategy file by path.
- Require a callable `generate_signals(bars, params)`.
- Return import errors with clear context.

`data_loader.py`:

- Load market data from `quant_data`.
- Enforce data kind, dataset, symbol, and date-window rules.
- Return strategy input rows and engine OHLC rows.

`engine_runner.py`:

- Build `quant_engine.EvaluationRequest`.
- Reject missing or unfillable signals deterministically.
- Run `screen` and `validate` through the Python API.
- Build evidence JSON through `quant_engine`.

`artifacts.py`:

- Create one result directory per run.
- Write config, strategy snapshot, bars, signals, request, summaries, evidence,
  and notes.

`cli.py`:

- Provide the `quant-strategies run <config>` command.
- Delegate to the same `run_config()` API used by consumers.

## Artifact Layout

Each run writes one directory:

```text
results/2026-05-20T213000Z-simple_momentum_spy_daily/
  config.toml
  strategy_snapshot.py
  bars.csv
  signals.csv
  request.json
  screen_summary.json
  validate_summary.json
  evidence.json
  notes.md
```

Failed runs should write as many useful artifacts as are safely available. A
failed validation is still a valid run artifact, not a crash.

## Error Handling

- Config errors stop before data loading.
- Data availability errors stop before strategy execution.
- Strategy import and signal-generation errors write `notes.md`.
- Zero generated signals writes available artifacts and marks the run failed.
- Signals with no matching decision bar or no available entry/exit fill fail
  closed.
- Engine validation failures write validation output and evidence when possible.
- No data adapter may fabricate missing observations.
- No adapter may silently change the requested date window in strict mode.

## Testing

Keep tests focused and synthetic:

- Config parser accepts a minimal valid TOML config.
- Config parser rejects missing required fields.
- Strategy loader imports a one-file strategy.
- Strategy loader rejects a file without `generate_signals`.
- Data loader behavior is tested with small synthetic Polars frames or
  monkeypatched `quant_data` loaders, not live database calls.
- Engine request builder rejects unfillable signals.
- Artifact writer creates the expected files for success and failure paths.
- CLI smoke test runs through the same `run_config()` path.
- Existing strategy tests remain focused on signal timing, side, weight,
  holding period, no-lookahead behavior, and degenerate inputs.

## Migration For Quant Autoresearch

`quant_autoresearch` should stop owning runner behavior. Its useful long-term
role is a consumer workspace or agent instruction layer that:

1. Edits or creates one strategy file in `quant_strategies`.
2. Edits or creates one run config in `quant_strategies/runs/`.
3. Calls the `quant_strategies` runner.
4. Reads the generated artifacts.
5. Reports keep, discard, or crash.

The current synthetic `quant_autoresearch` runner can be removed after the
`quant_strategies` runner package provides equivalent or better functionality.

## Verification Plan

Before considering implementation complete:

- Run `conda run -n quant pytest` in `quant_strategies`.
- Run a CLI smoke command against a synthetic or monkeypatched data adapter.
- Run `conda run -n quant pytest` in `quant_engine` to confirm the engine
  boundary remains intact.
- Confirm `quant_autoresearch` no longer needs its own runner to consume the
  workflow.
