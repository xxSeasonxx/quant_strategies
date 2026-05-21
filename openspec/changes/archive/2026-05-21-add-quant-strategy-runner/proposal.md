## Why

`quant_strategies` currently stores pure strategy files and focused tests, but
it has no clean way to run one strategy against real `quant-data` inputs and
produce deterministic `quant_engine` artifacts. This blocks `quant_autoresearch`
from being a simple consumer and keeps runnable strategy experimentation split
across projects.

## What Changes

- Add a package-style strategy runner inside `quant_strategies`.
- Add a public Python API for running one config-driven strategy experiment.
- Add a CLI wrapper for the same runner API.
- Add TOML run configs that name the strategy file, data source, symbol set,
  date window, strategy params, fill model, cost model, and output mode.
- Add explicit data adapters for generic bars, crypto perpetual funding bars,
  and FX bars with executable quotes.
- Write deterministic run artifacts including config, strategy snapshot, bars,
  signals, engine request, summaries, evidence, and notes.
- Keep `quant_engine` as the deterministic evaluator and keep
  `quant_autoresearch` as a consumer rather than a runner owner.

## Capabilities

### New Capabilities

- `strategy-runner`: Run a single flat strategy file through `quant_data` inputs
  and `quant_engine` evaluation using an explicit run config.

### Modified Capabilities

- None.

## Impact

- Adds a new `src/quant_strategies/runner/` package.
- Adds a console entry point such as `quant-strategies run <config>`.
- Adds `runs/` examples and ignored `results/` artifacts.
- Updates project metadata so `quant_strategies` can be installed as a package.
- Depends on existing `quant_data` public loader APIs and existing
  `quant_engine` Python APIs.
- Depends on `quant_engine` change `add-quote-based-engine-fills` for true
  bid/ask quote execution when configs use `fill_model.price = "quote"`.
- Updates docs to replace the current "does not evaluate strategies directly"
  wording with the narrower boundary that strategies remain pure while the
  repository owns a runner for explicit experiments.
