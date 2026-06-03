# VectorBT Pro

This note records the package facts that matter to `quant_strategies` and the
project boundary implied by those facts. It is not an official VectorBT Pro
guide.

## Package Facts

Local package inspection in Season's `quant` environment on 2026-06-01:

| Fact | Value |
| --- | --- |
| Import | `import vectorbtpro as vbt` |
| Version | `2026.4.7` |
| Package root | `/opt/anaconda3/envs/quant/lib/python3.12/site-packages/vectorbtpro/` |
| `Portfolio` module | `vectorbtpro/portfolio/base.py` |
| Project optional extra | `pip install -e '.[vectorbtpro]'` installs `pandas>=2.2` and `vectorbtpro` |
| Evaluation extra | `pip install -e '.[evaluation]'` installs `pandas>=2.2`, `pyarrow>=16`, and `vectorbtpro` |

Verify the local install with:

```bash
conda run -n quant python -c "import inspect, vectorbtpro as vbt; print(vbt.__version__); print(vbt.__file__); print(inspect.getmodule(vbt.Portfolio).__file__)"
```

The package is broad. The pieces relevant to this project are the portfolio
simulation APIs:

| API | Factual role |
| --- | --- |
| `vbt.Portfolio.from_signals(...)` | Simulates a portfolio from entry/exit signal arrays, including long/short entries and exits. |
| `vbt.Portfolio.from_orders(...)` | Simulates a portfolio from explicit order arrays: size, price, fees, slippage, direction, and related fields. |
| `vbt.Portfolio.from_order_func(...)` | Builds a portfolio from custom order functions, with Numba-oriented callback paths. |

The installed source shows the simulation kernels under
`vectorbtpro/portfolio/nb/`, including `from_signals.py`, `from_orders.py`, and
`from_order_func.py`. `Portfolio.from_signals` prepares and broadcasts inputs,
then delegates to those kernels.

Relevant `Portfolio.from_signals` inputs include:

| Input | Meaning |
| --- | --- |
| `close` | Close prices or OHLC data used for simulation. |
| `entries`, `exits` | Long entry and exit signal arrays. |
| `long_entries`, `long_exits`, `short_entries`, `short_exits` | Direction-specific signal arrays. |
| `size`, `size_type` | Position sizing inputs. |
| `price`, `fees`, `slippage` | Execution price, percentage fee, and percentage slippage inputs. |
| `cash_sharing`, `group_by`, `init_cash` | Portfolio grouping and capital model inputs. |
| `open`, `high`, `low` | Optional OHLC inputs used by stop/limit features. |
| `jitted`, `chunked`, `broadcast_kwargs` | Performance and broadcasting controls. |

Relevant `Portfolio` outputs include:

| Output | Meaning |
| --- | --- |
| `get_total_return()` / `total_return` | Portfolio total return. |
| `returns` | Portfolio return series. |
| `orders` | Order records. |
| `trades` | Trade records and trade analytics. |
| `stats(...)` | Metric builder for selected portfolio statistics. |
| `get_max_drawdown()` | Drawdown metric. |

Portfolio defaults observed in `vbt.settings["portfolio"]` include
`init_cash = 100.0`, `price = "close"`, `fees = 0.0`, `slippage = 0.0`, and
`cash_sharing = False`. A project adapter should still set every semantic field
it depends on explicitly.

## What It Is Most Helpful For

VectorBT Pro is most helpful as a fast vectorized research and portfolio
simulation workbench:

- testing signal matrices across assets, windows, and parameter grids;
- running cost, slippage, sizing, and cash-sharing sensitivity checks;
- studying portfolio NAV-path behavior, drawdowns, order records, and trade
  distributions;
- building research evaluation artifacts after a candidate has a stable
  signal definition;
- independently sanity-checking simple engine cases.

This makes it valuable for the implemented research evaluation layer. Evaluation
uses `quant-strategies evaluate candidate/evaluation.toml` or
`quant_strategies.evaluation.run_evaluation` and writes detailed trace artifacts
as Parquet through `pyarrow`. It does not by itself prove alpha, statistical
significance, economic durability, data quality, or paper-trading or
live-trading authorization.

## Project Boundary

`quant_strategies` does not use VectorBT Pro as a quick-run or validation
backend.

| Surface | Backend |
| --- | --- |
| Quick run | Internal `quant_strategies.engine` path through `core.engine_runner` |
| Validation verdict | Internal `EngineBackend`, using the same engine path |
| Evaluation run | VectorBT Pro for non-funding data; `project_perp_ledger_v1` for `crypto_perp_funding` |
| VectorBT Pro agreement oracle | Optional single-trade validation agreement check |

`quant_strategies.engine` is internal to the quick-run and validation paths in
this table. It is not a separate public user surface.

The reason is semantic, not just implementation preference:

