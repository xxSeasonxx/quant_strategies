## Context

`quant_strategies` is a flat strategy library. Strategy files expose pure
`generate_signals(bars, params)` functions and focused tests cover signal
timing, side, weight, holding period, and edge cases.

The missing piece is a clean run boundary:

```text
run config
  -> quant_data loaders
  -> flat strategy file
  -> quant_engine request
  -> deterministic result artifacts
```

`quant_engine` already evaluates explicit bars and signals. It should remain the
foundation for fill timing, costs, accounting, validation gates, and evidence.
`quant_autoresearch` should consume a stable `quant_strategies` runner instead
of owning a separate synthetic harness.

## Goals / Non-Goals

**Goals:**

- Add a package-style runner API inside `quant_strategies`.
- Support both Python API and CLI entrypoints backed by the same implementation.
- Load one strategy file from an explicit file path, not from a registry.
- Load real market data through public `quant_data` loader APIs.
- Run through `quant_engine` Python APIs and write deterministic artifacts.
- Support `fill_model.price = "quote"` for FX runs once the dependent
  `quant_engine` quote-fill change is available.
- Start with generic bars, crypto perp funding, and FX-with-quotes adapters.
- Keep implementation small enough to remain understandable and testable.

**Non-Goals:**

- Do not move this runner into `quant_engine`.
- Do not retain runner ownership in `quant_autoresearch`.
- Do not create strategy discovery, strategy registries, or plugin systems.
- Do not add autonomous loops or promotion decisions.
- Do not create per-strategy folders.
- Do not call data refresh, backfill, repair, or source-joining code.

## Decisions

### Package Runner Inside `quant_strategies`

Add a real package under `src/quant_strategies/runner/` instead of a single root
script.

Rationale: `quant_autoresearch` needs a clean consumer API. A package preserves
that boundary while still keeping strategy files flat.

Alternatives considered:

- Root script: simpler initially, but becomes harder to import and test as a
  consumer API.
- Runner in `quant_engine`: fewer repositories, but it couples engine
  foundations to strategy imports, data loading, configs, and artifacts.
- Runner in `quant_autoresearch`: keeps runnable behavior in a consumer rather
  than the strategy library that owns the strategy files.

### Explicit TOML Run Configs

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

Rationale: TOML is readable, has a standard-library parser in Python 3.11+, and
keeps experiment inputs versionable.

Run config validation uses Pydantic models at the external boundary after
`tomllib` parses the file. This makes invalid states hard to represent and gives
clear validation errors for missing fields, bad modes, bad paths, unsupported
data kinds, and malformed fill/cost settings.

Both `strategy_path` and `output.results_dir` must resolve inside the
`quant_strategies` repository. This keeps file reads and artifact writes inside
the project unless a future change explicitly designs external artifact sinks.

Alternatives considered:

- YAML: readable, but would require adding a parser dependency.
- JSON: standard-library support, but worse for hand-edited run configs.
- Python config modules: flexible, but too easy to mix executable logic with run
  settings.

### File Path Strategy Loading

`strategy_path` points to a single strategy file such as
`tested/simple_momentum.py`.

Rationale: this matches the flat-library rule and avoids a registry. The runner
requires a callable `generate_signals(bars, params)` and fails closed when it is
missing.

### Adapter-Oriented Data Loading

Start with three data adapter kinds:

```text
bars
  load_bars / load_universe_bars

crypto_perp_funding
  load_crypto_perp_bars_with_funding

forex_with_quotes
  load_fx_bars_with_quotes, including bid/ask fields for quote fills
```

Rationale: these cover the current tested/untested strategies and make future
asset-class expansion a data-adapter change rather than an engine change.

Adapters use public `quant_data.loader` APIs only. They must not perform data
materialization, refresh, backfill, repair, or raw source joining.

For `forex_with_quotes`, the adapter passes quote fields both to the strategy
input rows and to the engine OHLC rows. The engine evaluates quote-based fills
from the bid/ask fields on the selected entry and exit bars.

### Quote-Based Engine Fills

The runner depends on the separate `quant_engine` change
`add-quote-based-engine-fills` for executable bid/ask accounting. The runner
does not implement quote accounting itself.

Expected engine semantics:

```text
long entry   -> ask
long exit    -> bid
short entry  -> bid
short exit   -> ask
```

When a config uses `fill_model.price = "quote"`, the `forex_with_quotes` adapter
must preserve bid/ask fields in engine request bars so `quant_engine` can apply
those semantics. If the installed `quant_engine` does not support quote fills,
runner config validation or request construction should fail with a clear
dependency error rather than silently falling back to open/close fills.

Rationale: FX quote data is explicitly described by `quant-data` as executable
cost data. Treating `forex_with_quotes` as strategy-observable only would make
results too easy to misread as bid/ask-executed evidence.

Alternatives considered:

- Keep quotes as strategy-only observables: smaller change, but misleading for
  FX execution claims.
- Implement quote execution inside the runner: duplicates accounting outside the
  engine and weakens the deterministic evaluator boundary.

### Engine API Over Engine Subprocess

The runner should call `quant_engine` Python APIs for screening, validation, and
evidence generation. The CLI wraps the runner API rather than shelling out to
`quant-engine`.

Rationale: API calls are easier to test, easier for `quant_autoresearch` to
consume, and avoid subprocess-specific failure modes.

### Deterministic Artifact Directory

Each run writes one timestamped artifact directory:

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

Rationale: artifacts make each result auditable and keep the handoff to
`quant_autoresearch` simple.

### Fail Closed

The runner should fail before engine evaluation when config, data, strategy
import, signal shape, or fillability is invalid. Failed validation is not a
crash; it is a completed run with failed gates.

Rationale: research artifacts must not silently skip bad data, missing signals,
or unfillable trades.

## Risks / Trade-offs

- [Risk] Package structure adds more files than a root script → Mitigation:
  keep modules small and responsibility-oriented.
- [Risk] `quant_data` and `quant_engine` are local sibling projects rather than
  published dependencies → Mitigation: document editable-install setup and use
  tests that monkeypatch data loaders instead of requiring a live database.
- [Risk] Large multi-symbol one-minute windows can produce large in-memory
  frames and CSV artifacts → Mitigation: first version runs explicit windows
  only and does not add batch/multi-window execution.
- [Risk] Strategy signal output may not line up with engine fill bars →
  Mitigation: validate decision timestamps and entry/exit availability before
  calling the engine.
- [Risk] Adapter-specific fields can blur the engine contract → Mitigation:
  separate strategy input rows from engine OHLC rows.

## Migration Plan

1. Add package metadata and the runner package.
2. Add synthetic unit tests for config, strategy loading, data adapters, engine
   request building, artifact writing, and CLI wrapping.
3. Add one example run config and ignore generated `results/` artifacts.
4. Update README/AGENTS documentation for the new boundary: strategy code stays
   pure, while explicit runs are owned by the runner package.
5. Leave `quant_autoresearch` unchanged until the runner is verified.
6. After the runner is usable, remove or simplify the synthetic
   `quant_autoresearch` runner in a separate change.

Rollback is straightforward: remove the runner package, console entrypoint,
example run config, and docs updates. Strategy files and existing tests are not
rewritten by this change.

## Resolved Decisions

- Use Pydantic models for run-config validation.
- Ignore generated `results/` artifacts by default and commit only curated run
  configs, docs, and tests.