- The project engine reports linear signed per-trade activity sums.
- VectorBT Pro portfolio returns are NAV-path portfolio returns.
- Evaluation annualized metrics use full-grid portfolio returns from
  `portfolio_path`, including flat/no-position bars, and completed runs emit an
  `annualization_cadence` warning on obvious configured-cadence mismatches.
- Those objects only match in narrow cases.
- Funding-aware evaluation semantics belong to the project perp ledger, not to
  VectorBT Pro.
- Strategy purity still forbids calling VectorBT Pro inside strategy files.

VectorBT Pro evaluation output is named as portfolio/path evidence, not as a
project engine validation decision. Evaluation is not validation and does not authorize promotion, paper trading, or live trading. Benchmark-relative metrics are deferred.

## Evaluation Surface

The evaluation surface is an implemented stateless surface for
frozen-candidate portfolio/economic/path evidence. It requires a candidate-local
`evaluation.toml`, calls the data-kind-specific portfolio backend with explicit
assumptions, and returns `EvaluationRunResult`.
The checked-in example config is
`examples/strategies/simple_momentum_spy_daily_evaluation.toml`.

Detailed trace artifacts are Parquet only through `pyarrow`:

| Artifact | Contents |
| --- | --- |
| `tables/portfolio_path.parquet` | portfolio value, period return, and drawdown traces by scenario |
| `tables/trades.parquet` | trade traces by scenario |
| `tables/target_positions.parquet` | target-position entry/exit events by scenario; this is target schedule evidence, not realized broker position state |
| `tables/target_exposure_summary.parquet` | target exposure decision counts and target round-trip turnover by scenario and asset |
| `tables/funding_cashflows.parquet` | funding cashflow trace rows by scenario; empty but schema-valid for non-funding evaluations |

The companion JSON artifacts include `evaluation_metrics.json`,
`scenario_summary.json`, `data_manifest.json`, `evaluation_manifest.json`,
`environment.json`, and `notes.md`. There is no JSONL fallback path for
evaluation row snapshots or traces. Evaluation also writes
`audit/input_rows/{safe_window}-{hash}.parquet` normalized row snapshots and
`audit/decision_records/{safe_window}-{hash}.jsonl` decision records so
completed metrics can be traced through the artifact package.
`evaluation_metrics.json` and `evaluation_manifest.json` include the advisory
annualization cadence summary.

## Agreement Oracle

The project adapter lives at:

```text
src/quant_strategies/validation/vectorbtpro_backend.py
```

It builds `Portfolio.from_signals(...)` with close prices, long/short signal
frames, `fees`, `slippage`, `size_type = "valuepercent"`, `cash_sharing = True`,
`group_by = True`, and `init_cash = 100.0`.

The agreement logic lives at:

```text
src/quant_strategies/validation/agreement.py
```

The oracle:

- runs only when `[agreement_oracle] enabled = true`;
- reuses the engine verdict run rather than re-screening with VectorBT Pro;
- zeroes costs for the VectorBT Pro comparison;
- compares engine `gross_return` against VectorBT Pro zero-cost total return;
- is sound only for a single-trade, close-fill, threshold-free scenario;
- reports `skipped` when the scenario is outside that regime;
- reports `unavailable` when VectorBT Pro cannot be imported;
- fails validation only when an applicable comparison diverges beyond tolerance.

The adapter rejects unsupported semantics such as non-`open` intent, non-project
instrument ontology, `flat` target, non-`target_weight` sizing, leveraged target
weight above `1.0`, non-close fills, and threshold exit policies.

The research evaluation surface supports `crypto_perp_funding` through the
project-owned `project_perp_ledger_v1` ledger. Funding-aware scenarios do not
use VectorBT Pro `cash_dividends`; that contract was rejected because perp
funding is a position cashflow over `entry_time < funding_timestamp <= exit_time`,
not an asset dividend stream. VectorBT Pro remains the evaluation backend for
non-funding scenarios.

## Correct Use

Within `quant_strategies`, use VectorBT Pro through the evaluation surface when
the question is portfolio or research evaluation:

- "How sensitive is the strategy to fee/slippage assumptions?"
- "What does the NAV path, drawdown, and trade distribution look like?"
- "Does a simple one-trade price-path case agree with the project engine?"

For project artifacts, preserve the boundary:

- keep quick run and validation verdicts on the project engine;
- keep strategy files pure and free of VectorBT Pro calls;
- record data, config, signal arrays, sizing, costs, and portfolio settings;
- label VectorBT Pro metrics as NAV/portfolio metrics;
- do not compare VectorBT Pro total return to engine `net_return` unless the
  metric semantics have been made equivalent.

## Incorrect Use

Do not use VectorBT Pro as:

- a proof that a strategy has alpha;
- a replacement for data provenance and anti-lookahead checks;
- the validation verdict source;
- a candidate generation, parameter search, ranking, or stopping-rule engine;
- multi-trade confidence for the project engine's linear activity sums;
- a hidden dependency required for quick runs;
- an excuse to put data loading, simulation, or artifact writing inside
  strategy files.
